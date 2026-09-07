from django.contrib import admin
from .models import Announcement, AdminNotification, UserNotification

admin.site.register(Announcement)
admin.site.register(AdminNotification)
admin.site.register(UserNotification)

