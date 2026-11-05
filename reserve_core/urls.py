from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Mobile & Web App APIs
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

    # ReServe Admin Web Portal & Password Reset Portal Routes
    path('', views.login, name='custom-login'),
    path('login/', views.login, name='login-alias'),
    path('reset-password/', views.reset_password_page, name='reset-password-page'),
    path('dashboard/', views.admin_dashboard, name='custom-dashboard'),
    path('users/', views.admin_users, name='custom-users'),
    path('food-listing/', views.admin_food_listing, name='custom-food-listing'),
    path('donations/', views.admin_donations, name='custom-donations-main'),
    path('donations-view/', views.admin_donations, name='custom-donations'),
    path('payouts/', views.admin_payouts, name='custom-payouts'),
    path('announcements/', views.admin_announcements, name='custom-announcements'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)