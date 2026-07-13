# expert: days_between_dates_compute
# description: Calculates duration between two dates. Params: date_from (YYYY-MM-DD), date_to (YYYY-MM-DD, defaults to today). Returns JSON with output_type json containing days, weeks, months, years, and working da

def days_between_dates_compute(date_from='2024-01-01', date_to=''):
    import datetime, json
    try:
        d1 = datetime.date.fromisoformat(date_from.strip())
        d2 = datetime.date.fromisoformat(date_to.strip()) if date_to.strip() else datetime.date.today()
        if d1 > d2: d1, d2 = d2, d1
        delta = (d2 - d1).days
        months = (d2.year - d1.year) * 12 + d2.month - d1.month
        if d2.day < d1.day: months -= 1
        working_days = sum(1 for i in range(delta + 1) if (d1 + datetime.timedelta(days=i)).weekday() < 5)
        result = {'from': d1.isoformat(), 'to': d2.isoformat(), 'days': delta, 'weeks': delta // 7, 'months': months, 'years': round(delta / 365.25, 2), 'working_days': working_days, 'weekend_days': delta - working_days + 1}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
