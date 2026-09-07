from django.db import models


class Category(models.Model):
    category_id = models.AutoField(primary_key=True)
    category_name = models.CharField(max_length=100)

    class Meta:
        db_table = 'category'

    def __str__(self):
        return self.category_name


class UnitMetrics(models.Model):
    unit_id = models.AutoField(primary_key=True)
    unit_name = models.CharField(max_length=50)  # Kg, Grams, Pieces, Tali

    class Meta:
        db_table = 'unit_metrics'

    def __str__(self):
        return self.unit_name


class SafetyThreshold(models.Model):
    threshold_id = models.AutoField(primary_key=True)
    food_category = models.CharField(max_length=50)
    storage_type = models.CharField(max_length=50)
    max_safe_hours = models.IntegerField()

    class Meta:
        db_table = 'safety_threshold'

    def __str__(self):
        return f"{self.food_category} ({self.storage_type})"


class PerishableProduct(models.Model):
    prod_id = models.AutoField(primary_key=True)
    prod_name = models.CharField(max_length=255)
    prod_desc = models.TextField(blank=True, null=True)
    prod_type = models.CharField(max_length=255, blank=True, null=True)
    image_path = models.CharField(max_length=255)
    weight_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, db_column='category_id', related_name='products')
    unit = models.ForeignKey(UnitMetrics, on_delete=models.PROTECT, db_column='unit_id', related_name='products')
    merchant = models.ForeignKey('accounts.Merchant', on_delete=models.CASCADE, db_column='merch_id', related_name='products')
    threshold = models.ForeignKey(SafetyThreshold, on_delete=models.PROTECT, db_column='threshold_id', related_name='products')

    class Meta:
        db_table = 'perishable_product'

    def __str__(self):
        return self.prod_name


class ListingSafety(models.Model):
    listing_id = models.AutoField(primary_key=True)
    safety_anchor_time = models.DateTimeField()
    anchor_type = models.CharField(max_length=255)  # Preparation, Arrival
    estimated_expiry = models.DateTimeField()
    posted_temp = models.DecimalField(max_digits=5, decimal_places=2)
    humidity_index = models.DecimalField(max_digits=5, decimal_places=2)
    product = models.ForeignKey(PerishableProduct, on_delete=models.CASCADE, db_column='prod_id', related_name='safety_records')

    class Meta:
        db_table = 'listing_safety'


class ListingCommerce(models.Model):
    listing = models.OneToOneField(
        ListingSafety,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column='listing_id',
        related_name='commerce'
    )
    qty_available = models.IntegerField(default=0)
    qty_reserved = models.IntegerField(default=0)
    qty_sold = models.IntegerField(default=0)
    orig_price = models.DecimalField(max_digits=10, decimal_places=2)
    discounted_price = models.DecimalField(max_digits=10, decimal_places=2)
    floor_price = models.DecimalField(max_digits=10, decimal_places=2)
    current_price = models.DecimalField(max_digits=10, decimal_places=2)
    decay_interval = models.IntegerField(default=15)
    pickup_deadline = models.DateTimeField()
    status = models.CharField(max_length=50, default='Active')  # Active, Expired, Sold Out, Donated

    class Meta:
        db_table = 'listing_commerce'


class StockLedger(models.Model):
    ledger_id = models.AutoField(primary_key=True)
    transaction_type = models.CharField(max_length=100, blank=True, null=True)
    qty_change = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    listing = models.ForeignKey(ListingCommerce, on_delete=models.CASCADE, db_column='listing_id', related_name='stock_ledger_entries')

    class Meta:
        db_table = 'stock_ledger'