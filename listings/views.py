import re
import random
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from .utils import get_cebu_weather, calculate_ttt_expiry
from .models import (
    PerishableProduct,
    ListingSafety,
    ListingCommerce,
    Category,
    UnitMetrics,
    SafetyThreshold,
    StockLedger,
)
from accounts.models import Merchant, Consumer, User, SubscriptionPlan, Location
from donations.models import Donation
from notifications.models import AdminNotification
from transactions.models import OrderReservation, PaymentTransaction, WithdrawalReq
from .serializers import PerishableProductSerializer
from .utils import get_cebu_weather, calculate_ttt_expiry, calculate_haversine_km

import requests as http_requests
from django.conf import settings


def ensure_listing_reference_data():
    """
    Seeds SubscriptionPlan (1-2), UnitMetrics (1-4), Category (1-8), and SafetyThreshold (1)
    so foreign key lookups never fail.
    """
    SubscriptionPlan.objects.get_or_create(
        plan_id=1,
        defaults={"plan_name": "Free Tier (Basic)", "commission_rate": Decimal("10.00")},
    )
    SubscriptionPlan.objects.get_or_create(
        plan_id=2,
        defaults={"plan_name": "Premium Tier (Pro)", "commission_rate": Decimal("0.00")},
    )

    units = {
        1: "Gram (g)",
        2: "Kilogram (kg)",
        3: "Piece (pc)",
        4: "Pack (pk)",
    }
    for uid, uname in units.items():
        UnitMetrics.objects.get_or_create(unit_id=uid, defaults={"unit_name": uname})

    categories = {
        1: "Bread",
        2: "Pastry",
        3: "Cake",
        4: "Custom/Others",
        5: "Leafy Greens",
        6: "Vegetables",
        7: "Fruits",
        8: "Root Crops",
    }
    for cid, cname in categories.items():
        Category.objects.get_or_create(category_id=cid, defaults={"category_name": cname})

    SafetyThreshold.objects.get_or_create(
        threshold_id=1,
        defaults={
            "food_category": "General Perishable",
            "storage_type": "Standard",
            "max_safe_hours": 48,
        },
    )


def resolve_merchant(raw_id=None, email=None):
    if raw_id and str(raw_id).isdigit():
        m = Merchant.objects.select_related('user').filter(merch_id=int(raw_id)).first()
        if m:
            return m
    if email:
        m = Merchant.objects.select_related('user').filter(user__user_email__iexact=str(email).strip()).first()
        if m:
            return m
    return Merchant.objects.select_related('user').order_by('-merch_id').first()


def parse_frontend_expiry(expiry_date_str, expiry_time_str):
    if not expiry_date_str or not expiry_time_str:
        return None
    try:
        clean_date = str(expiry_date_str).replace(',', '').replace('Sept ', 'Sep ').strip()
        clean_time = re.sub(r'\s+', ' ', str(expiry_time_str).replace('\u202f', ' ').replace('\xa0', ' ')).strip()
        combined_str = f"{clean_date} {clean_time}"
        naive_dt = datetime.strptime(combined_str, "%b %d %Y %I:%M %p")
        return timezone.make_aware(naive_dt)
    except Exception as e:
        print("Expiry parse fallback notice:", e)
        return None


class MarketplaceFeedView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        donated_commerce_ids = Donation.objects.values_list('listing_id', flat=True)
        donated_product_ids = ListingCommerce.objects.filter(
            listing_id__in=donated_commerce_ids
        ).values_list('listing__product_id', flat=True)

        # 1. Resolve Consumer's GPS Coordinates (defaults to Cebu City center: 10.3157, 123.8854)
        cons_lat, cons_lng = 10.3157, 123.8854
        req_lat = request.GET.get('lat')
        req_lng = request.GET.get('lng')
        cons_id = request.GET.get('consumer')
        email = request.GET.get('email')

        if req_lat and req_lng:
            try:
                cons_lat, cons_lng = float(req_lat), float(req_lng)
            except ValueError:
                pass
        else:
            consumer_obj = None
            if cons_id and str(cons_id).isdigit():
                consumer_obj = Consumer.objects.select_related('user').filter(cons_id=int(cons_id)).first()
            if not consumer_obj and email:
                consumer_obj = Consumer.objects.select_related('user').filter(user__user_email__iexact=str(email).strip()).first()
            if consumer_obj:
                loc = Location.objects.filter(user=consumer_obj.user).order_by('-is_primary', '-loc_id').first()
                if loc:
                    cons_lat, cons_lng = float(loc.latitude), float(loc.longitude)

        now = timezone.now()
        listings = PerishableProduct.objects.select_related('category', 'merchant__user').exclude(
            prod_id__in=donated_product_ids
        )

        max_radius_km = float(request.GET.get('radius', 10.0))
        serialized_feed = []

        for item in listings:
            safety_rec = ListingSafety.objects.filter(product=item).first()
            if safety_rec:
                try:
                    if safety_rec.commerce.status in ['Draft', 'Flagged', 'Expired', 'Donated']:
                        continue
                    if (safety_rec.commerce.qty_available or 0) <= 0:
                        continue
                except Exception:
                    pass

                if safety_rec.estimated_expiry:
                    expiry_dt = safety_rec.estimated_expiry
                    if timezone.is_naive(expiry_dt):
                        expiry_dt = timezone.make_aware(expiry_dt)

                    if (expiry_dt - now).total_seconds() <= 1800:
                        continue

            # 2. Look up Merchant's GPS Coordinates & compute Haversine Distance
            merch_lat, merch_lng = 10.3157, 123.8854
            if item.merchant and item.merchant.user_id:
                m_loc = Location.objects.filter(user_id=item.merchant.user_id).order_by('-is_primary', '-loc_id').first()
                if m_loc:
                    merch_lat, merch_lng = float(m_loc.latitude), float(m_loc.longitude)

            dist_km = calculate_haversine_km(cons_lat, cons_lng, merch_lat, merch_lng)

            # Enforce 10 km Haversine radius matching
            if dist_km <= max_radius_km:
                item_data = PerishableProductSerializer(item).data
                item_data['distance_km'] = dist_km
                item_data['distance'] = f"{dist_km:.1f} km"
                item_data['merchant_lat'] = merch_lat
                item_data['merchant_lng'] = merch_lng
                serialized_feed.append(item_data)

        # Sort by nearest distance first, then by ID
        serialized_feed.sort(key=lambda x: x.get('distance_km', 99.0))
        return Response(serialized_feed, status=status.HTTP_200_OK)


class EstablishmentListingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        ensure_listing_reference_data()

        merchant = resolve_merchant(
            request.GET.get('merchant'),
            request.GET.get('email')
        )
        if merchant:
            listings = PerishableProduct.objects.filter(merchant=merchant).select_related('category', 'merchant')
        else:
            listings = PerishableProduct.objects.all().select_related('category', 'merchant')

        donated_commerce_ids = Donation.objects.values_list('listing_id', flat=True)
        donated_product_ids = ListingCommerce.objects.filter(
            listing_id__in=donated_commerce_ids
        ).values_list('listing__product_id', flat=True)

        listings = listings.exclude(prod_id__in=donated_product_ids)
        now = timezone.now()

        serialized_data = []
        flagged_count = 0

        for item in listings:
            serializer = PerishableProductSerializer(item)
            data = serializer.data

            item_status = data.get('status', 'Active')
            safety_rec = ListingSafety.objects.filter(product=item).first()

            if safety_rec and safety_rec.estimated_expiry and item_status == 'Active':
                expiry_dt = safety_rec.estimated_expiry
                if timezone.is_naive(expiry_dt):
                    expiry_dt = timezone.make_aware(expiry_dt)

                seconds_remaining = (expiry_dt - now).total_seconds()
                if seconds_remaining <= 1830:
                    item_status = "Flagged"
                    try:
                        commerce = safety_rec.commerce
                        commerce.status = "Flagged"
                        commerce.save()
                    except Exception:
                        pass

            if item_status == "Flagged":
                flagged_count += 1

            data['status'] = item_status
            serialized_data.append(data)

        return Response({
            "listings": serialized_data,
            "flagged_count": flagged_count
        }, status=status.HTTP_200_OK)


