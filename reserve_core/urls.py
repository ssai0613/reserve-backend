
from django.contrib import admin
from django.urls import path, include
from accounts import views as custom_admin_views

urlpatterns = [
    # Default Django Admin (Moved slightly so it doesn't conflict with your custom dashboard)
    path('sys-admin/', admin.site.urls), 
    
    # API Endpoints
    path('api/accounts/', include('accounts.urls')),
    
    # Teammates' Custom Admin GUI Routes
    path('', custom_admin_views.login, name='custom-login'),
    path('dashboard/', custom_admin_views.admin_dashboard, name='custom-dashboard'),
    path('users/', custom_admin_views.admin_users, name='custom-users'),
    path('food-listing/', custom_admin_views.admin_food_listing, name='custom-food-listing'),
    path('donations/', custom_admin_views.admin_donations, name='custom-donations'),
    path('payouts/', custom_admin_views.admin_payouts, name='custom-payouts'),
    path('announcements/', custom_admin_views.admin_announcements, name='custom-announcements'),
]