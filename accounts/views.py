import json
import datetime
import uuid
from decimal import Decimal
from django.shortcuts import render
from django.db.models import Sum, Count, Avg
from django.apps import apps
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.conf import settings
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import random
from django.core.cache import cache
from rest_framework.permissions import AllowAny
import re
import requests

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser

from rest_framework_simplejwt.views import TokenObtainPairView

from notifications.models import AdminNotification, UserNotification, Announcement
from transactions.models import WithdrawalReq, RatingReview, OrderReservation

from .models import Consumer, Merchant, User, FoodBank, Location
from .serializers import UserRegistrationSerializer, CustomLoginSerializer
from .merchant_serializers import MerchantRegistrationSerializer
from .utils import extract_cebu_permit_data


OTP_MEMORY_STORE = {}
PASSWORD_RESET_STORE = {}


def send_compliance_email(to_email, subject, body):
    print(f"\n--- [EMAIL DISPATCH TO: {to_email}] ---\nSubject: {subject}\n{body}\n--------------------------------------\n")
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'reserve.org.com@gmail.com'),
            recipient_list=[to_email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"SMTP Email Warning: {e}")
        return False


def send_twilio_sms(to_e164_phone, message_body):
    textbee_key = getattr(settings, 'TEXTBEE_API_KEY', '').strip()
    textbee_device = getattr(settings, 'TEXTBEE_DEVICE_ID', '').strip()

    print(f"\n--- [TEXTBEE SMS DISPATCH TO: {to_e164_phone}] ---\n{message_body}\n--------------------------------------------\n")

    if not textbee_key or not textbee_device:
        return False

    try:
        url = f"https://api.textbee.dev/api/v1/gateway/devices/{textbee_device}/send-sms"
        res = requests.post(
            url,
            json={"recipients": [to_e164_phone], "message": message_body},
            headers={"x-api-key": textbee_key},
            timeout=10,
        )
        if res.status_code in (200, 201):
            return True
        return False
    except Exception as e:
        print("TextBee SMS Error:", e)
        return False


def normalize_ph_phone(phone_raw):
    if not phone_raw:
        return None, None

    raw_str = str(phone_raw).strip()
    digits = re.sub(r'\D', '', raw_str)

    if digits.startswith('6309') and len(digits) == 13:
        digits = digits[2:]
    elif digits.startswith('639') and len(digits) == 12:
        digits = '0' + digits[2:]
    elif digits.startswith('9') and len(digits) == 10:
        digits = '0' + digits

    if len(digits) == 11 and digits.startswith('09'):
        subscriber = digits[1:]
        return f"+63{subscriber}", f"0{subscriber}"

    return None, None


def log_system_activity(notif_type, message, target_user=None, merchant=None, withdrawal=None):
    """
    Creates both an AdminNotification (with timestamp) and a UserNotification for the target user.
    """
    try:
        admin_user = User.objects.filter(user_role='Admin').first() or User.objects.first()
        if admin_user:
            AdminNotification.objects.create(
                user=admin_user,
                admin_notif_type=notif_type[:100],
                message=message,
                merchant=merchant,
                withdrawal=withdrawal,
            )
        if target_user:
            UserNotification.objects.create(
                user=target_user,
                message=message,
            )
    except Exception as e:
        print("Activity log notice:", e)


class SendRegistrationOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        channel = str(request.data.get('channel', '')).strip().lower()
        email = str(request.data.get('email', '')).strip().lower()
        raw_phone = str(
            request.data.get('phone')
            or request.data.get('phone_number')
            or request.data.get('phoneNumber')
            or ''
        ).strip()

        if channel == 'sms' or (raw_phone and not email):
            e164_phone, local_phone = normalize_ph_phone(raw_phone)
            if not e164_phone:
                return Response({
                    "error": f"Invalid Philippine phone number ('{raw_phone}'). Please enter an 11-digit mobile number starting with 09 (e.g. 09123456789)."
                }, status=status.HTTP_400_BAD_REQUEST)

            sms_otp = f"{random.randint(100000, 999999)}"
            sms_key = f"sms_{e164_phone}"
            OTP_MEMORY_STORE[sms_key] = {
                "sms_otp": sms_otp,
                "phone": e164_phone,
                "verified": False,
            }
            try:
                cache.set(f"reserve_{sms_key}", OTP_MEMORY_STORE[sms_key], timeout=600)
            except Exception:
                pass

            sms_sent = send_twilio_sms(
                e164_phone,
                f"RESERVE Cebu: Your 6-digit phone verification code is {sms_otp}. Valid for 10 mins."
            )

            return Response({
                "message": f"6-digit SMS OTP sent to {e164_phone}.",
                "normalized_phone": e164_phone,
                "local_phone": local_phone,
                "sms_sent": sms_sent,
            }, status=status.HTTP_200_OK)

        if not email or '@' not in email:
            return Response({"error": "Please enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(user_email__iexact=email).exists():
            return Response({"error": "This email address is already registered."}, status=status.HTTP_400_BAD_REQUEST)

        email_otp = f"{random.randint(100000, 999999)}"
        OTP_MEMORY_STORE[email] = {
            "email_otp": email_otp,
            "phone": raw_phone,
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

        return Response({
            "message": f"Email verification code sent to {email}.",
            "email_sent": email_sent,
            "dev_otp_preview": email_otp,
        }, status=status.HTTP_200_OK)


class VerifyRegistrationOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        channel = str(request.data.get('channel', '')).strip().lower()
        email = str(request.data.get('email', '')).strip().lower()
        raw_phone = str(
            request.data.get('phone')
            or request.data.get('phone_number')
            or request.data.get('phoneNumber')
            or ''
        ).strip()
        email_code = str(request.data.get('otp', '')).strip()
        sms_code = str(request.data.get('sms_otp', '')).strip()

        if channel == 'sms' or (sms_code and not email_code):
            e164_phone, _ = normalize_ph_phone(raw_phone)
            if not e164_phone:
                return Response({"error": "Invalid Philippine phone number."}, status=status.HTTP_400_BAD_REQUEST)

            sms_key = f"sms_{e164_phone}"
            record = OTP_MEMORY_STORE.get(sms_key) or cache.get(f"reserve_{sms_key}")
            if not record:
                return Response({"error": "SMS OTP expired or not found. Please tap 'Resend OTP'."}, status=status.HTTP_400_BAD_REQUEST)

            if sms_code != str(record.get("sms_otp", "")):
                return Response({"error": "Invalid 6-digit SMS OTP code. Please check your text messages."}, status=status.HTTP_400_BAD_REQUEST)

            record["verified"] = True
            OTP_MEMORY_STORE[sms_key] = record
            try:
                cache.set(f"reserve_{sms_key}", record, timeout=600)
            except Exception:
                pass

            return Response({"message": "Phone number verified successfully!"}, status=status.HTTP_200_OK)

        if raw_phone:
            e164_phone, _ = normalize_ph_phone(raw_phone)
            sms_key = f"sms_{e164_phone}" if e164_phone else ""
            sms_record = OTP_MEMORY_STORE.get(sms_key) or (cache.get(f"reserve_{sms_key}") if sms_key else None)
            if not sms_record or not sms_record.get("verified"):
                return Response({"error": "Please verify your Philippine mobile number via SMS OTP first."}, status=status.HTTP_400_BAD_REQUEST)

        record = OTP_MEMORY_STORE.get(email) or cache.get(f"reserve_otp_{email}")
        if not record:
            return Response({"error": "Email verification session expired. Please request a new code."}, status=status.HTTP_400_BAD_REQUEST)

        expected_email = str(record.get("email_otp", "")) if isinstance(record, dict) else str(record)
        if email_code != expected_email:
            return Response({"error": "Invalid Email OTP code. Please check your inbox."}, status=status.HTTP_400_BAD_REQUEST)

        OTP_MEMORY_STORE.pop(email, None)
        try:
            cache.delete(f"reserve_otp_{email}")
        except Exception:
            pass

        return Response({"message": "Both Phone and Email verified!"}, status=status.HTTP_200_OK)


class ForgotPasswordRequestView(APIView):
    """
    Sends a clickable password reset link to the user's email (or reserve.org.com@gmail.com for Admin).
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        is_admin_portal = bool(request.data.get('is_admin', False))
        email = str(request.data.get('email', '')).strip().lower()

        if is_admin_portal:
            target_user = User.objects.filter(user_role='Admin').first()
            recipient_email = getattr(settings, 'EMAIL_HOST_USER', 'reserve.org.com@gmail.com')
            if not target_user:
                return Response({"error": "No Admin account found in database."}, status=status.HTTP_404_NOT_FOUND)
            account_email = target_user.user_email
        else:
            if not email or '@' not in email:
                return Response({"error": "Please enter your registered email address."}, status=status.HTTP_400_BAD_REQUEST)
            target_user = User.objects.filter(user_email__iexact=email).first()
            if not target_user:
                return Response({"error": "No RESERVE account found with that email address."}, status=status.HTTP_404_NOT_FOUND)
            recipient_email = target_user.user_email
            account_email = target_user.user_email

        token = uuid.uuid4().hex
        PASSWORD_RESET_STORE[token] = {
            "user_id": target_user.user_id,
            "email": account_email,
            "is_admin": is_admin_portal,
        }
        try:
            cache.set(f"reserve_pw_reset_{token}", PASSWORD_RESET_STORE[token], timeout=1800)
        except Exception:
            pass

        host_scheme = request.scheme or "http"
        host_domain = request.get_host() or "127.0.0.1:8000"
        reset_link = f"{host_scheme}://{host_domain}/reset-password/?token={token}&email={account_email}"

        send_compliance_email(
            recipient_email,
            "RESERVE Cebu - Password Reset Link",
            f"Hello,\n\nA password reset was requested for your RESERVE account ({account_email}).\n\n"
            f"Click the link below to set a new password:\n{reset_link}\n\n"
            f"This link is valid for 30 minutes. If you did not request this, you can safely ignore this email."
        )

        return Response({
            "message": f"Password reset link has been sent to {recipient_email}. Please check your inbox and click the link to set a new password."
        }, status=status.HTTP_200_OK)


class ResetPasswordConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = str(request.data.get('token', '')).strip()
        new_password = str(request.data.get('new_password', '')).strip()
        confirm_password = str(request.data.get('confirm_password', '')).strip()

        if not token:
            return Response({"error": "Invalid or missing reset token."}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 6:
            return Response({"error": "Password must be at least 6 characters long."}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != confirm_password:
            return Response({"error": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        record = PASSWORD_RESET_STORE.get(token) or cache.get(f"reserve_pw_reset_{token}")
        if not record:
            return Response({"error": "This password reset link has expired or already been used."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(user_id=record['user_id']).first()
        if not user:
            return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        user.user_pass = make_password(new_password)
        user.save()

        PASSWORD_RESET_STORE.pop(token, None)
        try:
            cache.delete(f"reserve_pw_reset_{token}")
        except Exception:
            pass

        log_system_activity(
            "Security",
            f"Password successfully reset for {user.user_email} ({user.user_role}).",
            target_user=user,
        )

        return Response({"message": "Your password has been updated successfully! You may now log in."}, status=status.HTTP_200_OK)


def reset_password_page(request):
    token = request.GET.get('token', '')
    email = request.GET.get('email', '')
    return render(request, 'reset_password.html', {'token': token, 'email': email})


class UserSettingsToggleView(APIView):
    """
    Persists user notification/automation toggles in User.settings_json so they stay saved after logout/login.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        email = request.GET.get('email', '').strip()
        profile_id = request.GET.get('profile_id', '').strip()
        role = request.GET.get('role', 'Merchant').strip()

        user = None
        if email:
            user = User.objects.filter(user_email__iexact=email).first()
        elif profile_id.isdigit():
            if role.lower() == 'merchant':
                m = Merchant.objects.select_related('user').filter(merch_id=int(profile_id)).first()
                user = m.user if m else None
            elif role.lower() == 'consumer':
                c = Consumer.objects.select_related('user').filter(cons_id=int(profile_id)).first()
                user = c.user if c else None
            elif role.lower() == 'foodbank':
                f = FoodBank.objects.select_related('user').filter(org_id=int(profile_id)).first()
                user = f.user if f else None

        default_settings = {
            "pushNotif": True,
            "smsAlerts": True,
            "emailReports": False,
            "autoDonateExpiry": True,
        }
        if not user:
            return Response(default_settings, status=status.HTTP_200_OK)

        try:
            saved = json.loads(user.settings_json or '{}')
            default_settings.update(saved)
        except Exception:
            pass
        return Response(default_settings, status=status.HTTP_200_OK)

    def post(self, request):
        email = str(request.data.get('email', '')).strip()
        profile_id = str(request.data.get('profile_id', '')).strip()
        role = str(request.data.get('role', 'Merchant')).strip()
        settings_payload = request.data.get('settings', {})

        user = None
        if email:
            user = User.objects.filter(user_email__iexact=email).first()
        if not user and profile_id.isdigit():
            if role.lower() == 'merchant':
                m = Merchant.objects.select_related('user').filter(merch_id=int(profile_id)).first()
                user = m.user if m else None
            elif role.lower() == 'consumer':
                c = Consumer.objects.select_related('user').filter(cons_id=int(profile_id)).first()
                user = c.user if c else None
            elif role.lower() == 'foodbank':
                f = FoodBank.objects.select_related('user').filter(org_id=int(profile_id)).first()
                user = f.user if f else None

        if not user:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            current = json.loads(user.settings_json or '{}')
        except Exception:
            current = {}

        if isinstance(settings_payload, dict):
            current.update(settings_payload)

        user.settings_json = json.dumps(current)
        user.save()
        return Response({"message": "Preferences saved.", "settings": current}, status=status.HTTP_200_OK)


class SupportReportSubmitView(APIView):
    """
    Allows Consumers, Merchants, and Food Banks to submit Help & Support reports/tickets.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        role = str(request.data.get('role', 'User')).strip()
        email = str(request.data.get('email', '')).strip()
        category = str(request.data.get('category', 'General Inquiry')).strip()
        subject = str(request.data.get('subject', '')).strip()
        message = str(request.data.get('message', '')).strip()

        if not subject or not message:
            return Response({"error": "Please provide both a subject and detailed description."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(user_email__iexact=email).first() if email else None
        log_system_activity(
            "Support",
            f"[{role} Report - {category}] From {email or role}: {subject} — {message}",
            target_user=user,
        )

        admin_email = getattr(settings, 'EMAIL_HOST_USER', 'reserve.org.com@gmail.com')
        send_compliance_email(
            admin_email,
            f"RESERVE Help & Support Report [{role}: {category}]",
            f"Reporter Role: {role}\nReporter Email: {email}\nCategory: {category}\nSubject: {subject}\n\nDetails:\n{message}"
        )

        return Response({
            "message": "Your support report has been submitted to the ReServe Admin team. We will respond via email shortly."
        }, status=status.HTTP_201_CREATED)


class MerchantWithdrawalView(APIView):
    """
    Allows Merchants to submit and view withdrawal requests (GCash / Maya) with 10% free-tier fee calculation.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        merch_id = request.GET.get('merchant')
        if not merch_id or not str(merch_id).isdigit():
            return Response([], status=status.HTTP_200_OK)

        qs = WithdrawalReq.objects.filter(merchant_id=int(merch_id)).order_by('-withdrawal_id')
        data = []
        for w in qs:
            data.append({
                "withdrawal_id": w.withdrawal_id,
                "id": f"PO-{w.withdrawal_id}",
                "amount": float(w.amount or 0),
                "channel": w.channel or "GCash",
                "account_number": w.gcash_num,
                "account_name": w.account_name or w.merchant.contact_person or w.merchant.bus_name,
                "fee_deducted": float(w.fee_deducted or 0),
                "net_payout": float(w.net_payout or w.amount or 0),
                "reference_number": w.reference_number or "",
                "status": w.withdrawal_status,
                "created_at": w.created_at.strftime('%Y-%m-%d %I:%M %p') if w.created_at else timezone.now().strftime('%Y-%m-%d'),
                "processed_at": w.processed_at.strftime('%Y-%m-%d %I:%M %p') if w.processed_at else "",
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        merch_id = request.data.get('merchant_id')
        channel = str(request.data.get('channel', 'GCash')).strip()
        account_number = str(request.data.get('account_number', '')).strip()
        account_name = str(request.data.get('account_name', '')).strip()
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
        except Exception:
            return Response({"error": "Invalid withdrawal amount."}, status=status.HTTP_400_BAD_REQUEST)

        merchant = Merchant.objects.select_related('user', 'plan').filter(merch_id=merch_id).first()
        if not merchant:
            return Response({"error": "Merchant account not found."}, status=status.HTTP_404_NOT_FOUND)

        if amount <= Decimal('0'):
            return Response({"error": "Please enter a withdrawal amount greater than ₱0."}, status=status.HTTP_400_BAD_REQUEST)

        if amount > (merchant.wallet_bal or Decimal('0.00')):
            return Response({
                "error": f"Insufficient wallet balance (Available: ₱{float(merchant.wallet_bal or 0):,.2f})."
            }, status=status.HTTP_400_BAD_REQUEST)

        if not account_number or not account_name:
            return Response({"error": f"Please provide your {channel} account number and registered account name."}, status=status.HTTP_400_BAD_REQUEST)

        is_pro = merchant.plan_id == 2 or 'pro' in (merchant.plan.plan_name or '').lower()
        fee_rate = Decimal('0.00') if is_pro else Decimal('0.10')
        fee_deducted = (amount * fee_rate).quantize(Decimal('0.01'))
        net_payout = (amount - fee_deducted).quantize(Decimal('0.01'))

        w_req = WithdrawalReq.objects.create(
            merchant=merchant,
            amount=amount,
            channel=channel,
            gcash_num=account_number,
            account_name=account_name,
            fee_deducted=fee_deducted,
            net_payout=net_payout,
            withdrawal_status='Pending',
        )

        log_system_activity(
            "Payout",
            f"Withdrawal request PO-{w_req.withdrawal_id} from {merchant.bus_name}: ₱{float(amount):,.2f} ({channel} {account_number}, Net: ₱{float(net_payout):,.2f}).",
            target_user=merchant.user,
            merchant=merchant,
            withdrawal=w_req,
        )

        return Response({
            "message": f"Withdrawal request of ₱{float(amount):,.2f} submitted! Net transfer after {'0% Pro' if is_pro else '10% Free-Tier'} fee: ₱{float(net_payout):,.2f}.",
            "withdrawal_id": w_req.withdrawal_id,
        }, status=status.HTTP_201_CREATED)


class UserNotificationsFeedView(APIView):
    """
    Returns both UserNotifications and Broadcast Announcements for Consumers, Merchants, and Food Banks.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        email = request.GET.get('email', '').strip()
        role = request.GET.get('role', 'Consumer').strip()
        profile_id = request.GET.get('profile_id', '').strip()

        user = None
        if email:
            user = User.objects.filter(user_email__iexact=email).first()
        if not user and profile_id.isdigit():
            if role.lower() == 'merchant':
                m = Merchant.objects.select_related('user').filter(merch_id=int(profile_id)).first()
                user = m.user if m else None
            elif role.lower() == 'consumer':
                c = Consumer.objects.select_related('user').filter(cons_id=int(profile_id)).first()
                user = c.user if c else None
            elif role.lower() == 'foodbank':
                f = FoodBank.objects.select_related('user').filter(org_id=int(profile_id)).first()
                user = f.user if f else None

        notifications_data = []
        if user:
            for n in UserNotification.objects.filter(user=user).order_by('-created_at')[:30]:
                notifications_data.append({
                    "id": f"UN-{n.notif_id}",
                    "type": "Activity",
                    "title": "Account & Order Update",
                    "message": n.message,
                    "is_read": n.is_read,
                    "timestamp": n.created_at.strftime('%b %d, %Y • %I:%M %p') if n.created_at else "Just now",
                })

        broadcasts = AdminNotification.objects.filter(admin_notif_type__startswith='Broadcast').order_by('-pk')[:15]
        for b in broadcasts:
            audience = b.admin_notif_type.replace('Broadcast:', '').strip()
            if 'all' in audience.lower() or role.lower() in audience.lower():
                parts = (b.message or '').split(' || ', 1)
                title = parts[0] if len(parts) > 1 else 'System Announcement'
                body = parts[1] if len(parts) > 1 else b.message
                notifications_data.append({
                    "id": f"BC-{b.pk}",
                    "type": "Announcement",
                    "title": title,
                    "message": body,
                    "audience": audience,
                    "is_read": False,
                    "timestamp": b.created_at.strftime('%b %d, %Y • %I:%M %p') if getattr(b, 'created_at', None) else "Official Broadcast",
                })

        return Response({"notifications": notifications_data}, status=status.HTTP_200_OK)


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
                log_system_activity(
                    "Registration",
                    f"New Consumer registered: {full_name} ({user.user_email}).",
                    target_user=user,
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
                log_system_activity(
                    "KYB",
                    f"New Food Bank registration: {org_name} awaiting verification.",
                    target_user=user,
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
            # Inputted bus_name & address from the merchant are stored as the authoritative account name
            merchant = serializer.save()

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

            log_system_activity(
                "KYB",
                f"New merchant application: {merchant.bus_name}. OCR Confidence: {merchant.ocr_confidence}%",
                target_user=merchant.user,
                merchant=merchant,
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

            log_system_activity(
                "KYB",
                f"Food Bank {fb.org_name} resubmitted accreditation document for review.",
                target_user=fb.user,
            )

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

        log_system_activity(
            "KYB",
            f"Resubmitted/Renewed permit from {merchant.bus_name}. OCR Confidence: {merchant.ocr_confidence}%",
            target_user=merchant.user,
            merchant=merchant,
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
                log_system_activity(
                    "Compliance",
                    f"Consumer CID-{consumer.cons_id} ({consumer.cons_fullname}) suspended: {reason}.",
                    target_user=consumer.user,
                )
                return Response({"message": f"Consumer {consumer.cons_fullname} has been suspended."}, status=status.HTTP_200_OK)

            return Response({"error": "Invalid Consumer action"}, status=status.HTTP_400_BAD_REQUEST)

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
                log_system_activity(
                    "Approved",
                    f"Food Bank FB-{fb.org_id} ({fb.org_name}) approved and activated.",
                    target_user=fb.user,
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
                log_system_activity(
                    "Compliance",
                    f"Food Bank FB-{fb.org_id} ({fb.org_name}) requested to resubmit accreditation: {reason}.",
                    target_user=fb.user,
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
                log_system_activity(
                    "Compliance",
                    f"Food Bank FB-{fb.org_id} ({fb.org_name}) suspended: {reason}.",
                    target_user=fb.user,
                )
                return Response({"message": f"Food Bank {fb.org_name} suspended."}, status=status.HTTP_200_OK)

            elif action == 'notify':
                send_compliance_email(
                    fb.user.user_email,
                    "Important Notice from ReServe Admin",
                    f"Hello {fb.org_name},\n\nAdmin Notice: {reason}"
                )
                log_system_activity(
                    "Compliance",
                    f"Admin Notice to {fb.org_name}: {reason}",
                    target_user=fb.user,
                )
                return Response({"message": "Notification sent to Food Bank."}, status=status.HTTP_200_OK)

            return Response({"error": "Invalid Food Bank action"}, status=status.HTTP_400_BAD_REQUEST)

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
                # Save OCR comparison data ONLY to ocr_extracted_text (NEVER overwrite merchant.bus_name or merchant.address)
                for key in ['business_name', 'permit_number', 'lgu_anchor', 'business_address', 'nature_of_business', 'calendar_year', 'representative']:
                    if key in ocr_edits:
                        current_ocr[key] = ocr_edits[key]
                merchant.ocr_extracted_text = json.dumps(current_ocr)

                if ocr_edits.get('expiry_date'):
                    merchant.bus_expiry_date = ocr_edits['expiry_date']

            merchant.is_verified = True
            merchant.status = 'Active'
            merchant.status_reason = ''
            merchant.save()
            merchant.user.is_banned = False
            merchant.user.save()

            log_system_activity(
                "Approved",
                f"Merchant MID-{merchant.merch_id} ({merchant.bus_name}) approved by Admin.",
                target_user=merchant.user,
                merchant=merchant,
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
            log_system_activity(
                "Compliance",
                f"Merchant MID-{merchant.merch_id} ({merchant.bus_name}) requested to resubmit permit: {reason}.",
                target_user=merchant.user,
                merchant=merchant,
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
            log_system_activity(
                "Compliance",
                f"Merchant MID-{merchant.merch_id} ({merchant.bus_name}) suspended: {reason}.",
                target_user=merchant.user,
                merchant=merchant,
            )
            return Response({"message": f"Merchant {merchant.bus_name} has been suspended."}, status=status.HTTP_200_OK)

        elif action == 'notify':
            is_renewal = request.data.get('is_renewal', False)
            if is_renewal:
                merchant.status = 'Renewal Required'
                merchant.status_reason = reason
                merchant.save()

            log_system_activity(
                "Compliance",
                f"Compliance Notice to {merchant.bus_name}: {reason}",
                target_user=merchant.user,
                merchant=merchant,
            )
            send_compliance_email(
                merchant.user.user_email,
                "Official Compliance Notice - ReServe Admin",
                f"Hello {merchant.bus_name},\n\nMessage from ReServe Admin:\n\"{reason}\"\n\n"
                f"Please log into your ReServe Merchant Portal to take any necessary action."
            )
            return Response({"message": f"Notification sent to {merchant.bus_name}."}, status=status.HTTP_200_OK)

        return Response({"error": "Invalid action parameter."}, status=status.HTTP_400_BAD_REQUEST)


def fetch_dynamic_records(app_labels, filter_kwargs=None, limit=15):
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

                    title = None
                    for field in ['prod_name', 'food_name', 'item_name', 'title', 'listing_name', 'name', 'description']:
                        if hasattr(obj, field) and getattr(obj, field):
                            title = str(getattr(obj, field))
                            break
                    if not title and hasattr(obj, 'listing') and getattr(obj, 'listing'):
                        listing_obj = getattr(obj, 'listing')
                        if hasattr(listing_obj, 'listing') and hasattr(listing_obj.listing, 'product'):
                            title = listing_obj.listing.product.prod_name
                        else:
                            for f in ['prod_name', 'food_name', 'item_name', 'title', 'name']:
                                if hasattr(listing_obj, f):
                                    title = str(getattr(listing_obj, f))
                                    break

                    est_name = None
                    if hasattr(obj, 'merchant') and getattr(obj, 'merchant'):
                        est_name = getattr(obj.merchant, 'bus_name', str(obj.merchant))
                    elif hasattr(obj, 'listing') and getattr(obj, 'listing'):
                        l_obj = getattr(obj, 'listing')
                        if hasattr(l_obj, 'merchant'):
                            est_name = getattr(l_obj.merchant, 'bus_name', '')
                        elif hasattr(l_obj, 'listing') and hasattr(l_obj.listing, 'product'):
                            est_name = getattr(l_obj.listing.product.merchant, 'bus_name', '')

                    buyer_name = None
                    if hasattr(obj, 'consumer') and getattr(obj, 'consumer'):
                        buyer_name = getattr(obj.consumer, 'cons_fullname', str(obj.consumer))
                    elif hasattr(obj, 'foodbank') and getattr(obj, 'foodbank'):
                        buyer_name = getattr(obj.foodbank, 'org_name', str(obj.foodbank))
                    elif hasattr(obj, 'food_bank') and getattr(obj, 'food_bank'):
                        buyer_name = getattr(obj.food_bank, 'org_name', str(obj.food_bank))

                    amount_str = "Donation"
                    for field in ['downpayment_amount', 'total_amount', 'amount', 'discounted_price', 'price', 'orig_price']:
                        if hasattr(obj, field) and getattr(obj, field) is not None:
                            val = getattr(obj, field)
                            try:
                                amount_str = f"₱{float(val):,.2f}"
                            except Exception:
                                amount_str = str(val)
                            break
                    if amount_str == "Donation":
                        for qfield in ['order_qty', 'quantity', 'qty', 'weight_kg']:
                            if hasattr(obj, qfield) and getattr(obj, qfield) is not None:
                                amount_str = f"{getattr(obj, qfield)} qty/kg"
                                break

                    status_val = "Active"
                    for sfield in ['order_status', 'status', 'claim_status', 'listing_status', 'withdrawal_status']:
                        if hasattr(obj, sfield) and getattr(obj, sfield):
                            status_val = str(getattr(obj, sfield))
                            break

                    date_str = datetime.date.today().strftime('%Y-%m-%d')
                    for dfield in ['ordered_at', 'created_at', 'order_date', 'date_created', 'claimed_at', 'pickup_time', 'expiry_date']:
                        if hasattr(obj, dfield) and getattr(obj, dfield):
                            dval = getattr(obj, dfield)
                            if hasattr(dval, 'strftime'):
                                date_str = dval.strftime('%Y-%m-%d %I:%M %p')
                            else:
                                date_str = str(dval)[:16]
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


def admin_user_transactions_api(request, role, account_id):
    role_clean = role.lower()
    records = []

    if role_clean in ('consumer', 'merchant'):
        if role_clean == 'consumer':
            orders = OrderReservation.objects.select_related(
                'consumer',
                'listing__listing__product__merchant',
                'listing__listing__product__unit'
            ).filter(consumer_id=account_id).order_by('-ordered_at', 'order_id')[:40]
        else:
            orders = OrderReservation.objects.select_related(
                'consumer',
                'listing__listing__product__merchant',
                'listing__listing__product__unit'
            ).filter(listing__listing__product__merchant_id=account_id).order_by('-ordered_at', 'order_id')[:40]

        grouped = {}
        for o in orders:
            b_code = str(o.qr_voucher_code or f"ORD-{o.order_id}").split("-")[0]
            comm = o.listing
            saf = comm.listing if comm else None
            prod = saf.product if saf else None
            merch = prod.merchant if prod else None

            u_price = Decimal(str(comm.discounted_price if comm else 0))
            o_price = Decimal(str(comm.orig_price if comm and comm.orig_price else u_price))
            line_tot = (u_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
            dep = Decimal(str(o.downpayment_amount or 0)).quantize(Decimal('0.01'))
            rem = max(Decimal('0.00'), line_tot - dep)

            item_entry = {
                "name": prod.prod_name if prod else f"Item #{o.order_id}",
                "qty": o.order_qty,
                "unit_price": f"₱{float(u_price):,.2f}",
                "orig_price": f"₱{float(o_price):,.2f}",
                "subtotal": f"₱{float(line_tot):,.2f}",
            }

            if b_code not in grouped:
                grouped[b_code] = {
                    "id": b_code,
                    "items": [item_entry],
                    "establishment": merch.bus_name if merch else "Partner Merchant",
                    "address": merch.address if merch and merch.address else "Cebu City",
                    "buyer": o.consumer.cons_fullname if o.consumer else "Consumer",
                    "buyer_email": o.consumer.user.user_email if (o.consumer and o.consumer.user) else "",
                    "date": timezone.localtime(o.ordered_at).strftime('%b %d, %Y • %I:%M %p') if o.ordered_at else 'N/A',
                    "pickup_deadline": timezone.localtime(saf.estimated_expiry).strftime('%b %d, %Y • %I:%M %p') if (saf and saf.estimated_expiry) else 'Standard Window',
                    "total_dec": line_tot,
                    "dep_dec": dep,
                    "rem_dec": rem,
                    "status": o.order_status,
                }
            else:
                g = grouped[b_code]
                g["items"].append(item_entry)
                g["total_dec"] += line_tot
                g["dep_dec"] += dep
                g["rem_dec"] += rem

        for b_code, g in grouped.items():
            it_list = g["items"]
            title_str = (
                f"{it_list[0]['name']} (x{it_list[0]['qty']})"
                if len(it_list) == 1
                else f"{it_list[0]['name']} +{len(it_list) - 1} more"
            )
            records.append({
                "id": b_code,
                "title": title_str,
                "items_breakdown": it_list,
                "establishment": g["establishment"],
                "address": g["address"],
                "buyer": g["buyer"],
                "buyer_email": g["buyer_email"],
                "date": g["date"],
                "pickup_deadline": g["pickup_deadline"],
                "total_value": f"₱{float(g['total_dec']):,.2f}",
                "deposit_paid": f"₱{float(g['dep_dec']):,.2f}",
                "remaining_balance": f"₱{float(g['rem_dec']):,.2f}",
                "amount": f"₱{float(g['total_dec']):,.2f} (10% Dep: ₱{float(g['dep_dec']):,.2f})",
                "status": g["status"],
            })
    elif role_clean == 'foodbank':
        records = fetch_dynamic_records(['donations'], {'foodbank_id': account_id, 'food_bank_id': account_id}, limit=15)

    return JsonResponse({'transactions': records})

@csrf_exempt
def update_admin_profile_api(request):
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


def get_base_admin_context(active_page):
    admin_user = User.objects.filter(user_role='Admin').first()
    return {
        'active_page': active_page,
        'pending_merchants': Merchant.objects.filter(status='Pending').count(),
        'recent_notifications': AdminNotification.objects.select_related('merchant').order_by('-pk')[:10],
        'admin_email': admin_user.user_email if admin_user else 'reserve.org.com@gmail.com',
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
    """
    Displays all food listings categorized by Active vs. Flagged/Expired, with full expiry date & time,
    plus clickable Merchant Profile cards displaying active listing counts and full merchant histories.
    """
    context = get_base_admin_context('food-listing')
    merchant_filter = request.GET.get('merchant', '').replace('MID-', '').strip()
    selected_merch_id = int(merchant_filter) if merchant_filter.isdigit() else None

    from listings.models import PerishableProduct, ListingSafety, ListingCommerce

    now = timezone.now()
    products_qs = PerishableProduct.objects.select_related('category', 'unit', 'merchant__user', 'merchant__plan').order_by('-prod_id')
    if selected_merch_id:
        products_qs = products_qs.filter(merchant_id=selected_merch_id)

    listings_list = []
    active_listings_count = 0
    flagged_listings_count = 0
    expired_listings_count = 0

    # Track per-merchant active/total counts
    merch_listing_stats = {}

    all_products = list(PerishableProduct.objects.select_related('category', 'unit', 'merchant__user', 'merchant__plan').order_by('-prod_id'))
    safety_records = {
        s.product_id: s
        for s in ListingSafety.objects.select_related('commerce').all()
    }

    for prod in all_products:
        m_id = prod.merchant_id
        if m_id not in merch_listing_stats:
            merch_listing_stats[m_id] = {'active': 0, 'flagged_expired': 0, 'total': 0, 'items': []}

        s_rec = safety_records.get(prod.prod_id)
        comm = getattr(s_rec, 'commerce', None) if s_rec else None

        status_val = comm.status if comm else 'Active'
        qty_val = comm.qty_available if comm else 1
        orig_p = float(comm.orig_price) if comm else 0.0
        disc_p = float(comm.current_price or comm.discounted_price) if comm else 0.0

        expiry_dt = s_rec.estimated_expiry if s_rec else None
        if expiry_dt:
            if timezone.is_naive(expiry_dt):
                expiry_dt = timezone.make_aware(expiry_dt)
            if expiry_dt <= now and status_val == 'Active':
                status_val = 'Expired'
            expiry_str = timezone.localtime(expiry_dt).strftime('%b %d, %Y %I:%M %p')
            date_str = timezone.localtime(expiry_dt).strftime('%Y-%m-%d')
        else:
            expiry_str = 'Not Set'
            date_str = datetime.date.today().strftime('%Y-%m-%d')

        is_flagged_or_expired = ('flag' in status_val.lower()) or ('expir' in status_val.lower()) or (qty_val <= 0 and status_val != 'Active')
        category_bucket = 'flagged_expired' if is_flagged_or_expired else 'active'

        merch_listing_stats[m_id]['total'] += 1
        if category_bucket == 'active':
            merch_listing_stats[m_id]['active'] += 1
        else:
            merch_listing_stats[m_id]['flagged_expired'] += 1

        item_dict = {
            'raw_id': prod.prod_id,
            'id': f"FL-{prod.prod_id}",
            'title': prod.prod_name,
            'description': prod.prod_desc or 'Fresh surplus food item listed for community rescue.',
            'establishment': prod.merchant.bus_name if prod.merchant else 'Verified Partner',
            'merchant_id': m_id,
            'address': prod.merchant.address if prod.merchant and prod.merchant.address else 'Cebu City, Philippines',
            'date': date_str,
            'expiry': expiry_str,
            'temperature': f"{float(s_rec.posted_temp):.1f}°C" if s_rec and s_rec.posted_temp else "28.0°C",
            'quantity': f"{qty_val} {prod.unit.unit_name if prod.unit else 'pcs'}",
            'orig_price': f"₱{orig_p:,.2f}",
            'disc_price': f"₱{disc_p:,.2f}",
            'category': prod.category.category_name if prod.category else (prod.merchant.merch_type if prod.merchant else 'Surplus'),
            'status': status_val,
            'bucket': category_bucket,
            'image_url': prod.image_path if str(prod.image_path).startswith('http') else (f"/media/{prod.image_path}" if prod.image_path else ""),
        }
        merch_listing_stats[m_id]['items'].append(item_dict)

        if not selected_merch_id or selected_merch_id == m_id:
            listings_list.append(item_dict)
            if category_bucket == 'active':
                active_listings_count += 1
            else:
                if 'flag' in status_val.lower():
                    flagged_listings_count += 1
                else:
                    expired_listings_count += 1

    # Build clickable Merchant Profiles cards with ratings & histories
    merchant_profiles = []
    for m in Merchant.objects.select_related('user', 'plan').all().order_by('-merch_id'):
        m_stats = merch_listing_stats.get(m.merch_id, {'active': 0, 'flagged_expired': 0, 'total': 0, 'items': []})
        reviews_qs = RatingReview.objects.filter(surplus_listing__listing__product__merchant=m)
        rev_count = reviews_qs.count()
        avg_score = reviews_qs.aggregate(avg=Avg('rating_score'))['avg'] or 0.0

        merchant_profiles.append({
            'merch_id': m.merch_id,
            'id_label': f"MID-{m.merch_id}",
            'bus_name': m.bus_name,
            'merch_type': m.merch_type,
            'address': m.address or 'Cebu City, Cebu',
            'contact_person': m.contact_person or 'Owner',
            'phone': m.phone or 'N/A',
            'hotline': m.hotline or 'N/A',
            'email': m.user.user_email,
            'status': m.status,
            'plan_name': m.plan.plan_name if m.plan else 'Basic',
            'wallet_bal': f"₱{float(m.wallet_bal or 0):,.2f}",
            'expiry_date': m.bus_expiry_date.strftime('%Y-%m-%d') if m.bus_expiry_date else 'N/A',
            'permit_url': f"/media/{m.bus_permit_path}" if m.bus_permit_path else '',
            'active_count': m_stats['active'],
            'flagged_expired_count': m_stats['flagged_expired'],
            'total_count': m_stats['total'],
            'avg_rating': f"{float(avg_score):.1f}",
            'review_count': rev_count,
            'items_json': json.dumps(m_stats['items']),
        })

    claimed_count = OrderReservation.objects.filter(order_status='Completed').count()

    context.update({
        'listings': listings_list,
        'merchant_profiles': merchant_profiles,
        'selected_merch_id': selected_merch_id,
        'active_listings_count': active_listings_count,
        'active_stores_count': Merchant.objects.filter(status='Active').count(),
        'claimed_produce_count': claimed_count,
        'flagged_listings_count': flagged_listings_count + expired_listings_count,
    })
    return render(request, 'admin_food_listing.html', context)


def admin_donations(request):
    context = get_base_admin_context('donations')
    fb_filter = request.GET.get('foodbank', '').replace('FB-', '').strip()
    selected_fb_id = int(fb_filter) if fb_filter.isdigit() else None
    filter_kwargs = {'foodbank_id': selected_fb_id, 'food_bank_id': selected_fb_id} if selected_fb_id else None

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
        if selected_fb_id and fb.org_id != selected_fb_id:
            continue
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

    # Build clickable Food Bank Profile cards for Visit Profile redirection
    foodbank_profiles = []
    for fb in FoodBank.objects.select_related('user').all().order_by('-org_id'):
        foodbank_profiles.append({
            'org_id': fb.org_id,
            'id_label': f"FB-{fb.org_id}",
            'org_name': fb.org_name,
            'address': fb.address or 'Cebu City, Cebu',
            'contact_person': fb.contact_person or 'Coordinator',
            'phone': fb.phone or 'N/A',
            'hotline': fb.hotline or 'N/A',
            'email': fb.user.user_email,
            'status': fb.status,
            'total_received': float(fb.total_food_received or 0),
            'permit_url': f"/media/{fb.accreditation_path}" if fb.accreditation_path else '',
            'date': fb.user.created_at.strftime('%Y-%m-%d'),
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
        'foodbank_profiles': foodbank_profiles,
        'selected_fb_id': selected_fb_id,
    })
    return render(request, 'admin_donation_hub.html', context)

def admin_payouts(request):
    context = get_base_admin_context('payouts')
    payout_rows = []
    pending_count = 0
    approved_count = 0
    processing_count = 0

    withdrawals = WithdrawalReq.objects.select_related('merchant__user', 'merchant__plan').order_by('-withdrawal_id')
    for w in withdrawals:
        m = w.merchant
        bal = float(m.wallet_bal or 0)
        amt = float(w.amount or 0)
        is_pro = m.plan_id == 2 or ('pro' in (m.plan.plan_name or '').lower() if m.plan else False)
        fee = float(w.fee_deducted) if w.fee_deducted is not None else (0.0 if is_pro else round(amt * 0.10, 2))
        net = float(w.net_payout) if w.net_payout is not None else round(amt - fee, 2)
        st = w.withdrawal_status or 'Pending'

        if 'pend' in st.lower():
            pending_count += 1
        elif 'approv' in st.lower() or 'settled' in st.lower():
            approved_count += 1
        else:
            processing_count += 1

        payout_rows.append({
            'raw_id': w.withdrawal_id,
            'id': f"PO-{w.withdrawal_id}",
            'is_merchant_wallet': False,
            'merchant_id': f"MID-{m.merch_id}",
            'merchant_name': m.bus_name,
            'contact_person': m.contact_person or 'Owner',
            'merchant_phone': m.phone or 'N/A',
            'merchant_email': m.user.user_email,
            'tier_name': 'Pro Tier (0% Fee)' if is_pro else 'Free Tier (10% Fee)',
            'channel': w.channel or 'GCash',
            'account_number': w.gcash_num or m.phone or '09170000000',
            'account_name': w.account_name or m.contact_person or m.bus_name,
            'date': w.created_at.strftime('%Y-%m-%d %I:%M %p') if w.created_at else m.user.created_at.strftime('%Y-%m-%d'),
            'current_balance': f"₱{bal:,.2f}",
            'requested_amount': f"₱{amt:,.2f}",
            'fee_deducted': f"₱{fee:,.2f}",
            'net_payout': f"₱{net:,.2f}",
            'reference_number': w.reference_number or '',
            'status': st,
        })

    if not payout_rows:
        merchants_with_bal = Merchant.objects.select_related('user', 'plan').all().order_by('-wallet_bal', '-user__created_at')
        for m in merchants_with_bal:
            bal = float(m.wallet_bal or 0)
            is_pro = m.plan_id == 2
            fee = 0.0 if is_pro else round(bal * 0.10, 2)
            net = round(bal - fee, 2)
            st = 'Pending' if bal > 0 else 'Settled'
            if st == 'Pending':
                pending_count += 1
            else:
                approved_count += 1
            payout_rows.append({
                'raw_id': m.merch_id,
                'id': f"PO-{m.merch_id}",
                'is_merchant_wallet': True,
                'merchant_id': f"MID-{m.merch_id}",
                'merchant_name': m.bus_name,
                'contact_person': m.contact_person or 'Owner',
                'merchant_phone': m.phone or 'N/A',
                'merchant_email': m.user.user_email,
                'tier_name': 'Pro Tier (0% Fee)' if is_pro else 'Free Tier (10% Fee)',
                'channel': 'GCash',
                'account_number': m.phone or 'Not Set',
                'account_name': m.contact_person or m.bus_name,
                'date': m.user.created_at.strftime('%Y-%m-%d'),
                'current_balance': f"₱{bal:,.2f}",
                'requested_amount': f"₱{bal:,.2f}",
                'fee_deducted': f"₱{fee:,.2f}",
                'net_payout': f"₱{net:,.2f}",
                'reference_number': '',
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
        b_dt = timezone.localtime(b.created_at) if getattr(b, 'created_at', None) else timezone.now()
        broadcasts.append({
            'id': b.pk,
            'audience': audience,
            'title': title,
            'body': body,
            'created_at_str': b_dt.strftime('%b %d, %Y • %I:%M %p'),
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
            from listings.models import PerishableProduct, ListingSafety
            prod = PerishableProduct.objects.select_related('merchant__user').filter(prod_id=raw_id).first()
            if prod:
                if action == 'delete':
                    prod_name = prod.prod_name
                    merch_user = prod.merchant.user if prod.merchant else None
                    prod.delete()
                    log_system_activity(
                        "Listing",
                        f"Admin removed food listing '{prod_name}'.",
                        target_user=merch_user,
                    )
                    return JsonResponse({'message': 'Listing removed.'})
                elif action == 'flag':
                    s_rec = ListingSafety.objects.select_related('commerce').filter(product=prod).first()
                    if s_rec and hasattr(s_rec, 'commerce'):
                        s_rec.commerce.status = 'Flagged'
                        s_rec.commerce.save()
                    log_system_activity(
                        "Compliance",
                        f"Your food listing '{prod.prod_name}' was flagged by Admin for review.",
                        target_user=prod.merchant.user if prod.merchant else None,
                        merchant=prod.merchant,
                    )
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
            is_wallet = data.get('is_merchant_wallet', False)
            reference_number = str(data.get('reference_number', '')).strip()
            reject_reason = str(data.get('reason', 'Invalid account details')).strip()

            if action == 'approve' and not reference_number:
                return JsonResponse({'error': 'Please enter the GCash/Maya transfer reference number to confirm payout.'}, status=400)

            if is_wallet:
                merchant = Merchant.objects.select_related('user').filter(merch_id=raw_id).first()
                if merchant:
                    if action == 'approve':
                        paid_amt = merchant.wallet_bal
                        merchant.wallet_bal = Decimal('0.00')
                        merchant.save()
                        log_system_activity(
                            "Payout",
                            f"Payout of ₱{float(paid_amt):,.2f} settled for {merchant.bus_name} (Ref #: {reference_number}).",
                            target_user=merchant.user,
                            merchant=merchant,
                        )
                        send_compliance_email(
                            merchant.user.user_email,
                            "RESERVE Cebu - Payout Transferred!",
                            f"Hello {merchant.bus_name},\n\nYour wallet payout of ₱{float(paid_amt):,.2f} has been transferred!\n"
                            f"Transfer Reference Number: {reference_number}\n\nThank you for partnering with RESERVE Cebu."
                        )
                    return JsonResponse({'message': f'Payout {action}d for {merchant.bus_name}.'})
            else:
                w_obj = WithdrawalReq.objects.select_related('merchant__user').filter(withdrawal_id=raw_id).first()
                if w_obj:
                    merchant = w_obj.merchant
                    if action == 'approve':
                        w_obj.withdrawal_status = 'Approved'
                        w_obj.reference_number = reference_number
                        w_obj.processed_at = timezone.now()
                        w_obj.save()

                        if merchant.wallet_bal >= w_obj.amount:
                            merchant.wallet_bal -= w_obj.amount
                        else:
                            merchant.wallet_bal = Decimal('0.00')
                        merchant.save()

                        log_system_activity(
                            "Payout",
                            f"Withdrawal PO-{w_obj.withdrawal_id} (₱{float(w_obj.amount):,.2f} via {w_obj.channel or 'GCash'}) approved for {merchant.bus_name}. Ref #: {reference_number}.",
                            target_user=merchant.user,
                            merchant=merchant,
                            withdrawal=w_obj,
                        )
                        send_compliance_email(
                            merchant.user.user_email,
                            "RESERVE Cebu - Withdrawal Approved & Transferred",
                            f"Hello {merchant.bus_name},\n\nYour withdrawal request (PO-{w_obj.withdrawal_id}) for ₱{float(w_obj.amount):,.2f} "
                            f"(Net Transfer: ₱{float(w_obj.net_payout or w_obj.amount):,.2f} to {w_obj.channel or 'GCash'} {w_obj.gcash_num}) has been approved!\n\n"
                            f"Official Transfer Reference Number: {reference_number}"
                        )
                        return JsonResponse({'message': f'Withdrawal PO-{w_obj.withdrawal_id} approved with Ref #{reference_number}.'})
                    else:
                        w_obj.withdrawal_status = 'Rejected'
                        w_obj.processed_at = timezone.now()
                        w_obj.save()
                        log_system_activity(
                            "Payout",
                            f"Withdrawal PO-{w_obj.withdrawal_id} for {merchant.bus_name} was rejected ({reject_reason}).",
                            target_user=merchant.user,
                            merchant=merchant,
                            withdrawal=w_obj,
                        )
                        return JsonResponse({'message': f'Withdrawal PO-{w_obj.withdrawal_id} rejected.'})
            return JsonResponse({'message': 'Payout updated.'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Unknown module or action'}, status=400)