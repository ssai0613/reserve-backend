from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import UserRegistrationSerializer
from .models import Consumer

class UserRegistrationView(APIView):
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            
            # Automatically create a related profile based on the user_role
            role = user.user_role.lower()
            if role == 'consumer':
                # Create a blank consumer profile attached to this new user
                Consumer.objects.create(user=user, cons_fullname="New Consumer")
            
            # Merchants and Food Banks require KYB document uploads in a separate step
            
            return Response({
                "message": "Account created successfully", 
                "user_id": user.user_id,
                "role": user.user_role
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)