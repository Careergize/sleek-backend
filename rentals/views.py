import logging
from decimal import Decimal, ROUND_HALF_UP

import pdfkit
import stripe
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Car, Booking, Payment
from .serializers import CarSerializer, BookingSerializer

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from xhtml2pdf import pisa


class InvoiceAPIView(APIView):

    def get(self, request):
        return render(
            request,
            'rentals/Sleek_Rental_Agreement_Template.html',
        )

# ponytail: AED is a 2-decimal currency on Stripe -> amount in fils (AED 1.00 = 100).


# =========================
# PRICE CALCULATION (server-side source of truth)
# Mirrors the frontend's calculation exactly, so a client can never send an
# arbitrary total_price. Always recompute here rather than trusting the client.
# =========================
TWO_PLACES = Decimal('0.01')
BABY_SEAT_RATE_PER_DAY = Decimal('25')


def _compute_full_total(car, pickup_date, dropoff_date, baby_seat, pay_now):
    days = (dropoff_date - pickup_date).days or 1
    base_price = car.price_day * days
    if baby_seat:
        base_price += BABY_SEAT_RATE_PER_DAY * days

    discount = (base_price * Decimal('0.05')) if pay_now else Decimal('0')
    vat = (base_price - discount) * Decimal('0.05')
    total = base_price - discount + vat
    return total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# =========================
# BOOKING CONFIRMATION EMAIL
# Shared by the manual "send email" endpoint (used for Pay Later, right after
# booking creation) and the Stripe webhook (used for Pay Now, right after
# payment is confirmed). Kept in one place so both flows send the exact same
# email and neither can drift out of sync.
# =========================
def send_booking_confirmation_email(booking):
    html_content = render_to_string(
        'rentals/Sleek_Rental_Agreement_Template.html',
        {'booking': booking}
    )

    pdf_data = html_to_pdf_bytes(html_content)

    subject = f"Rental Agreement - {booking.car.brand} {booking.car.name}"
    body = f"""Dear {booking.name},

Your booking has been confirmed. Please find your rental agreement attached.

Booking Details:
Vehicle: {booking.car.brand} {booking.car.name}
Pickup Date: {booking.pickup_date}
Pickup Time: {booking.pickup_time}
Drop-off Date: {booking.dropoff_date}
Drop-off Time: {booking.dropoff_time}
Total Amount: AED {booking.total_price}

Thank you for choosing Sleek Car Rental.

Regards,
Sleek Car Rental LLC"""

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[booking.email],
    )

    email.attach(
        f"Rental_Agreement_{booking.id}.pdf",
        pdf_data,
        "application/pdf"
    )

    email.send(fail_silently=False)


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
        car = serializer.validated_data['car']
        pickup = serializer.validated_data['pickup_date']
        dropoff = serializer.validated_data['dropoff_date']
        baby_seat = serializer.validated_data.get('baby_seat', False)

        # Always recompute the real total server-side. Never trust total_price
        # from the client as the "full" amount owed.
        full_total = _compute_full_total(car, pickup, dropoff, baby_seat, pay_now)

        if not pay_now:
            # Pay Later: no online payment, the full amount is due on pickup.
            # Booking is confirmed immediately and the frontend triggers the
            # confirmation email right after this call succeeds.
            serializer.validated_data['total_price'] = full_total
            booking = serializer.save(status='confirmed')

            return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

        # =========================
        # Pay Now
        # =========================
        if not settings.STRIPE_SECRET_KEY:
            return Response(
                {'detail': 'Online payments are not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Client sends how much of the total they want to pre-book online now.
        # It must be at least 50% of the real total — enforced here, not just
        # in the UI, since the UI check can be bypassed by calling the API directly.
        prebook_amount = serializer.validated_data.get('total_price')
        min_prebook = (full_total / 2).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        if prebook_amount is None or prebook_amount < min_prebook:
            return Response(
                {
                    'detail': (
                        f'Pre-book amount must be at least AED {min_prebook} '
                        f'(50% of the total AED {full_total}).'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Booking stays "pending" until Stripe confirms payment via webhook —
        # that's the only place status flips to "confirmed" for Pay Now, and
        # that's also the only place the confirmation email is sent for Pay Now.
        serializer.validated_data['total_price'] = prebook_amount
        booking = serializer.save(status='pending')

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

    if not booking_id:
        return

    booking = Booking.objects.filter(pk=booking_id).first()
    if not booking:
        return

    # Payment is confirmed by Stripe -> booking is confirmed now, and only now.
    booking.payment_status = 'paid'
    booking.status = 'confirmed'
    booking.save(update_fields=['payment_status', 'status'])

    # Send the confirmation email only after status is actually "confirmed".
    # Errors are logged, not raised: Stripe retries webhooks on non-2xx, and
    # we don't want a flaky email send to cause duplicate payment processing.
    try:
        send_booking_confirmation_email(booking)
    except Exception:
        logger.exception('Failed to send confirmation email for booking %s', booking.id)


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



from io import BytesIO
from playwright.sync_api import sync_playwright
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

def html_to_pdf_bytes(html_content):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        pdf_bytes = page.pdf(format="A4", print_background=True)
        browser.close()
        return pdf_bytes

class SendBookingEmailAPIView(APIView):

    def post(self, request, pk):
        try:
            booking = Booking.objects.select_related('car').get(pk=pk)
        except Booking.DoesNotExist:
            return Response(
                {"success": False, "message": "Booking not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if booking.status != "confirmed":
            return Response(
                {
                    "success": False,
                    "message": "Booking is not confirmed yet",
                    "booking_status": booking.status
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            send_booking_confirmation_email(booking)

            return Response(
                {
                    "success": True,
                    "message": "Booking confirmation email sent successfully",
                    "booking_id": booking.id,
                    "email": booking.email
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.exception("Failed to send booking email: %s", e)
            return Response(
                {
                    "success": False,
                    "message": "Failed to send email",
                    "error": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )