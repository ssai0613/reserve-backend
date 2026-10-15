import datetime
from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, Merchant, Consumer, FoodBank


class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['user_email', 'user_pass', 'user_role']
        extra_kwargs = {
            'user_pass': {'write_only': True}
        }

    def create(self, validated_data):
        validated_data['user_pass'] = make_password(validated_data['user_pass'])
        return super().create(validated_data)


class CustomLoginSerializer(serializers.Serializer):
    user_email = serializers.EmailField()
    user_pass = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('user_email')
        password = attrs.get('user_pass')

        try:
            user = User.objects.get(user_email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"error": "Invalid email or password"})

        if not check_password(password, user.user_pass):
            raise serializers.ValidationError({"error": "Invalid email or password"})

        role = user.user_role
        account_status = 'Active'
        status_reason = ''
        profile_id = user.user_id
        entity_name = ''
        expiry_date_str = ''

        if role == 'Merchant':
            try:
                merchant = Merchant.objects.get(user=user)
                profile_id = merchant.merch_id
                entity_name = merchant.bus_name
                account_status = merchant.status
                status_reason = merchant.status_reason or ''
                expiry_date_str = str(merchant.bus_expiry_date) if merchant.bus_expiry_date else ''

                # Automatic Annual Permit Expiry Check on Login
                if merchant.bus_expiry_date and account_status == 'Active':
                    days_until_expiry = (merchant.bus_expiry_date - datetime.date.today()).days
                    if days_until_expiry < 0:
                        account_status = 'Renewal Required'
                        status_reason = f"Your Business Permit expired on {merchant.bus_expiry_date}. Please upload your renewed permit to continue operating."
                        merchant.status = account_status
                        merchant.status_reason = status_reason
                        merchant.save()
                    elif days_until_expiry <= 30:
                        # Warn them or prompt renewal if within 30 days
                        status_reason = f"Your Business Permit expires in {days_until_expiry} days ({merchant.bus_expiry_date})."
            except Merchant.DoesNotExist:
                pass

        elif role == 'FoodBank':
            try:
                fb = FoodBank.objects.get(user=user)
                profile_id = fb.org_id
                entity_name = fb.org_name
                account_status = fb.status
                status_reason = fb.status_reason or ''
                expiry_date_str = str(fb.accreditation_expiry) if fb.accreditation_expiry else ''
            except FoodBank.DoesNotExist:
                pass

        elif role == 'Consumer':
            try:
                cons = Consumer.objects.get(user=user)
                profile_id = cons.cons_id
                entity_name = cons.cons_fullname
                account_status = cons.status or 'Active'
                status_reason = cons.status_reason or ''
            except Consumer.DoesNotExist:
                pass

        refresh = RefreshToken()
        refresh['user_id'] = user.user_id

        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'role': role,
            'profile_id': profile_id,
            'entity_name': entity_name,
            'account_status': account_status,
            'status_reason': status_reason,
            'expiry_date': expiry_date_str
        }