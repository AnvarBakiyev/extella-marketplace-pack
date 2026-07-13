# expert: weather_lookup_get
# description: Fetches current weather and 3-day forecast for a city using wttr.in. Params: city (city name), units (metric/imperial). Returns JSON with output_type json containing current conditions and forecast.

def weather_lookup_get(city='London', units='metric'):
    import urllib.request, urllib.parse, json
    try:
        city_enc = urllib.parse.quote(city.strip())
        url = 'https://wttr.in/' + city_enc + '?format=j1'
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        cur = data['current_condition'][0]
        area = data.get('nearest_area', [{}])[0]
        area_name = area.get('areaName', [{}])[0].get('value', city)
        country = area.get('country', [{}])[0].get('value', '')
        if units == 'imperial':
            temp = cur['temp_F'] + '°F'
            feels = cur['FeelsLikeF'] + '°F'
        else:
            temp = cur['temp_C'] + '°C'
            feels = cur['FeelsLikeC'] + '°C'
        desc = cur.get('weatherDesc', [{}])[0].get('value', '')
        forecast = []
        for day in data.get('weather', [])[:3]:
            forecast.append({'date': day.get('date'), 'max': (day.get('maxtempC') + '°C') if units == 'metric' else (day.get('maxtempF') + '°F'), 'min': (day.get('mintempC') + '°C') if units == 'metric' else (day.get('mintempF') + '°F'), 'description': day.get('hourly', [{}])[4].get('weatherDesc', [{}])[0].get('value', '')})
        result = {'location': area_name + (', ' + country if country else ''), 'temperature': temp, 'feels_like': feels, 'description': desc, 'humidity': cur.get('humidity') + '%', 'wind_kmph': cur.get('windspeedKmph') + ' km/h', 'visibility_km': cur.get('visibility') + ' km', 'forecast': forecast}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
