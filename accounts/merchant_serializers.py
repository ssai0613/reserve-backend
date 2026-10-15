from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.core.files.storage import default_storage
from .models import User, Merchant

class MerchantRegistrationSerializer(serializers.ModelSerializer):
    # User fields
    user_email = serializers.EmailField(write_only=True)
    user_pass = serializers.CharField(write_only=True)
    
    # Merchant fields
    bus_name = serializers.CharField(max_length=255)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    contact_person = serializers.CharField(max_length=255, required=False, allow_blank=True)
    hotline = serializers.CharField(max_length=50, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    merch_type = serializers.CharField(max_length=50)
    
    bus_permit_path = serializers.FileField()
    bus_expiry_date = serializers.DateField()

    class Meta:
        model = Merchant
        fields = [
            'user_email', 'user_pass', 'bus_name', 
            'address', 'contact_person', 'hotline', 'phone',
            'merch_type', 'bus_permit_path', 'bus_expiry_date'
        ]

    def create(self, validated_data):
        email = validated_data.pop('user_email')
        password = validated_data.pop('user_pass')
        
        permit_file = validated_data.pop('bus_permit_path')
        saved_path = default_storage.save(permit_file.name, permit_file)
        
        user = User.objects.create(
            user_email=email,
            user_pass=make_password(password),
            user_role='Merchant'
        )
        
        merchant = Merchant.objects.create(
            user=user,
            plan_id=1, 
            is_verified=False,
            status='Pending',
            bus_permit_path=saved_path,
            **validated_data # This automatically handles address, contact_person, hotline, and phone
        )
        return merchant