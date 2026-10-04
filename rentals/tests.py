from decimal import Decimal
from unittest import mock
from datetime import date, timedelta

import stripe
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Car, Booking, Payment
from .availability import available_count, rental_datetime


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
        'pickup_date': '2030-01-01', 'dropoff_date': '2030-01-04',
        'pickup_time': '09:00 AM', 'dropoff_time': '09:00 AM',
        'name': 'Jane', 'phone': '501234567', 'email': 'jane@example.com',
        'baby_seat': False, 'pay_now': pay_now,
        'total_price': str(total), 'status': 'pending',
    }


class CreateCheckoutSessionTests(TestCase):
    """Booking POST: Pay Later vs Pay Now (Stripe Checkout)."""

    def setUp(self):
        self.car = _make_car()

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_three_vehicles_allow_three_checkouts_and_block_fourth(self):
        self.car.fleet_count = 3
        self.car.save()
        query = '?pickup_date=2030-01-01&dropoff_date=2030-01-04&pickup_time=09%3A00%20AM&dropoff_time=09%3A00%20AM'
        with mock.patch('stripe.checkout.Session.create') as checkout:
            for index in range(3):
                checkout.return_value = mock.Mock(id=f'cs_capacity_{index}', url='https://stripe.test/checkout')
                self.assertEqual(self.client.get(f'/api/cars/{self.car.id}/{query}').json()['available_count'], 3 - index)
                response = self.client.post('/api/bookings/', _booking_payload(self.car, True, '224.44'), content_type='application/json')
                self.assertEqual(response.status_code, 201)
            response = self.client.post('/api/bookings/', _booking_payload(self.car, True, '224.44'), content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(checkout.call_count, 3)
        self.assertEqual(self.client.get(f'/api/cars/{self.car.id}/{query}').json()['available_count'], 0)
        Booking.objects.filter(pk=Booking.objects.first().pk).update(payment_status='failed')
        self.assertEqual(self.client.get(f'/api/cars/{self.car.id}/{query}').json()['available_count'], 1)

    def test_availability_uses_peak_occupancy_not_total_overlaps(self):
        self.car.fleet_count = 2
        self.car.save()
        for start, end in [(1, 2), (2, 3)]:
            Booking.objects.create(car=self.car, pickup_date=date(2030, 1, start), dropoff_date=date(2030, 1, end),
                                   pickup_time='09:00 AM', dropoff_time='09:00 AM', name='Jane', phone='501234567',
                                   email='jane@example.com', total_price='74.82', status='confirmed')
        self.assertEqual(available_count(self.car, rental_datetime(date(2030, 1, 1), '09:00 AM'), rental_datetime(date(2030, 1, 3), '09:00 AM')), 1)
        self.assertEqual(available_count(self.car, rental_datetime(date(2030, 1, 3), '09:00 AM'), rental_datetime(date(2030, 1, 4), '09:00 AM')), 2)

    def test_old_pending_checkout_does_not_reserve_inventory(self):
        booking = Booking.objects.create(car=self.car, pickup_date=date(2030, 1, 1), dropoff_date=date(2030, 1, 4),
                                         pickup_time='09:00 AM', dropoff_time='09:00 AM', name='Jane', phone='501234567',
                                         email='jane@example.com', total_price='224.44', status='pending')
        Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now() - timedelta(minutes=31))
        self.assertEqual(available_count(self.car, rental_datetime(date(2030, 1, 1), '09:00 AM'), rental_datetime(date(2030, 1, 4), '09:00 AM')), 1)

    def test_pay_later_is_rejected(self):
        resp = self.client.post('/api/bookings/', _booking_payload(self.car, False, '224.44'), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_invalid_fields_do_not_start_payment(self):
        for field, value in [('name', ' '), ('phone', '123'), ('email', 'invalid'),
                             ('pickup_date', '2020-01-01'), ('dropoff_date', '2030-01-01'),
                             ('pickup_time', 'invalid'), ('dropoff_time', '')]:
            with self.subTest(field=field), mock.patch('stripe.checkout.Session.create') as checkout:
                payload = _booking_payload(self.car, True, '224.44')
                payload[field] = value
                resp = self.client.post('/api/bookings/', payload, content_type='application/json')
                self.assertEqual(resp.status_code, 400)
                checkout.assert_not_called()
                self.assertEqual(Booking.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_one_day_booking_is_allowed(self):
        payload = _booking_payload(self.car, True, '74.82')
        payload['dropoff_date'] = '2030-01-02'
        with mock.patch('stripe.checkout.Session.create', return_value=mock.Mock(id='cs_one_day', url='https://stripe.test/one-day')) as checkout:
            resp = self.client.post('/api/bookings/', payload, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Booking.objects.get().total_price, Decimal('74.82'))
        self.assertEqual(checkout.call_args.kwargs['line_items'][0]['price_data']['unit_amount'], 7482)

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_payment_must_equal_half(self):
        for amount in ['224.43', '224.45', '448.88']:
            with self.subTest(amount=amount), mock.patch('stripe.checkout.Session.create') as checkout:
                resp = self.client.post('/api/bookings/', _booking_payload(self.car, True, amount), content_type='application/json')
                self.assertEqual(resp.status_code, 400)
                checkout.assert_not_called()
                self.assertEqual(Booking.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_pay_now_without_secret_returns_503_and_deletes_booking(self):
        resp = self.client.post(
            '/api/bookings/', _booking_payload(self.car, True, '224.44'),
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
                '/api/bookings/', _booking_payload(self.car, True, '224.44'),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['checkout_url'], 'https://stripe.test/session/123')

        # Half of the server-calculated discounted, VAT-inclusive three-day total.
        booking = Booking.objects.first()
        self.assertEqual(booking.total_price, Decimal('224.44'))

        payment = Payment.objects.first()

        # Verify the Stripe call shape: AED -> fils, metadata, redirect URLs.
        _, kwargs = m.call_args
        self.assertEqual(kwargs['mode'], 'payment')
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'aed')
        self.assertEqual(kwargs['line_items'][0]['price_data']['unit_amount'], 22444)
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
                '/api/bookings/', _booking_payload(self.car, True, '224.44'),
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
