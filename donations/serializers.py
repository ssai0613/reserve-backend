from rest_framework import serializers
from .models import Donation, DonationRequest


# ---------------------------------------------------------------
# Helpers that reach into the merchant / listing tables
# ---------------------------------------------------------------

def merchant_address(merchant):
    locations = list(merchant.user.locations.all())
    if not locations:
        return "Address not provided"
    primary = next((l for l in locations if l.is_primary), locations[0])
    return primary.address_name


def merchant_contact(merchant):
    """Returns (phone, full name, email) of the merchant's first contact."""
    contacts = list(merchant.contacts.all())
    if not contacts:
        return "No contact info", "", ""
    c = contacts[0]
    return c.contact_phone, c.contact_fullname, c.contact_email


def donation_parts(donation):
    """(ListingCommerce | None, ListingSafety | None, PerishableProduct | None)"""
    commerce = donation.listing
    safety = commerce.listing if commerce else None
    product = safety.product if safety else None
    return commerce, safety, product


def donation_expires_at(donation):
    """
    The moment this food stops being safe / collectable: the earlier of the
    estimated safety expiry and the pickup deadline. None for manual donations
    that aren't tied to a listing.
    """
    commerce, safety, _ = donation_parts(donation)
    times = []
    if safety and safety.estimated_expiry:
        times.append(safety.estimated_expiry)
    if commerce and commerce.pickup_deadline:
        times.append(commerce.pickup_deadline)
    return min(times) if times else None


def donation_is_ttt(donation):
    trigger = (donation.trigger_type or '').lower()
    return trigger == 'system' or 'ttt' in trigger


def donation_food_name(donation):
    _, _, product = donation_parts(donation)
    return product.prod_name if product else "Surplus Bundle"


def donation_food_type(donation):
    _, _, product = donation_parts(donation)
    return product.category.category_name if product else "General Supplies"


def donation_unit(donation):
    _, _, product = donation_parts(donation)
    return product.unit.unit_name if product else "pcs"


# ---------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------

class DonationRequestSerializer(serializers.ModelSerializer):
    merchant_name = serializers.SerializerMethodField()

    class Meta:
        model = DonationRequest
        fields = [
            'donation_req_id', 'food_type', 'qty_needed', 'status',
            'created_at', 'updated_at', 'merchant', 'merchant_name', 'food_bank',
        ]
        # The food bank comes from the login token and the status is
        # controlled by the server, never by the request body.
        read_only_fields = [
            'donation_req_id', 'status', 'created_at', 'updated_at',
            'merchant', 'food_bank',
        ]

    def get_merchant_name(self, obj):
        return obj.merchant.bus_name if obj.merchant else None

    def validate_qty_needed(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be at least 1.")
        return value

    def validate_food_type(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Please choose a food type.")
        return value


class DonationSerializer(serializers.ModelSerializer):
    food_name = serializers.SerializerMethodField()
    food_type = serializers.SerializerMethodField()
    unit_name = serializers.SerializerMethodField()
    image_path = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    is_ttt = serializers.SerializerMethodField()
    merchant_name = serializers.CharField(source='merchant.bus_name', read_only=True)
    merchant_address = serializers.SerializerMethodField()
    merchant_contact = serializers.SerializerMethodField()
    merchant_contact_name = serializers.SerializerMethodField()
    food_bank_name = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = [
            'donation_id', 'trigger_type', 'is_ttt', 'qty_donated', 'unit_name',
            'status', 'created_at', 'updated_at',
            'merchant', 'merchant_name', 'merchant_address',
            'merchant_contact', 'merchant_contact_name',
            'food_bank', 'food_bank_name', 'listing', 
            'food_name', 'food_type', 'image_path', 'expires_at',
        ]

    def get_food_name(self, obj):
        return donation_food_name(obj)

    def get_food_type(self, obj):
        return donation_food_type(obj)

    def get_unit_name(self, obj):
        return donation_unit(obj)

    def get_image_path(self, obj):
        _, _, product = donation_parts(obj)
        return product.image_path if product else None

    def get_expires_at(self, obj):
        expires = donation_expires_at(obj)
        return expires.isoformat() if expires else None

    def get_is_ttt(self, obj):
        return donation_is_ttt(obj)

    def get_merchant_address(self, obj):
        return merchant_address(obj.merchant)

    def get_merchant_contact(self, obj):
        return merchant_contact(obj.merchant)[0]

    def get_merchant_contact_name(self, obj):
        return merchant_contact(obj.merchant)[1]

    # Change bus_name to org_name
    def get_food_bank_name(self, obj):
        return obj.food_bank.org_name if obj.food_bank else None
