import logging

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Car, Booking, Payment
from .serializers import CarSerializer, BookingSerializer

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

# ponytail: AED is a 2-decimal currency on Stripe -> amount in fils (AED 1.00 = 100).



# =========================
# CAR LIST + CREATE
# =========================

class CarListCreateAPIView(APIView):

    def get(self, request):

        cars = Car.objects.all()

        serializer = CarSerializer(cars, many=True)

        return Response(serializer.data)

    def post(self, request):

        serializer = CarSerializer(data=request.data)

        if serializer.is_valid():

            serializer.save()

            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


# =========================
# CAR DETAIL
# =========================

class CarDetailAPIView(APIView):

    def get_object(self, pk):

        try:
            return Car.objects.get(pk=pk)

        except Car.DoesNotExist:
            return None

    def get(self, request, pk):

        car = self.get_object(pk)

        if not car:

            return Response(
                {"error": "Car not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = CarSerializer(car)

        return Response(serializer.data)

    def put(self, request, pk):

        car = self.get_object(pk)

        if not car:

            return Response(
                {"error": "Car not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = CarSerializer(
            car,
            data=request.data
        )

        if serializer.is_valid():

            serializer.save()

            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    def patch(self, request, pk):

        car = self.get_object(pk)

        if not car:

            return Response(
                {"error": "Car not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = CarSerializer(
            car,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():

            serializer.save()

            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    def delete(self, request, pk):

        car = self.get_object(pk)

        if not car:

            return Response(
                {"error": "Car not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        car.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# =========================
# BOOKING LIST + CREATE
# =========================

class BookingListCreateAPIView(APIView):

    def get(self, request):

        bookings = Booking.objects.all().order_by('-created_at')

        serializer = BookingSerializer(
            bookings,
            many=True
        )

        return Response(serializer.data)

    def post(self, request):

        serializer = BookingSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        pay_now = serializer.validated_data.get('pay_now')

        if not pay_now:
            # Pay Later: compute total_price server-side from car rate × rental days.
            car = serializer.validated_data['car']
            pickup = serializer.validated_data['pickup_date']
            dropoff = serializer.validated_data['dropoff_date']
            days = (dropoff - pickup).days or 1
            serializer.validated_data['total_price'] = car.price_day * days

        booking = serializer.save(status='pending')

        # Pay Later: no charge, booking is just a reservation request.
        if not pay_now:
            return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

        # Pay Now: use the client-sent pre-book amount directly.
        if not settings.STRIPE_SECRET_KEY:
            booking.delete()
            return Response(
                {'detail': 'Online payments are not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if booking.total_price <= 0:
            booking.delete()
            return Response(
                {'detail': 'Pre-book amount must be greater than 0.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_fils = int(booking.total_price * 100)

        payment = Payment.objects.create(
            booking=booking,
            amount=booking.total_price,
            currency='aed',
            status='pending',
        )

        try:
            session = stripe.checkout.Session.create(
                mode='payment',
                line_items=[{
                    'quantity': 1,
                    'price_data': {
                        'currency': 'aed',
                        'unit_amount': amount_fils,
                        'product_data': {
                            'name': f'{booking.car.brand} {booking.car.name} — Pre-book',
                        },
                    },
                }],
                customer_email=booking.email,
                metadata={
                    'booking_id': str(booking.id),
                    'payment_id': str(payment.id),
                },
                success_url=f'{settings.FRONTEND_URL}/booking/result?status=success',
                cancel_url=f'{settings.FRONTEND_URL}/booking/result?status=cancel',
            )
        except stripe.error.StripeError as exc:
            payment.status = 'failed'
            payment.save(update_fields=['status'])
            booking.delete()
            logger.warning('Stripe Checkout creation failed: %s', exc)
            return Response(
                {'detail': 'Could not start payment. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment.stripe_session_id = session.id
        payment.save(update_fields=['stripe_session_id'])

        return Response(
            {'checkout_url': session.url},
            status=status.HTTP_201_CREATED,
        )


# =========================
# BOOKING DETAIL
# =========================

class BookingDetailAPIView(APIView):

    def get_object(self, pk):

        try:
            return Booking.objects.get(pk=pk)

        except Booking.DoesNotExist:
            return None

    def get(self, request, pk):

        booking = self.get_object(pk)

        if not booking:

            return Response(
                {"error": "Booking not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = BookingSerializer(booking)

        return Response(serializer.data)

    def put(self, request, pk):

        booking = self.get_object(pk)

        if not booking:

            return Response(
                {"error": "Booking not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = BookingSerializer(
            booking,
            data=request.data
        )

        if serializer.is_valid():

            serializer.save()

            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    def patch(self, request, pk):

        booking = self.get_object(pk)

        if not booking:

            return Response(
                {"error": "Booking not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = BookingSerializer(
            booking,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():

            serializer.save()

            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    def delete(self, request, pk):

        booking = self.get_object(pk)

        if not booking:

            return Response(
                {"error": "Booking not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        booking.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# =========================
# STRIPE WEBHOOK
# Plain Django view (not DRF): needs the raw body for signature verification,
# and no auth/CSRF. Stripe POSTs signed events here after a Checkout completes.
# =========================
@csrf_exempt
def stripe_webhook(request):

    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        return HttpResponse('webhook secret not configured', status=200)

    try:
        event = stripe.Webhook.construct_event(
            payload=request.body,
            sig_header=request.headers.get('stripe-signature', ''),
            secret=secret,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse('invalid payload', status=400)

    event_type = event['type']
    data = event['data']['object']

    if event_type == 'checkout.session.completed':
        _handle_checkout_completed(data)
    elif event_type == 'checkout.session.expired':
        _handle_checkout_expired(data)
    elif event_type == 'payment_intent.payment_failed':
        _handle_payment_failed(data)
    elif event_type == 'charge.refunded':
        _handle_charge_refunded(data)

    return HttpResponse(status=200)


def _handle_checkout_completed(session):
    metadata = session.get('metadata', {})
    booking_id = metadata.get('booking_id')
    payment_id = metadata.get('payment_id')

    if payment_id:
        Payment.objects.filter(pk=payment_id).update(
            stripe_payment_intent_id=session.get('payment_intent'),
            status='succeeded',
        )
    elif booking_id:
        # Fallback for old sessions without payment_id in metadata
        Payment.objects.filter(booking_id=booking_id, status='pending').update(
            stripe_session_id=session.get('id'),
            stripe_payment_intent_id=session.get('payment_intent'),
            status='succeeded',
        )

    if booking_id:
        Booking.objects.filter(pk=booking_id).update(payment_status='paid')


def _handle_checkout_expired(session):
    metadata = session.get('metadata', {})
    booking_id = metadata.get('booking_id')
    payment_id = metadata.get('payment_id')

    if payment_id:
        Payment.objects.filter(pk=payment_id).update(status='failed')
    elif booking_id:
        Payment.objects.filter(booking_id=booking_id, status='pending').update(status='failed')

    if booking_id:
        Booking.objects.filter(pk=booking_id).update(payment_status='failed')


def _handle_payment_failed(payment_intent):
    payment = Payment.objects.filter(
        stripe_payment_intent_id=payment_intent.get('id'),
    ).first()

    if payment:
        payment.status = 'failed'
        payment.save(update_fields=['status'])
        payment.booking.payment_status = 'failed'
        payment.booking.save(update_fields=['payment_status'])


def _handle_charge_refunded(charge):
    payment_intent_id = charge.get('payment_intent')
    if not payment_intent_id:
        return

    payment = Payment.objects.filter(
        stripe_payment_intent_id=payment_intent_id,
    ).first()

    if payment:
        payment.status = 'refunded'
        payment.refund_reason = charge.get('reason', '')
        payment.save(update_fields=['status', 'refund_reason'])
        payment.booking.payment_status = 'refunded'
        payment.booking.save(update_fields=['payment_status'])