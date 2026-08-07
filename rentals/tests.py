from decimal import Decimal
from unittest import mock

import stripe
from django.test import TestCase, override_settings

from .models import Car, Booking, Payment


def _make_car():
    return Car.objects.create(
        brand='Toyota', name='Corolla', category='sedan', image='cars/x.jpg',
        price_day=Decimal('150.00'), price_week=Decimal('900.00'),
        price_month=Decimal('3500.00'), mileage_limit=250,
        additional_mileage=Decimal('1.50'), min_rental=1, location='DXB',
        specs={}, overview={}, features={}, description='test',
    )


def _booking_payload(car, pay_now, total):
    return {
        'car': car.id,
        'pickup_date': '2030-01-01', 'dropoff_date': '2030-01-03',
        'pickup_time': '09:00 AM', 'dropoff_time': '09:00 AM',
        'name': 'Jane', 'phone': '501234567', 'email': 'jane@example.com',
        'baby_seat': False, 'pay_now': pay_now,
        'total_price': str(total), 'status': 'pending',
    }


class CreateCheckoutSessionTests(TestCase):
    """Booking POST: Pay Later vs Pay Now (Stripe Checkout)."""

    def setUp(self):
        self.car = _make_car()

    def test_pay_later_creates_booking_without_stripe(self):
        resp = self.client.post(
            '/api/bookings/', _booking_payload(self.car, False, '0'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertNotIn('checkout_url', resp.json())
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(Booking.objects.first().status, 'pending')
        # Server computes total_price: 150.00/day × 2 days
        self.assertEqual(Booking.objects.first().total_price, Decimal('300.00'))

    @override_settings(STRIPE_SECRET_KEY='')
    def test_pay_now_without_secret_returns_503_and_deletes_booking(self):
        resp = self.client.post(
            '/api/bookings/', _booking_payload(self.car, True, '50.00'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(Booking.objects.count(), 0)  # rolled back

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_pay_now_zero_amount_returns_400_and_deletes_booking(self):
        resp = self.client.post(
            '/api/bookings/', _booking_payload(self.car, True, '0'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_x', FRONTEND_URL='https://fe.test')
    def test_pay_now_creates_session_and_redirects(self):
        fake = mock.Mock(id='cs_test_session_123', url='https://stripe.test/session/123')
        with mock.patch('stripe.checkout.Session.create', return_value=fake) as m:
            resp = self.client.post(
                '/api/bookings/', _booking_payload(self.car, True, '50.00'),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['checkout_url'], 'https://stripe.test/session/123')

        # Client-sent amount used directly (50.00 AED).
        booking = Booking.objects.first()
        self.assertEqual(booking.total_price, Decimal('50.00'))

        payment = Payment.objects.first()

        # Verify the Stripe call shape: AED -> fils, metadata, redirect URLs.
        _, kwargs = m.call_args
        self.assertEqual(kwargs['mode'], 'payment')
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'aed')
        self.assertEqual(kwargs['line_items'][0]['price_data']['unit_amount'], 5000)
        self.assertEqual(kwargs['metadata'], {
            'booking_id': str(booking.id),
            'payment_id': str(payment.id),
        })
        self.assertEqual(kwargs['customer_email'], 'jane@example.com')
        self.assertEqual(kwargs['success_url'], 'https://fe.test/booking/result?status=success')
        # Booking stays pending until the webhook confirms payment.
        self.assertEqual(booking.status, 'pending')

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_pay_now_stripe_failure_returns_502_and_deletes_booking(self):
        with mock.patch('stripe.checkout.Session.create',
                        side_effect=stripe.error.AuthenticationError('bad key')):
            resp = self.client.post(
                '/api/bookings/', _booking_payload(self.car, True, '50.00'),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(Booking.objects.count(), 0)


class WebhookTests(TestCase):
    """Signature verification + booking status flip."""

    def _event(self, event_type, booking_id=None):
        meta = {'booking_id': str(booking_id)} if booking_id else {}
        return {
            'type': event_type,
            'data': {'object': {'metadata': meta}},
        }

    def test_no_secret_configured_is_noop_200(self):
        with override_settings(STRIPE_WEBHOOK_SECRET=''):
            resp = self.client.post('/api/stripe/webhook/', '{}',
                                    content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_invalid_signature_returns_400(self):
        with override_settings(STRIPE_WEBHOOK_SECRET='whsec_x'):
            with mock.patch('stripe.Webhook.construct_event',
                            side_effect=stripe.error.SignatureVerificationError(
                                'bad sig', 'payload')):
                resp = self.client.post('/api/stripe/webhook/', '{}',
                                        content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_completed_event_flips_booking_to_paid(self):
        car = _make_car()
        booking = Booking.objects.create(
            car=car, pickup_date='2030-01-01', dropoff_date='2030-01-03',
            pickup_time='09:00 AM', dropoff_time='09:00 AM', name='Jane',
            phone='501234567', email='jane@example.com', total_price=Decimal('50.00'),
        )
        self.assertEqual(booking.payment_status, 'pending')

        with override_settings(STRIPE_WEBHOOK_SECRET='whsec_x'):
            with mock.patch('stripe.Webhook.construct_event',
                            return_value=self._event('checkout.session.completed', booking.id)):
                resp = self.client.post('/api/stripe/webhook/', '{}',
                                        content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'paid')

    def test_unrelated_event_does_not_touch_bookings(self):
        car = _make_car()
        booking = Booking.objects.create(
            car=car, pickup_date='2030-01-01', dropoff_date='2030-01-03',
            pickup_time='09:00 AM', dropoff_time='09:00 AM', name='Jane',
            phone='501234567', email='jane@example.com', total_price=Decimal('50.00'),
        )
        with override_settings(STRIPE_WEBHOOK_SECRET='whsec_x'):
            with mock.patch('stripe.Webhook.construct_event',
                            return_value=self._event('invoice.paid', booking.id)):
                resp = self.client.post('/api/stripe/webhook/', '{}',
                                        content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'pending')  # untouched
