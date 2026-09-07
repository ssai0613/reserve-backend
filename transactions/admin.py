from django.contrib import admin
from .models import OrderReservation, PaymentTransaction, WithdrawalReq, RatingReview

admin.site.register(OrderReservation)
admin.site.register(PaymentTransaction)
admin.site.register(WithdrawalReq)
admin.site.register(RatingReview)
