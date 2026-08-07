
# Create your models here.
from django.db import models


class Car(models.Model):

    CATEGORY_CHOICES = [
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('sports', 'Sports'),
        ('luxury', 'Luxury'),
        ('convertible', 'Convertible'),
        ('van', 'Van'),
        ('coupe', 'Coupe'),
        ('supercar', 'Supercar'),
    ]

    brand = models.CharField(max_length=100)
    name = models.CharField(max_length=100)

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES
    )

    image = models.ImageField(
        upload_to='cars/'
    )

    price_day = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    price_week = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    price_month = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    mileage_limit = models.IntegerField()
    additional_mileage = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    min_rental = models.IntegerField()

    location = models.CharField(max_length=255)

    specs = models.JSONField(default=dict)
    overview = models.JSONField(default=dict)
    features = models.JSONField(default=dict)

    description = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.brand} {self.name}"


class Booking(models.Model):

    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name='bookings'
    )

    pickup_date = models.DateField()
    dropoff_date = models.DateField()

    pickup_time = models.CharField(max_length=20)
    dropoff_time = models.CharField(max_length=20)

    name = models.CharField(max_length=255)

    phone = models.CharField(max_length=20)

    email = models.EmailField()

    baby_seat = models.BooleanField(default=False)
    pay_now = models.BooleanField(default=False)

    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    status = models.CharField(
        max_length=50,
        default='pending'
    )

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.car.name}"


class Payment(models.Model):

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name='payments',
    )

    stripe_session_id = models.CharField(
        max_length=255,
        unique=True,
        blank=True,
        null=True,
    )

    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default='aed',
    )

    status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
    )

    refund_reason = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment {self.id} — {self.booking.name} — {self.status}"