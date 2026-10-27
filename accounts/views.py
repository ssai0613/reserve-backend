import json
import datetime
from decimal import Decimal
from django.shortcuts import render
from django.db.models import Sum, Count
from django.apps import apps
from django.contrib.auth.hashers import check_password
from django.core.mail import send_mail
from django.conf import settings
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import random
from django.core.cache import cache
from rest_framework.permissions import AllowAny
import re
import requests

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from notifications.models import AdminNotification

from .models import Consumer, Merchant, User, FoodBank, Location
from .serializers import UserRegistrationSerializer, CustomLoginSerializer
from .merchant_serializers import MerchantRegistrationSerializer
from .utils import extract_cebu_permit_data, simulate_ocr_extraction


def send_compliance_email(to_email, subject, body):
    """
    Sends an email notification to the user.
    Safely falls back to terminal logging if SMTP is not yet configured in settings.py.
    """
    print(f"\n--- [EMAIL DISPATCH TO: {to_email}] ---\nSubject: {subject}\n{body}\n--------------------------------------\n")
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@reserve-cebu.com'),
            recipient_list=[to_email],
            fail_silently=True,
        )
    except Exception as e:
        print(f"Email Notice Log: {e}")


def fetch_dynamic_records(app_labels, filter_kwargs=None, limit=15):
    """
    Safely queries models from teammates' apps (listings, transactions, donations)
    and normalizes them into a clean dictionary list for templates and JSON APIs.
    """
    records = []
    for label in app_labels:
        try:
            app_config = apps.get_app_config(label)
            for model in app_config.get_models():
                qs = model.objects.all()
                if filter_kwargs:
                    valid_filters = {}
                    model_fields = [f.name for f in model._meta.get_fields()]
                    for k, v in filter_kwargs.items():
                        if k in model_fields:
                            valid_filters[k] = v
                    if valid_filters:
                        qs = qs.filter(**valid_filters)
                    else:
                        continue

                for obj in qs.order_by('-pk')[:limit]:
                    pk_val = getattr(obj, obj._meta.pk.name, '')
                    
                    # Resolve item / food title
                    title = None
                    for field in ['food_name', 'item_name', 'title', 'listing_name', 'name', 'description']:
                        if hasattr(obj, field) and getattr(obj, field):
                            title = str(getattr(obj, field))
                            break
                    if not title and hasattr(obj, 'listing') and getattr(obj, 'listing'):
                        listing_obj = getattr(obj, 'listing')
                        for f in ['food_name', 'item_name', 'title', 'name']:
                            if hasattr(listing_obj, f):
                                title = str(getattr(listing_obj, f))
                                break

                    # Resolve merchant / establishment name
                    est_name = None
                    if hasattr(obj, 'merchant') and getattr(obj, 'merchant'):
                        est_name = getattr(obj.merchant, 'bus_name', str(obj.merchant))
                    elif hasattr(obj, 'listing') and getattr(obj, 'listing') and hasattr(obj.listing, 'merchant'):
                        est_name = getattr(obj.listing.merchant, 'bus_name', '')

                    # Resolve buyer / recipient name
                    buyer_name = None
                    if hasattr(obj, 'consumer') and getattr(obj, 'consumer'):
                        buyer_name = getattr(obj.consumer, 'cons_fullname', str(obj.consumer))
                    elif hasattr(obj, 'foodbank') and getattr(obj, 'foodbank'):
                        buyer_name = getattr(obj.foodbank, 'org_name', str(obj.foodbank))
                    elif hasattr(obj, 'food_bank') and getattr(obj, 'food_bank'):
                        buyer_name = getattr(obj.food_bank, 'org_name', str(obj.food_bank))

                    # Resolve price / quantity
                    amount_str = "Donation"
                    for field in ['total_amount', 'amount', 'discounted_price', 'price', 'orig_price']:
                        if hasattr(obj, field) and getattr(obj, field) is not None:
                            val = getattr(obj, field)
                            try:
                                amount_str = f"₱{float(val):,.2f}"
                            except Exception:
                                amount_str = str(val)
                            break
                    if amount_str == "Donation":
                        for qfield in ['quantity', 'qty', 'weight_kg']:
                            if hasattr(obj, qfield) and getattr(obj, qfield) is not None:
                                amount_str = f"{getattr(obj, qfield)} qty/kg"
                                break

                    # Resolve status
                    status_val = "Active"
                    for sfield in ['status', 'order_status', 'claim_status', 'listing_status']:
                        if hasattr(obj, sfield) and getattr(obj, sfield):
                            status_val = str(getattr(obj, sfield))
                            break

                    # Resolve date
                    date_str = datetime.date.today().strftime('%Y-%m-%d')
                    for dfield in ['created_at', 'order_date', 'date_created', 'claimed_at', 'pickup_time', 'expiry_date']:
                        if hasattr(obj, dfield) and getattr(obj, dfield):
                            dval = getattr(obj, dfield)
                            if hasattr(dval, 'strftime'):
                                date_str = dval.strftime('%Y-%m-%d')
                            else:
                                date_str = str(dval)[:10]
                            break

                    prefix = label[:3].upper()
                    records.append({
                        'id': f"{prefix}-{pk_val}",
                        'title': title or f"{model.__name__} #{pk_val}",
                        'establishment': est_name or "Partner Merchant",
                        'buyer': buyer_name or "Verified User",
                        'date': date_str,
                        'amount': amount_str,
                        'status': status_val,
                    })
        except Exception:
            continue
    return records[:limit]




