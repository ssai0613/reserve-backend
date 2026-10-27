from django.urls import path
from .views import (
    CreatePayMongoCheckoutView,
    MarketplaceFeedView,
    CreateListingView,
    UpdateListingView,
    DeleteListingView,
    EstablishmentNotificationsView,
    EstablishmentAnnouncementsView,
    EstablishmentListingsView,
    CalculateExpiryPreviewView,
    MerchantPortalSummaryView,
    ConsumerPortalView,
)

urlpatterns = [
    path('', MarketplaceFeedView.as_view(), name='marketplace-feed-root'),
    path('feed/', MarketplaceFeedView.as_view(), name='marketplace-feed'),
    path('create/', CreateListingView.as_view(), name='create-listing'),
    path('update/<int:pk>/', UpdateListingView.as_view(), name='update-listing'),
    path('delete/<int:pk>/', DeleteListingView.as_view(), name='delete-listing'),
    path('calculate-preview/', CalculateExpiryPreviewView.as_view(), name='calculate_preview'),
    path('notifications/', EstablishmentNotificationsView.as_view(), name='establishment-notifications'),
    path('announcements/', EstablishmentAnnouncementsView.as_view(), name='establishment-announcements'),
    path('establishment/', EstablishmentListingsView.as_view(), name='establishment-listings'),
    path('merchant-portal/<str:merch_id>/', MerchantPortalSummaryView.as_view(), name='merchant-portal-summary'),
    path('consumer-portal/<str:cons_id>/', ConsumerPortalView.as_view(), name='consumer-portal'),
    path('paymongo-checkout/', CreatePayMongoCheckoutView.as_view(), name='paymongo-checkout'),
]