# expert: percentage_calculator_compute
# description: Performs percentage calculations: percent_of (X% of Y), what_percent (X is ?% of Y), percent_change (% change from X to Y), discount (price after X% discount from Y), reverse (original from Y being X%

def percentage_calculator_compute(calculation_type='percent_of', value_x='15', value_y='200'):
    import json
    try:
        x, y = float(value_x), float(value_y)
        if calculation_type == 'percent_of':
            res = round(x / 100 * y, 4)
            label = str(x) + '% of ' + str(y) + ' = ' + str(res)
        elif calculation_type == 'what_percent':
            if y == 0: return json.dumps({'status': 'error', 'message': 'Y cannot be zero'})
            res = round(x / y * 100, 4)
            label = str(x) + ' is ' + str(res) + '% of ' + str(y)
        elif calculation_type == 'percent_change':
            if x == 0: return json.dumps({'status': 'error', 'message': 'X (original value) cannot be zero'})
            res = round((y - x) / abs(x) * 100, 4)
            direction = 'increase' if res >= 0 else 'decrease'
            label = str(abs(res)) + '% ' + direction + ' from ' + str(x) + ' to ' + str(y)
        elif calculation_type == 'discount':
            discount_amt = round(y * x / 100, 4)
            res = round(y - discount_amt, 4)
            label = str(y) + ' after ' + str(x) + '% discount = ' + str(res) + ' (saved: ' + str(discount_amt) + ')'
        else:
            if x == 0: return json.dumps({'status': 'error', 'message': 'X (percentage) cannot be zero'})
            res = round(y / x * 100, 4)
            label = str(y) + ' is ' + str(x) + '% of ' + str(res)
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': {'result': res, 'label': label, 'type': calculation_type}})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
