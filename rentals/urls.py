from django.urls import path

from .views import (
    CarListCreateAPIView,
    CarDetailAPIView,
    BookingListCreateAPIView,
    BookingDetailAPIView,
    stripe_webhook,
)
urlpatterns = [

    # Cars
    path(
        'cars/',
        CarListCreateAPIView.as_view(),
        name='car-list-create'
    ),

    path(
        'cars/<int:pk>/',
        CarDetailAPIView.as_view(),
        name='car-detail'
    ),

    # Bookings
    path(
        'bookings/',
        BookingListCreateAPIView.as_view(),
        name='booking-list-create'
    ),

    path(
        'bookings/<int:pk>/',
        BookingDetailAPIView.as_view(),
        name='booking-detail'
    ),

    # Stripe webhook (raw, signed POST from Stripe)
    path(
        'stripe/webhook/',
        stripe_webhook,
        name='stripe-webhook'
    ),
]