def normalize_ph_phone(phone_raw):
    """
    Validates and normalizes a Philippine mobile number:
    Accepts '09171234567' (11 digits) or '+639171234567' (13 chars) or '639171234567'.
    Returns ('+639171234567', '09171234567') or (None, None) if invalid.
    """
    cleaned = re.sub(r'[\s\-\(\)]', '', str(phone_raw or ''))
    if re.match(r'^09\d{9}$', cleaned):
        return f"+63{cleaned[1:]}", cleaned
    if re.match(r'^\+639\d{9}$', cleaned):
        return cleaned, f"0{cleaned[3:]}"
    if re.match(r'^639\d{9}$', cleaned):
        return f"+{cleaned}", f"0{cleaned[2:]}"
    return None, None


def send_compliance_email(to_email, subject, body):
    """
    Dispatches a real SMTP email via Gmail when EMAIL_HOST_USER & EMAIL_HOST_PASSWORD are set.
    """
    print(f"\n--- [EMAIL DISPATCH TO: {to_email}] ---\nSubject: {subject}\n{body}\n--------------------------------------\n")
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@reserve-cebu.com'),
            recipient_list=[to_email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"SMTP Email Warning: {e}")
        return False


def send_twilio_sms(to_e164_phone, message_body):
    """
    Sends a real SMS to a +63 Philippine mobile number using Twilio REST API.
    """
    sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_num = getattr(settings, 'TWILIO_PHONE_NUMBER', '')

    print(f"\n--- [TWILIO SMS DISPATCH TO: {to_e164_phone}] ---\n{message_body}\n--------------------------------------------\n")
    if not sid or not token or not from_num:
        print("Twilio credentials not yet set in .env; logged SMS above.")
        return False

    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        res = requests.post(
            url,
            data={"To": to_e164_phone, "From": from_num, "Body": message_body},
            auth=(sid, token),
            timeout=8,
        )
        if res.status_code in (200, 201):
            return True
        print("Twilio API response:", res.text)
        return False
    except Exception as e:
        print("Twilio SMS Error:", e)
        return False


OTP_MEMORY_STORE = {}


class SendRegistrationOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        raw_phone = str(request.data.get('phone', '')).strip()

        if not email or '@' not in email:
            return Response({"error": "Please enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(user_email__iexact=email).exists():
            return Response({"error": "This email address is already registered."}, status=status.HTTP_400_BAD_REQUEST)

        e164_phone, local_phone = normalize_ph_phone(raw_phone)
        if not e164_phone:
            return Response({
                "error": "Invalid Philippine phone number. Please enter an 11-digit mobile number starting with 09 (e.g. 09171234567) or +639 (e.g. +639171234567)."
            }, status=status.HTTP_400_BAD_REQUEST)

        email_otp = f"{random.randint(100000, 999999)}"
        sms_otp = f"{random.randint(100000, 999999)}"

        OTP_MEMORY_STORE[email] = {
            "email_otp": email_otp,
            "sms_otp": sms_otp,
            "phone": e164_phone,
        }
        try:
            cache.set(f"reserve_otp_{email}", OTP_MEMORY_STORE[email], timeout=600)
        except Exception:
            pass

        email_sent = send_compliance_email(
            email,
            "RESERVE Cebu - Email Verification Code",
            f"Welcome to RESERVE!\n\nYour 6-digit Email Verification Code is: {email_otp}\n\nThis code expires in 10 minutes."
        )
        sms_sent = send_twilio_sms(
            e164_phone,
            f"RESERVE Cebu: Your 6-digit phone verification code is {sms_otp}. Valid for 10 mins."
        )

        return Response({
            "message": f"Verification codes sent to {email} and {e164_phone}.",
            "normalized_phone": e164_phone,
            "local_phone": local_phone,
            "email_sent": email_sent,
            "sms_sent": sms_sent,
        }, status=status.HTTP_200_OK)


class VerifyRegistrationOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        email_code = str(request.data.get('otp', '')).strip()
        sms_code = str(request.data.get('sms_otp', '')).strip()

        record = OTP_MEMORY_STORE.get(email)
        if not record:
            try:
                record = cache.get(f"reserve_otp_{email}")
            except Exception:
                record = None

        if not record:
            return Response({"error": "Verification session expired. Please request a new code."}, status=status.HTTP_400_BAD_REQUEST)

        # Support both dictionary (dual email + sms) and legacy string
        if isinstance(record, dict):
            expected_email = str(record.get("email_otp", ""))
            expected_sms = str(record.get("sms_otp", ""))
            if email_code != expected_email:
                return Response({"error": "Invalid Email OTP code. Please check your inbox."}, status=status.HTTP_400_BAD_REQUEST)
            if sms_code and sms_code != expected_sms:
                return Response({"error": "Invalid SMS OTP code. Please check your text messages."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            if email_code != str(record):
                return Response({"error": "Invalid OTP code."}, status=status.HTTP_400_BAD_REQUEST)

        OTP_MEMORY_STORE.pop(email, None)
        try:
            cache.delete(f"reserve_otp_{email}")
        except Exception:
            pass
        return Response({"message": "Email and Philippine mobile number verified!"}, status=status.HTTP_200_OK)


class UserRegistrationView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            role = user.user_role.lower()
            address = request.data.get('address', 'Cebu City, Cebu')

            # Save GPS coordinates to Location table for Haversine matching
            try:
                lat = float(request.data.get('latitude') or 10.3157)
                lng = float(request.data.get('longitude') or 123.8854)
            except (ValueError, TypeError):
                lat, lng = 10.3157, 123.8854

            Location.objects.create(
                user=user,
                address_name=address,
                latitude=lat,
                longitude=lng,
                is_primary=True
            )

            if role == 'consumer':
                full_name = request.data.get('full_name', 'Unknown User')
                phone = request.data.get('phone_number', '')

                Consumer.objects.create(
                    user=user,
                    cons_fullname=full_name,
                    phone_num=phone,
                    address=address
                )
            elif role == 'foodbank':
                org_name = request.data.get('org_name', 'Community Food Bank')
                contact_person = request.data.get('contact_person', '')
                hotline = request.data.get('hotline', '')
                phone = request.data.get('phone', '')
                cert_file = request.FILES.get('accreditation_path')
                saved_path = default_storage.save(cert_file.name, cert_file) if cert_file else 'default_cert.jpg'

                FoodBank.objects.create(
                    user=user,
                    org_name=org_name,
                    address=address,
                    contact_person=contact_person,
                    hotline=hotline,
                    phone=phone,
                    accreditation_path=saved_path,
                    status='Pending'
                )
                AdminNotification.objects.create(
                    user_id=1,
                    admin_notif_type='KYB',
                    message=f"New Food Bank registration: {org_name} awaiting verification."
                )

            return Response({
                "message": "Account created successfully",
                "user_id": user.user_id,
                "role": user.user_role
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MerchantRegistrationView(APIView):
    permission_classes = [AllowAny]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        serializer = MerchantRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            merchant = serializer.save()

            # Save Merchant GPS coordinates to Location table for Haversine matching
            try:
                lat = float(request.data.get('latitude') or 10.3157)
                lng = float(request.data.get('longitude') or 123.8854)
            except (ValueError, TypeError):
                lat, lng = 10.3157, 123.8854

            Location.objects.create(
                user=merchant.user,
                address_name=merchant.address or 'Cebu City, Cebu',
                latitude=lat,
                longitude=lng,
                is_primary=True
            )

            ocr_results = extract_cebu_permit_data(merchant.bus_permit_path)
            if 'raw_text' in ocr_results:
                del ocr_results['raw_text']

            detected_expiry = ocr_results.get('expiry_date')
            if detected_expiry and detected_expiry != 'Not Detected':
                merchant.bus_expiry_date = detected_expiry

            merchant.ocr_extracted_text = json.dumps(ocr_results)
            merchant.ocr_confidence = ocr_results.get('confidence_score', 0.0)
            merchant.save()

            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type='KYB',
                message=f"New merchant application: {merchant.bus_name}. OCR Confidence: {merchant.ocr_confidence}%",
                merchant=merchant
            )

            return Response({
                "message": "Merchant registration submitted successfully. Under review by admin.",
                "merchant_id": merchant.merch_id,
                "ocr_analysis": ocr_results
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer


class DocumentResubmissionView(APIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, merch_id):
        role = request.data.get('role', 'Merchant')
        permit_file = request.FILES.get('bus_permit_path')

        if not permit_file:
            return Response({"error": "Please attach a valid permit or certificate file."}, status=status.HTTP_400_BAD_REQUEST)

        saved_path = default_storage.save(permit_file.name, permit_file)

        if role == 'FoodBank':
            try:
                fb = FoodBank.objects.get(org_id=merch_id)
            except FoodBank.DoesNotExist:
                return Response({"error": "Food Bank not found."}, status=status.HTTP_404_NOT_FOUND)

            fb.accreditation_path = saved_path
            fb.status = 'Pending'
            fb.status_reason = ''
            fb.save()

            return Response({
                "message": "Document resubmitted successfully! Your account is now back under Admin review."
            }, status=status.HTTP_200_OK)

        try:
            merchant = Merchant.objects.get(merch_id=merch_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND)

        merchant.bus_permit_path = saved_path

        ocr_results = extract_cebu_permit_data(saved_path)
        if 'raw_text' in ocr_results:
            del ocr_results['raw_text']

        detected_expiry = ocr_results.get('expiry_date')
        if detected_expiry and detected_expiry != 'Not Detected':
            merchant.bus_expiry_date = detected_expiry

        merchant.ocr_extracted_text = json.dumps(ocr_results)
        merchant.ocr_confidence = ocr_results.get('confidence_score', 0.0)
        merchant.status = 'Pending'
        merchant.status_reason = ''
        merchant.is_verified = False
        merchant.save()

        AdminNotification.objects.create(
            user_id=1,
            admin_notif_type='KYB',
            message=f"Resubmitted/Renewed permit from {merchant.bus_name}. OCR Confidence: {merchant.ocr_confidence}%",
            merchant=merchant
        )

        return Response({
            "message": "Permit uploaded and scanned! Your application is now pending Admin verification.",
            "ocr_analysis": ocr_results
        }, status=status.HTTP_200_OK)


class AdminMerchantApprovalView(APIView):
    def get(self, request):
        pending_merchants = Merchant.objects.filter(status='Pending')
        data = [{
            "merchant_id": m.merch_id,
            "business_name": m.bus_name,
            "merchant_type": m.merch_type,
            "expiry_date": m.bus_expiry_date,
            "status": m.status,
            "permit_path": str(m.bus_permit_path)
        } for m in pending_merchants]

        return Response({"pending_merchants": data}, status=status.HTTP_200_OK)

    def patch(self, request, merch_id):
        action = request.data.get('action')
        role = request.data.get('role', 'Merchant')
        reason = request.data.get('reason', '')

        # 1. CONSUMER ACTIONS
        if role == 'Consumer':
            try:
                consumer = Consumer.objects.select_related('user').get(cons_id=merch_id)
            except Consumer.DoesNotExist:
                return Response({"error": "Consumer not found"}, status=status.HTTP_404_NOT_FOUND)

            if action == 'suspend':
                consumer.status = 'Suspended'
                consumer.status_reason = reason
                consumer.save()
                consumer.user.is_banned = True
                consumer.user.save()

                appeal_link = f"http://127.0.0.1:8000/appeal/?role=consumer&id={consumer.cons_id}"
                send_compliance_email(
                    consumer.user.user_email,
                    "ReServe Account Suspended",
                    f"Hello {consumer.cons_fullname},\n\nYour account has been suspended due to: {reason}.\n"
                    f"If you wish to appeal this decision, please submit an appeal here: {appeal_link}"
                )
                return Response({"message": f"Consumer {consumer.cons_fullname} has been suspended."}, status=status.HTTP_200_OK)

            return Response({"error": "Invalid Consumer action"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. FOOD BANK ACTIONS
        if role == 'FoodBank':
            try:
                fb = FoodBank.objects.select_related('user').get(org_id=merch_id)
            except FoodBank.DoesNotExist:
                return Response({"error": "Food Bank not found"}, status=status.HTTP_404_NOT_FOUND)

            if action == 'approve':
                fb.status = 'Active'
                fb.status_reason = ''
                fb.save()
                fb.user.is_banned = False
                fb.user.save()
                send_compliance_email(
                    fb.user.user_email,
                    "ReServe Food Bank Approved",
                    f"Hello {fb.org_name},\n\nYour organization has been verified and approved on ReServe!"
                )
                return Response({"message": f"Food Bank {fb.org_name} approved."}, status=status.HTTP_200_OK)

            elif action == 'reject':
                fb.status = 'Resubmit Required'
                fb.status_reason = reason
                fb.save()
                reupload_link = f"http://127.0.0.1:8000/reupload/?role=foodbank&id={fb.org_id}"
                send_compliance_email(
                    fb.user.user_email,
                    "Action Required: ReServe Food Bank Verification",
                    f"Hello {fb.org_name},\n\nYour accreditation document could not be verified due to: {reason}.\n"
                    f"Please log into your account or use this link to upload a clearer copy: {reupload_link}"
                )
                return Response({"message": f"Food Bank {fb.org_name} flagged for resubmission."}, status=status.HTTP_200_OK)

            elif action == 'suspend':
                fb.status = 'Suspended'
                fb.status_reason = reason
                fb.save()
                fb.user.is_banned = True
                fb.user.save()
                appeal_link = f"http://127.0.0.1:8000/appeal/?role=foodbank&id={fb.org_id}"
                send_compliance_email(
                    fb.user.user_email,
                    "ReServe Food Bank Account Suspended",
                    f"Hello {fb.org_name},\n\nYour account has been suspended due to: {reason}.\n"
                    f"To reactivate your account, submit an appeal here: {appeal_link}"
                )
                return Response({"message": f"Food Bank {fb.org_name} suspended."}, status=status.HTTP_200_OK)

            elif action == 'notify':
                send_compliance_email(
                    fb.user.user_email,
                    "Important Notice from ReServe Admin",
                    f"Hello {fb.org_name},\n\nAdmin Notice: {reason}"
                )
                return Response({"message": "Notification sent to Food Bank."}, status=status.HTTP_200_OK)

            return Response({"error": "Invalid Food Bank action"}, status=status.HTTP_400_BAD_REQUEST)

        # 3. MERCHANT ACTIONS
        try:
            merchant = Merchant.objects.select_related('user').get(merch_id=merch_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        if action == 'approve':
            ocr_edits = request.data.get('ocr_edits', {})
            try:
                current_ocr = json.loads(merchant.ocr_extracted_text or '{}')
            except Exception:
                current_ocr = {}

            if ocr_edits:
                for key in ['business_name', 'permit_number', 'lgu_anchor', 'business_address', 'nature_of_business', 'calendar_year', 'representative']:
                    if key in ocr_edits:
                        current_ocr[key] = ocr_edits[key]
                merchant.ocr_extracted_text = json.dumps(current_ocr)

                # Sync edited business name & address directly to the Merchant record if valid
                if ocr_edits.get('business_name') and ocr_edits['business_name'] != 'Not Detected':
                    merchant.bus_name = ocr_edits['business_name']
                if ocr_edits.get('business_address') and ocr_edits['business_address'] != 'Not Detected':
                    merchant.address = ocr_edits['business_address']
                if ocr_edits.get('expiry_date'):
                    merchant.bus_expiry_date = ocr_edits['expiry_date']

            merchant.is_verified = True
            merchant.status = 'Active'
            merchant.status_reason = ''
            merchant.save()
            merchant.user.is_banned = False
            merchant.user.save()

            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type='Approved',
                message=f"Merchant MID-{merchant.merch_id} ({merchant.bus_name}) approved by Admin.",
                merchant=merchant
            )

            send_compliance_email(
                merchant.user.user_email,
                "ReServe Merchant Application Approved",
                f"Hello {merchant.bus_name},\n\nYour business permit has been verified and your account is now Active!"
            )
            return Response({"message": f"Merchant {merchant.bus_name} has been approved successfully."}, status=status.HTTP_200_OK)
        
        elif action == 'reject':
            merchant.is_verified = False
            merchant.status = 'Resubmit Required'
            merchant.status_reason = reason
            merchant.save()

            reupload_link = f"http://127.0.0.1:8000/reupload/?role=merchant&id={merchant.merch_id}"
            send_compliance_email(
                merchant.user.user_email,
                "Action Required: ReServe Business Permit Verification",
                f"Hello {merchant.bus_name},\n\nYour application requires attention due to: {reason}.\n"
                f"Your registration details have been saved. Please log in or click here to upload a new document copy: {reupload_link}"
            )
            return Response({"message": f"Merchant {merchant.bus_name} notified to resubmit document."}, status=status.HTTP_200_OK)

        elif action == 'suspend':
            merchant.is_verified = False
            merchant.status = 'Suspended'
            merchant.status_reason = reason
            merchant.save()
            merchant.user.is_banned = True
            merchant.user.save()

            appeal_link = f"http://127.0.0.1:8000/appeal/?role=merchant&id={merchant.merch_id}"
            send_compliance_email(
                merchant.user.user_email,
                "ReServe Merchant Account Suspended",
                f"Hello {merchant.bus_name},\n\nYour merchant account has been suspended. Reason: {reason}.\n"
                f"If you wish to appeal and reactivate your account, click here: {appeal_link}"
            )
            return Response({"message": f"Merchant {merchant.bus_name} has been suspended."}, status=status.HTTP_200_OK)

        elif action == 'notify':
            is_renewal = request.data.get('is_renewal', False)
            if is_renewal:
                merchant.status = 'Renewal Required'
                merchant.status_reason = reason
                merchant.save()

            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type='Compliance',
                message=f"Notice sent to {merchant.bus_name}: {reason}",
                merchant=merchant
            )
            send_compliance_email(
                merchant.user.user_email,
                "Official Compliance Notice - ReServe Admin",
                f"Hello {merchant.bus_name},\n\nMessage from ReServe Admin:\n\"{reason}\"\n\n"
                f"Please log into your ReServe Merchant Portal to take any necessary action."
            )
            return Response({"message": f"Notification sent to {merchant.bus_name}."}, status=status.HTTP_200_OK)

        return Response({"error": "Invalid action parameter."}, status=status.HTTP_400_BAD_REQUEST)


# --- LIVE JSON API ENDPOINTS FOR MODALS & ADMIN PROFILE ---

def admin_user_transactions_api(request, role, account_id):
    """
    Returns live transactions/listings/donations for a specific Consumer, Merchant, or FoodBank.
    """
    role_clean = role.lower()
    records = []

    if role_clean == 'consumer':
        records = fetch_dynamic_records(['transactions'], {'consumer_id': account_id}, limit=10)
    elif role_clean == 'merchant':
        records = fetch_dynamic_records(['transactions', 'listings', 'donations'], {'merchant_id': account_id}, limit=10)
    elif role_clean == 'foodbank':
        records = fetch_dynamic_records(['donations'], {'foodbank_id': account_id, 'food_bank_id': account_id}, limit=10)

    return JsonResponse({'transactions': records})


@csrf_exempt
def update_admin_profile_api(request):
    """
    Updates the Super Admin's email address in the User database table.
    """
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            new_email = body.get('email', '').strip()
            admin_user = User.objects.filter(user_role='Admin').first()
            if admin_user and new_email:
                admin_user.user_email = new_email
                admin_user.save()
                return JsonResponse({'message': 'Admin email updated successfully!', 'email': new_email})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid request'}, status=400)


# --- CUSTOM ADMIN GUI VIEWS & ACTION API ---

def get_base_admin_context(active_page):
    """
    Provides the shared header context (notifications, pending count, admin email, active nav tab)
    for base_admin.html across all 6 Admin pages.
    """
    admin_user = User.objects.filter(user_role='Admin').first()
    return {
        'active_page': active_page,
        'pending_merchants': Merchant.objects.filter(status='Pending').count(),
        'recent_notifications': AdminNotification.objects.select_related('merchant').order_by('-pk')[:6],
        'admin_email': admin_user.user_email if admin_user else 'admin@reserve.org',
    }


def login(request):
    return render(request, 'login.html')


def admin_dashboard(request):
    context = get_base_admin_context('dashboard')
    active_merchants_count = Merchant.objects.filter(status='Active').count()
    total_consumers = Consumer.objects.count()
    total_foodbanks = FoodBank.objects.count()

    cons_saved = Consumer.objects.aggregate(total=Sum('total_food_saved'))['total'] or Decimal('0.00')
    fb_received = FoodBank.objects.aggregate(total=Sum('total_food_received'))['total'] or Decimal('0.00')
    total_food_rescued_kg = float(cons_saved + fb_received)

    merch_wallets = Merchant.objects.aggregate(total=Sum('wallet_bal'))['total'] or Decimal('0.00')
    total_value_rescued = float(merch_wallets)

    total_merch_all = Merchant.objects.count()
    bakeshop_count = Merchant.objects.filter(merch_type__icontains='bake').count()
    market_count = Merchant.objects.filter(merch_type__icontains='market').count()
    other_count = max(0, total_merch_all - bakeshop_count - market_count)

    if total_merch_all > 0:
        bakeshop_pct = round((bakeshop_count / total_merch_all) * 100)
        market_pct = round((market_count / total_merch_all) * 100)
        other_pct = max(0, 100 - bakeshop_pct - market_pct)
    else:
        bakeshop_pct, market_pct, other_pct = 0, 0, 0

    today = datetime.date.today()
    chart_labels = []
    chart_counts = []
    for i in range(5, -1, -1):
        month_date = (today.replace(day=1) - datetime.timedelta(days=i * 28)).replace(day=1)
        chart_labels.append(month_date.strftime('%b %Y'))
        m_count = User.objects.filter(
            created_at__year=month_date.year,
            created_at__month=month_date.month
        ).count()
        chart_counts.append(m_count)

    context.update({
        'active_merchants': active_merchants_count,
        'total_consumers': total_consumers,
        'total_foodbanks': total_foodbanks,
        'total_food_rescued_kg': f"{total_food_rescued_kg:,.1f}",
        'total_value_rescued': f"{total_value_rescued:,.2f}",
        'bakeshop_pct': bakeshop_pct,
        'market_pct': market_pct,
        'other_pct': other_pct,
        'bakeshop_count': bakeshop_count,
        'market_count': market_count,
        'other_count': other_count,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_counts_json': json.dumps(chart_counts),
        'live_transactions': fetch_dynamic_records(['listings', 'transactions', 'donations'], limit=6),
    })
    return render(request, 'admin_dashboard.html', context)


def admin_users(request):
    context = get_base_admin_context('users')
    consumers = Consumer.objects.select_related('user').all().order_by('-user__created_at')
    merchants = Merchant.objects.select_related('user').all().order_by('-user__created_at')
    foodbanks = FoodBank.objects.select_related('user').all().order_by('-user__created_at')

    context.update({
        'consumers': consumers,
        'merchants': merchants,
        'foodbanks': foodbanks,
        'total_registered': consumers.count() + merchants.count() + foodbanks.count(),
        'active_accounts': (
            consumers.filter(status='Active').count() +
            merchants.filter(status='Active').count() +
            foodbanks.filter(status='Active').count()
        ),
        'banned_accounts': (
            consumers.exclude(status='Active').count() +
            merchants.exclude(status='Active').count() +
            foodbanks.exclude(status='Active').count()
        ),
    })
    return render(request, 'admin_user_manage.html', context)


def admin_food_listing(request):
    context = get_base_admin_context('food-listing')
    merchant_filter = request.GET.get('merchant', '').replace('MID-', '').strip()
    filter_kwargs = {'merchant_id': int(merchant_filter)} if merchant_filter.isdigit() else None

    listings_list = []
    flagged_count = 0
    claimed_count = 0

    try:
        app_config = apps.get_app_config('listings')
        for model in app_config.get_models():
            qs = model.objects.all()
            if filter_kwargs and 'merchant' in [f.name for f in model._meta.get_fields()]:
                qs = qs.filter(merchant_id=filter_kwargs['merchant_id'])

            for obj in qs.order_by('-pk')[:100]:
                pk_val = getattr(obj, obj._meta.pk.name)
                title = None
                for f in ['food_name', 'item_name', 'title', 'listing_name', 'name']:
                    if hasattr(obj, f) and getattr(obj, f):
                        title = str(getattr(obj, f))
                        break
                if not title:
                    continue

                desc = getattr(obj, 'description', None) or getattr(obj, 'food_desc', None) or 'Fresh surplus food item listed for community rescue.'
                qty = getattr(obj, 'quantity', None) or getattr(obj, 'qty', None) or getattr(obj, 'stock', 1)
                orig_p = getattr(obj, 'orig_price', None) or getattr(obj, 'original_price', None) or getattr(obj, 'price', 0)
                disc_p = getattr(obj, 'discounted_price', None) or getattr(obj, 'disc_price', None) or getattr(obj, 'price', 0)
                cat = getattr(obj, 'category', None) or getattr(obj, 'food_category', None) or getattr(obj, 'food_type', None)

                est_name = "Verified Partner"
                est_addr = "Cebu City, Philippines"
                if hasattr(obj, 'merchant') and getattr(obj, 'merchant'):
                    m_obj = getattr(obj, 'merchant')
                    est_name = getattr(m_obj, 'bus_name', est_name)
                    est_addr = getattr(m_obj, 'address', None) or est_addr
                    if not cat:
                        cat = getattr(m_obj, 'merch_type', 'Surplus')

                status_val = str(getattr(obj, 'status', None) or getattr(obj, 'listing_status', 'Active'))
                if 'flag' in status_val.lower():
                    flagged_count += 1
                if 'claim' in status_val.lower() or 'sold' in status_val.lower() or 'complet' in status_val.lower():
                    claimed_count += 1

                date_str = datetime.date.today().strftime('%Y-%m-%d')
                for df in ['created_at', 'date_posted', 'listing_date', 'expiry_date']:
                    if hasattr(obj, df) and getattr(obj, df):
                        dval = getattr(obj, df)
                        date_str = dval.strftime('%Y-%m-%d') if hasattr(dval, 'strftime') else str(dval)[:10]
                        break

                expiry_str = str(getattr(obj, 'expiry_date', None) or getattr(obj, 'pickup_until', None) or date_str)[:16]
                img_path = getattr(obj, 'image_path', None) or getattr(obj, 'food_image', None) or getattr(obj, 'photo', '')

                listings_list.append({
                    'raw_id': pk_val,
                    'id': f"FL-{pk_val}",
                    'model_name': model.__name__,
                    'title': title,
                    'description': desc,
                    'establishment': est_name,
                    'address': est_addr,
                    'date': date_str,
                    'expiry': expiry_str,
                    'quantity': qty,
                    'orig_price': f"₱{float(orig_p):,.2f}" if orig_p else "₱0.00",
                    'disc_price': f"₱{float(disc_p):,.2f}" if disc_p else "Donation",
                    'category': cat or 'Surplus',
                    'status': status_val,
                    'image_url': f"/media/{img_path}" if img_path else "",
                })
    except Exception as e:
        print(f"Listings fetch notice: {e}")

    tx_claimed = len(fetch_dynamic_records(['transactions'], limit=500))
    context.update({
        'listings': listings_list,
        'active_listings_count': len([l for l in listings_list if l['status'].lower() == 'active']),
        'active_stores_count': Merchant.objects.filter(status='Active').count(),
        'claimed_produce_count': max(claimed_count, tx_claimed),
        'flagged_listings_count': flagged_count,
    })
    return render(request, 'admin_food_listing.html', context)


def admin_donations(request):
    context = get_base_admin_context('donations')
    fb_filter = request.GET.get('foodbank', '').replace('FB-', '').strip()
    filter_kwargs = {'foodbank_id': int(fb_filter), 'food_bank_id': int(fb_filter)} if fb_filter.isdigit() else None

    raw_donations = fetch_dynamic_records(['donations'], filter_kwargs=filter_kwargs, limit=100)
    pending_requests = []
    active_transfers = []
    flagged_drops = 0

    for d in raw_donations:
        st = d['status'].lower()
        if 'flag' in st or 'issue' in st:
            flagged_drops += 1
        if 'pending' in st or 'request' in st:
            pending_requests.append(d)
        else:
            active_transfers.append(d)

    pending_fbs = FoodBank.objects.filter(status='Pending').select_related('user')
    for fb in pending_fbs:
        pending_requests.append({
            'raw_id': fb.org_id,
            'id': f"REQ-{fb.org_id}",
            'is_fb_org': True,
            'establishment': fb.org_name,
            'date': fb.user.created_at.strftime('%Y-%m-%d'),
            'title': 'Surplus Produce & Bakery Allotments',
            'amount': '50 - 150 kg',
            'status': fb.status,
            'address': fb.address or 'Cebu City, Philippines',
            'contact': f"{fb.phone or 'N/A'} ({fb.contact_person or 'NGO Coordinator'})",
        })

    fb_received = FoodBank.objects.aggregate(total=Sum('total_food_received'))['total'] or Decimal('0.00')
    context.update({
        'total_hubs': FoodBank.objects.count(),
        'total_donated': int(fb_received) if fb_received > 0 else len(raw_donations),
        'pending_review_count': len(pending_requests),
        'ongoing_drops_count': len(active_transfers),
        'flagged_drops_count': flagged_drops,
        'pending_requests': pending_requests,
        'active_transfers': active_transfers,
    })
    return render(request, 'admin_donation_hub.html', context)


def admin_payouts(request):
    context = get_base_admin_context('payouts')
    merchants_with_bal = Merchant.objects.select_related('user').all().order_by('-wallet_bal', '-user__created_at')
    payout_rows = []
    pending_count = 0
    approved_count = 0
    processing_count = 0

    try:
        tx_app = apps.get_app_config('transactions')
        for model in tx_app.get_models():
            if 'payout' in model.__name__.lower() or 'withdraw' in model.__name__.lower():
                for obj in model.objects.all().order_by('-pk')[:50]:
                    pk_val = getattr(obj, obj._meta.pk.name)
                    m_obj = getattr(obj, 'merchant', None)
                    m_name = getattr(m_obj, 'bus_name', 'Partner Merchant') if m_obj else 'Partner Merchant'
                    m_bal = getattr(m_obj, 'wallet_bal', Decimal('0.00')) if m_obj else Decimal('0.00')
                    amt = getattr(obj, 'amount', None) or getattr(obj, 'payout_amount', m_bal)
                    st = str(getattr(obj, 'status', 'Pending'))
                    dval = getattr(obj, 'created_at', None) or getattr(obj, 'request_date', datetime.date.today())
                    d_str = dval.strftime('%Y-%m-%d') if hasattr(dval, 'strftime') else str(dval)[:10]

                    if 'pend' in st.lower():
                        pending_count += 1
                    elif 'approv' in st.lower() or 'complete' in st.lower() or 'paid' in st.lower():
                        approved_count += 1
                    else:
                        processing_count += 1

                    payout_rows.append({
                        'raw_id': pk_val,
                        'id': f"PO-{pk_val}",
                        'is_merchant_wallet': False,
                        'merchant_name': m_name,
                        'date': d_str,
                        'current_balance': f"₱{float(m_bal):,.2f}",
                        'requested_amount': f"₱{float(amt):,.2f}",
                        'status': st,
                    })
    except Exception:
        pass

    if not payout_rows:
        for m in merchants_with_bal:
            bal = float(m.wallet_bal or 0)
            st = 'Pending' if bal > 0 else 'Settled'
            if st == 'Pending':
                pending_count += 1
            else:
                approved_count += 1
            payout_rows.append({
                'raw_id': m.merch_id,
                'id': f"PO-{m.merch_id}",
                'is_merchant_wallet': True,
                'merchant_name': m.bus_name,
                'date': m.user.created_at.strftime('%Y-%m-%d'),
                'current_balance': f"₱{bal:,.2f}",
                'requested_amount': f"₱{bal:,.2f}",
                'status': st,
            })

    context.update({
        'payouts': payout_rows,
        'total_requests': len(payout_rows),
        'pending_approval_count': pending_count,
        'successful_count': approved_count,
        'processing_count': processing_count,
    })
    return render(request, 'admin_payout_requests.html', context)


def admin_announcements(request):
    context = get_base_admin_context('announcements')
    broadcasts_qs = AdminNotification.objects.filter(
        admin_notif_type__startswith='Broadcast'
    ).order_by('-pk')

    broadcasts = []
    for b in broadcasts_qs:
        audience = b.admin_notif_type.replace('Broadcast:', '').strip() or 'All Users (System-wide)'
        parts = (b.message or '').split(' || ', 1)
        title = parts[0] if len(parts) > 1 else 'System Announcement'
        body = parts[1] if len(parts) > 1 else b.message
        broadcasts.append({
            'id': b.pk,
            'audience': audience,
            'title': title,
            'body': body,
        })

    context['broadcasts'] = broadcasts
    return render(request, 'admin_announcements.html', context)


@csrf_exempt
def admin_portal_action_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
        module = data.get('module')
        action = data.get('action')
        raw_id = data.get('id')

        if module == 'announcement':
            if action == 'create':
                audience = data.get('audience', 'All Users (System-wide)')
                title = data.get('title', '').strip()
                body = data.get('body', '').strip()
                if not title or not body:
                    return JsonResponse({'error': 'Title and message body are required.'}, status=400)

                notif = AdminNotification.objects.create(
                    user_id=1,
                    admin_notif_type=f"Broadcast:{audience}"[:50],
                    message=f"{title} || {body}"
                )
                return JsonResponse({'message': 'Broadcast published!', 'id': notif.pk})
            elif action == 'delete':
                AdminNotification.objects.filter(pk=raw_id).delete()
                return JsonResponse({'message': 'Broadcast deleted.'})

        elif module == 'listing':
            app_config = apps.get_app_config('listings')
            for model in app_config.get_models():
                qs = model.objects.filter(pk=raw_id)
                if qs.exists():
                    obj = qs.first()
                    if action == 'delete':
                        obj.delete()
                        return JsonResponse({'message': 'Listing removed.'})
                    elif action == 'flag':
                        for sfield in ['status', 'listing_status']:
                            if hasattr(obj, sfield):
                                setattr(obj, sfield, 'Flagged')
                                obj.save()
                                break
                        return JsonResponse({'message': 'Listing flagged.'})
            return JsonResponse({'message': 'Listing status updated.'})

        elif module == 'donation':
            is_fb_org = data.get('is_fb_org', False)
            if is_fb_org:
                fb = FoodBank.objects.filter(org_id=raw_id).first()
                if fb:
                    fb.status = 'Active' if action == 'approve' else 'Rejected'
                    fb.save()
                    return JsonResponse({'message': f'Food Bank hub status updated to {fb.status}.'})

            app_config = apps.get_app_config('donations')
            for model in app_config.get_models():
                qs = model.objects.filter(pk=raw_id)
                if qs.exists():
                    obj = qs.first()
                    new_status = {
                        'approve': 'Approved',
                        'reject': 'Rejected',
                        'deliver': 'Delivered',
                        'flag': 'Flagged'
                    }.get(action, 'Updated')
                    for sfield in ['status', 'claim_status', 'donation_status']:
                        if hasattr(obj, sfield):
                            setattr(obj, sfield, new_status)
                            obj.save()
                            break
                    return JsonResponse({'message': f'Donation record updated to {new_status}.'})
            return JsonResponse({'message': 'Donation status updated.'})

        elif module == 'payout':
            is_wallet = data.get('is_merchant_wallet', True)
            if is_wallet:
                merchant = Merchant.objects.filter(merch_id=raw_id).first()
                if merchant:
                    if action == 'approve':
                        paid_amt = merchant.wallet_bal
                        merchant.wallet_bal = Decimal('0.00')
                        merchant.save()
                        AdminNotification.objects.create(
                            user_id=1,
                            admin_notif_type='Payout',
                            message=f"Payout of ₱{paid_amt:,.2f} settled for {merchant.bus_name}.",
                            merchant=merchant
                        )
                    return JsonResponse({'message': f'Payout {action}d for {merchant.bus_name}.'})
            else:
                tx_app = apps.get_app_config('transactions')
                for model in tx_app.get_models():
                    if 'payout' in model.__name__.lower() or 'withdraw' in model.__name__.lower():
                        obj = model.objects.filter(pk=raw_id).first()
                        if obj and hasattr(obj, 'status'):
                            obj.status = 'Approved' if action == 'approve' else 'Rejected'
                            obj.save()
                            return JsonResponse({'message': f'Payout request {obj.status}.'})
            return JsonResponse({'message': 'Payout updated.'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Unknown module or action'}, status=400)
