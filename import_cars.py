import os
import json
import django
from django.db import transaction

# Set up the Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sleekbackend.settings')
django.setup()

from rentals.models import Car

def run_import():
    file_path = 'django_cars.js'
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # More robust extraction: find the start and end of the JSON array
    start = text.find('[')
    end = text.rfind(']') + 1
    json_text = text[start:end]
    
    cars_data = json.loads(json_text)

    with transaction.atomic():
        for car in cars_data:
            Car.objects.update_or_create(
                id=car['id'],
                defaults={
                    'brand': car['brand'],
                    'name': car['name'],
                    'category': car['category'],
                    'image': car['image'].replace('/media/', ''),
                    'price_day': car['price_day'],
                    'price_week': car['price_week'],
                    'price_month': car['price_month'],
                    'mileage_limit': car['mileage_limit'],
                    'additional_mileage': car['additional_mileage'],
                    'min_rental': car['min_rental'],
                    'location': car['location'],
                    'specs': car['specs'],
                    'overview': car['overview'],
                    'features': car['features'],
                    'description': car['description']
                }
            )
    print(f"Successfully imported {len(cars_data)} cars.")

if __name__ == '__main__':
    run_import()