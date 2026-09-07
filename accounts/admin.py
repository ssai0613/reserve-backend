from django.contrib import admin
from .models import User, UserSession, AccDeletionReq, Location, SubscriptionPlan, Merchant, MerchantContact, Consumer, FoodBank

admin.site.register(User)
admin.site.register(UserSession)
admin.site.register(AccDeletionReq)
admin.site.register(Location)
admin.site.register(SubscriptionPlan)
admin.site.register(MerchantContact)
admin.site.register(Merchant)
admin.site.register(Consumer)
admin.site.register(FoodBank)