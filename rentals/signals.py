from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Booking, Car


@receiver(post_save, sender=Booking)
def update_car_status_on_booking_save(sender, instance, created, **kwargs):
    car = instance.car

    if instance.status == "confirmed":
        if car.status != "booked":
            car.status = "booked"
            car.save(update_fields=["status"])

    elif instance.status in ("cancelled", "completed"):
        still_active = Booking.objects.filter(
            car=car, status="confirmed"
        ).exclude(pk=instance.pk).exists()

        if not still_active and car.status == "booked":
            car.status = "available"
            car.save(update_fields=["status"])


@receiver(post_delete, sender=Booking)
def free_car_on_booking_delete(sender, instance, **kwargs):
    car = instance.car
    still_active = Booking.objects.filter(car=car, status="confirmed").exists()
    if not still_active and car.status == "booked":
        car.status = "available"
        car.save(update_fields=["status"])