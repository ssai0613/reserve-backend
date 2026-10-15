import requests
import math
from datetime import timedelta
from django.utils import timezone  

def get_cebu_weather():
    # We will put your real key here
    api_key = "8bd489c369df2c695b3586947411a92f" 
    city = "Cebu City,PH"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        current_temp = data['main']['temp']
        current_humidity = data['main']['humidity']
        
        print(f"Engine: Live weather fetched - {current_temp}°C, {current_humidity}%")
        return current_temp, current_humidity
        
    except Exception as e:
        print(f"Weather API Error: {e}")
        # Fallback values just in case your Wi-Fi drops during the panel presentation
        return 30.0, 75.0

def calculate_ttt_expiry(base_hours, current_temp, prep_dt):
    # If prep_dt is naive, make it aware
    if timezone.is_naive(prep_dt):
        prep_dt = timezone.make_aware(prep_dt)
        
    # Temperature adjustment factor (Arrhenius / Q10 concept simplified)
    # For every degree above 25°C, shelf life degrades faster
    temp_diff = current_temp - 25.0
    adjustment_factor = max(0.5, 1.0 - (temp_diff * 0.03)) # degrades faster in heat
    
    adjusted_hours = base_hours * adjustment_factor
    
    # Add the exact hours (including fractional hours/minutes) to the preparation datetime
    expiry_dt = prep_dt + timedelta(hours=adjusted_hours)
    
    return expiry_dt