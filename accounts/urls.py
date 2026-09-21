from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import UserRegistrationView, CustomLoginView, MerchantRegistrationView, AdminMerchantApprovalView
from . import views

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('register/merchant/', MerchantRegistrationView.as_view(), name='merchant-register'),
    path('admin/merchants/', AdminMerchantApprovalView.as_view(), name='admin-merchant-list'),
    path('admin/merchants/<int:merch_id>/', AdminMerchantApprovalView.as_view(), name='admin-merchant-action'),
    path('login/', CustomLoginView.as_view(), name='token_obtain_pair'),
    path('login/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('admin/merchant/<int:merch_id>/approval/', views.AdminMerchantApprovalView.as_view(), name='admin-merchant-approval'),
]