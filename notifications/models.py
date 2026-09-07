from django.db import models


class Announcement(models.Model):
    announcement_id = models.AutoField(primary_key=True)
    target_audience = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, db_column='user_id', related_name='announcements')

    class Meta:
        db_table = 'announcement'


class UserNotification(models.Model):
    notif_id = models.AutoField(primary_key=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, db_column='user_id', related_name='user_notifications')

    class Meta:
        db_table = 'user_notification'


class AdminNotification(models.Model):
    admin_notif_id = models.AutoField(primary_key=True)
    admin_notif_type = models.CharField(max_length=100)  # KYB, Payout, System
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, db_column='user_id', related_name='admin_notifications')
    merchant = models.ForeignKey('accounts.Merchant', on_delete=models.SET_NULL, null=True, blank=True, db_column='merch_id', related_name='admin_notifications')
    withdrawal = models.ForeignKey('transactions.WithdrawalReq', on_delete=models.SET_NULL, null=True, blank=True, db_column='withdrawal_id', related_name='admin_notifications')

    class Meta:
        db_table = 'admin_notification'