class CalculateExpiryPreviewView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        prep_date_str = request.GET.get('prep_date', None)
        storage = request.GET.get('storage', 'Ambient (25°C)')
        category_name = request.GET.get('category', 'Bakery')

        current_temp, _ = get_cebu_weather()

        prep_dt = timezone.now()
        if prep_date_str:
            try:
                cleaned_str = prep_date_str.replace(',', '').replace('Sept ', 'Sep ').strip()
                try:
                    prep_dt = datetime.strptime(cleaned_str, "%b %d %Y %I:%M %p")
                except ValueError:
                    prep_dt = datetime.strptime(cleaned_str, "%b %d %Y")

                if timezone.is_naive(prep_dt):
                    prep_dt = timezone.make_aware(prep_dt)
            except Exception as e:
                print("Date parse error:", e)

        category_defaults = {
            'Bakery': 36.0,
            'Bread': 72.0,
            'Pastries': 24.0,
            'Pastry': 48.0,
            'Cake': 24.0,
            'Produce': 96.0,
            'Leafy Greens': 48.0,
            'Vegetables': 72.0,
            'Fruits': 96.0,
            'Root Crops': 240.0,
            'Desserts & Sweets': 18.0,
        }
        base_hours = category_defaults.get(category_name, 48.0)

        if 'Frozen' in storage:
            base_hours *= 5.0
        elif 'Chilled' in storage:
            base_hours *= 2.5

        calculated_expiry = calculate_ttt_expiry(base_hours, current_temp, prep_dt)

        return Response({
            "date": calculated_expiry.strftime("%b %d, %Y"),
            "time": calculated_expiry.strftime("%I:%M %p"),
            "temp": current_temp
        }, status=status.HTTP_200_OK)


