from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import User

class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['user_email', 'user_pass', 'user_role']
        extra_kwargs = {
            'user_pass': {'write_only': True} # Ensures the password is never returned in API responses
        }

    def create(self, validated_data):
        # Securely hash the password before saving to the database
        validated_data['user_pass'] = make_password(validated_data['user_pass'])
        return super().create(validated_data)