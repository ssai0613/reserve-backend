from rest_framework import serializers
from .models import PerishableProduct, ListingCommerce

class PerishableProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerishableProduct
        fields = '__all__'