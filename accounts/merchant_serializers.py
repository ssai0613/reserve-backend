from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import User, Merchant

class MerchantRegistrationSerializer(serializers.ModelSerializer):
    # User fields
    user_email = serializers.EmailField(write_only=True)
    user_pass = serializers.CharField(write_only=True)
    
    # Merchant fields
    bus_name = serializers.CharField(max_length=255)
    merch_type = serializers.CharField(max_length=50)
    bus_permit_path = serializers.FileField() # Handles file uploads
    bus_expiry_date = serializers.DateField()

    class Meta:
        model = Merchant
        fields = [
            'user_email', 'user_pass', 'bus_name', 
            'merch_type', 'bus_permit_path', 'bus_expiry_date'
        ]

    def create(self, validated_data):
        # Extract user data
        email = validated_data.pop('user_email')
        password = validated_data.pop('user_pass')
        
        # Create the base user with role 'Merchant'
        user = User.objects.create(
            user_email=email,
            user_pass=make_password(password),
            user_role='Merchant'
        )
        
        # Create the merchant profile linked to this user
        merchant = Merchant.objects.create(
            user=user,
            plan_id=1, # Defaults to Basic Plan
            is_verified=False,
            status='Pending',
            **validated_data
        )
        return merchant