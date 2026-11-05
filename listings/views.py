import re
import random
import uuid
import requests as http_requests
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.db.models import Avg
from django.contrib.auth.hashers import make_password
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from .utils import get_cebu_weather, calculate_ttt_expiry, calculate_haversine_km
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
from notifications.models import AdminNotification, UserNotification
from transactions.models import OrderReservation, PaymentTransaction, WithdrawalReq, RatingReview
from .serializers import PerishableProductSerializer


def ensure_listing_reference_data():
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
        3: "Piece (pc)",
        4: "Pack (pk)",
    }
    for uid, uname in {1: "Gram (g)", 2: "Kilogram (kg)", 3: "Piece (pc)", 4: "Pack (pk)"}.items():
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
        m = Merchant.objects.select_related('user', 'plan').filter(merch_id=int(raw_id)).first()
        if m:
            return m
    if email:
        m = Merchant.objects.select_related('user', 'plan').filter(user__user_email__iexact=str(email).strip()).first()
        if m:
            return m
    return Merchant.objects.select_related('user', 'plan').order_by('-merch_id').first()


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


def base_voucher_code(raw_code):
    return str(raw_code or "").strip().upper().split("-")[0]


class MarketplaceFeedView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        donated_commerce_ids = Donation.objects.values_list('listing_id', flat=True)
        donated_product_ids = ListingCommerce.objects.filter(
            listing_id__in=donated_commerce_ids
        ).values_list('listing__product_id', flat=True)

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
        listings = list(
            PerishableProduct.objects.select_related('category', 'unit', 'merchant__user')
            .exclude(prod_id__in=donated_product_ids)
        )

        prod_ids = [item.prod_id for item in listings]
        safety_map = {}
        for s in ListingSafety.objects.filter(product_id__in=prod_ids).select_related('commerce'):
            if s.product_id not in safety_map:
                safety_map[s.product_id] = s

        merch_user_ids = {item.merchant.user_id for item in listings if item.merchant and item.merchant.user_id}
        loc_map = {}
        for l in Location.objects.filter(user_id__in=merch_user_ids).order_by('-is_primary', '-loc_id'):
            if l.user_id not in loc_map:
                loc_map[l.user_id] = (float(l.latitude), float(l.longitude))

        max_radius_km = float(request.GET.get('radius', 10.0))
        serialized_feed = []

        for item in listings:
            safety_rec = safety_map.get(item.prod_id)
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

            merch_lat, merch_lng = 10.3157, 123.8854
            if item.merchant and item.merchant.user_id in loc_map:
                merch_lat, merch_lng = loc_map[item.merchant.user_id]

            dist_km = calculate_haversine_km(cons_lat, cons_lng, merch_lat, merch_lng)

            if dist_km <= max_radius_km:
                item_data = PerishableProductSerializer(item).data
                item_data['distance_km'] = dist_km
                item_data['distance'] = f"{dist_km:.1f} km"
                item_data['merchant_lat'] = merch_lat
                item_data['merchant_lng'] = merch_lng
                serialized_feed.append(item_data)

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

            exp_fmt = final_expiry.strftime("%b %d, %Y %I:%M %p")
            if merchant and merchant.user:
                UserNotification.objects.create(
                    user=merchant.user,
                    message=f"Listing '{new_listing.prod_name}' published ({parsed_qty} available). Live Cebu temp: {current_temp:.1f}°C • Expiry: {exp_fmt}."
                )
            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type="Listing",
                message=f"{merchant.bus_name if merchant else 'Merchant'} posted '{new_listing.prod_name}' (Exp: {exp_fmt} @ {current_temp:.1f}°C).",
                merchant=merchant,
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
            listing = PerishableProduct.objects.select_related('merchant__user').get(pk=pk)
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
    Strictly sorted by time (latest at index 0) with target_route for click navigation.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        events = []
        merchant = resolve_merchant(request.GET.get('merchant'), request.GET.get('email'))
        if not merchant:
            return Response([], status=status.HTTP_200_OK)

        now = timezone.now()
        now_ts = now.timestamp()

        # 1. Customer Purchases & Reservations (Grouped by Base Voucher Code)
        recent_orders = OrderReservation.objects.filter(
            listing__listing__product__merchant=merchant
        ).select_related('consumer', 'listing__listing__product').order_by('-ordered_at')[:30]

        seen_vouchers = set()
        for o in recent_orders:
            b_code = base_voucher_code(o.qr_voucher_code)
            v_key = f"{b_code}-{o.order_status}"
            if v_key in seen_vouchers:
                continue
            seen_vouchers.add(v_key)

            prod_name = o.listing.listing.product.prod_name if (o.listing and o.listing.listing and o.listing.listing.product) else "Surplus Item"
            buyer_name = o.consumer.cons_fullname if o.consumer else "A consumer"
            o_dt = timezone.localtime(o.ordered_at) if o.ordered_at else now
            time_str = o_dt.strftime("%b %d, %Y • %I:%M %p")
            sort_ts = o_dt.timestamp()

            if o.order_status == "Pending":
                events.append({
                    "id": f"order-pend-{b_code}",
                    "type": "order",
                    "title": f"New Customer Reservation ({b_code})",
                    "description": f"{buyer_name} reserved {prod_name} (Voucher {b_code}). Tap to review order in Orders.",
                    "time": time_str,
                    "sort_ts": sort_ts,
                    "target_route": "/establishment/orders",
                    "read": False,
                })
            elif o.order_status == "Completed":
                events.append({
                    "id": f"order-done-{b_code}",
                    "type": "order",
                    "title": f"Order Pickup Completed ({b_code})",
                    "description": f"{buyer_name} picked up order {b_code}. Deposit credited to your Active Wallet.",
                    "time": time_str,
                    "sort_ts": sort_ts + 1,
                    "target_route": "/establishment/earnings",
                    "read": False,
                })

        # 2. Customer Ratings & Reviews
        recent_reviews = RatingReview.objects.filter(
            surplus_listing__listing__product__merchant=merchant
        ).select_related('consumer', 'surplus_listing__listing__product').order_by('-review_id')[:15]

        for rev in recent_reviews:
            p_name = rev.surplus_listing.listing.product.prod_name if (rev.surplus_listing and rev.surplus_listing.listing) else "Food Listing"
            c_name = rev.consumer.cons_fullname if rev.consumer else "Consumer"
            stars = "★" * int(rev.rating_score or 5)
            r_dt = timezone.localtime(rev.created_at) if getattr(rev, 'created_at', None) else now
            events.append({
                "id": f"review-{rev.review_id}",
                "type": "review",
                "title": f"New Customer Rating {stars} ({rev.rating_score}/5)",
                "description": f"{c_name} rated '{p_name}': \"{rev.review_comment or 'Great food rescue experience!'}\"",
                "time": r_dt.strftime("%b %d, %Y • %I:%M %p"),
                "sort_ts": r_dt.timestamp(),
                "target_route": "/establishment/dashboard",
                "read": False,
            })

        # 3. Live Cebu Weather & TTT Shelf-Life Impact
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
                    f"Ambient TTT shelf-life decay is accelerated by ~{rate_pct}% across your {active_count} active listing(s)."
                )
            else:
                weather_desc = (
                    f"Cebu City weather is currently {curr_temp:.1f}°C ({curr_hum}% humidity). "
                    f"TTT shelf-life conditions are stable for your {active_count} active listing(s)."
                )
            events.append({
                "id": f"weather-ttt-{now.strftime('%Y%m%d-%H')}",
                "type": "expiry_1hr",
                "title": f"Live Cebu Weather & Expiry Impact ({curr_temp:.1f}°C)",
                "description": weather_desc,
                "time": timezone.localtime(now).strftime("%b %d, %Y • %I:%M %p"),
                "sort_ts": now_ts - 60,
                "target_route": "/establishment/listing",
                "read": False,
            })

        # 4. 1-Hour Expiry & Flagged Warnings
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
                            "time": timezone.localtime(expiry_dt).strftime("%b %d, %Y • %I:%M %p"),
                            "sort_ts": now_ts,
                            "target_route": "/establishment/listing",
                            "read": False,
                        })
                    else:
                        mins_left = max(1, int(seconds_remaining / 60))
                        events.append({
                            "id": f"expiry-1hr-{safety.pk}",
                            "type": "expiry_1hr",
                            "title": "1-Hour Expiry Warning",
                            "description": f"Your listing '{prod_name}' will reach its expiry window in {mins_left} mins. Consider donating it to a Food Bank!",
                            "time": f"In ~{mins_left} mins ({timezone.localtime(expiry_dt).strftime('%I:%M %p')})",
                            "sort_ts": now_ts - 10,
                            "target_route": "/establishment/donation",
                            "read": False,
                        })

        # 5. Food Bank Claims on This Merchant's Donations
        my_donations = Donation.objects.filter(
            merchant=merchant,
            status__in=['Claimed', 'Completed']
        ).select_related('food_bank', 'listing__listing__product').order_by('-updated_at')[:10]

        for don in my_donations:
            fb_name = don.food_bank.org_name if don.food_bank else "Partner Food Bank"
            p_name = don.listing.listing.product.prod_name if (don.listing and don.listing.listing and don.listing.listing.product) else "Surplus Donation"
            d_dt = timezone.localtime(don.updated_at) if don.updated_at else now
            events.append({
                "id": f"don-claim-{don.donation_id}-{don.status}",
                "type": "donation",
                "title": "Donation Claimed by Food Bank!" if don.status == "Claimed" else "Donation Received by Food Bank",
                "description": f"{fb_name} {don.status.lower()} your donation of {don.qty_donated}x {p_name}.",
                "time": d_dt.strftime("%b %d, %Y • %I:%M %p"),
                "sort_ts": d_dt.timestamp(),
                "target_route": "/establishment/donation",
                "read": False,
            })

        # 6. Direct Account Compliance / Payout Notices
        direct_notifs = AdminNotification.objects.filter(
            merchant=merchant,
            admin_notif_type__in=['Compliance', 'Payout']
        ).order_by('-pk')[:10]

        for an in direct_notifs:
            an_dt = timezone.localtime(an.created_at) if getattr(an, 'created_at', None) else now
            target_rt = "/establishment/earnings" if an.admin_notif_type == "Payout" else "/establishment/profile"
            events.append({
                "id": f"compliance-{an.pk}",
                "type": "system",
                "title": f"Account Update ({an.admin_notif_type})",
                "description": an.message,
                "time": an_dt.strftime("%b %d, %Y • %I:%M %p"),
                "sort_ts": an_dt.timestamp(),
                "target_route": target_rt,
                "read": False,
            })

        # Sort strictly latest first
        events.sort(key=lambda x: x.get("sort_ts", 0), reverse=True)
        return Response(events, status=status.HTTP_200_OK)


