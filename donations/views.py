from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import FoodBank, Merchant, User, Location
from listings.models import Category
from .models import Donation, DonationRequest
from .serializers import (
    DonationRequestSerializer,
    DonationSerializer,
    donation_expires_at,
    donation_food_name,
    donation_unit,
)

DEFAULT_FOOD_TYPES = [
    "Bread & Pastries",
    "Cooked Meals",
    "Fruits & Vegetables",
    "Meat & Seafood",
    "Dairy & Eggs",
    "Beverages",
    "Other",
]

OFFER_SELECT = (
    'merchant',
    'merchant__user',
    'listing__listing__product__category',
    'listing__listing__product__unit',
)
OFFER_PREFETCH = ('merchant__user__locations', 'merchant__contacts')


class FoodBankAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


def resolve_foodbank(request):
    org_id = (
        request.GET.get('org_id')
        or request.data.get('org_id')
        or request.GET.get('foodbank')
    )
    email = request.GET.get('email') or request.data.get('email')
    if org_id and str(org_id).isdigit():
        fb = FoodBank.objects.select_related('user').filter(org_id=int(org_id)).first()
        if fb:
            return fb
    if email:
        fb = FoodBank.objects.select_related('user').filter(user__user_email__iexact=str(email).strip()).first()
        if fb:
            return fb
    return FoodBank.objects.select_related('user').order_by('-org_id').first()


def seconds_left(donation):
    expires = donation_expires_at(donation)
    if not expires:
        return None
    return max(0, int((expires - timezone.now()).total_seconds()))


