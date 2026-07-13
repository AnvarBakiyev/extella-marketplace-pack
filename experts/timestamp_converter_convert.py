# expert: timestamp_converter_convert
# description: Converts Unix timestamps to human-readable dates and vice versa. Params: value (timestamp integer or date string), direction (ts_to_date/date_to_ts/now). Returns JSON with output_type json containing 

def timestamp_converter_convert(value='', direction='now'):
    import datetime, json, time
    try:
        if direction == 'now' or not value:
            ts = int(time.time())
            dt = datetime.datetime.utcfromtimestamp(ts)
        elif direction == 'ts_to_date':
            ts = int(float(value.strip()))
            dt = datetime.datetime.utcfromtimestamp(ts)
        else:
            fmts = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
            dt = None
            for fmt in fmts:
                try: dt = datetime.datetime.strptime(value.strip(), fmt); break
                except: pass
            if not dt: return json.dumps({'status': 'error', 'message': 'Could not parse date. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS'})
            ts = int((dt - datetime.datetime(1970, 1, 1)).total_seconds())
        result = {'unix_timestamp': ts, 'utc': dt.strftime('%Y-%m-%d %H:%M:%S UTC'), 'iso8601': dt.strftime('%Y-%m-%dT%H:%M:%SZ'), 'readable': dt.strftime('%B %d, %Y at %H:%M:%S UTC')}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
