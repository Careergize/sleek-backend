# Availability is calculated from fleet_count and date-overlapping bookings.
# Booking saves must not mark the whole model as booked: another vehicle of
# the same model may still be available, and future bookings do not occupy it now.