class DonationRequestView(FoodBankAPIView):
    def get(self, request):
        fb = resolve_foodbank(request)
        requests_qs = DonationRequest.objects.all().select_related('merchant', 'food_bank').order_by('-donation_req_id')
        if request.GET.get('org_id') and fb:
            requests_qs = requests_qs.filter(food_bank=fb)
        return Response(DonationRequestSerializer(requests_qs, many=True).data)

    def post(self, request):
        fb = resolve_foodbank(request)
        serializer = DonationRequestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(food_bank=fb, status='Active')
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        req_id = request.data.get('donation_req_id')
        new_status = request.data.get('status', 'Cancelled')

        req_obj = DonationRequest.objects.filter(donation_req_id=req_id).first()
        if not req_obj:
            return Response({"error": "Request not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.data.get('merchant'):
            m_obj = Merchant.objects.filter(merch_id=request.data.get('merchant')).first()
            if m_obj:
                req_obj.merchant = m_obj

        req_obj.status = new_status
        req_obj.updated_at = timezone.now()
        req_obj.save()
        return Response(DonationRequestSerializer(req_obj).data)


class FoodTypesView(FoodBankAPIView):
    def get(self, request):
        names = list(Category.objects.order_by('category_name').values_list('category_name', flat=True))
        return Response({"food_types": names or DEFAULT_FOOD_TYPES})


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
        fb = resolve_foodbank(request)
        action = request.data.get('action')

        if action not in ('accept', 'decline', 'received'):
            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            donation = Donation.objects.select_for_update().filter(donation_id=donation_id).first()
            if not donation:
                return Response({"error": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)

            if action == 'accept':
                donation.food_bank = fb
                donation.status = 'Claimed'
            elif action == 'decline':
                donation.status = 'Declined'
            else:
                donation.status = 'Completed'
                target_fb = donation.food_bank or fb
                if target_fb:
                    target_fb.total_food_received = Decimal(str(target_fb.total_food_received or 0)) + Decimal(str(donation.qty_donated or 1))
                    target_fb.save(update_fields=['total_food_received'])

            donation.updated_at = timezone.now()
            donation.save()

        return Response(DonationSerializer(donation).data)


def build_activity(fb=None, limit=100):
    """
    Builds role-specific notifications & activity strictly for the Food Bank.
    """
    events = []
    req_qs = DonationRequest.objects.filter(food_bank=fb).select_related('merchant') if fb else DonationRequest.objects.all().select_related('merchant')

    for r in req_qs:
        if r.status == 'Fulfilled':
            m_name = r.merchant.bus_name if r.merchant else "A partner merchant"
            events.append({
                "id": f"req-{r.donation_req_id}-fulfilled",
                "type": "request",
                "title": "Wishlist Request Fulfilled!",
                "detail": f"{m_name} fulfilled your request for {r.qty_needed} units of {r.food_type}.",
                "time": r.updated_at or r.created_at,
                "is_read": False,
            })
        else:
            events.append({
                "id": f"req-{r.donation_req_id}-posted",
                "type": "request",
                "title": f"Request ({r.status}): {r.food_type}",
                "detail": f"{r.qty_needed} items requested · Status: {r.status}",
                "time": r.created_at,
                "is_read": True,
            })

    for d in Donation.objects.all().select_related('merchant', 'merchant__user', 'food_bank'):
        if d.food_bank and fb and d.food_bank.org_id != fb.org_id and d.status != 'Active':
            continue

        merchant_name = d.merchant.bus_name if d.merchant else "Partner Merchant"
        unit_str = donation_unit(d) or "items"
        food_str = donation_food_name(d) or "Surplus Food"

        if d.status == 'Active':
            events.append({
                "id": f"don-{d.donation_id}-active",
                "type": "donation",
                "title": "New Surplus Donation Available!",
                "detail": f"{merchant_name} posted {d.qty_donated} {unit_str} of {food_str} for pickup.",
                "time": d.created_at,
                "is_read": False,
            })
        elif d.status in ('Claimed', 'Completed'):
            events.append({
                "id": f"don-{d.donation_id}-{d.status.lower()}",
                "type": "donation",
                "title": "Donation Claimed" if d.status == "Claimed" else "Donation Handoff Completed",
                "detail": f"{d.qty_donated} {unit_str} of {food_str} from {merchant_name} ({d.status}).",
                "time": d.updated_at or d.created_at,
                "is_read": False,
            })

    events.sort(key=lambda e: e["time"], reverse=True)
    for e in events:
        e["time"] = e["time"].isoformat()
    return events[:limit]


class ActivityLogView(FoodBankAPIView):
    def get(self, request):
        fb = resolve_foodbank(request)
        return Response(build_activity(fb=fb))


class DashboardView(FoodBankAPIView):
    def get(self, request):
        fb = resolve_foodbank(request)
        my_requests = DonationRequest.objects.filter(food_bank=fb) if fb else DonationRequest.objects.all()
        active_requests = list(my_requests.filter(status='Active').select_related('merchant').order_by('-donation_req_id'))

        offers_qs = Donation.objects.filter(status='Active').select_related(*OFFER_SELECT).prefetch_related(*OFFER_PREFETCH).order_by('donation_id')
        offers = list(offers_qs)

        in_prog_count = Donation.objects.filter(food_bank=fb, status__in=['Claimed', 'In-Transit']).count() if fb else 0
        exp_soon = sum(1 for o in offers if (seconds_left(o) or 999999) < 10800)
        partner_ids = set(Donation.objects.filter(status__in=['Claimed', 'Completed']).values_list('merchant_id', flat=True))

        return Response({
            "org_name": fb.org_name if fb else "Food Bank Portal",
            "stats": {
                "total_requests": my_requests.count(),
                "active_requests": len(active_requests),
                "fulfilled_requests": my_requests.filter(status='Fulfilled').count(),
                "offers_available": len(offers),
                "expiring_soon": exp_soon,
                "in_progress": in_prog_count,
                "food_received": float(fb.total_food_received or 0) if fb else 0.0,
                "partners": len(partner_ids),
            },
            "urgent_offers": DonationSerializer(offers[:3], many=True).data,
            "active_requests": DonationRequestSerializer(active_requests[:3], many=True).data,
            "recent_activity": build_activity(fb=fb, limit=5),
        })


class PartnersView(FoodBankAPIView):
    def get(self, request):
        fb = resolve_foodbank(request)
        merchants = Merchant.objects.select_related('user').all()
        partners_list = []
        total_items_received = 0

        for m in merchants:
            m_donations = Donation.objects.filter(merchant=m).order_by('-created_at')
            if not m_donations.exists():
                continue

            active_offers = m_donations.filter(status='Active').count()
            completed_dons = m_donations.filter(status__in=['Completed', 'Claimed'])
            rec_qty = sum(int(d.qty_donated or 0) for d in completed_dons)
            total_items_received += rec_qty
            req_filled = DonationRequest.objects.filter(merchant=m, status='Fulfilled').count()

            history = []
            for d in m_donations[:5]:
                history.append({
                    "food_name": donation_food_name(d) or "Surplus Bundle",
                    "qty": d.qty_donated,
                    "unit": donation_unit(d) or "units",
                    "status": d.status,
                    "date": d.created_at.strftime("%Y-%m-%d") if d.created_at else "",
                })

            last_dt = m_donations.first().created_at.isoformat() if m_donations.first() and m_donations.first().created_at else ""
            partners_list.append({
                "merchant_id": m.merch_id,
                "name": m.bus_name,
                "type": m.merch_type or "Food Establishment",
                "is_verified": m.is_verified,
                "address": m.address or "Cebu City",
                "contact_phone": m.phone or m.hotline or "Not Provided",
                "contact_name": m.contact_person or "Store Manager",
                "contact_email": m.user.user_email if m.user else "",
                "donations_count": m_donations.count(),
                "received_qty": rec_qty,
                "requests_fulfilled": req_filled,
                "active_offers": active_offers,
                "last_activity": last_dt,
                "history": history,
            })

        return Response({
            "partners": partners_list,
            "summary": {
                "count": len(partners_list),
                "items_received": total_items_received,
            },
        })


class FoodBankProfilePortalView(FoodBankAPIView):
    """
    Enterprise Settings & Live Profile endpoint for Food Bank accounts.
    """
    def get(self, request, org_id):
        fb = resolve_foodbank(request)
        if org_id and str(org_id).isdigit():
            found = FoodBank.objects.select_related('user').filter(org_id=int(org_id)).first()
            if found:
                fb = found
        if not fb:
            return Response({"error": "Food Bank not found"}, status=status.HTTP_404_NOT_FOUND)

        loc = Location.objects.filter(user=fb.user).order_by('-is_primary', '-loc_id').first()
        return Response({
            "org_id": fb.org_id,
            "org_name": fb.org_name,
            "contact_person": fb.contact_person or "Coordinator",
            "email": fb.user.user_email,
            "phone": fb.phone or "",
            "hotline": fb.hotline or "",
            "address": fb.address or "Cebu City",
            "status": fb.status,
            "accreditation_path": fb.accreditation_path or "",
            "total_food_received": float(fb.total_food_received or 0),
            "latitude": float(loc.latitude) if loc else 10.3157,
            "longitude": float(loc.longitude) if loc else 123.8854,
        })

    def post(self, request, org_id):
        fb = resolve_foodbank(request)
        if org_id and str(org_id).isdigit():
            found = FoodBank.objects.select_related('user').filter(org_id=int(org_id)).first()
            if found:
                fb = found
        if not fb:
            return Response({"error": "Food Bank not found"}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get("action")
        if action == "update_profile":
            fb.org_name = request.data.get("org_name", fb.org_name)
            fb.contact_person = request.data.get("contact_person", fb.contact_person)
            fb.phone = request.data.get("phone", fb.phone)
            fb.hotline = request.data.get("hotline", fb.hotline)
            fb.address = request.data.get("address", fb.address)
            fb.save()

            new_email = request.data.get("email", "").strip()
            if new_email and new_email != fb.user.user_email:
                fb.user.user_email = new_email
                fb.user.save()

            if "latitude" in request.data and "longitude" in request.data:
                try:
                    lat_v = float(request.data["latitude"])
                    lng_v = float(request.data["longitude"])
                    loc_obj = Location.objects.filter(user=fb.user).order_by('-is_primary', '-loc_id').first()
                    if loc_obj:
                        loc_obj.address_name = fb.address or "Cebu City"
                        loc_obj.latitude = lat_v
                        loc_obj.longitude = lng_v
                        loc_obj.save()
                    else:
                        Location.objects.create(
                            user=fb.user,
                            address_name=fb.address or "Cebu City",
                            latitude=lat_v,
                            longitude=lng_v,
                            is_primary=True,
                        )
                except Exception:
                    pass
            return Response({"message": "Food Bank profile and Cebu City location updated!"})

        elif action == "change_password":
            new_pw = request.data.get("new_password", "").strip()
            if len(new_pw) < 6:
                return Response({"error": "Password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)
            fb.user.user_pass = make_password(new_pw)
            fb.user.save()
            return Response({"message": "Password updated successfully!"})

        return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)