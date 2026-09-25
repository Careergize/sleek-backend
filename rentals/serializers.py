from rest_framework import serializers
from .models import Car, Booking, Payment


class CarSerializer(serializers.ModelSerializer):

    class Meta:
        model = Car
        fields = '__all__'


class PaymentSerializer(serializers.ModelSerializer):

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class BookingSerializer(serializers.ModelSerializer):
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = '__all__'
    #     read_only_fields = ['payment_status']   # 'status' is writable now

    # def validate_status(self, value):
    #     if value not in ('pending', 'confirmed'):
    #         raise serializers.ValidationError("Invalid status.")
    #     return value