class EstablishmentAnnouncementsView(APIView):
    """
    Returns announcements from the merchant's registration date onward, sorted newest first.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        merchant = resolve_merchant(request.GET.get('merchant'), request.GET.get('email'))
        broadcasts_qs = AdminNotification.objects.filter(
            admin_notif_type__startswith='Broadcast'
        ).order_by('-pk')

        if merchant and merchant.user and merchant.user.created_at:
            # Show announcements from the date the account registered onward
            start_of_reg_day = merchant.user.created_at.replace(hour=0, minute=0, second=0, microsecond=0)
            broadcasts_qs = broadcasts_qs.filter(
                created_at__gte=start_of_reg_day
            ) | broadcasts_qs.filter(created_at__isnull=True)
            broadcasts_qs = broadcasts_qs.order_by('-pk')

        announcements = []
        for b in broadcasts_qs[:25]:
            audience = b.admin_notif_type.replace('Broadcast:', '').strip() or 'All Users (System-wide)'
            if audience not in ['All Users (System-wide)', 'Merchants Only']:
                continue
            parts = (b.message or '').split(' || ', 1)
            title = parts[0] if len(parts) > 1 else 'System Announcement'
            body = parts[1] if len(parts) > 1 else b.message
            b_dt = timezone.localtime(b.created_at) if getattr(b, 'created_at', None) else timezone.now()
            announcements.append({
                "id": f"broadcast-{b.pk}",
                "audience": audience,
                "title": title,
                "body": body,
                "date": b_dt.strftime("%b %d, %Y • %I:%M %p"),
                "sort_ts": b_dt.timestamp(),
            })

        announcements.sort(key=lambda x: x.get("sort_ts", 0), reverse=True)
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

        # Merchant Overall Rating Tally
        reviews_qs = RatingReview.objects.filter(
            surplus_listing__listing__product__merchant=merchant
        ).select_related('consumer', 'surplus_listing__listing__product').order_by('-review_id')
        review_count = reviews_qs.count()
        avg_rating_val = reviews_qs.aggregate(avg=Avg('rating_score'))['avg'] or 0.0

        # Track monthly earnings across the last 10 months
        monthly_earnings_map = {}
        month_sequence = []
        for i in range(9, -1, -1):
            m_dt = (now.date().replace(day=1) - timedelta(days=i * 28)).replace(day=1)
            m_key = m_dt.strftime("%b")
            if m_key not in monthly_earnings_map:
                monthly_earnings_map[m_key] = Decimal('0.00')
                month_sequence.append(m_key)

        # 1. Inspect OrderReservation rows for this merchant & consolidate multi-item checkouts by Base Voucher Code
        orders_qs = OrderReservation.objects.filter(
            listing__listing__product__merchant=merchant
        ).select_related(
            'consumer__user',
            'listing__listing__product__category',
            'listing__listing__product__unit'
        ).order_by('-ordered_at', 'order_id')

        grouped_orders = {}
        for o in orders_qs:
            commerce = o.listing
            safety = commerce.listing if commerce else None
            prod = safety.product if safety else None
            if not prod:
                continue

            seen_order_keys.add(prod.prod_id)
            b_code = base_voucher_code(o.qr_voucher_code)
            unit_name = prod.unit.unit_name if prod.unit else "pc"
            unit_short = unit_name.split("(")[1].replace(")", "").strip() if "(" in unit_name and ")" in unit_name else unit_name
            cat_name = prod.category.category_name if prod.category else "Surplus"

            disc_price = Decimal(str(commerce.discounted_price or 0))
            orig_price = Decimal(str(commerce.orig_price or disc_price))
            line_total = (disc_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
            line_orig_total = (orig_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
            deposit_paid = Decimal(str(o.downpayment_amount or 0)).quantize(Decimal('0.01'))
            cash_due = max(Decimal('0.00'), line_total - deposit_paid)

            pickup_date_str = timezone.localtime(safety.estimated_expiry).strftime("%b %d, %Y") if safety and safety.estimated_expiry else "Today"
            pickup_time_str = timezone.localtime(safety.estimated_expiry).strftime("%I:%M %p") if safety and safety.estimated_expiry else "05:00 PM"

            expiry_label = f"{pickup_date_str} • {pickup_time_str}"
            if safety and safety.estimated_expiry:
                exp_dt = safety.estimated_expiry
                if timezone.is_naive(exp_dt):
                    exp_dt = timezone.make_aware(exp_dt)
                secs_left = (exp_dt - now).total_seconds()
                if 0 < secs_left <= 7200 and o.order_status == 'Pending':
                    nearing_expiry_count += 1
                if secs_left <= 0:
                    expiry_label = f"Expired ({pickup_date_str} {pickup_time_str})"
                elif secs_left < 3600:
                    expiry_label = f"{max(1, int(secs_left // 60))}m left ({pickup_time_str})"
                else:
                    expiry_label = f"{int(secs_left // 3600)}h left ({pickup_date_str} {pickup_time_str})"

            line_item_info = {
                "order_id": o.order_id,
                "prod_id": prod.prod_id,
                "food_name": prod.prod_name,
                "category": cat_name,
                "qty": o.order_qty,
                "unit": unit_short,
                "unit_price": f"₱{disc_price:,.2f}",
                "orig_price": f"₱{orig_price:,.2f}",
                "subtotal": f"₱{line_total:,.2f}",
                "image": prod.image_path or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                "expiry": f"{pickup_date_str} • {pickup_time_str}",
            }

            if b_code not in grouped_orders:
                o_local = timezone.localtime(o.ordered_at) if o.ordered_at else now
                grouped_orders[b_code] = {
                    "id": b_code,
                    "order_id": o.order_id,
                    "prod_id": prod.prod_id,
                    "commerce_id": commerce.pk,
                    "customer": o.consumer.cons_fullname if o.consumer else "Consumer",
                    "customer_phone": o.consumer.phone_num if (o.consumer and o.consumer.phone_num) else "Verified Buyer",
                    "items_list": [line_item_info],
                    "total_qty_num": o.order_qty,
                    "unit_short": unit_short,
                    "ordered_dt": o_local,
                    "time": o_local.strftime("%b %d, %Y | %I:%M %p"),
                    "expiry": expiry_label if o.order_status == 'Pending' else "Picked Up",
                    "expiryDate": pickup_date_str,
                    "expiryTime": pickup_time_str,
                    "status": "Pending Pickup" if o.order_status == 'Pending' else "Successful",
                    "raw_status": o.order_status,
                    "image": prod.image_path or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                    "establishment": merchant.bus_name,
                    "total_val_dec": line_total,
                    "orig_val_dec": line_orig_total,
                    "deposit_dec": deposit_paid,
                    "cash_dec": cash_due,
                    "category": cat_name,
                    "description": prod.prod_desc or "Consumer rescue reservation.",
                    "preparationDate": (safety.safely_anchor_time if safety else None) or pickup_date_str,
                    "storageCondition": "Standard",
                    "pickupDate": pickup_date_str,
                    "pickupTime": pickup_time_str,
                    "rescueVoucher": True,
                }
            else:
                grp = grouped_orders[b_code]
                grp["items_list"].append(line_item_info)
                grp["total_qty_num"] += o.order_qty
                grp["total_val_dec"] += line_total
                grp["orig_val_dec"] += line_orig_total
                grp["deposit_dec"] += deposit_paid
                grp["cash_dec"] += cash_due

        for b_code, grp in grouped_orders.items():
            items_list = grp["items_list"]
            if len(items_list) == 1:
                item_summary_title = items_list[0]["food_name"]
                qty_summary = f"{items_list[0]['qty']} {items_list[0]['unit']}"
            else:
                names_joined = ", ".join(f"{i['qty']}x {i['food_name']}" for i in items_list)
                item_summary_title = f"{items_list[0]['food_name']} +{len(items_list) - 1} more ({names_joined})"
                qty_summary = f"{grp['total_qty_num']} items"

            total_p = grp["total_val_dec"]
            orig_p = grp["orig_val_dec"]
            dep_p = grp["deposit_dec"]
            cash_p = grp["cash_dec"]

            card = {
                "id": b_code,
                "order_id": grp["order_id"],
                "prod_id": grp["prod_id"],
                "commerce_id": grp["commerce_id"],
                "customer": grp["customer"],
                "customer_phone": grp["customer_phone"],
                "item": item_summary_title,
                "items_breakdown": items_list,
                "qty": qty_summary,
                "raw_qty": grp["total_qty_num"],
                "time": grp["time"],
                "expiry": grp["expiry"],
                "expiryDate": grp["expiryDate"],
                "expiryTime": grp["expiryTime"],
                "status": grp["status"],
                "image": grp["image"],
                "establishment": grp["establishment"],
                "unit_price": items_list[0]["unit_price"],
                "original_total": f"₱{orig_p:,.2f}",
                "total_price": f"₱{total_p:,.2f}",
                "deposit_paid": f"₱{dep_p:,.2f}",
                "cash_due": f"₱{cash_p:,.2f}",
                "price": f"₱{total_p:,.2f} (10% Paid: ₱{dep_p:,.2f} | 90% Cash: ₱{cash_p:,.2f})",
                "category": grp["category"],
                "description": grp["description"],
                "preparationDate": grp["preparationDate"],
                "storageCondition": grp["storageCondition"],
                "pickupDate": grp["pickupDate"],
                "pickupTime": grp["pickupTime"],
                "rescueVoucher": True,
            }

            if grp["raw_status"] == "Pending":
                pending_orders.append(card)
            elif grp["raw_status"] == "Completed":
                completed_orders.append(card)
                is_premium = (merchant.plan_id == 2)
                comm_fee = Decimal('0.00') if is_premium else dep_p
                net_earn = (total_p - comm_fee).quantize(Decimal('0.01'))
                m_label = grp["ordered_dt"].strftime("%b")
                if m_label in monthly_earnings_map:
                    monthly_earnings_map[m_label] += net_earn

                transactions_list.append({
                    "id": b_code,
                    "customer": grp["customer"],
                    "date": grp["time"],
                    "food": item_summary_title,
                    "items_breakdown": items_list,
                    "qty": qty_summary,
                    "original": f"₱{orig_p:,.2f}",
                    "discounted": f"₱{total_p:,.2f}",
                    "deposit_paid": f"₱{dep_p:,.2f}",
                    "cash_collected": f"₱{cash_p:,.2f}",
                    "commission_fee": f"₱{comm_fee:,.2f}",
                    "net": f"₱{net_earn:,.2f}",
                    "total": f"₱{net_earn:,.2f}",
                })

        # 2. Inspect Product Commerce records for metrics
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
            qty_sold = int(commerce.qty_sold or 0)

            pickup_date_str = timezone.localtime(safety.estimated_expiry).strftime("%b %d, %Y") if safety and safety.estimated_expiry else "Today"

            if qty_sold > 0:
                gross_total = disc_price * Decimal(qty_sold)
                reservation_fee_10pct = (gross_total * Decimal('0.10')).quantize(Decimal('0.01'))
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
                    transactions_list.append({
                        "id": f"OID{900 + prod.prod_id}",
                        "customer": "Verified Consumer",
                        "date": pickup_date_str,
                        "food": prod.prod_name,
                        "items_breakdown": [{
                            "food_name": prod.prod_name,
                            "qty": qty_sold,
                            "unit": unit_short,
                            "unit_price": f"₱{disc_price:,.2f}",
                            "subtotal": f"₱{gross_total:,.2f}",
                        }],
                        "qty": f"{qty_sold} {unit_short}",
                        "original": f"₱{orig_price:,.2f}",
                        "discounted": f"₱{disc_price:,.2f}",
                        "deposit_paid": f"₱{reservation_fee_10pct:,.2f}",
                        "cash_collected": f"₱{(gross_total - reservation_fee_10pct):,.2f}",
                        "commission_fee": f"₱{commission_fee:,.2f}",
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

        # 3. Donations
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

        # 4. Real Withdrawal History from WithdrawalReq
        withdrawals_list = []
        w_reqs = WithdrawalReq.objects.filter(merchant=merchant).order_by('-withdrawal_id')
        for w in w_reqs:
            amt_v = float(w.amount or 0)
            fee_v = float(w.fee_deducted or 0)
            net_v = float(w.net_payout or amt_v)
            withdrawals_list.append({
                "id": f"PO-{w.withdrawal_id}",
                "withdrawal_id": w.withdrawal_id,
                "amount": f"₱{amt_v:,.2f}",
                "raw_amount": amt_v,
                "fee_deducted": f"₱{fee_v:,.2f}",
                "net_payout": f"₱{net_v:,.2f}",
                "channel": w.channel or "GCash",
                "account_number": w.gcash_num or merchant.phone or "",
                "account_name": w.account_name or merchant.contact_person or merchant.bus_name,
                "reference_number": w.reference_number or "",
                "status": w.withdrawal_status or "Pending",
                "created_at": timezone.localtime(w.created_at).strftime("%b %d, %Y • %I:%M %p") if getattr(w, 'created_at', None) else "Recent",
                "processed_at": timezone.localtime(w.processed_at).strftime("%b %d, %Y • %I:%M %p") if getattr(w, 'processed_at', None) else "",
            })

        wallet_bal = Decimal(str(merchant.wallet_bal or 0))
        if total_earnings_val == 0 and wallet_bal > 0:
            total_earnings_val = wallet_bal

        cur_month_key = now.strftime("%b")
        if cur_month_key in monthly_earnings_map and monthly_earnings_map[cur_month_key] == 0 and total_earnings_val > 0:
            monthly_earnings_map[cur_month_key] = total_earnings_val

        monthly_earnings_chart = [
            {"month": m_k, "amount": float(monthly_earnings_map.get(m_k, Decimal('0.00')))}
            for m_k in month_sequence
        ]

        rescued_kg_float = float(total_rescued_kg)
        co2_avoided_float = round(rescued_kg_float * 2.0, 1)
        people_helped_count = int(successful_rescues_count)
        portions_rescued_count = int(round(rescued_kg_float * 2))

        months_labels = month_sequence[-6:] if len(month_sequence) >= 6 else ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"]
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
                "avg_rating": round(float(avg_rating_val), 1) if review_count > 0 else 0.0,
                "review_count": review_count,
                "reviews": [
                    {
                        "id": r.review_id,
                        "consumer": r.consumer.cons_fullname if r.consumer else "Verified Consumer",
                        "item": r.surplus_listing.listing.product.prod_name if (r.surplus_listing and r.surplus_listing.listing) else "Surplus Food",
                        "score": r.rating_score,
                        "comment": r.review_comment or "",
                        "date": timezone.localtime(r.created_at).strftime("%b %d, %Y • %I:%M %p") if getattr(r, 'created_at', None) else "Recent",
                    }
                    for r in reviews_qs[:20]
                ],
            },
            "orders": {
                "active_pickups_count": len(pending_orders),
                "nearing_expiry_count": nearing_expiry_count,
                "pending_orders": pending_orders,
                "completed_orders": completed_orders,
            },
            "earnings": {
                "total_earnings": f"₱{float(total_earnings_val):,.2f}",
                "raw_total_earnings": float(total_earnings_val),
                "wallet_balance": f"₱{float(wallet_bal):,.2f}",
                "raw_wallet_balance": float(wallet_bal),
                "saved_on_spoilage": f"₱{float(saved_spoilage_val):,.2f}",
                "transactions_completed": len(completed_orders),
                "monthly_earnings": monthly_earnings_chart,
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

        elif action == "preview_order":
            raw_code = base_voucher_code(request.data.get("order_code", ""))
            prod_id = request.data.get("prod_id")

            matching_orders = list(
                OrderReservation.objects.filter(
                    qr_voucher_code__istartswith=raw_code,
                    listing__listing__product__merchant=merchant
                ).select_related('listing__listing__product__category', 'listing__listing__product__unit', 'consumer')
            ) if raw_code else []

            if not matching_orders and prod_id:
                matching_orders = list(
                    OrderReservation.objects.filter(
                        listing__listing__product__prod_id=prod_id,
                        listing__listing__product__merchant=merchant,
                        order_status='Pending'
                    ).select_related('listing__listing__product__category', 'listing__listing__product__unit', 'consumer')
                )

            if not matching_orders:
                return Response({"error": f"No matching order found for voucher '{raw_code}'."}, status=status.HTTP_404_NOT_FOUND)

            if all(o.order_status == 'Completed' for o in matching_orders):
                return Response({"error": f"Voucher {raw_code} has already been claimed and completed."}, status=status.HTTP_400_BAD_REQUEST)

            first_o = matching_orders[0]
            total_price = Decimal('0.00')
            deposit_paid = Decimal('0.00')
            total_qty = 0
            items_breakdown = []

            for o in matching_orders:
                comm = o.listing
                saf = comm.listing if comm else None
                prd = saf.product if saf else None
                u_name = prd.unit.unit_name if prd and prd.unit else "pc"
                u_short = u_name.split("(")[1].replace(")", "").strip() if "(" in u_name and ")" in u_name else u_name
                d_price = Decimal(str(comm.discounted_price or 0))
                l_tot = (d_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
                dep = Decimal(str(o.downpayment_amount or 0)).quantize(Decimal('0.01'))

                total_price += l_tot
                deposit_paid += dep
                total_qty += o.order_qty
                items_breakdown.append({
                    "food_name": prd.prod_name if prd else "Surplus Food",
                    "qty": o.order_qty,
                    "unit": u_short,
                    "unit_price": f"₱{d_price:,.2f}",
                    "subtotal": f"₱{l_tot:,.2f}",
                })

            cash_due = max(Decimal('0.00'), total_price - deposit_paid)
            first_saf = first_o.listing.listing if first_o.listing else None
            first_prd = first_saf.product if first_saf else None
            exp_date_str = timezone.localtime(first_saf.estimated_expiry).strftime("%b %d, %Y") if first_saf and first_saf.estimated_expiry else "Today"
            exp_time_str = timezone.localtime(first_saf.estimated_expiry).strftime("%I:%M %p") if first_saf and first_saf.estimated_expiry else "05:00 PM"

            item_title = (
                items_breakdown[0]["food_name"]
                if len(items_breakdown) == 1
                else f"{items_breakdown[0]['food_name']} +{len(items_breakdown) - 1} more"
            )

            return Response({
                "order": {
                    "id": base_voucher_code(first_o.qr_voucher_code),
                    "prod_id": first_prd.prod_id if first_prd else None,
                    "customer": first_o.consumer.cons_fullname if first_o.consumer else "Consumer",
                    "customer_phone": first_o.consumer.phone_num if (first_o.consumer and first_o.consumer.phone_num) else "Verified Buyer",
                    "item": item_title,
                    "items_breakdown": items_breakdown,
                    "category": first_prd.category.category_name if (first_prd and first_prd.category) else "Surplus",
                    "qty": f"{total_qty} items" if len(items_breakdown) > 1 else f"{items_breakdown[0]['qty']} {items_breakdown[0]['unit']}",
                    "unit_price": items_breakdown[0]["unit_price"],
                    "total_price": f"₱{total_price:,.2f}",
                    "deposit_paid": f"₱{deposit_paid:,.2f}",
                    "cash_due": f"₱{cash_due:,.2f}",
                    "price": f"₱{total_price:,.2f} (10% Paid: ₱{deposit_paid:,.2f} | 90% Cash: ₱{cash_due:,.2f})",
                    "time": timezone.localtime(first_o.ordered_at).strftime("%b %d, %Y • %I:%M %p") if first_o.ordered_at else "Recent",
                    "pickupDate": exp_date_str,
                    "pickupTime": exp_time_str,
                    "expiry": f"{exp_date_str} • {exp_time_str}",
                    "status": "Pending Pickup",
                    "image": (first_prd.image_path if first_prd else "") or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                }
            }, status=status.HTTP_200_OK)

        elif action == "confirm_order":
            prod_id = request.data.get("prod_id")
            raw_code = base_voucher_code(request.data.get("order_code", ""))

            matching_orders = list(
                OrderReservation.objects.filter(
                    qr_voucher_code__istartswith=raw_code,
                    listing__listing__product__merchant=merchant,
                    order_status='Pending'
                ).select_related('listing__listing__product', 'consumer__user')
            ) if raw_code else []

            if not matching_orders and prod_id:
                matching_orders = list(
                    OrderReservation.objects.filter(
                        listing__listing__product__prod_id=prod_id,
                        listing__listing__product__merchant=merchant,
                        order_status='Pending'
                    ).select_related('listing__listing__product', 'consumer__user')
                )

            if matching_orders:
                total_deposit = Decimal('0.00')
                total_gross = Decimal('0.00')
                total_weight = Decimal('0.00')
                released_names = []
                consumer_obj = matching_orders[0].consumer

                for order_res in matching_orders:
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

                    dep_amt = Decimal(str(order_res.downpayment_amount or 0))
                    grs_amt = Decimal(str(commerce.discounted_price or 0)) * Decimal(qty_done)
                    total_deposit += dep_amt
                    total_gross += grs_amt
                    total_weight += Decimal(str(order_res.rescued_weight_kg or 1))
                    released_names.append(f"{qty_done}x {prod.prod_name}")

                    StockLedger.objects.create(
                        listing=commerce,
                        transaction_type="Pickup_Confirmed",
                        qty_change=-qty_done,
                        reason=f"Verified voucher {raw_code}"
                    )

                if consumer_obj:
                    consumer_obj.total_food_saved = Decimal(str(consumer_obj.total_food_saved or 0)) + total_weight
                    consumer_obj.save()
                    if consumer_obj.user:
                        UserNotification.objects.create(
                            user=consumer_obj.user,
                            message=f"Pickup completed for Voucher {raw_code} ({', '.join(released_names)}) at {merchant.bus_name}! Tap 'My Claims' to rate and review your order."
                        )

                cash_90pct = max(Decimal('0.00'), total_gross - total_deposit)
                merchant.wallet_bal = Decimal(str(merchant.wallet_bal or 0)) + total_deposit
                merchant.save()

                AdminNotification.objects.create(
                    user_id=1,
                    admin_notif_type="Reservation",
                    message=f"Order {raw_code} ({', '.join(released_names)}) released by {merchant.bus_name}.",
                    merchant=merchant,
                )

                return Response({
                    "message": (
                        f"Voucher {raw_code} Released ({', '.join(released_names)})!\n"
                        f"• Collected 90% Cash from Customer: ₱{float(cash_90pct):,.2f}\n"
                        f"• 10% Online Deposit Credited to Wallet: ₱{float(total_deposit):,.2f}"
                    )
                }, status=status.HTTP_200_OK)

            return Response({"error": "Matching pending voucher or order ID not found."}, status=status.HTTP_404_NOT_FOUND)

        elif action == "request_withdrawal":
            current_bal = Decimal(str(merchant.wallet_bal or 0))
            if current_bal <= 0:
                return Response({"error": "Your active wallet balance is ₱0.00."}, status=status.HTTP_400_BAD_REQUEST)

            raw_amt = request.data.get("amount")
            try:
                req_amt = Decimal(str(raw_amt)) if raw_amt is not None else current_bal
            except Exception:
                return Response({"error": "Please enter a valid withdrawal amount."}, status=status.HTTP_400_BAD_REQUEST)

            if req_amt <= 0 or req_amt > current_bal:
                return Response({
                    "error": f"Please enter an amount between ₱1.00 and your available balance (₱{float(current_bal):,.2f})."
                }, status=status.HTTP_400_BAD_REQUEST)

            channel = str(request.data.get("channel", "GCash")).strip()
            account_number = str(request.data.get("account_number") or merchant.phone or "").strip()
            account_name = str(request.data.get("account_name") or merchant.contact_person or merchant.bus_name).strip()

            if not account_number or not account_name:
                return Response({
                    "error": f"Please enter both your {channel} account number and account name."
                }, status=status.HTTP_400_BAD_REQUEST)

            is_premium = (merchant.plan_id == 2)
            fee_deducted = Decimal('0.00') if is_premium else (req_amt * Decimal('0.10')).quantize(Decimal('0.01'))
            net_payout = (req_amt - fee_deducted).quantize(Decimal('0.01'))
            tier_label = "Premium Tier (0% Fee)" if is_premium else f"Free Tier (10% Fee: -₱{float(fee_deducted):,.2f})"

            w_req = WithdrawalReq.objects.create(
                merchant=merchant,
                amount=req_amt,
                channel=channel,
                gcash_num=account_number,
                account_name=account_name,
                fee_deducted=fee_deducted,
                net_payout=net_payout,
                withdrawal_status="Pending",
            )

            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type="Payout",
                message=f"Withdrawal Request PO-{w_req.withdrawal_id} of ₱{float(req_amt):,.2f} (Net: ₱{float(net_payout):,.2f} via {channel} {account_number}) submitted by {merchant.bus_name}.",
                merchant=merchant,
                withdrawal=w_req,
            )

            return Response({
                "message": (
                    f"Withdrawal Request PO-{w_req.withdrawal_id} Submitted!\n"
                    f"• Channel: {channel} ({account_number} - {account_name})\n"
                    f"• Requested Amount: ₱{float(req_amt):,.2f}\n"
                    f"• {tier_label}\n"
                    f"• Net Payout to Receive: ₱{float(net_payout):,.2f}"
                ),
                "withdrawal_id": w_req.withdrawal_id,
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
            'listing__listing__product__merchant__user',
            'listing__listing__product__unit',
            'listing__listing__product__category'
        ).order_by('-ordered_at', 'order_id')

        consumer_loc = Location.objects.filter(user=consumer.user).order_by('-is_primary', '-loc_id').first()

        consumer_reviews = {
            r.order_id: r for r in RatingReview.objects.filter(consumer=consumer) if r.order_id
        }

        grouped_claims = {}
        notifs_list = []

        for o in orders_qs:
            commerce = o.listing
            safety = commerce.listing if commerce else None
            prod = safety.product if safety else None
            merch = prod.merchant if prod else None

            b_code = base_voucher_code(o.qr_voucher_code)

            merch_lat, merch_lng = 10.3157, 123.8854
            if merch and merch.user:
                m_loc = Location.objects.filter(user=merch.user).order_by('-is_primary', '-loc_id').first()
                if m_loc:
                    merch_lat, merch_lng = float(m_loc.latitude), float(m_loc.longitude)

            unit_price = Decimal(str(commerce.discounted_price if commerce else 0))
            orig_unit_price = Decimal(str(commerce.orig_price if commerce and commerce.orig_price else unit_price))
            total_val = (unit_price * Decimal(o.order_qty)).quantize(Decimal('0.01'))
            paid_deposit = Decimal(str(o.downpayment_amount or (total_val * Decimal('0.10')))).quantize(Decimal('0.01'))
            remaining_bal = max(Decimal('0.00'), total_val - paid_deposit)
            savings_val = max(Decimal('0.00'), (orig_unit_price - unit_price) * Decimal(o.order_qty))

            pickup_deadline_str = (
                timezone.localtime(safety.estimated_expiry).strftime("%b %d, %Y %I:%M %p")
                if safety and safety.estimated_expiry
                else "Today, 5:00 PM"
            )
            o_local = timezone.localtime(o.ordered_at) if o.ordered_at else timezone.now()
            order_date_str = o_local.strftime("%b %d, %Y • %I:%M %p")

            existing_rev = consumer_reviews.get(o.order_id)
            if not existing_rev and commerce:
                existing_rev = RatingReview.objects.filter(consumer=consumer, surplus_listing=commerce).first()

            line_item = {
                "order_id": o.order_id,
                "prod_id": prod.prod_id if prod else None,
                "food_name": prod.prod_name if prod else f"Rescue Item #{o.order_id}",
                "qty": o.order_qty,
                "unit_price": f"{float(unit_price):.2f}",
                "orig_price": f"{float(orig_unit_price):.2f}",
                "subtotal": f"{float(total_val):.2f}",
                "image": (prod.image_path if prod else "") or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                "pickup_deadline": pickup_deadline_str,
            }

            if b_code not in grouped_claims:
                grouped_claims[b_code] = {
                    "order_id": o.order_id,
                    "order_ids": [o.order_id],
                    "prod_id": prod.prod_id if prod else None,
                    "commerce_id": commerce.pk if commerce else None,
                    "merchant_id": merch.merch_id if merch else None,
                    "voucher_code": b_code,
                    "status": o.order_status,
                    "total_qty": o.order_qty,
                    "items_breakdown": [line_item],
                    "category": prod.category.category_name if (prod and prod.category) else "Surplus",
                    "description": prod.prod_desc if prod else "",
                    "image": (prod.image_path if prod else "") or "https://images.unsplash.com/photo-1509440159596-0249088772ff",
                    "establishment": merch.bus_name if merch else "Partner Establishment",
                    "address": (merch.address if merch and merch.address else "Cebu City"),
                    "merchant_lat": merch_lat,
                    "merchant_lng": merch_lng,
                    "pickup_deadline": pickup_deadline_str,
                    "ordered_at": order_date_str,
                    "sort_ts": o_local.timestamp(),
                    "total_val_dec": total_val,
                    "paid_dec": paid_deposit,
                    "rem_dec": remaining_bal,
                    "sav_dec": savings_val,
                    "is_reviewed": bool(existing_rev),
                    "rating_score": existing_rev.rating_score if existing_rev else 0,
                    "review_comment": existing_rev.review_comment if existing_rev else "",
                }
            else:
                g = grouped_claims[b_code]
                g["order_ids"].append(o.order_id)
                g["total_qty"] += o.order_qty
                g["items_breakdown"].append(line_item)
                g["total_val_dec"] += total_val
                g["paid_dec"] += paid_deposit
                g["rem_dec"] += remaining_bal
                g["sav_dec"] += savings_val
                if existing_rev and not g["is_reviewed"]:
                    g["is_reviewed"] = True
                    g["rating_score"] = existing_rev.rating_score
                    g["review_comment"] = existing_rev.review_comment

        claims_list = []
        for b_code, g in grouped_claims.items():
            ib = g["items_breakdown"]
            if len(ib) == 1:
                food_summary = ib[0]["food_name"]
            else:
                food_summary = f"{ib[0]['food_name']} +{len(ib) - 1} more ({', '.join(str(x['qty']) + 'x ' + x['food_name'] for x in ib)})"

            claim_row = {
                "order_id": g["order_id"],
                "order_ids": g["order_ids"],
                "prod_id": g["prod_id"],
                "commerce_id": g["commerce_id"],
                "merchant_id": g["merchant_id"],
                "voucher_code": b_code,
                "status": g["status"],
                "qty": g["total_qty"],
                "food_name": food_summary,
                "items_breakdown": ib,
                "category": g["category"],
                "description": g["description"],
                "image": g["image"],
                "establishment": g["establishment"],
                "address": g["address"],
                "merchant_lat": g["merchant_lat"],
                "merchant_lng": g["merchant_lng"],
                "pickup_deadline": g["pickup_deadline"],
                "ordered_at": g["ordered_at"],
                "total_value": f"{float(g['total_val_dec']):.2f}",
                "paid_today": f"{float(g['paid_dec']):.2f}",
                "remaining_balance": f"{float(g['rem_dec']):.2f}",
                "savings": f"{float(g['sav_dec']):.2f}",
                "is_reviewed": g["is_reviewed"],
                "rating_score": g["rating_score"],
                "review_comment": g["review_comment"],
            }
            claims_list.append(claim_row)

            if g["status"] == "Pending":
                notifs_list.append({
                    "id": f"ord-pend-{b_code}",
                    "type": "order",
                    "icon": "checkmark-circle-outline",
                    "title": f"Reservation Confirmed ({b_code})",
                    "text": f"Your reservation for {food_summary} at {g['establishment']} is ready for pickup before {g['pickup_deadline']}.",
                    "time": g["ordered_at"],
                    "sort_ts": g["sort_ts"],
                    "target_route": f"/consumer/claims?voucher={b_code}",
                    "unread": True,
                })
            elif g["status"] == "Completed":
                notifs_list.append({
                    "id": f"ord-done-{b_code}",
                    "type": "order",
                    "icon": "pricetag-outline",
                    "title": f"Pickup Completed ({b_code})",
                    "text": f"You rescued {food_summary} and saved ₱{float(g['sav_dec']):.2f}! Tap to view summary & rate your experience.",
                    "time": g["ordered_at"],
                    "sort_ts": g["sort_ts"] + 1,
                    "target_route": f"/consumer/claims?voucher={b_code}",
                    "unread": False,
                })

        # Announcements from consumer's registration date onward
        broadcasts_qs = AdminNotification.objects.filter(admin_notif_type__startswith='Broadcast').order_by('-pk')
        if consumer.user and consumer.user.created_at:
            start_reg = consumer.user.created_at.replace(hour=0, minute=0, second=0, microsecond=0)
            broadcasts_qs = (
                broadcasts_qs.filter(created_at__gte=start_reg) |
                broadcasts_qs.filter(created_at__isnull=True)
            ).order_by('-pk')

        for b in broadcasts_qs[:15]:
            aud = b.admin_notif_type.replace('Broadcast:', '').strip()
            if aud in ['All Users (System-wide)', 'Consumers Only']:
                parts = (b.message or '').split(' || ', 1)
                b_local = timezone.localtime(b.created_at) if getattr(b, 'created_at', None) else timezone.now()
                notifs_list.append({
                    "id": f"bcast-{b.pk}",
                    "type": "announcement",
                    "icon": "megaphone-outline",
                    "title": parts[0] if len(parts) > 1 else "System Announcement",
                    "text": parts[1] if len(parts) > 1 else b.message,
                    "time": b_local.strftime("%b %d, %Y • %I:%M %p"),
                    "sort_ts": b_local.timestamp(),
                    "target_route": "/consumer/homepage",
                    "unread": True,
                })

        notifs_list.sort(key=lambda x: x.get("sort_ts", 0), reverse=True)

        return Response({
            "profile": {
                "cons_id": consumer.cons_id,
                "full_name": consumer.cons_fullname,
                "email": consumer.user.user_email,
                "phone": consumer.phone_num or "",
                "address": consumer.address or "Cebu City",
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

        elif action == "submit_review":
            order_id = request.data.get("order_id")
            voucher_code = base_voucher_code(request.data.get("voucher_code", ""))
            rating_score = int(request.data.get("rating_score", 5))
            review_comment = str(request.data.get("review_comment", "")).strip()

            rating_score = max(1, min(5, rating_score))
            if voucher_code:
                batch_orders = list(
                    OrderReservation.objects.select_related('listing__listing__product__merchant__user').filter(
                        qr_voucher_code__istartswith=voucher_code,
                        consumer=consumer
                    )
                )
            else:
                batch_orders = list(
                    OrderReservation.objects.select_related('listing__listing__product__merchant__user').filter(
                        order_id=order_id,
                        consumer=consumer
                    )
                )

            if not batch_orders:
                return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
            if any(o.order_status != "Completed" for o in batch_orders):
                return Response({"error": "You can only rate and review completed pickups."}, status=status.HTTP_400_BAD_REQUEST)

            first_order = batch_orders[0]
            first_comm = first_order.listing
            first_prod = first_comm.listing.product if (first_comm and first_comm.listing) else None
            merch = first_prod.merchant if first_prod else None

            for o_obj in batch_orders:
                RatingReview.objects.update_or_create(
                    consumer=consumer,
                    order=o_obj,
                    defaults={
                        "rating_score": rating_score,
                        "review_comment": review_comment,
                        "surplus_listing": o_obj.listing,
                    }
                )

            stars_str = "★" * rating_score
            item_names = ", ".join(
                o.listing.listing.product.prod_name
                for o in batch_orders
                if o.listing and o.listing.listing and o.listing.listing.product
            )
            if merch and merch.user:
                UserNotification.objects.create(
                    user=merch.user,
                    message=f"{consumer.cons_fullname} rated '{item_names or 'your food'}' {stars_str} ({rating_score}/5): \"{review_comment or 'Great food rescue!'}\""
                )
            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type="Review",
                message=f"{consumer.cons_fullname} rated {merch.bus_name if merch else 'Merchant'} ({item_names or 'Order'}): {rating_score}/5 stars.",
                merchant=merch,
            )

            return Response({
                "message": "Thank you! Your rating and review have been posted to the food listing and merchant profile.",
                "rating_score": rating_score,
                "review_comment": review_comment,
            }, status=status.HTTP_201_CREATED)

        elif action == "checkout":
            items = request.data.get("items", [])
            payment_method = request.data.get("payment_method", "GCash")
            if not items:
                return Response({"error": "Your cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

            # Validate stock first across all items in the batch
            validated_lines = []
            for cart_item in items:
                prod_id = cart_item.get("id")
                qty = max(1, int(cart_item.get("quantity", 1)))
                prod = PerishableProduct.objects.filter(prod_id=prod_id).select_related('merchant__user').first()
                if not prod:
                    continue
                safety = ListingSafety.objects.filter(product=prod).first()
                commerce = getattr(safety, 'commerce', None) if safety else None
                if not commerce or commerce.qty_available < qty:
                    return Response(
                        {"error": f"Insufficient stock for {prod.prod_name} (only {commerce.qty_available if commerce else 0} left)."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                validated_lines.append((cart_item, prod, safety, commerce, qty))

            if not validated_lines:
                return Response({"error": "No valid listings found to reserve."}, status=status.HTTP_400_BAD_REQUEST)

            shared_base_voucher = None
            created_claims = []
            batch_names = []
            batch_deposit_total = Decimal('0.00')
            first_merchant = validated_lines[0][1].merchant

            for idx, (cart_item, prod, safety, commerce, qty) in enumerate(validated_lines, start=1):
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

                temp_code = f"TMP-{random.randint(100000, 999999)}-{idx}"
                order_obj = OrderReservation.objects.create(
                    order_qty=qty,
                    order_status='Pending',
                    downpayment_amount=deposit_10pct,
                    qr_voucher_code=temp_code,
                    rescued_weight_kg=total_w_kg,
                    consumer=consumer,
                    listing=commerce
                )
                if shared_base_voucher is None:
                    shared_base_voucher = f"OID{100 + order_obj.order_id}"
                    final_voucher_code = shared_base_voucher
                else:
                    final_voucher_code = f"{shared_base_voucher}-{idx}"

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

                batch_names.append(f"{qty}x {prod.prod_name}")
                batch_deposit_total += deposit_10pct

                pickup_str = (
                    timezone.localtime(safety.estimated_expiry).strftime("%b %d, %Y %I:%M %p")
                    if safety and safety.estimated_expiry
                    else "Today, 5:00 PM"
                )

                created_claims.append({
                    "order_id": order_obj.order_id,
                    "voucher_code": shared_base_voucher,
                    "food_name": prod.prod_name,
                    "qty": qty,
                    "establishment": prod.merchant.bus_name if prod.merchant else "Partner Establishment",
                    "address": prod.merchant.address if prod.merchant and prod.merchant.address else "Cebu City",
                    "pickup_deadline": pickup_str,
                    "total_value": f"{float(line_subtotal):.2f}",
                    "paid_today": f"{float(deposit_10pct):.2f}",
                    "remaining_balance": f"{float(balance_90pct):.2f}",
                })

            if first_merchant and first_merchant.user:
                UserNotification.objects.create(
                    user=first_merchant.user,
                    message=f"New reservation {shared_base_voucher} from {consumer.cons_fullname}: {', '.join(batch_names)} (10% Deposit Paid via {payment_method}: ₱{float(batch_deposit_total):.2f})."
                )

            AdminNotification.objects.create(
                user_id=1,
                admin_notif_type="Reservation",
                message=f"{consumer.cons_fullname} reserved {', '.join(batch_names)} ({shared_base_voucher}) from {first_merchant.bus_name if first_merchant else 'Merchant'}.",
                merchant=first_merchant,
            )

            return Response({
                "message": "Reservation confirmed and 10% deposit paid!",
                "voucher_code": shared_base_voucher,
                "claims": created_claims,
            }, status=status.HTTP_201_CREATED)

        return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)


class CreatePayMongoCheckoutView(APIView):
    """
    Creates a real Xendit Invoice strictly restricted to GCash and Maya ("GCASH", "PAYMAYA").
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        amount_php = max(20.0, float(request.data.get("amount", 20.0)))
        description = str(request.data.get("description", "RESERVE 10% Reservation Deposit"))

        xendit_key = getattr(settings, "XENDIT_SECRET_KEY", "").strip()

        if not xendit_key or not xendit_key.startswith("xnd_"):
            return Response({
                "error": "XENDIT_SECRET_KEY is missing or invalid in .env. Please add your xnd_development_... key."
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            res = http_requests.post(
                "https://api.xendit.co/v2/invoices",
                json={
                    "external_id": f"reserve-{uuid.uuid4().hex[:10]}",
                    "amount": round(amount_php, 2),
                    "description": description,
                    "currency": "PHP",
                    "payment_methods": ["GCASH", "PAYMAYA"],
                    "success_redirect_url": "http://localhost:8081/consumer/claims",
                    "failure_redirect_url": "http://localhost:8081/consumer/cart",
                },
                auth=(xendit_key, ""),
                timeout=10,
            )
            data = res.json()
            if res.status_code in (200, 201) and data.get("invoice_url"):
                return Response({
                    "checkout_url": data["invoice_url"],
                    "session_id": data.get("id", "xendit-session"),
                    "amount_charged_php": amount_php,
                }, status=status.HTTP_200_OK)

            return Response({
                "error": data.get("message", "Xendit API rejected invoice creation request.")
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)