from django.db import migrations, models


STATUS_FIELD = models.CharField(max_length=20, default='available', choices=[
    ('available', 'Available'), ('booked', 'Booked'), ('maintenance', 'Maintenance'), ('inactive', 'Inactive'),
])


def ensure_status_column(apps, schema_editor):
    # Car.status existed in application code but was missing from migration history.
    Car = apps.get_model('rentals', 'Car')
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, Car._meta.db_table)
    if not any(column.name == 'status' for column in columns):
        field = STATUS_FIELD.clone()
        field.set_attributes_from_name('status')
        schema_editor.add_field(Car, field)


def clear_legacy_booking_status(apps, schema_editor):
    Car = apps.get_model('rentals', 'Car')
    Booking = apps.get_model('rentals', 'Booking')
    # Previously a single confirmed booking marked the entire model as booked.
    car_ids = Booking.objects.filter(status='confirmed').values_list('car_id', flat=True)
    Car.objects.filter(status='booked', pk__in=car_ids).update(status='available')


class Migration(migrations.Migration):
    dependencies = [('rentals', '0004_booking_payment_status_payment')]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(ensure_status_column, migrations.RunPython.noop)],
            state_operations=[migrations.AddField(model_name='car', name='status', field=STATUS_FIELD)],
        ),
        migrations.AddField(
            model_name='car', name='fleet_count',
            field=models.PositiveIntegerField(default=1, help_text='Number of vehicles available for this model.'),
        ),
        migrations.RunPython(clear_legacy_booking_status, migrations.RunPython.noop),
    ]
