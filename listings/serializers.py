from rest_framework import serializers
from .models import PerishableProduct, ListingSafety, UnitMetrics, Category

class PerishableProductSerializer(serializers.ModelSerializer):
    # Explicitly declare unit and category to accept incoming IDs properly
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitMetrics.objects.all())
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = PerishableProduct
        fields = '__all__'

    def to_representation(self, instance):
        # 1. Get the default product data 
        data = super().to_representation(instance)
        
        # --- SWAP CATEGORY ID FOR THE READABLE STRING ---
        if instance.category:
            try:
                data['category'] = instance.category.category_name 
            except AttributeError:
                data['category'] = instance.get_category_display()
        # -----------------------------------------------------

        # 2. Make EXACTLY ONE trip to Supabase for all safety info
        safety = ListingSafety.objects.filter(product=instance).first()
        
        if safety:
            # Anchor Time
            data['safely_anchor_time'] = safety.safely_anchor_time
            
            # Storage Condition
            if safety.posted_temp is not None:
                temp = float(safety.posted_temp)
                if temp <= -10:
                    data['storage_condition'] = "Frozen (-18°C)"
                elif temp <= 10:
                    data['storage_condition'] = "Chilled (4°C)"
                else:
                    data['storage_condition'] = "Ambient (25°C)"
            else:
                data['storage_condition'] = "Ambient (25°C)"
                
            # Expiry Date & Time
            data['expiry_date'] = None
            data['expiry_time'] = None
            
            if safety.estimated_expiry:
                try:
                    data['expiry_date'] = safety.estimated_expiry.strftime("%b %d, %Y")
                    data['expiry_time'] = safety.estimated_expiry.strftime("%I:%M %p")
                except Exception:
                    pass 

            # --- GRAB PRICING & QUANTITY FROM LISTING COMMERCE ---
            try:
                commerce = safety.commerce 
                data['commerce_id'] = commerce.pk
                data['original_price'] = commerce.orig_price
                data['price'] = commerce.discounted_price 
                data['floor_price'] = commerce.floor_price
                data['quantity'] = commerce.qty_available 
            except Exception:
                data['original_price'] = "0.00"
                data['price'] = "0.00"
                data['floor_price'] = "0.00"
                data['qty_available'] = 0
            # -----------------------------------------------

        else:
            # Defaults if no safety record exists
            data['safely_anchor_time'] = None
            data['storage_condition'] = "Ambient (25°C)"
            data['expiry_date'] = None
            data['expiry_time'] = None
            data['original_price'] = "0.00"
            data['price'] = "0.00"
            data['floor_price'] = "0.00"
            data['qty_available'] = 0

        return data