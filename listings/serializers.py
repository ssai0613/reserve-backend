from django.db.models import Avg
from rest_framework import serializers
from transactions.models import RatingReview
from .models import PerishableProduct, ListingSafety, UnitMetrics, Category


class PerishableProductSerializer(serializers.ModelSerializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitMetrics.objects.all())
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = PerishableProduct
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)

        data['unit_id'] = instance.unit_id
        if instance.category:
            data['category'] = instance.category.category_name
            data['category_name'] = instance.category.category_name

        if instance.merchant:
            data['merchant_id'] = instance.merchant.merch_id
            data['merchant_name'] = instance.merchant.bus_name
            data['merchant_address'] = instance.merchant.address or "Cebu City, Philippines"

            merch_reviews = RatingReview.objects.filter(
                surplus_listing__listing__product__merchant=instance.merchant
            )
            m_count = merch_reviews.count()
            m_avg = merch_reviews.aggregate(avg=Avg('rating_score'))['avg'] or 0.0
            data['merchant_avg_rating'] = round(float(m_avg), 1) if m_count > 0 else 0.0
            data['merchant_review_count'] = m_count
        else:
            data['merchant_avg_rating'] = 0.0
            data['merchant_review_count'] = 0

        raw_prod_type = instance.prod_type or "Plain|dynamic"
        if "|" in raw_prod_type:
            sec_class, price_mode = raw_prod_type.split("|", 1)
        else:
            sec_class, price_mode = raw_prod_type, "dynamic"
        data['secondary_classification'] = sec_class or "Plain"
        data['pricing_mode'] = price_mode or "dynamic"

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

                prod_reviews = RatingReview.objects.filter(surplus_listing=commerce).select_related('consumer').order_by('-review_id')
                p_count = prod_reviews.count()
                p_avg = prod_reviews.aggregate(avg=Avg('rating_score'))['avg'] or 0.0
                data['avg_rating'] = round(float(p_avg), 1) if p_count > 0 else 0.0
                data['review_count'] = p_count
                data['reviews'] = [
                    {
                        "id": r.review_id,
                        "consumer": r.consumer.cons_fullname if r.consumer else "Verified Consumer",
                        "score": r.rating_score,
                        "comment": r.review_comment or "",
                        "date": r.created_at.strftime("%b %d, %Y") if getattr(r, 'created_at', None) else "Recent",
                    }
                    for r in prod_reviews[:10]
                ]
            except Exception:
                data['original_price'] = "0.00"
                data['price'] = "0.00"
                data['floor_price'] = "0.00"
                data['quantity'] = 0
                data['qty_available'] = 0
                data['status'] = "Active"
                data['avg_rating'] = 0.0
                data['review_count'] = 0
                data['reviews'] = []
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
            data['avg_rating'] = 0.0
            data['review_count'] = 0
            data['reviews'] = []

        return data