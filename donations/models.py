from django.db import models


class DonationRequest(models.Model):
    donation_req_id = models.AutoField(primary_key=True)
    qty_needed = models.IntegerField()
    status = models.CharField(max_length=50, default='Active')  # Active, Fulfilled, Cancelled
    merchant = models.ForeignKey('accounts.Merchant', on_delete=models.SET_NULL, null=True, blank=True, db_column='merch_id', related_name='fulfilled_donation_requests')
    food_bank = models.ForeignKey('accounts.FoodBank', on_delete=models.CASCADE, db_column='org_id', related_name='donation_requests')
    listing = models.ForeignKey('listings.ListingCommerce', on_delete=models.SET_NULL, null=True, blank=True, db_column='listing_id', related_name='donation_requests')

    class Meta:
        db_table = 'donation_request'


class Donation(models.Model):
    donation_id = models.AutoField(primary_key=True)
    trigger_type = models.CharField(max_length=255, default='Manual')  # Manual vs System (TTT-forced)
    qty_donated = models.IntegerField()
    status = models.CharField(max_length=50, default='Active')  # Active, Claimed, In-Transit, Completed
    merchant = models.ForeignKey('accounts.Merchant', on_delete=models.CASCADE, db_column='merch_id', related_name='donations')
    food_bank = models.ForeignKey('accounts.FoodBank', on_delete=models.CASCADE, db_column='org_id', related_name='received_donations')
    listing = models.ForeignKey('listings.ListingCommerce', on_delete=models.CASCADE, db_column='listing_id', related_name='donations')

    class Meta:
        db_table = 'donation'