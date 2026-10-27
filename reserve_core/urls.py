from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sys-admin/', admin.site.urls),

    # Teammates' Mobile App & Auth APIs (Mapped with and without 'api/' prefix)
    path('api/listings/', include('listings.urls')),
    path('listings/', include('listings.urls')),
    
    path('api/accounts/', include('accounts.urls')),
    path('accounts/', include('accounts.urls')),
    
    path('api/donations/', include('donations.urls')),
    path('donations/', include('donations.urls')),
    
    path('api/transactions/', include('transactions.urls')),
    path('transactions/', include('transactions.urls')),

    path('api/auth/', include('dj_rest_auth.urls')),
    path('api/auth/registration/', include('dj_rest_auth.registration.urls')),
    path('api/auth/social/', include('allauth.urls')),

    # ReServe Custom Admin Web Portal GUI Routes
    path('', views.login, name='custom-login'),
    path('login/', views.login, name='login-alias'),
    path('dashboard/', views.admin_dashboard, name='custom-dashboard'),
    path('users/', views.admin_users, name='custom-users'),
    path('food-listing/', views.admin_food_listing, name='custom-food-listing'),
    path('donations-view/', views.admin_donations, name='custom-donations'),
    path('payouts/', views.admin_payouts, name='custom-payouts'),
    path('announcements/', views.admin_announcements, name='custom-announcements'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)