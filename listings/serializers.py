from rest_framework import serializers
from .models import PerishableProduct, ListingSafety, UnitMetrics, Category


class PerishableProductSerializer(serializers.ModelSerializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitMetrics.objects.all())
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = PerishableProduct
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # 1. Include readable Category Name and Unit ID
        data['unit_id'] = instance.unit_id
        if instance.category:
            data['category'] = instance.category.category_name
            data['category_name'] = instance.category.category_name

        # 2. Include Merchant Establishment Name
        if instance.merchant:
            data['merchant_name'] = instance.merchant.bus_name

        # 3. Unpack secondary_classification and pricing_mode from prod_type (e.g. "Plain|dynamic")
        raw_prod_type = instance.prod_type or "Plain|dynamic"
        if "|" in raw_prod_type:
            sec_class, price_mode = raw_prod_type.split("|", 1)
        else:
            sec_class, price_mode = raw_prod_type, "dynamic"
        data['secondary_classification'] = sec_class or "Plain"
        data['pricing_mode'] = price_mode or "dynamic"

        # 4. Fetch Safety & Commerce metadata
        safety = ListingSafety.objects.filter(product=instance).first()

        if safety:
            data['safely_anchor_time'] = safety.safely_anchor_time

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

            data['expiry_date'] = None
            data['expiry_time'] = None
            data['expires_at'] = None

            if safety.estimated_expiry:
                try:
                    data['expiry_date'] = safety.estimated_expiry.strftime("%b %d, %Y")
                    data['expiry_time'] = safety.estimated_expiry.strftime("%I:%M %p")
                    data['expires_at'] = safety.estimated_expiry.isoformat()
                except Exception:
                    pass

            try:
                commerce = safety.commerce
                data['commerce_id'] = commerce.pk
                data['original_price'] = str(commerce.orig_price)
                data['price'] = str(commerce.discounted_price)
                data['floor_price'] = str(commerce.floor_price)
                data['quantity'] = commerce.qty_available
                data['qty_available'] = commerce.qty_available
                data['status'] = commerce.status or "Active"
            except Exception:
                data['original_price'] = "0.00"
                data['price'] = "0.00"
                data['floor_price'] = "0.00"
                data['quantity'] = 0
                data['qty_available'] = 0
                data['status'] = "Active"
        else:
            data['safely_anchor_time'] = None
            data['storage_condition'] = "Ambient (25°C)"
            data['expiry_date'] = None
            data['expiry_time'] = None
            data['original_price'] = "0.00"
            data['price'] = "0.00"
            data['floor_price'] = "0.00"
            data['quantity'] = 0
            data['qty_available'] = 0
            data['status'] = "Active"

        return data