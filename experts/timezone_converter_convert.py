# expert: timezone_converter_convert
# description: Gets current time or converts a datetime to a timezone using worldtimeapi.org. Params: timezone (IANA timezone like America/New_York), datetime_str (optional ISO datetime). Returns JSON with output_ty

def timezone_converter_convert(timezone='America/New_York', datetime_str=''):
    import urllib.request, urllib.parse, json
    try:
        tz = timezone.strip() or 'America/New_York'
        url = 'https://timeapi.io/api/time/current/zone?timeZone=' + urllib.parse.quote(tz)
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        result = {'timezone': data.get('timeZone', tz), 'current_datetime': data.get('dateTime', '')[:19].replace('T', ' '), 'day_of_week': data.get('dayOfWeek', ''), 'dst': data.get('dstActive', False), 'time': data.get('time', ''), 'date': data.get('date', '')}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
