import json
from django.shortcuts import render
from django.contrib.auth.hashers import check_password
from django.core.mail import send_mail
from django.conf import settings

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from notifications.models import AdminNotification

from .models import Consumer, Merchant, User, FoodBank
from .serializers import UserRegistrationSerializer, CustomLoginSerializer
from .merchant_serializers import MerchantRegistrationSerializer
from .utils import extract_cebu_permit_data, simulate_ocr_extraction
from django.core.files.storage import default_storage


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


class UserRegistrationView(APIView):
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            
            role = user.user_role.lower()
            if role == 'consumer':
                full_name = request.data.get('full_name', 'Unknown User')
                phone = request.data.get('phone_number', '')
                address = request.data.get('address', '')
                
                Consumer.objects.create(
                    user=user, 
                    cons_fullname=full_name,
                    phone_num=phone,
                    address=address
                )
            
            return Response({
                "message": "Account created successfully", 
                "user_id": user.user_id,
                "role": user.user_role
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer


class MerchantRegistrationView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        serializer = MerchantRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            merchant = serializer.save()
            
            # Execute the Cebu Anchor-Text OCR Engine
            ocr_results = extract_cebu_permit_data(merchant.bus_permit_path)
            
            # Strip raw_text so HTML attributes remain clean and lightweight
            if 'raw_text' in ocr_results:
                del ocr_results['raw_text']
            
            # Automatically sync OCR-detected expiry date if valid
            detected_expiry = ocr_results.get('expiry_date')
            if detected_expiry and detected_expiry != 'Not Detected':
                merchant.bus_expiry_date = detected_expiry

            # Save structured JSON metadata & confidence score to database
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

class DocumentResubmissionView(APIView):
    parser_classes = (MultiPartParser, FormParser)

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

        # Default: Merchant Resubmission / Annual Renewal
        try:
            merchant = Merchant.objects.get(merch_id=merch_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND)

        merchant.bus_permit_path = saved_path

        # Re-run the Cebu City AI OCR Engine on the newly uploaded permit
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
        """
        Unified Compliance Controller for Merchant, Consumer, and FoodBank actions.
        Actions supported: 'approve', 'reject', 'suspend', 'notify'
        """
        action = request.data.get('action')
        role = request.data.get('role', 'Merchant')
        reason = request.data.get('reason', '')

        # ---------------------------------------------------------
        # 1. CONSUMER ACTIONS
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 2. FOOD BANK ACTIONS
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 3. MERCHANT ACTIONS
        # ---------------------------------------------------------
        try:
            merchant = Merchant.objects.select_related('user').get(merch_id=merch_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        if action == 'approve':
            # Save manually edited OCR fields if provided by the Admin
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

                # Sync edited expiry date if Admin updated Calendar Validity
                edited_expiry = ocr_edits.get('expiry_date')
                if edited_expiry:
                    merchant.bus_expiry_date = edited_expiry

            merchant.is_verified = True
            merchant.status = 'Active'
            merchant.status_reason = ''
            merchant.save()
            merchant.user.is_banned = False
            merchant.user.save()

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


# --- CUSTOM ADMIN GUI VIEWS ---

def login(request):
    return render(request, 'login.html')

def admin_dashboard(request):
    active_merchants_count = Merchant.objects.filter(status='Active').count()
    pending_merchants_count = Merchant.objects.filter(status='Pending').count()
    total_consumers = Consumer.objects.count()
    total_foodbanks = FoodBank.objects.count()

    context = {
        'active_merchants': active_merchants_count,
        'pending_merchants': pending_merchants_count,
        'total_consumers': total_consumers,
        'total_foodbanks': total_foodbanks,
    }
    return render(request, 'admin_dashboard.html', context)

def admin_users(request):
    consumers = Consumer.objects.select_related('user').all().order_by('-user__created_at')
    merchants = Merchant.objects.select_related('user').all().order_by('-user__created_at')
    foodbanks = FoodBank.objects.select_related('user').all().order_by('-user__created_at')

    context = {
        'consumers': consumers,
        'merchants': merchants,
        'foodbanks': foodbanks,
        
        'total_registered': consumers.count() + merchants.count() + foodbanks.count(),
        'active_accounts': merchants.filter(status='Active').count(),
        'banned_accounts': merchants.filter(status='Suspended').count(), 
    }
    return render(request, 'admin_user_manage.html', context)

def admin_food_listing(request):
    return render(request, 'admin_food_listing.html')

def admin_donations(request):
    return render(request, 'admin_donation_hub.html')

def admin_payouts(request):
    return render(request, 'admin_payout_requests.html')

def admin_announcements(request):
    return render(request, 'admin_announcements.html')