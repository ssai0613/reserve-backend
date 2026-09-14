from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User

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

        # Check the hashed password
        if not check_password(password, user.user_pass):
            raise serializers.ValidationError({"error": "Invalid email or password"})

        # Manually generate the JWT tokens
        refresh = RefreshToken()
        refresh['user_id'] = user.user_id 
        
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'role': user.user_role
        }