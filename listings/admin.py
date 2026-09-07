from django.contrib import admin
from .models import Category, UnitMetrics, SafetyThreshold, PerishableProduct, ListingCommerce, ListingSafety, StockLedger


admin.site.register(Category)
admin.site.register(UnitMetrics)
admin.site.register(SafetyThreshold)
admin.site.register(PerishableProduct)
admin.site.register(ListingSafety)
admin.site.register(ListingCommerce)
admin.site.register(StockLedger)