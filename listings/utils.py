import requests
import math
from datetime import timedelta
from django.utils import timezone


def get_cebu_weather():
    api_key = "8bd489c369df2c695b3586947411a92f"
    city = "Cebu City,PH"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"

    try:
        response = requests.get(url, timeout=4)
        data = response.json()

        current_temp = data['main']['temp']
        current_humidity = data['main']['humidity']

        print(f"Engine: Live weather fetched - {current_temp}°C, {current_humidity}%")
        return current_temp, current_humidity

    except Exception as e:
        print(f"Weather API Error: {e}")
        return 30.0, 75.0


def calculate_ttt_expiry(base_hours, current_temp, prep_dt):
    if timezone.is_naive(prep_dt):
        prep_dt = timezone.make_aware(prep_dt)

    temp_diff = current_temp - 25.0
    adjustment_factor = max(0.5, 1.0 - (temp_diff * 0.03))
    adjusted_hours = base_hours * adjustment_factor
    expiry_dt = prep_dt + timedelta(hours=adjusted_hours)

    return expiry_dt


def calculate_haversine_km(lat1, lon1, lat2, lon2):
    """
    Calculates the great-circle distance in kilometers between two GPS points
    in Cebu City using the Haversine formula.
    """
    try:
        r = 6371.0  # Earth's mean radius in km
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(r * c, 2)
    except Exception:
        return 1.0