from datetime import datetime
from datetime import timedelta
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from .utils import get_cebu_weather, calculate_ttt_expiry
from .models import PerishableProduct, ListingSafety, ListingCommerce  
from donations.models import Donation
from .serializers import PerishableProductSerializer


class MarketplaceFeedView(APIView):
    permission_classes = [AllowAny] 

    def get(self, request):
        donated_commerce_ids = Donation.objects.values_list('listing_id', flat=True)
        donated_product_ids = ListingCommerce.objects.filter(
            listing_id__in=donated_commerce_ids
        ).values_list('listing__product_id', flat=True)

        now = timezone.now() + timedelta(hours=8)

        # Get all valid perishable products excluding donated ones
        listings = PerishableProduct.objects.select_related('category').exclude(prod_id__in=donated_product_ids)
        
        valid_listings = []
        for item in listings:
            # Fetch safety record directly using the reverse relation or filter
            safety_rec = ListingSafety.objects.filter(product=item).first()
            if safety_rec and safety_rec.estimated_expiry:
                expiry_dt = safety_rec.estimated_expiry
                if timezone.is_naive(expiry_dt):
                    expiry_dt = timezone.make_aware(expiry_dt)
                
                seconds_remaining = (expiry_dt - now).total_seconds()
                # Only keep items with more than 30 mins left (1800 seconds)
                if seconds_remaining > 1800:
                    valid_listings.append(item.prod_id)
            else:
                valid_listings.append(item.prod_id)
        
        filtered_listings = PerishableProduct.objects.filter(prod_id__in=valid_listings)
        serializer = PerishableProductSerializer(filtered_listings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class EstablishmentListingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        # 1. Check if the frontend passed a merchant ID (e.g., ?merchant=1 for bakeshop, ?merchant=2 for vendor)
        merchant_id = request.GET.get('merchant', 1) 

        # 2. Filter listings strictly by that merchant ID
        listings = PerishableProduct.objects.filter(merchant_id=merchant_id).select_related('category')

        # 3. Exclude donated items
        donated_commerce_ids = Donation.objects.values_list('listing_id', flat=True)
        donated_product_ids = ListingCommerce.objects.filter(
            listing_id__in=donated_commerce_ids
        ).values_list('listing__product_id', flat=True)

        listings = listings.exclude(prod_id__in=donated_product_ids)
        
        now = timezone.now() + timedelta(hours=8)
        
        serialized_data = []
        flagged_count = 0

        for item in listings:
            serializer = PerishableProductSerializer(item)
            data = serializer.data
            
            item_status = "Active"
            safety_rec = ListingSafety.objects.filter(product=item).first()
            if safety_rec and safety_rec.estimated_expiry:
                expiry_dt = safety_rec.estimated_expiry
                if timezone.is_naive(expiry_dt):
                    expiry_dt = timezone.make_aware(expiry_dt)
                
                seconds_remaining = (expiry_dt - now).total_seconds()
                if seconds_remaining <= 1830:
                    item_status = "Flagged"
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
        category_name = request.GET.get('category', 'Bakery') # Grab category from frontend query params
        
        print("DEBUG - Received prep_date from frontend:", prep_date_str) 
        print("DEBUG - Received storage from frontend:", storage)
        print("DEBUG - Received category from frontend:", category_name)
        
        current_temp, current_humidity = get_cebu_weather()
        
        prep_dt = timezone.now()
        if prep_date_str:
            try:
                cleaned_str = prep_date_str.replace(',', '').strip()
                try:
                    prep_dt = datetime.strptime(cleaned_str, "%b %d %Y %I:%M %p")
                except ValueError:
                    prep_dt = datetime.strptime(cleaned_str, "%b %d %Y")
                
                if timezone.is_naive(prep_dt):
                    prep_dt = timezone.make_aware(prep_dt)
            except Exception as e:
                print("Date parse error:", e)

        # Dynamic category baseline hours based on your 4 approved categories
        category_defaults = {
            'Bakery': 36.0,
            'Pastries': 24.0,
            'Produce': 96.0,
            'Desserts & Sweets': 18.0
        }
        base_hours = category_defaults.get(category_name, 24.0)

        # Storage condition multipliers
        if 'Frozen' in storage:
            base_hours *= 5.0
        elif 'Chilled' in storage:
            base_hours *= 2.5
            
        calculated_expiry = calculate_ttt_expiry(base_hours, current_temp, prep_dt)
        
        formatted_date = calculated_expiry.strftime("%b %d, %Y")
        formatted_time_12h = calculated_expiry.strftime("%I:%M %p") 
        
        return Response({
            "date": formatted_date,
            "time": formatted_time_12h,
            "temp": current_temp
        }, status=status.HTTP_200_OK)


class CreateListingView(APIView):
    permission_classes = [AllowAny] 

    def post(self, request):
        print("🔥 FULL INCOMING REQUEST DATA:", request.data)
        serializer = PerishableProductSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            new_listing = serializer.save()
            
            current_temp, current_humidity = get_cebu_weather()
            
            # --- MAP STORAGE CONDITION ---
            storage = request.data.get('storage_condition', 'Ambient (25°C)')
            posted_temp = 25.00
            if "Frozen" in storage:
                posted_temp = -18.00
            elif "Chilled" in storage:
                posted_temp = 4.00
            
            # --- FIX: PARSE CUSTOM EXPIRY STRING TO DATETIME ---
            expiry_date_str = request.data.get('expiry_date')
            expiry_time_str = request.data.get('expiry_time')
            final_expiry = None
            
            if expiry_date_str and expiry_time_str:
                try:
                    # Remove commas to unify format: "Sep 16 2026 11:59 AM"
                    clean_date = expiry_date_str.replace(',', '').strip() 
                    clean_time = expiry_time_str.strip()
                    combined_str = f"{clean_date} {clean_time}"
                    
                    naive_dt = datetime.strptime(combined_str, "%b %d %Y %I:%M %p")
                    final_expiry = timezone.make_aware(naive_dt)
                except ValueError:
                    pass # Fallback to TTT calculation below if parsing fails
            
            # Fallback to TTT calculation if frontend didn't provide a valid date
            if not final_expiry:
                base_hours = 24.0 
                final_expiry = calculate_ttt_expiry(base_hours, current_temp, timezone.now())

            # 1. Save Safety Record to a variable
            safety_record = ListingSafety.objects.create(
                product=new_listing, 
                safely_anchor_time=request.data.get('preparation_date'),
                anchor_type='Preparation',
                estimated_expiry=final_expiry,  
                posted_temp=posted_temp,
                humidity_index=current_humidity  
            )
            
            # Grab quantity from 'quantity' since that's what your app is sending
            raw_qty = request.data.get('quantity') or request.data.get('qty_available', 0)
            try:
                parsed_qty = int(raw_qty) if raw_qty != "" and raw_qty is not None else 0
            except (ValueError, TypeError):
                parsed_qty = 0

            print("DEBUG - Parsed Quantity for DB:", parsed_qty)

            ListingCommerce.objects.create(
                listing=safety_record, 
                orig_price=request.data.get('orig_price', 0.00),
                discounted_price=request.data.get('discounted_price', 0.00),
                floor_price=request.data.get('floor_price', 0.00),
                current_price=request.data.get('orig_price', 0.00), 
                qty_available=parsed_qty,  # Now correctly uses 10!
                pickup_deadline=final_expiry 
            )
            
            return Response({
                "message": "Listing, Safety, and Pricing created successfully!", 
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UpdateListingView(APIView):
    permission_classes = [AllowAny]

    def put(self, request, pk):
        try:
            listing = PerishableProduct.objects.get(pk=pk)
        except PerishableProduct.DoesNotExist:
            return Response({"error": "Listing not found"}, status=status.HTTP_404_NOT_FOUND)

        listing.prod_name = request.data.get("prod_name", listing.prod_name)
        listing.prod_desc = request.data.get("prod_desc", listing.prod_desc)
        listing.weight_per_unit = request.data.get("weight_per_unit", listing.weight_per_unit)

        unit_id = request.data.get("unit") or request.data.get("unit_id")
        if unit_id:
            listing.unit_id = unit_id  
            
        category_id = request.data.get("category")
        if category_id:
            listing.category_id = category_id
        
        listing.save()

        safety_record = ListingSafety.objects.filter(product=listing).first()
        if safety_record:
            # 1. Update Prep Date
            prep_date_str = request.data.get("preparation_date")
            if prep_date_str:
                safety_record.safely_anchor_time = prep_date_str

            # 2. Update Storage Condition
            storage = request.data.get("storage_condition")
            if storage:
                if "Frozen" in storage:
                    safety_record.posted_temp = -18.00
                elif "Chilled" in storage:
                    safety_record.posted_temp = 4.00
                else:
                    safety_record.posted_temp = 25.00 
            
            # 3. Update Manual Expiry
            expiry_date_str = request.data.get('expiry_date')
            expiry_time_str = request.data.get('expiry_time')
            if expiry_date_str and expiry_time_str:
                try:
                    clean_date = expiry_date_str.replace(',', '').strip() 
                    clean_time = expiry_time_str.strip()
                    combined_str = f"{clean_date} {clean_time}"
                    
                    naive_dt = datetime.strptime(combined_str, "%b %d %Y %I:%M %p")
                    safety_record.estimated_expiry = timezone.make_aware(naive_dt)
                except ValueError:
                    pass
            
            safety_record.save()

            # --- UPDATE COMMERCE (QUANTITY & PRICING) ---
            try:
                commerce = safety_record.commerce
                
                # Update Quantity
                raw_qty = request.data.get("quantity") or request.data.get("qty_available")
                if raw_qty is not None and raw_qty != "":
                    commerce.qty_available = int(raw_qty)

                # Update Pricing Fields
                orig_price = request.data.get("orig_price") or request.data.get("original_price")
                if orig_price is not None and orig_price != "":
                    commerce.orig_price = orig_price

                disc_price = request.data.get("discounted_price") or request.data.get("price")
                if disc_price is not None and disc_price != "":
                    commerce.discounted_price = disc_price
                    commerce.current_price = disc_price # Sync current live price base

                floor_price = request.data.get("floor_price")
                if floor_price is not None and floor_price != "":
                    commerce.floor_price = floor_price

                commerce.save()
            except Exception as e:
                print("Error updating commerce record on edit:", e)

        return Response({"message": "Listing updated successfully"}, status=status.HTTP_200_OK)
    
class DeleteListingView(APIView):
    permission_classes = [AllowAny] # Change to IsAuthenticated later if needed

    def delete(self, request, pk):
        try:
            # Find the main product
            listing = PerishableProduct.objects.get(pk=pk)
            
            # Deleting the main product will automatically cascade and delete 
            # the linked ListingSafety and ListingCommerce records!
            listing.delete()
            
            return Response({"message": "Listing successfully deleted!"}, status=status.HTTP_200_OK)
            
        except PerishableProduct.DoesNotExist:
            return Response({"error": "Listing not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
class EstablishmentNotificationsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        events = []
        # Adjust 'now' to match your local timezone offset if Django is running in UTC
        now = timezone.now() + timedelta(hours=8) 

        for safety in ListingSafety.objects.filter(estimated_expiry__isnull=False).select_related('product'):
            if safety.estimated_expiry:
                expiry_dt = safety.estimated_expiry
                if timezone.is_naive(expiry_dt):
                    expiry_dt = timezone.make_aware(expiry_dt)

                time_diff = expiry_dt - now
                seconds_remaining = time_diff.total_seconds()
                
                print(f"LOCAL ALIGNED CHECK - {safety.product.prod_name if safety.product else 'Item'}: {seconds_remaining} seconds left")

                # Trigger if under 1 hour (3600 seconds) or past due
                if seconds_remaining < 3600:
                    prod_name = safety.product.prod_name if safety.product else "Surplus Item"
                    
                    if seconds_remaining <= 0:
                        title = "Listing Expired"
                        description = f"Your listing '{prod_name}' has reached its suggested expiry time."
                        time_label = "Just now"
                    else:
                        mins_left = max(1, int(seconds_remaining / 60))
                        title = "Urgent: Expiring Soon!"
                        description = f"Your listing '{prod_name}' will expire in about {mins_left} minute(s)."
                        time_label = f"In ~{mins_left} mins"

                    events.append({
                        "id": f"expiry-{safety.pk}",
                        "type": "system",
                        "title": title,
                        "description": description,
                        "time": time_label,
                        "read": False
                    })

        # 2. FOODBANK DONATION REQUESTS
        try:
            from donations.models import DonationRequest
            for req in DonationRequest.objects.all().select_related('food_bank'):
                fb_name = req.food_bank.org_name if req.food_bank else "A food bank"
                description = f"{fb_name} posted a request: {req.qty_needed} units of {req.food_type}."
                
                events.append({
                    "id": f"req-{req.donation_req_id}", 
                    "type": "donation",
                    "title": "New Foodbank Request!", 
                    "description": description,
                    "time": "Recently",
                    "read": False
                })
        except ImportError:
            pass

        return Response(events, status=status.HTTP_200_OK)