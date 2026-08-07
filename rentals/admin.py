from django.contrib import admin

from .models import Car, Booking, Payment


admin.site.register(Car)
admin.site.register(Booking)
admin.site.register(Payment)