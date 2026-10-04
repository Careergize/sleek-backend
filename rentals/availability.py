from datetime import datetime, timedelta, timezone
from django.db.models import Q
from django.utils import timezone as django_timezone

CHECKOUT_HOLD_MINUTES = 30


def rental_datetime(date, time):
    parsed = datetime.strptime(time, '%I:%M %p').time()
    return datetime.combine(date, parsed, tzinfo=timezone(timedelta(hours=4)))


def available_count(car, start=None, end=None):
    if car.status in ('maintenance', 'inactive', 'booked'):
        return 0
    now = django_timezone.now()
    start = start or now
    end = end or start + timedelta(microseconds=1)
    bookings = car.bookings.filter(
        Q(status='confirmed') |
        Q(status='pending', payment_status='pending', created_at__gte=now - timedelta(minutes=CHECKOUT_HOLD_MINUTES))
    ).filter(pickup_date__lte=end.astimezone(timezone(timedelta(hours=4))).date(),
             dropoff_date__gte=start.astimezone(timezone(timedelta(hours=4))).date())
    events = []
    for booking in bookings:
        try:
            pickup = rental_datetime(booking.pickup_date, booking.pickup_time)
            dropoff = rental_datetime(booking.dropoff_date, booking.dropoff_time)
        except ValueError:
            # Legacy bookings without formatted times conservatively occupy their dates.
            pickup = rental_datetime(booking.pickup_date, '12:00 AM')
            dropoff = rental_datetime(booking.dropoff_date + timedelta(days=1), '12:00 AM')
        if pickup < end and dropoff > start:
            events.extend([(max(start, pickup), 1), (min(end, dropoff), -1)])
    occupied = peak = 0
    for _, delta in sorted(events):
        occupied += delta
        peak = max(peak, occupied)
    return max(0, car.fleet_count - peak)
