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
    merch_type = serializers.CharField(max_length=50)
    bus_permit_path = serializers.FileField() # Accepts the incoming file
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
        
        # --- NEW: INTERCEPT AND SAVE THE PHYSICAL FILE ---
        permit_file = validated_data.pop('bus_permit_path')
        saved_path = default_storage.save(permit_file.name, permit_file)
        
        # Create the base user with role 'Merchant'
        user = User.objects.create(
            user_email=email,
            user_pass=make_password(password),
            user_role='Merchant'
        )
        
        # Create the merchant profile linked to this user
        merchant = Merchant.objects.create(
            user=user,
            plan_id=1, 
            is_verified=False,
            status='Pending',
            bus_permit_path=saved_path, # Save the physical file's location to the DB
            **validated_data
        )
        return merchant