class CreateListingView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ensure_listing_reference_data()

        mutable_data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)

        merchant = resolve_merchant(
            mutable_data.get('merchant'),
            mutable_data.get('email')
        )
        if merchant:
            mutable_data['merchant'] = merchant.merch_id

            if merchant.plan_id == 1:
                weekly_count = PerishableProduct.objects.filter(merchant=merchant).count()
                if weekly_count >= 10:
                    return Response(
                        {
                            "error": "Free Tier Limit Reached: You have reached the maximum of 10 listings per week. Upgrade to Premium Tier in your Profile for unlimited listings!"
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

        sec_class = mutable_data.get('secondary_classification', 'Plain')
        price_mode = mutable_data.get('pricing_mode', 'dynamic')
        mutable_data['prod_type'] = f"{sec_class}|{price_mode}"

        if not mutable_data.get('threshold'):
            mutable_data['threshold'] = 1

        serializer = PerishableProductSerializer(data=mutable_data, context={'request': request})

        if serializer.is_valid():
            new_listing = serializer.save()
            current_temp, current_humidity = get_cebu_weather()

            storage = mutable_data.get('storage_condition', 'Ambient (25°C)')
            posted_temp = 25.00
            if "Frozen" in storage:
                posted_temp = -18.00
            elif "Chilled" in storage:
                posted_temp = 4.00

            final_expiry = parse_frontend_expiry(
                mutable_data.get('expiry_date'),
                mutable_data.get('expiry_time')
            )
            if not final_expiry:
                final_expiry = calculate_ttt_expiry(48.0, current_temp, timezone.now())

            safety_record = ListingSafety.objects.create(
                product=new_listing,
                safely_anchor_time=mutable_data.get('preparation_date'),
                anchor_type='Preparation',
                estimated_expiry=final_expiry,
                posted_temp=posted_temp,
                humidity_index=current_humidity
            )

            raw_qty = mutable_data.get('quantity') or mutable_data.get('qty_available', 0)
            try:
                parsed_qty = int(float(raw_qty)) if raw_qty not in ("", None) else 0
            except (ValueError, TypeError):
                parsed_qty = 0

            listing_status = mutable_data.get('status', 'Active')

            ListingCommerce.objects.create(
                listing=safety_record,
                orig_price=mutable_data.get('orig_price') or mutable_data.get('original_price') or 0.00,
                discounted_price=mutable_data.get('discounted_price') or mutable_data.get('price') or 0.00,
                floor_price=mutable_data.get('floor_price') or 0.00,
                current_price=mutable_data.get('discounted_price') or mutable_data.get('price') or 0.00,
                qty_available=parsed_qty,
                pickup_deadline=final_expiry,
                status=listing_status
            )

            return Response({
                "message": "Listing, Safety, and Pricing created successfully!",
                "data": PerishableProductSerializer(new_listing).data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdateListingView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, pk):
        ensure_listing_reference_data()

        try:
            listing = PerishableProduct.objects.get(pk=pk)
        except PerishableProduct.DoesNotExist:
            return Response({"error": "Listing not found"}, status=status.HTTP_404_NOT_FOUND)

        listing.prod_name = request.data.get("prod_name", listing.prod_name)
        listing.prod_desc = request.data.get("prod_desc", listing.prod_desc)
        listing.weight_per_unit = request.data.get("weight_per_unit", listing.weight_per_unit or 0)
        if request.data.get("image_path"):
            listing.image_path = request.data.get("image_path")

        if "secondary_classification" in request.data or "pricing_mode" in request.data:
            raw_existing = (listing.prod_type or "Plain|dynamic").split("|")
            sec_class = request.data.get("secondary_classification", raw_existing[0])
            price_mode = request.data.get("pricing_mode", raw_existing[1] if len(raw_existing) > 1 else "dynamic")
            listing.prod_type = f"{sec_class}|{price_mode}"

        unit_id = request.data.get("unit") or request.data.get("unit_id")
        if unit_id:
            listing.unit_id = unit_id

        category_id = request.data.get("category")
        if category_id and str(category_id).isdigit():
            listing.category_id = int(category_id)

        listing.save()

        safety_record = ListingSafety.objects.filter(product=listing).first()
        if safety_record:
            prep_date_str = request.data.get("preparation_date")
            if prep_date_str:
                safety_record.safely_anchor_time = prep_date_str

            storage = request.data.get("storage_condition")
            if storage:
                if "Frozen" in storage:
                    safety_record.posted_temp = -18.00
                elif "Chilled" in storage:
                    safety_record.posted_temp = 4.00
                else:
                    safety_record.posted_temp = 25.00

            parsed_exp = parse_frontend_expiry(
                request.data.get('expiry_date'),
                request.data.get('expiry_time')
            )
            if parsed_exp:
                safety_record.estimated_expiry = parsed_exp

            safety_record.save()

            try:
                commerce = safety_record.commerce

                raw_qty = request.data.get("quantity") or request.data.get("qty_available")
                if raw_qty not in (None, ""):
                    commerce.qty_available = int(float(raw_qty))

                orig_price = request.data.get("orig_price") or request.data.get("original_price")
                if orig_price not in (None, ""):
                    commerce.orig_price = orig_price

                disc_price = request.data.get("discounted_price") or request.data.get("price")
                if disc_price not in (None, ""):
                    commerce.discounted_price = disc_price
                    commerce.current_price = disc_price

                floor_price = request.data.get("floor_price")
                if floor_price not in (None, ""):
                    commerce.floor_price = floor_price

                new_status = request.data.get("status")
                if new_status:
                    commerce.status = new_status

                commerce.save()
            except Exception as e:
                print("Error updating commerce record on edit:", e)

        return Response({
            "message": "Listing updated successfully",
            "data": PerishableProductSerializer(listing).data
        }, status=status.HTTP_200_OK)


class DeleteListingView(APIView):
    permission_classes = [AllowAny]

    def delete(self, request, pk):
        try:
            listing = PerishableProduct.objects.get(pk=pk)
            listing.delete()
            return Response({"message": "Listing successfully deleted!"}, status=status.HTTP_200_OK)
        except PerishableProduct.DoesNotExist:
            return Response({"error": "Listing not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EstablishmentNotificationsView(APIView):
    """
    Strictly Merchant-Scoped Notifications:
    1. Customer Purchases & Reservations on THIS merchant's listings
    2. Live Cebu Weather & TTT Shelf-Life Impact for THIS merchant's active items
    3. 1-Hr Expiry & Flagged Alerts for THIS merchant's listings
    4. Food Bank Claims on THIS merchant's donations & direct compliance notices
    """
    permission_classes = [AllowAny]

    def get(self, request):
        events = []
        merchant = resolve_merchant(request.GET.get('merchant'), request.GET.get('email'))
        if not merchant:
            return Response([], status=status.HTTP_200_OK)

        now = timezone.now()

        # 1. Customer Purchases & Reservations (Strictly for THIS Merchant)
        recent_orders = OrderReservation.objects.filter(
            listing__listing__product__merchant=merchant
        ).select_related('consumer', 'listing__listing__product').order_by('-ordered_at')[:15]

        for o in recent_orders:
            prod_name = o.listing.listing.product.prod_name if (o.listing and o.listing.listing and o.listing.listing.product) else "Surplus Item"
            buyer_name = o.consumer.cons_fullname if o.consumer else "A consumer"
            time_str = o.ordered_at.strftime("%b %d, %I:%M %p") if o.ordered_at else "Recently"

            if o.order_status == "Pending":
                events.append({
                    "id": f"order-pend-{o.order_id}",
                    "type": "order",
                    "title": f"New Customer Reservation ({o.qr_voucher_code})",
                    "description": f"{buyer_name} reserved {o.order_qty}x {prod_name}. 10% online deposit (₱{float(o.downpayment_amount or 0):.2f}) secured in escrow.",
                    "time": time_str,
                    "read": False,
                })
            elif o.order_status == "Completed":
                events.append({
                    "id": f"order-done-{o.order_id}",
                    "type": "order",
                    "title": f"Order Pickup Completed ({o.qr_voucher_code})",
                    "description": f"{buyer_name} picked up {o.order_qty}x {prod_name}. ₱{float(o.downpayment_amount or 0):.2f} deposit credited to your Active Wallet.",
                    "time": time_str,
                    "read": False,
                })

        # 2. Live Cebu Weather & TTT Shelf-Life Impact Notice (Only if merchant has active listings)
        active_safety_qs = ListingSafety.objects.filter(
            product__merchant=merchant,
            estimated_expiry__isnull=False
        ).select_related('product')

        active_count = active_safety_qs.count()
        if active_count > 0:
            curr_temp, curr_hum = get_cebu_weather()
            temp_diff = curr_temp - 25.0
            rate_pct = round(abs(temp_diff * 3.0), 1)
            if curr_temp > 27.0:
                weather_desc = (
                    f"Cebu City is currently at {curr_temp:.1f}°C ({curr_hum}% humidity). "
                    f"Ambient TTT shelf-life decay is accelerated by ~{rate_pct}% across your {active_count} active listing(s). Keep items chilled if possible."
                )
            else:
                weather_desc = (
                    f"Cebu City weather is currently {curr_temp:.1f}°C ({curr_hum}% humidity). "
                    f"TTT shelf-life conditions are stable for your {active_count} active listing(s)."
                )
            events.append({
                "id": f"weather-ttt-{now.strftime('%Y%m%d-%H')}",
                "type": "expiry_1hr",
                "title": f"Cebu Weather & TTT Update ({curr_temp:.1f}°C)",
                "description": weather_desc,
                "time": "Live TTT Monitor",
                "read": False,
            })

        # 3. 1-Hour Expiry & Flagged Warnings (Strictly for THIS Merchant)
        for safety in active_safety_qs:
            if safety.estimated_expiry:
                expiry_dt = safety.estimated_expiry
                if timezone.is_naive(expiry_dt):
                    expiry_dt = timezone.make_aware(expiry_dt)

                seconds_remaining = (expiry_dt - now).total_seconds()
                if seconds_remaining < 3600:
                    prod_name = safety.product.prod_name if safety.product else "Surplus Item"
                    if seconds_remaining <= 1830:
                        events.append({
                            "id": f"expiry-flag-{safety.pk}",
                            "type": "suggested_expiry",
                            "title": "Listing Flagged / Reached Safety Limit",
                            "description": f"Your listing '{prod_name}' reached its 30-min TTT safety threshold and was flagged.",
                            "time": "Action Required",
                            "read": False,
                        })
                    else:
                        mins_left = max(1, int(seconds_remaining / 60))
                        events.append({
                            "id": f"expiry-1hr-{safety.pk}",
                            "type": "expiry_1hr",
                            "title": "1-Hour Expiry Warning",
                            "description": f"Your listing '{prod_name}' will reach its expiry window in {mins_left} mins. Consider donating it to a Food Bank!",
                            "time": f"In ~{mins_left} mins",
                            "read": False,
                        })

        # 4. Food Bank Claims on THIS Merchant's Donations
        my_donations = Donation.objects.filter(
            merchant=merchant,
            status__in=['Claimed', 'Completed']
        ).select_related('food_bank', 'listing__listing__product').order_by('-updated_at')[:10]

        for don in my_donations:
            fb_name = don.food_bank.org_name if don.food_bank else "Partner Food Bank"
            p_name = don.listing.listing.product.prod_name if (don.listing and don.listing.listing and don.listing.listing.product) else "Surplus Donation"
            events.append({
                "id": f"don-claim-{don.donation_id}-{don.status}",
                "type": "donation",
                "title": "Donation Claimed by Food Bank!" if don.status == "Claimed" else "Donation Received by Food Bank",
                "description": f"{fb_name} {don.status.lower()} your donation of {don.qty_donated}x {p_name}.",
                "time": don.updated_at.strftime("%b %d, %I:%M %p") if don.updated_at else "Recently",
                "read": False,
            })

        # 5. Direct Account Compliance / Payout Notices (Strictly for THIS Merchant — excludes Admin KYB logs)
        direct_notifs = AdminNotification.objects.filter(
            merchant=merchant,
            admin_notif_type__in=['Compliance', 'Payout']
        ).order_by('-pk')[:8]

        for an in direct_notifs:
            events.append({
                "id": f"compliance-{an.pk}",
                "type": "system",
                "title": f"Account Update ({an.admin_notif_type})",
                "description": an.message,
                "time": "Official Notice",
                "read": False,
            })

        return Response(events, status=status.HTTP_200_OK)


class EstablishmentAnnouncementsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        broadcasts_qs = AdminNotification.objects.filter(
            admin_notif_type__startswith='Broadcast'
        ).order_by('-pk')[:25]

        announcements = []
        for b in broadcasts_qs:
            audience = b.admin_notif_type.replace('Broadcast:', '').strip() or 'All Users (System-wide)'
            if audience not in ['All Users (System-wide)', 'Merchants Only']:
                continue
            parts = (b.message or '').split(' || ', 1)
            title = parts[0] if len(parts) > 1 else 'System Announcement'
            body = parts[1] if len(parts) > 1 else b.message
            announcements.append({
                "id": f"broadcast-{b.pk}",
                "audience": audience,
                "title": title,
                "body": body,
                "date": "Official Broadcast",
            })

        return Response(announcements, status=status.HTTP_200_OK)


class MerchantPortalSummaryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, merch_id):
        ensure_listing_reference_data()
        merchant = resolve_merchant(merch_id, request.GET.get('email'))
        if not merchant:
            return Response({"error": "No merchant found"}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        products = PerishableProduct.objects.filter(merchant=merchant).select_related('category', 'unit').order_by('-prod_id')

        pending_orders = []
        completed_orders = []
        transactions_list = []
        recent_impact = []

        total_earnings_val = Decimal('0.00')
        saved_spoilage_val = Decimal('0.00')
        total_rescued_kg = Decimal('0.00')
        nearing_expiry_count = 0
        successful_rescues_count = 0
        seen_order_keys = set()

        merch_loc = Location.objects.filter(user=merchant.user).order_by('-is_primary', '-loc_id').first()

        # 1. Inspect OrderReservation rows for this merchant
        orders_qs = OrderReservation.objects.filter(
            listing__listing__product__merchant=merchant
        ).select_related(
            'consumer__user',
            'listing__listing__product__category',
            'listing__listing__product__unit'
        ).order_by('-ordered_at')

        for o in orders_qs:
            commerce = o.listing
            safety = commerce.listing if commerce else None
            prod = safety.product if safety else None
            if not prod:
                continue

            unit_name = prod.unit.unit_name if prod.unit else "pc"
            unit_short = unit_name.split("(")[1].replace(")", "").strip() if "(" in unit_name and ")" in unit_name else unit_name
            cat_name = prod.category.category_name if prod.category else "Surplus"

            disc_price = Decimal(str(commerce.discounted_price or 0))
            total_price = (disc_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
            deposit_paid = Decimal(str(o.downpayment_amount or 0)).quantize(Decimal('0.01'))
            cash_due = max(Decimal('0.00'), total_price - deposit_paid)

            pickup_date_str = safety.estimated_expiry.strftime("%B %d, %Y") if safety and safety.estimated_expiry else "Today"
            pickup_time_str = safety.estimated_expiry.strftime("%I:%M %p") if safety and safety.estimated_expiry else "05:00 PM"

            expiry_label = "Active"
            if safety and safety.estimated_expiry:
                exp_dt = safety.estimated_expiry
                if timezone.is_naive(exp_dt):
                    exp_dt = timezone.make_aware(exp_dt)
                secs_left = (exp_dt - now).total_seconds()
                if 0 < secs_left <= 7200 and o.order_status == 'Pending':
                    nearing_expiry_count += 1
                if secs_left <= 0:
                    expiry_label = "Expired"
                elif secs_left < 3600:
                    expiry_label = f"{max(1, int(secs_left // 60))} mins left"
                else:
                    expiry_label = f"{int(secs_left // 3600)} hrs left"

            order_card = {
                "id": o.qr_voucher_code,
                "prod_id": prod.prod_id,
                "commerce_id": commerce.pk,
                "customer": o.consumer.cons_fullname if o.consumer else "Consumer",
                "item": prod.prod_name,
                "qty": f"{o.order_qty} {unit_short}",
                "raw_qty": o.order_qty,
                "time": o.ordered_at.strftime("%b %d | %I:%M %p") if o.ordered_at else f"Today | {pickup_time_str}",
                "expiry": expiry_label if o.order_status == 'Pending' else "Picked Up",
                "status": "Pending Pickup" if o.order_status == 'Pending' else "Successful",
                "image": prod.image_path or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                "establishment": merchant.bus_name,
                "price": f"₱{total_price:,.2f} (10% Paid: ₱{deposit_paid:,.2f} | 90% Cash: ₱{cash_due:,.2f})",
                "category": cat_name,
                "description": prod.prod_desc or "Consumer rescue reservation.",
                "preparationDate": (safety.safely_anchor_time if safety else None) or pickup_date_str,
                "storageCondition": "Standard",
                "pickupDate": pickup_date_str,
                "pickupTime": pickup_time_str,
                "rescueVoucher": True,
            }

            if o.order_status == 'Pending':
                pending_orders.append(order_card)
            elif o.order_status == 'Completed':
                completed_orders.append(order_card)
            seen_order_keys.add(prod.prod_id)

        # 2. Inspect Product Commerce records for sold metrics & fallback reservations
        for prod in products:
            safety = ListingSafety.objects.filter(product=prod).first()
            commerce = getattr(safety, 'commerce', None) if safety else None
            if not commerce:
                continue

            unit_label = prod.unit.unit_name if prod.unit else "pc"
            unit_short = unit_label.split("(")[1].replace(")", "").strip() if "(" in unit_label and ")" in unit_label else unit_label
            cat_name = prod.category.category_name if prod.category else "Bakery"

            disc_price = Decimal(str(commerce.discounted_price or 0))
            orig_price = Decimal(str(commerce.orig_price or disc_price))
            qty_reserved = int(commerce.qty_reserved or 0)
            qty_sold = int(commerce.qty_sold or 0)

            pickup_date_str = safety.estimated_expiry.strftime("%B %d, %Y") if safety and safety.estimated_expiry else "Today"
            pickup_time_str = safety.estimated_expiry.strftime("%I:%M %p") if safety and safety.estimated_expiry else "05:00 PM"

            if qty_reserved > 0 and prod.prod_id not in seen_order_keys:
                pending_orders.append({
                    "id": f"OID{100 + prod.prod_id}",
                    "prod_id": prod.prod_id,
                    "commerce_id": commerce.pk,
                    "customer": "Consumer Reservation",
                    "item": prod.prod_name,
                    "qty": f"{qty_reserved} {unit_short}",
                    "raw_qty": qty_reserved,
                    "time": f"Reserved | {pickup_time_str}",
                    "expiry": "Active",
                    "status": "Pending Pickup",
                    "image": prod.image_path or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                    "establishment": merchant.bus_name,
                    "price": f"₱{(disc_price * Decimal(qty_reserved)):,.2f}",
                    "category": cat_name,
                    "description": prod.prod_desc or "Consumer reserved surplus order.",
                    "preparationDate": (safety.safely_anchor_time if safety else None) or pickup_date_str,
                    "storageCondition": "Standard",
                    "pickupDate": pickup_date_str,
                    "pickupTime": pickup_time_str,
                    "rescueVoucher": True,
                })

            if qty_sold > 0:
                gross_total = disc_price * Decimal(qty_sold)
                reservation_fee_10pct = (gross_total * Decimal('0.10')).quantize(Decimal('0.01'))
                cash_on_pickup_90pct = (gross_total * Decimal('0.90')).quantize(Decimal('0.01'))

                is_premium = (merchant.plan_id == 2)
                commission_fee = Decimal('0.00') if is_premium else reservation_fee_10pct
                net_unit_earning = disc_price if is_premium else (disc_price * Decimal('0.90')).quantize(Decimal('0.01'))
                net_line_total = (gross_total - commission_fee).quantize(Decimal('0.01'))

                spoilage_saved = max(Decimal('0.00'), (orig_price - disc_price) * Decimal(qty_sold))

                total_earnings_val += net_line_total
                saved_spoilage_val += spoilage_saved
                successful_rescues_count += qty_sold

                raw_weight = Decimal(str(prod.weight_per_unit or 0))
                if prod.unit_id == 1:
                    unit_kg = (raw_weight / Decimal('1000')) if raw_weight > 0 else Decimal('0.1')
                elif prod.unit_id == 2:
                    unit_kg = raw_weight if raw_weight > 0 else Decimal('1.0')
                else:
                    unit_kg = raw_weight if raw_weight > 0 else Decimal('1.0')

                item_kg = unit_kg * Decimal(qty_sold)
                total_rescued_kg += item_kg

                if prod.prod_id not in seen_order_keys:
                    completed_orders.append({
                        "id": f"OID{900 + prod.prod_id}",
                        "prod_id": prod.prod_id,
                        "commerce_id": commerce.pk,
                        "customer": "Verified Consumer",
                        "item": prod.prod_name,
                        "qty": f"{qty_sold} {unit_short}",
                        "time": f"{pickup_date_str} | {pickup_time_str}",
                        "expiry": "Picked Up",
                        "status": "Successful",
                        "image": prod.image_path or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                        "establishment": merchant.bus_name,
                        "price": f"₱{gross_total:,.2f} (10% Online: ₱{reservation_fee_10pct:,.2f} | 90% Cash: ₱{cash_on_pickup_90pct:,.2f})",
                        "category": cat_name,
                        "description": prod.prod_desc or "Successfully picked up by consumer.",
                        "preparationDate": (safety.safely_anchor_time if safety else None) or pickup_date_str,
                        "storageCondition": "Standard",
                        "pickupDate": pickup_date_str,
                        "pickupTime": pickup_time_str,
                        "rescueVoucher": True,
                    })

                transactions_list.append({
                    "food": prod.prod_name,
                    "qty": str(qty_sold),
                    "original": f"₱{orig_price:,.2f}",
                    "discounted": f"₱{disc_price:,.2f}",
                    "net": f"₱{net_unit_earning:,.2f}",
                    "total": f"₱{net_line_total:,.2f}",
                })

                recent_impact.append({
                    "id": f"imp-prod-{prod.prod_id}",
                    "icon": "restaurant-outline",
                    "title": f"{prod.prod_name} sold & rescued",
                    "description": f"{qty_sold} {unit_short} ({float(item_kg):,.1f} kg) claimed by consumers.",
                    "date": pickup_date_str,
                })

        # 3. Only count Donations in Impact once Claimed / Fulfilled
        donations_qs = Donation.objects.filter(merchant=merchant).order_by('-donation_id')
        for don in donations_qs:
            if str(don.status).lower() in ['claimed', 'claimed by food bank', 'fulfilled', 'completed', 'delivered']:
                don_qty = int(don.qty_donated or 1)
                successful_rescues_count += 1
                total_rescued_kg += Decimal(don_qty) * Decimal('1.0')
                recent_impact.append({
                    "id": f"imp-don-{don.donation_id}",
                    "icon": "heart-outline",
                    "title": "Donation Fulfilled",
                    "description": f"{don_qty} kg/units received by partner food bank.",
                    "date": "Completed",
                })

        # 4. Withdrawal History
        payout_notifs = AdminNotification.objects.filter(
            merchant=merchant,
            admin_notif_type__icontains='Payout'
        ).order_by('-pk')[:10]

        withdrawals_list = []
        for idx, p_notif in enumerate(payout_notifs, start=1):
            status_str = "Pending" if "Request" in p_notif.message else "Completed"
            amt_str = (
                "₱" + p_notif.message.split("₱")[1].split(" ")[0]
                if "₱" in p_notif.message
                else f"₱{float(merchant.wallet_bal or 0):,.2f}"
            )
            withdrawals_list.append({
                "id": f"PO0{idx}",
                "amount": amt_str,
                "status": status_str,
            })

        wallet_bal = Decimal(str(merchant.wallet_bal or 0))
        if total_earnings_val == 0 and wallet_bal > 0:
            total_earnings_val = wallet_bal

        rescued_kg_float = float(total_rescued_kg)
        co2_avoided_float = round(rescued_kg_float * 2.0, 1)
        people_helped_count = int(successful_rescues_count)
        portions_rescued_count = int(round(rescued_kg_float * 2))

        months_labels = ["May", "Jun", "Jul", "Aug", "Sep", "Oct"]
        monthly_impact = [
            {"month": m_label, "rescued": round(rescued_kg_float, 1) if idx == len(months_labels) - 1 else 0}
            for idx, m_label in enumerate(months_labels)
        ]

        return Response({
            "profile": {
                "merch_id": merchant.merch_id,
                "bus_name": merchant.bus_name,
                "merch_type": merchant.merch_type or "Bakeshop",
                "email": merchant.user.user_email,
                "phone": merchant.phone or merchant.hotline or "Not Provided",
                "hotline": merchant.hotline or "N/A",
                "contact_person": merchant.contact_person or "Manager",
                "address": merchant.address or "Cebu City, Philippines",
                "status": merchant.status,
                "expiry_date": str(merchant.bus_expiry_date or ""),
                "plan_id": merchant.plan_id,
                "plan_name": "Premium Tier (Pro)" if merchant.plan_id == 2 else "Free Tier (Basic)",
                "weekly_listings_used": len(products),
                "weekly_listings_limit": "Unlimited" if merchant.plan_id == 2 else "10",
                "latitude": float(merch_loc.latitude) if merch_loc else 10.3157,
                "longitude": float(merch_loc.longitude) if merch_loc else 123.8854,
            },
            "orders": {
                "active_pickups_count": len(pending_orders),
                "nearing_expiry_count": nearing_expiry_count,
                "pending_orders": pending_orders,
                "completed_orders": completed_orders,
            },
            "earnings": {
                "total_earnings": f"₱{float(total_earnings_val):,.2f}",
                "wallet_balance": f"₱{float(wallet_bal):,.2f}",
                "raw_wallet_balance": float(wallet_bal),
                "saved_on_spoilage": f"₱{float(saved_spoilage_val):,.2f}",
                "transactions_completed": len(completed_orders),
                "transactions": transactions_list,
                "withdrawals": withdrawals_list,
            },
            "impact": {
                "food_rescued_kg": f"{rescued_kg_float:,.1f}",
                "people_helped": f"{people_helped_count:,}",
                "successful_rescues": f"{successful_rescues_count:,}",
                "co2_avoided_kg": f"{co2_avoided_float:,.1f}",
                "portions_rescued": f"{portions_rescued_count:,}",
                "monthly_data": monthly_impact,
                "recent_impact": recent_impact[:6],
            }
        }, status=status.HTTP_200_OK)

    def post(self, request, merch_id):
        ensure_listing_reference_data()
        merchant = resolve_merchant(merch_id, request.data.get('email'))
        if not merchant:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get("action")

        if action == "update_profile":
            merchant.bus_name = request.data.get("bus_name", merchant.bus_name)
            merchant.phone = request.data.get("phone", merchant.phone)
            merchant.address = request.data.get("address", merchant.address)
            merchant.contact_person = request.data.get("contact_person", merchant.contact_person)
            merchant.save()

            new_email = request.data.get("email")
            if new_email and new_email != merchant.user.user_email:
                merchant.user.user_email = new_email
                merchant.user.save()

            if "latitude" in request.data and "longitude" in request.data:
                try:
                    lat_v = float(request.data["latitude"])
                    lng_v = float(request.data["longitude"])
                    loc_obj = Location.objects.filter(user=merchant.user).order_by('-is_primary', '-loc_id').first()
                    if loc_obj:
                        loc_obj.address_name = merchant.address or "Cebu City"
                        loc_obj.latitude = lat_v
                        loc_obj.longitude = lng_v
                        loc_obj.save()
                    else:
                        Location.objects.create(
                            user=merchant.user,
                            address_name=merchant.address or "Cebu City",
                            latitude=lat_v,
                            longitude=lng_v,
                            is_primary=True,
                        )
                except Exception:
                    pass

            return Response({
                "message": "Profile updated successfully!",
                "bus_name": merchant.bus_name
            }, status=status.HTTP_200_OK)

        elif action == "change_password":
            new_password = request.data.get("new_password", "").strip()
            if len(new_password) < 6:
                return Response({"error": "Password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)
            merchant.user.user_pass = make_password(new_password)
            merchant.user.save()
            return Response({"message": "Password updated successfully!"}, status=status.HTTP_200_OK)

        elif action == "confirm_order":
            prod_id = request.data.get("prod_id")
            raw_code = str(request.data.get("order_code", "")).upper().strip()

            order_res = OrderReservation.objects.filter(
                qr_voucher_code__iexact=raw_code,
                listing__listing__product__merchant=merchant
            ).select_related('listing__listing__product', 'consumer').first()

            if not order_res and prod_id:
                order_res = OrderReservation.objects.filter(
                    listing__listing__product__prod_id=prod_id,
                    listing__listing__product__merchant=merchant,
                    order_status='Pending'
                ).select_related('listing__listing__product', 'consumer').first()

            if order_res:
                if order_res.order_status == 'Completed':
                    return Response({"error": "This voucher has already been claimed and completed."}, status=status.HTTP_400_BAD_REQUEST)

                commerce = order_res.listing
                prod = commerce.listing.product
                qty_done = int(order_res.order_qty or 1)

                commerce.qty_reserved = max(0, (commerce.qty_reserved or 0) - qty_done)
                commerce.qty_sold = (commerce.qty_sold or 0) + qty_done
                if commerce.qty_available == 0 and commerce.qty_reserved == 0:
                    commerce.status = "Sold Out"
                commerce.save()

                order_res.order_status = 'Completed'
                order_res.save()

                if order_res.consumer:
                    order_res.consumer.total_food_saved = Decimal(str(order_res.consumer.total_food_saved or 0)) + Decimal(str(order_res.rescued_weight_kg or 1))
                    order_res.consumer.save()

                deposit_amt = Decimal(str(order_res.downpayment_amount or 0))
                gross_amt = Decimal(str(commerce.discounted_price or 0)) * Decimal(qty_done)
                cash_90pct = max(Decimal('0.00'), gross_amt - deposit_amt)

                merchant.wallet_bal = Decimal(str(merchant.wallet_bal or 0)) + deposit_amt
                merchant.save()

                StockLedger.objects.create(
                    listing=commerce,
                    transaction_type="Pickup_Confirmed",
                    qty_change=-qty_done,
                    reason=f"Verified voucher {order_res.qr_voucher_code}"
                )

                return Response({
                    "message": (
                        f"Voucher {order_res.qr_voucher_code} Verified for {prod.prod_name}!\n"
                        f"• Collect 90% Cash from Customer: ₱{float(cash_90pct):,.2f}\n"
                        f"• 10% Online Deposit Credited to Wallet: ₱{float(deposit_amt):,.2f}"
                    )
                }, status=status.HTTP_200_OK)

            clean_digits = re.sub(r'\D', '', raw_code)
            target_prod = None
            if prod_id:
                target_prod = PerishableProduct.objects.filter(prod_id=prod_id, merchant=merchant).first()
            elif clean_digits.isdigit():
                num_val = int(clean_digits)
                lookup_id = num_val - 100 if num_val > 100 else num_val
                target_prod = PerishableProduct.objects.filter(prod_id=lookup_id, merchant=merchant).first()
                if not target_prod:
                    target_prod = PerishableProduct.objects.filter(prod_id=num_val, merchant=merchant).first()

            if not target_prod:
                return Response({"error": "Matching voucher or order ID not found."}, status=status.HTTP_404_NOT_FOUND)

            safety = ListingSafety.objects.filter(product=target_prod).first()
            commerce = getattr(safety, 'commerce', None) if safety else None
            if not commerce:
                return Response({"error": "Commerce record not found."}, status=status.HTTP_400_BAD_REQUEST)

            qty_to_complete = commerce.qty_reserved if commerce.qty_reserved > 0 else (1 if commerce.qty_available > 0 else 0)
            if qty_to_complete <= 0:
                return Response({"error": "No remaining stock or reservation to fulfill."}, status=status.HTTP_400_BAD_REQUEST)

            gross_sale = Decimal(str(commerce.discounted_price or 0)) * Decimal(qty_to_complete)
            reservation_deposit_10pct = (gross_sale * Decimal('0.10')).quantize(Decimal('0.01'))
            cash_collected_90pct = (gross_sale * Decimal('0.90')).quantize(Decimal('0.01'))

            if commerce.qty_reserved >= qty_to_complete:
                commerce.qty_reserved -= qty_to_complete
            else:
                commerce.qty_available = max(0, commerce.qty_available - qty_to_complete)

            commerce.qty_sold = (commerce.qty_sold or 0) + qty_to_complete
            if commerce.qty_available == 0 and commerce.qty_reserved == 0:
                commerce.status = "Sold Out"
            commerce.save()

            StockLedger.objects.create(
                listing=commerce,
                transaction_type="Pickup_Confirmed",
                qty_change=-qty_to_complete,
                reason=f"Verified pickup for {target_prod.prod_name} ({raw_code or 'Direct'})"
            )

            merchant.wallet_bal = Decimal(str(merchant.wallet_bal or 0)) + reservation_deposit_10pct
            merchant.save()

            return Response({
                "message": (
                    f"Pickup verified for {target_prod.prod_name}!\n"
                    f"• Collect 90% Cash from Customer: ₱{float(cash_collected_90pct):,.2f}\n"
                    f"• 10% Online Reservation Fee Added to Wallet: ₱{float(reservation_deposit_10pct):,.2f}"
                )
            }, status=status.HTTP_200_OK)

        elif action == "request_withdrawal":
            current_bal = Decimal(str(merchant.wallet_bal or 0))
            if current_bal <= 0:
                return Response({"error": "Your active wallet balance is ₱0.00."}, status=status.HTTP_400_BAD_REQUEST)

            is_premium = (merchant.plan_id == 2)
            fee_deducted = Decimal('0.00') if is_premium else (current_bal * Decimal('0.10')).quantize(Decimal('0.01'))
            net_payout = (current_bal - fee_deducted).quantize(Decimal('0.01'))
            tier_label = "Premium Tier (0% Fee)" if is_premium else f"Free Tier (10% Fee: -₱{float(fee_deducted):,.2f})"

            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type="Payout Request",
                message=f"Payout Request of ₱{float(net_payout):,.2f} [{tier_label}] submitted by {merchant.bus_name}.",
                merchant=merchant
            )
            return Response({
                "message": (
                    f"Withdrawal Request Submitted!\n"
                    f"• Gross Wallet Balance: ₱{float(current_bal):,.2f}\n"
                    f"• {tier_label}\n"
                    f"• Net Payout to Receive: ₱{float(net_payout):,.2f}"
                )
            }, status=status.HTTP_200_OK)

        elif action == "upgrade_tier":
            target_plan = int(request.data.get("plan_id", 2))
            merchant.plan_id = target_plan
            merchant.save()
            plan_label = "Premium Tier (Unlimited Listings, 0% Commission)" if target_plan == 2 else "Free Tier (10 Listings/Week, 10% Commission)"
            return Response({
                "message": f"Subscription updated to {plan_label}!",
                "plan_id": merchant.plan_id,
                "plan_name": "Premium Tier (Pro)" if merchant.plan_id == 2 else "Free Tier (Basic)"
            }, status=status.HTTP_200_OK)

        return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)


class ConsumerPortalView(APIView):
    permission_classes = [AllowAny]

    def _resolve_consumer(self, cons_id=None, email=None):
        if cons_id and str(cons_id).isdigit():
            c = Consumer.objects.select_related('user').filter(cons_id=int(cons_id)).first()
            if c:
                return c
        if email:
            c = Consumer.objects.select_related('user').filter(user__user_email__iexact=str(email).strip()).first()
            if c:
                return c
        return Consumer.objects.select_related('user').order_by('-cons_id').first()

    def get(self, request, cons_id):
        consumer = self._resolve_consumer(cons_id, request.GET.get('email'))
        if not consumer:
            return Response({"error": "Consumer not found"}, status=status.HTTP_404_NOT_FOUND)

        orders_qs = OrderReservation.objects.filter(consumer=consumer).select_related(
            'listing__listing__product__merchant',
            'listing__listing__product__unit'
        ).order_by('-ordered_at')

        consumer_loc = Location.objects.filter(user=consumer.user).order_by('-is_primary', '-loc_id').first()
        

        claims_list = []
        notifs_list = []

        for o in orders_qs:
            commerce = o.listing
            safety = commerce.listing if commerce else None
            prod = safety.product if safety else None
            merch = prod.merchant if prod else None

            unit_price = Decimal(str(commerce.discounted_price if commerce else 0))
            orig_unit_price = Decimal(str(commerce.orig_price if commerce and commerce.orig_price else unit_price))
            total_val = (unit_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
            paid_deposit = Decimal(str(o.downpayment_amount or (total_val * Decimal('0.10')))).quantize(Decimal('0.01'))
            remaining_bal = max(Decimal('0.00'), total_val - paid_deposit)
            savings_val = max(Decimal('0.00'), (orig_unit_price - unit_price) * Decimal(o.order_qty))

            pickup_deadline_str = (
                safety.estimated_expiry.strftime("%b %d, %Y %I:%M %p")
                if safety and safety.estimated_expiry
                else "Today, 5:00 PM"
            )
            order_date_str = o.ordered_at.strftime("%b %d, %Y %I:%M %p") if o.ordered_at else "Recently"

            claims_list.append({
                "order_id": o.order_id,
                "voucher_code": o.qr_voucher_code,
                "status": o.order_status,
                "qty": o.order_qty,
                "food_name": prod.prod_name if prod else f"Rescue Item #{o.order_id}",
                "image": (prod.image_path if prod else "") or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                "establishment": merch.bus_name if merch else "Partner Establishment",
                "address": (merch.address if merch and merch.address else "Cebu City"),
                "pickup_deadline": pickup_deadline_str,
                "ordered_at": order_date_str,
                "total_value": f"{float(total_val):.2f}",
                "paid_today": f"{float(paid_deposit):.2f}",
                "remaining_balance": f"{float(remaining_bal):.2f}",
                "savings": f"{float(savings_val):.2f}",
            })

            if o.order_status == "Pending":
                notifs_list.append({
                    "id": f"ord-pend-{o.order_id}",
                    "icon": "checkmark-circle-outline",
                    "title": "Reservation Confirmed",
                    "text": f"Your reservation for {prod.prod_name if prod else 'food'} ({o.qr_voucher_code}) is ready for pickup before {pickup_deadline_str}.",
                    "time": order_date_str,
                    "unread": True,
                })
            elif o.order_status == "Completed":
                notifs_list.append({
                    "id": f"ord-done-{o.order_id}",
                    "icon": "pricetag-outline",
                    "title": "Rescue Completed & Savings Logged!",
                    "text": f"You rescued {prod.prod_name if prod else 'food'} and saved ₱{float(savings_val):.2f}!",
                    "time": order_date_str,
                    "unread": False,
                })

        broadcasts = AdminNotification.objects.filter(admin_notif_type__startswith='Broadcast').order_by('-pk')[:5]
        for b in broadcasts:
            aud = b.admin_notif_type.replace('Broadcast:', '').strip()
            if aud in ['All Users (System-wide)', 'Consumers Only']:
                parts = (b.message or '').split(' || ', 1)
                notifs_list.append({
                    "id": f"bcast-{b.pk}",
                    "icon": "megaphone-outline",
                    "title": parts[0] if len(parts) > 1 else "System Announcement",
                    "text": parts[1] if len(parts) > 1 else b.message,
                    "time": "Official Broadcast",
                    "unread": True,
                })

        return Response({
            "profile": {
                "cons_id": consumer.cons_id,
                "full_name": consumer.cons_fullname,
                "email": consumer.user.user_email,
                "phone": consumer.phone_num or "",
                "address": consumer.address or "Lapu-Lapu / Cebu City",
                "total_food_saved": float(consumer.total_food_saved or 0),
                "latitude": float(consumer_loc.latitude) if consumer_loc else 10.3157,
                "longitude": float(consumer_loc.longitude) if consumer_loc else 123.8854,
            },
            "claims": claims_list,
            "notifications": notifs_list,
        }, status=status.HTTP_200_OK)

    def post(self, request, cons_id):
        consumer = self._resolve_consumer(cons_id, request.data.get('email'))
        if not consumer:
            return Response({"error": "Consumer account not found."}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get("action")

        if action == "update_profile":
            if "full_name" in request.data and request.data["full_name"].strip():
                consumer.cons_fullname = request.data["full_name"].strip()
            if "phone" in request.data:
                consumer.phone_num = request.data["phone"].strip()
            if "address" in request.data:
                consumer.address = request.data["address"].strip()
            consumer.save()

            if "email" in request.data and request.data["email"].strip():
                new_email = request.data["email"].strip()
                if User.objects.exclude(user_id=consumer.user.user_id).filter(user_email__iexact=new_email).exists():
                    return Response({"error": "That email is already in use."}, status=status.HTTP_400_BAD_REQUEST)
                consumer.user.user_email = new_email
                consumer.user.save()

            if "latitude" in request.data and "longitude" in request.data:
                try:
                    lat_v = float(request.data["latitude"])
                    lng_v = float(request.data["longitude"])
                    loc_obj = Location.objects.filter(user=consumer.user).order_by('-is_primary', '-loc_id').first()
                    if loc_obj:
                        loc_obj.address_name = consumer.address or "Cebu City"
                        loc_obj.latitude = lat_v
                        loc_obj.longitude = lng_v
                        loc_obj.save()
                    else:
                        Location.objects.create(
                            user=consumer.user,
                            address_name=consumer.address or "Cebu City",
                            latitude=lat_v,
                            longitude=lng_v,
                            is_primary=True,
                        )
                except Exception:
                    pass

            return Response({
                "message": "Account details updated successfully!",
                "full_name": consumer.cons_fullname,
                "email": consumer.user.user_email,
                "phone": consumer.phone_num or "",
            }, status=status.HTTP_200_OK)

        elif action == "change_password":
            new_pw = request.data.get("new_password", "").strip()
            if len(new_pw) < 6:
                return Response({"error": "New password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)
            consumer.user.user_pass = make_password(new_pw)
            consumer.user.save()
            return Response({"message": "Password changed successfully!"}, status=status.HTTP_200_OK)

        elif action == "checkout":
            items = request.data.get("items", [])
            payment_method = request.data.get("payment_method", "GCash")
            if not items:
                return Response({"error": "Your cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

            created_claims = []
            for cart_item in items:
                prod_id = cart_item.get("id")
                qty = max(1, int(cart_item.get("quantity", 1)))

                prod = PerishableProduct.objects.filter(prod_id=prod_id).select_related('merchant').first()
                if not prod:
                    continue

                safety = ListingSafety.objects.filter(product=prod).first()
                commerce = getattr(safety, 'commerce', None) if safety else None
                if not commerce or commerce.qty_available < qty:
                    return Response(
                        {"error": f"Insufficient stock for {prod.prod_name} (only {commerce.qty_available if commerce else 0} left)."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                commerce.qty_available -= qty
                commerce.qty_reserved = (commerce.qty_reserved or 0) + qty
                commerce.save()

                live_unit_price = Decimal(str(cart_item.get("price") or commerce.discounted_price or 0))
                line_subtotal = (live_unit_price * Decimal(qty)).quantize(Decimal('0.01'))
                deposit_10pct = (line_subtotal * Decimal('0.10')).quantize(Decimal('0.01'))
                balance_90pct = max(Decimal('0.00'), line_subtotal - deposit_10pct)

                raw_w = Decimal(str(prod.weight_per_unit or 0))
                unit_kg = (raw_w / Decimal('1000')) if (prod.unit_id == 1 and raw_w > 0) else (raw_w if raw_w > 0 else Decimal('1.0'))
                total_w_kg = (unit_kg * Decimal(qty)).quantize(Decimal('0.01'))

                temp_code = f"TMP-{random.randint(100000, 999999)}"
                order_obj = OrderReservation.objects.create(
                    order_qty=qty,
                    order_status='Pending',
                    downpayment_amount=deposit_10pct,
                    qr_voucher_code=temp_code,
                    rescued_weight_kg=total_w_kg,
                    consumer=consumer,
                    listing=commerce
                )
                final_voucher_code = f"OID{100 + order_obj.order_id}"
                order_obj.qr_voucher_code = final_voucher_code
                order_obj.save()

                is_premium = (prod.merchant.plan_id == 2) if prod.merchant else False
                comm_taken = Decimal('0.00') if is_premium else deposit_10pct
                merch_earn = line_subtotal if is_premium else balance_90pct

                PaymentTransaction.objects.create(
                    gateway_ref_id=f"{payment_method.upper()}-{order_obj.order_id}-{random.randint(1000, 9999)}",
                    transac_status='Success',
                    commission_taken=comm_taken,
                    merchant_earnings=merch_earn,
                    order=order_obj
                )

                pickup_str = (
                    safety.estimated_expiry.strftime("%b %d, %Y %I:%M %p")
                    if safety and safety.estimated_expiry
                    else "Today, 5:00 PM"
                )

                created_claims.append({
                    "order_id": order_obj.order_id,
                    "voucher_code": final_voucher_code,
                    "food_name": prod.prod_name,
                    "qty": qty,
                    "establishment": prod.merchant.bus_name if prod.merchant else "Partner Establishment",
                    "address": prod.merchant.address if prod.merchant and prod.merchant.address else "Cebu City",
                    "pickup_deadline": pickup_str,
                    "total_value": f"{float(line_subtotal):.2f}",
                    "paid_today": f"{float(deposit_10pct):.2f}",
                    "remaining_balance": f"{float(balance_90pct):.2f}",
                })

            return Response({
                "message": "Reservation confirmed and 10% deposit paid!",
                "claims": created_claims,
            }, status=status.HTTP_201_CREATED)

        return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)


class CreatePayMongoCheckoutView(APIView):
    """
    Creates a REAL PayMongo Checkout Session (GCash, PayMaya, Card) when PAYMONGO_SECRET_KEY
    is configured in .env, returning the live checkout_url and session_id.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        amount_php = float(request.data.get("amount", 10.0))
        description = str(request.data.get("description", "RESERVE 10% Reservation Deposit"))
        payment_type = str(request.data.get("payment_method", "gcash")).lower()

        # PayMongo minimum checkout session amount is ₱20.00 (2000 centavos) in standard API, or 100 centavos
        amount_centavos = max(2000, int(round(amount_php * 100)))
        secret_key = getattr(settings, "PAYMONGO_SECRET_KEY", "").strip()

        if not secret_key:
            return Response({
                "error": "PAYMONGO_SECRET_KEY is not set in .env yet. Add your PayMongo Secret Key (sk_test_...) to use the live hosted checkout, or use the Instant Simulator button."
            }, status=status.HTTP_400_BAD_REQUEST)

        pm_types = ["gcash", "paymaya", "card"]
        if "maya" in payment_type:
            pm_types = ["paymaya", "gcash"]
        elif "gcash" in payment_type:
            pm_types = ["gcash", "paymaya"]

        payload = {
            "data": {
                "attributes": {
                    "send_email_receipt": True,
                    "show_description": True,
                    "show_line_items": True,
                    "description": description,
                    "payment_method_types": pm_types,
                    "line_items": [
                        {
                            "currency": "PHP",
                            "amount": amount_centavos,
                            "description": description,
                            "name": "RESERVE Cebu Food Rescue",
                            "quantity": 1,
                        }
                    ],
                    "success_url": "http://localhost:8081/consumer/claims",
                    "cancel_url": "http://localhost:8081/consumer/cart",
                }
            }
        }

        try:
            res = http_requests.post(
                "https://api.paymongo.com/v1/checkout_sessions",
                json=payload,
                auth=(secret_key, ""),
                timeout=10,
            )
            data = res.json()
            if res.status_code in (200, 201) and "data" in data:
                checkout_url = data["data"]["attributes"]["checkout_url"]
                session_id = data["data"]["id"]
                return Response({
                    "checkout_url": checkout_url,
                    "session_id": session_id,
                    "amount_charged_php": amount_centavos / 100.0,
                }, status=status.HTTP_200_OK)
            return Response({
                "error": data.get("errors", [{}])[0].get("detail", "PayMongo API rejected request.")
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)