from decimal import Decimal
from accounts.models import FoodBank


from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from listings.models import Category
from .models import Donation, DonationRequest
from .serializers import (
    DonationRequestSerializer, DonationSerializer,
    donation_expires_at, donation_food_name, donation_unit,
    merchant_address, merchant_contact,
)

DEFAULT_FOOD_TYPES = [
    "Bread & Pastries", "Cooked Meals", "Fruits & Vegetables",
    "Meat & Seafood", "Dairy & Eggs", "Beverages", "Other",
]

OFFER_SELECT = (
    'merchant', 'merchant__user',
    'listing__listing__product__category', 'listing__listing__product__unit',
)
OFFER_PREFETCH = ('merchant__user__locations', 'merchant__contacts')


class FoodBankAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


def seconds_left(donation):
    expires = donation_expires_at(donation)
    if not expires:
        return None
    return max(0, int((expires - timezone.now()).total_seconds()))


# ---------------------------------------------------------------
# REQUESTS
# ---------------------------------------------------------------

class DonationRequestView(FoodBankAPIView):
    def get(self, request):
        # Temporary: returns all requests or empty list while auth is in progress
        requests_qs = DonationRequest.objects.all().select_related('merchant').order_by('-donation_req_id')
        return Response(DonationRequestSerializer(requests_qs, many=True).data)

    def post(self, request):
        serializer = DonationRequestSerializer(data=request.data)
        if serializer.is_valid():
            # Get the first food bank as a temporary fallback while auth is being built
            dummy_fb = FoodBank.objects.first()
            serializer.save(food_bank=dummy_fb, status='Active')
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request):
        """A food bank can cancel its requests."""
        dummy_fb = FoodBank.objects.first()
        
        req_id = request.data.get('donation_req_id')
        new_status = request.data.get('status', 'Cancelled')

        req_obj = DonationRequest.objects.filter(
            donation_req_id=req_id, food_bank=dummy_fb
        ).first()
        
        # Fallback search if food_bank didn't match during testing
        if not req_obj:
            req_obj = DonationRequest.objects.filter(donation_req_id=req_id).first()

        if not req_obj:
            return Response({"error": "Request not found."}, status=status.HTTP_404_NOT_FOUND)

        req_obj.status = new_status
        req_obj.updated_at = timezone.now()
        req_obj.save()
        
        return Response(DonationRequestSerializer(req_obj).data)


class FoodTypesView(FoodBankAPIView):
    def get(self, request):
        names = list(Category.objects.order_by('category_name')
                     .values_list('category_name', flat=True))
        return Response({"food_types": names or DEFAULT_FOOD_TYPES})


# ---------------------------------------------------------------
# DONATION OFFERS
# ---------------------------------------------------------------

class AvailableDonationsView(FoodBankAPIView):
    def get(self, request):
        donations = Donation.objects.all().select_related(*OFFER_SELECT).prefetch_related(*OFFER_PREFETCH).order_by('-donation_id')
        return Response(DonationSerializer(donations, many=True).data)

    def post(self, request):
        serializer = DonationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(status='Active')
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DonationRespondView(FoodBankAPIView):
    def patch(self, request, donation_id):
        dummy_fb = FoodBank.objects.first()
        action = request.data.get('action')
        
        if action not in ('accept', 'decline', 'received'):
            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            donation = Donation.objects.select_for_update().filter(donation_id=donation_id).first()
            if not donation:
                return Response({"error": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)

            if action == 'accept':
                donation.food_bank = dummy_fb
                donation.status = 'Claimed'
            elif action == 'decline':
                donation.status = 'Declined'
            else:  # received
                donation.status = 'Completed'
                if dummy_fb:
                    dummy_fb.total_food_received += Decimal(donation.qty_donated)
                    dummy_fb.save(update_fields=['total_food_received'])

            donation.updated_at = timezone.now()
            donation.save()

        return Response(DonationSerializer(donation).data)


# ---------------------------------------------------------------
# ACTIVITY LOG
# ---------------------------------------------------------------

def build_activity(limit=100):
    events = []
    
    # Requests posted by the food bank
    for r in DonationRequest.objects.all().select_related('merchant'):
        detail = f"{r.qty_needed} items · {r.food_type}"
        events.append({
            "id": f"req-{r.donation_req_id}-posted", 
            "type": "request",
            "title": "You posted a request", 
            "detail": detail, 
            "time": r.created_at,
            "is_read": True
        })

    # Donations posted by merchants (Triggers the notification)
    for d in Donation.objects.all().select_related('merchant', 'merchant__user'):
        merchant_name = "A partner merchant"
        if d.merchant:
            if hasattr(d.merchant, 'establishment_name') and d.merchant.establishment_name:
                merchant_name = d.merchant.establishment_name
            elif d.merchant.user:
                user = d.merchant.user
                merchant_name = getattr(user, 'first_name', None) or getattr(user, 'username', 'A partner merchant')

        # Safely extract unit and food name using your serializer helpers
        unit_str = donation_unit(d) or "items"
        food_str = donation_food_name(d) or "Surplus Food"

        detail = f"{merchant_name} posted a new donation: {d.qty_donated} {unit_str} of {food_str}"
        
        events.append({
            "id": f"don-{d.donation_id}-posted", 
            "type": "donation",
            "title": "New Merchant Donation Posted!", 
            "detail": detail, 
            "time": d.created_at,
            "is_read": False
        })

    events.sort(key=lambda e: e["time"], reverse=True)
    for e in events:
        e["time"] = e["time"].isoformat()
    return events[:limit]


class ActivityLogView(FoodBankAPIView):
    def get(self, request):
        return Response(build_activity())


# ---------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------

class DashboardView(FoodBankAPIView):
    def get(self, request):
        my_requests = DonationRequest.objects.all()
        active_requests = list(my_requests.filter(status='Active').select_related('merchant').order_by('-donation_req_id'))
        
        # Fetch actual available donations for urgent offers
        offers_qs = Donation.objects.filter(status='Active').select_related(*OFFER_SELECT).prefetch_related(*OFFER_PREFETCH).order_by('donation_id')
        offers = list(offers_qs)

        return Response({
            "org_name": "Food Bank Portal",
            "stats": {
                "total_requests": my_requests.count(),
                "active_requests": len(active_requests),
                "fulfilled_requests": my_requests.filter(status='Fulfilled').count(),
                "offers_available": len(offers),
                "expiring_soon": 0,
                "in_progress": 0,
                "food_received": 0.0,
                "partners": 0,
            },
            "urgent_offers": DonationSerializer(offers[:3], many=True).data,
            "active_requests": DonationRequestSerializer(active_requests[:3], many=True).data,
            "recent_activity": build_activity(limit=5),
        })


# ---------------------------------------------------------------
# PARTNERS
# ---------------------------------------------------------------

class PartnersView(FoodBankAPIView):
    def get(self, request):
        return Response({
            "partners": [],
            "summary": {
                "count": 0,
                "items_received": 0,
            },
        })