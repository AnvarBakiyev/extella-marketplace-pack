# expert: age_calculator_compute
# description: Calculates exact age from a birth date. Params: birth_date (YYYY-MM-DD), as_of_date (YYYY-MM-DD or blank for today). Returns JSON with output_type json containing years, months, days, total_days, and 

def age_calculator_compute(birth_date='1990-01-01', as_of_date=''):
    import datetime, json
    try:
        bd = datetime.date.fromisoformat(birth_date.strip())
        today = datetime.date.fromisoformat(as_of_date.strip()) if as_of_date.strip() else datetime.date.today()
        years = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        months_total = (today.year - bd.year) * 12 + today.month - bd.month
        if today.day < bd.day: months_total -= 1
        total_days = (today - bd).days
        try:
            next_bd = bd.replace(year=today.year)
            if next_bd < today: next_bd = bd.replace(year=today.year + 1)
        except ValueError:
            next_bd = datetime.date(today.year + (1 if (today.month, today.day) >= (bd.month, bd.day) else 0), bd.month, 28)
        days_to_bd = (next_bd - today).days
        result = {'years': years, 'months': months_total, 'days': total_days, 'weeks': total_days // 7, 'next_birthday': next_bd.strftime('%B %d, %Y'), 'days_to_birthday': days_to_bd}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
