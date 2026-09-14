from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import UserRegistrationSerializer, CustomLoginSerializer
from .models import Consumer, Merchant, User
from django.contrib.auth.hashers import check_password
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .merchant_serializers import MerchantRegistrationSerializer
from .utils import simulate_ocr_extraction
from notifications.models import AdminNotification
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

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

class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomLoginSerializer

class MerchantRegistrationView(APIView):
    parser_classes = (MultiPartParser, FormParser) # Required to accept image/file uploads

    def post(self, request):
        serializer = MerchantRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            merchant = serializer.save()
            
            # Run the OCR extraction on the uploaded permit
            ocr_results = simulate_ocr_extraction(merchant.bus_permit_path)
            
            # Create an admin notification for the validation queue
            AdminNotification.objects.create(
                user_id=1, # Assumes admin user ID is 1
                admin_notif_type='KYB',
                message=f"New merchant application: {merchant.bus_name}. OCR Confidence: {ocr_results['confidence_score']}%",
                merchant=merchant
            )
            
            return Response({
                "message": "Merchant registration submitted successfully. Under review by admin.",
                "merchant_id": merchant.merch_id,
                "ocr_analysis": ocr_results
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AdminMerchantApprovalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Optional: Verify if the requester is an Admin
        try:
            user = User.objects.get(user_email=request.user.username) # or request.user depending on auth setup
            if user.user_role != 'Admin':
                return Response({"error": "Unauthorized access"}, status=status.HTTP_403_FORBIDDEN)
        except User.DoesNotExist:
            pass

        # Fetch all merchants whose verification is pending
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
        # Approve or reject merchant application
        action = request.data.get('action') # Expected: 'approve' or 'reject'

        try:
            merchant = Merchant.objects.get(merch_id=merch_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        if action == 'approve':
            merchant.is_verified = True
            merchant.status = 'Active'
            merchant.save()
            return Response({"message": f"Merchant {merchant.bus_name} has been approved successfully."}, status=status.HTTP_200_OK)
        
        elif action == 'reject':
            merchant.is_verified = False
            merchant.status = 'Rejected'
            merchant.save()
            return Response({"message": f"Merchant {merchant.bus_name} application has been rejected."}, status=status.HTTP_200_OK)

        return Response({"error": "Invalid action parameter. Use 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)