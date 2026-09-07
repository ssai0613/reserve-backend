from django.contrib import admin
from .models import DonationRequest, Donation

admin.site.register(Donation)
admin.site.register(DonationRequest)
