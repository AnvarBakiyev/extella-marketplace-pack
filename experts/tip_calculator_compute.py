# expert: tip_calculator_compute
# description: Calculates tip and splits bill among people. Params: bill (total bill amount), tip_percent (tip percentage, default 15), people (number of people, default 2). Returns JSON with output_type json.

def tip_calculator_compute(bill='100', tip_percent='15', people='2'):
    import json
    try:
        b = float(bill)
        tp = float(tip_percent)
        n = max(1, int(people))
        tip = round(b * tp / 100, 2)
        total = round(b + tip, 2)
        per_person = round(total / n, 2)
        tip_per_person = round(tip / n, 2)
        result = {'bill': b, 'tip_percent': tp, 'tip_amount': tip, 'total': total, 'people': n, 'per_person': per_person, 'tip_per_person': tip_per_person}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
