from django.db import models


class OrderReservation(models.Model):
    order_id = models.AutoField(primary_key=True)
    order_qty = models.IntegerField()
    order_status = models.CharField(max_length=255, default='Pending')  # Pending, Completed, Cancelled, No-Show
    ordered_at = models.DateTimeField(auto_now_add=True)
    downpayment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    qr_voucher_code = models.CharField(max_length=255, unique=True)
    rescued_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    consumer = models.ForeignKey('accounts.Consumer', on_delete=models.CASCADE, db_column='cons_id', related_name='orders')
    listing = models.ForeignKey('listings.ListingCommerce', on_delete=models.CASCADE, db_column='listing_id', related_name='orders')

    class Meta:
        db_table = 'order_reservation'


class PaymentTransaction(models.Model):
    transac_id = models.AutoField(primary_key=True)
    gateway_ref_id = models.CharField(max_length=255, unique=True)
    transac_status = models.CharField(max_length=50)  # Success, Failed, Refunded
    commission_taken = models.DecimalField(max_digits=10, decimal_places=2)
    merchant_earnings = models.DecimalField(max_digits=10, decimal_places=2)
    processed_at = models.DateTimeField(auto_now_add=True)
    order = models.OneToOneField(OrderReservation, on_delete=models.CASCADE, db_column='order_id', related_name='payment')

    class Meta:
        db_table = 'payment_transaction'


class WithdrawalReq(models.Model):
    withdrawal_id = models.AutoField(primary_key=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    channel = models.CharField(max_length=50, default='GCash', null=True, blank=True)  # GCash or Maya
    gcash_num = models.CharField(max_length=30)
    account_name = models.CharField(max_length=255, null=True, blank=True)
    fee_deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True)
    net_payout = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True)
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    withdrawal_status = models.CharField(max_length=50, default='Pending')  # Pending, Approved, Rejected
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    merchant = models.ForeignKey('accounts.Merchant', on_delete=models.CASCADE, db_column='merch_id', related_name='withdrawal_requests')

    class Meta:
        db_table = 'withdrawal_req'


class RatingReview(models.Model):
    review_id = models.AutoField(primary_key=True)
    rating_score = models.IntegerField()  # Range: 1-5
    review_comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    consumer = models.ForeignKey('accounts.Consumer', on_delete=models.CASCADE, db_column='cons_id', related_name='reviews')
    surplus_listing = models.ForeignKey('listings.ListingCommerce', on_delete=models.CASCADE, db_column='surplus_list_id', related_name='reviews')
    order = models.ForeignKey(OrderReservation, on_delete=models.SET_NULL, null=True, blank=True, db_column='order_id', related_name='reviews')

    class Meta:
        db_table = 'rating_review'