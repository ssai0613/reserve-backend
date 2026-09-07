from django.db import models


class User(models.Model):
    user_id = models.AutoField(primary_key=True)
    user_email = models.CharField(max_length=255, unique=True)
    user_pass = models.CharField(max_length=255)
    user_role = models.CharField(max_length=50)  # Admin, Merchant, Consumer, FoodBank
    is_banned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user'

    def __str__(self):
        return f"{self.user_email} ({self.user_role})"


class UserSession(models.Model):
    ses_id = models.AutoField(primary_key=True)
    ses_token = models.CharField(max_length=255)
    ses_info = models.TextField(blank=True, null=True)
    ses_login_time = models.DateTimeField(auto_now_add=True)
    ses_logout_time = models.DateTimeField(blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='sessions')

    class Meta:
        db_table = 'user_session'


class AccDeletionReq(models.Model):
    req_id = models.AutoField(primary_key=True)
    req_reason = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50, default='Pending')
    time_requested = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='deletion_requests')

    class Meta:
        db_table = 'acc_deletion_req'


class Location(models.Model):
    loc_id = models.AutoField(primary_key=True)
    address_name = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()
    is_primary = models.BooleanField(default=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='locations')

    class Meta:
        db_table = 'location'


class SubscriptionPlan(models.Model):
    plan_id = models.AutoField(primary_key=True)
    plan_name = models.CharField(max_length=50)  # Basic / Pro
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = 'subscription_plan'

    def __str__(self):
        return self.plan_name


class Merchant(models.Model):
    merch_id = models.AutoField(primary_key=True)
    bus_name = models.CharField(max_length=255)
    merch_type = models.CharField(max_length=50)
    bus_permit_path = models.CharField(max_length=255)
    bus_expiry_date = models.DateField()
    is_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=50, default='Pending')
    wallet_bal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id', related_name='merchant_profile')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, db_column='plan_id', related_name='merchants')

    class Meta:
        db_table = 'merchant'

    def __str__(self):
        return self.bus_name


class MerchantContact(models.Model):
    contact_id = models.AutoField(primary_key=True)
    contact_fullname = models.CharField(max_length=255)
    contact_email = models.CharField(max_length=100)
    contact_phone = models.CharField(max_length=20)
    position = models.CharField(max_length=50)
    valid_id_path = models.TextField()
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, db_column='merch_id', related_name='contacts')

    class Meta:
        db_table = 'merchant_contact'


class FoodBank(models.Model):
    org_id = models.AutoField(primary_key=True)
    org_name = models.CharField(max_length=255)
    accreditation_path = models.CharField(max_length=255)
    accreditation_expiry = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=50, default='Pending')
    total_food_received = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id', related_name='food_bank_profile')

    class Meta:
        db_table = 'food_bank'

    def __str__(self):
        return self.org_name


class Consumer(models.Model):
    cons_id = models.AutoField(primary_key=True)
    cons_fullname = models.CharField(max_length=255)
    phone_num = models.CharField(max_length=20, blank=True, null=True)
    total_food_saved = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id', related_name='consumer_profile')

    class Meta:
        db_table = 'consumer'

    def __str__(self):
        return self.cons_fullname