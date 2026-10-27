from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    SendRegistrationOTPView,
    VerifyRegistrationOTPView,
    UserRegistrationView,
    CustomLoginView,
    MerchantRegistrationView,
    AdminMerchantApprovalView,
    DocumentResubmissionView,
    admin_user_transactions_api,
    update_admin_profile_api,
    admin_portal_action_api,
)

urlpatterns = [
    path('send-otp/', SendRegistrationOTPView.as_view(), name='send-otp'),
    path('verify-otp/', VerifyRegistrationOTPView.as_view(), name='verify-otp'),
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('register/merchant/', MerchantRegistrationView.as_view(), name='merchant-register'),
    path('admin/merchants/', AdminMerchantApprovalView.as_view(), name='admin-merchant-list'),
    path('admin/merchants/<int:merch_id>/', AdminMerchantApprovalView.as_view(), name='admin-merchant-action'),
    path('login/', CustomLoginView.as_view(), name='token_obtain_pair'),
    path('login/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('admin/merchant/<int:merch_id>/approval/', AdminMerchantApprovalView.as_view(), name='admin-merchant-approval'),
    path('merchant/<int:merch_id>/resubmit-permit/', DocumentResubmissionView.as_view(), name='merchant-resubmit-permit'),
    path('admin/user-transactions/<str:role>/<int:account_id>/', admin_user_transactions_api, name='admin-user-transactions'),
    path('admin/profile/update/', update_admin_profile_api, name='admin-profile-update'),
    path('admin/portal-action/', admin_portal_action_api, name='admin-portal-action'),
]