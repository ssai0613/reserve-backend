from django.urls import path
from .views import MarketplaceFeedView, CreateListingView, UpdateListingView, DeleteListingView, EstablishmentNotificationsView, EstablishmentListingsView
from . import views



urlpatterns = [
    path('', MarketplaceFeedView.as_view(), name='marketplace-feed-root'), # <--- Add this line!
    path('feed/', MarketplaceFeedView.as_view(), name='marketplace-feed'),
    path('create/', CreateListingView.as_view(), name='create-listing'),
    path('update/<int:pk>/', UpdateListingView.as_view(), name='update-listing'),
    path('delete/<int:pk>/', DeleteListingView.as_view(), name='delete-listing'),
    path('calculate-preview/', views.CalculateExpiryPreviewView.as_view(), name='calculate_preview'),
    path('notifications/', EstablishmentNotificationsView.as_view(), name='establishment-notifications'),
    path('establishment/', EstablishmentListingsView.as_view(), name='establishment-listings'),
]