# expert: bmi_calculator_compute
# description: Calculates BMI from weight and height. Params: weight (number), height (number), units (metric: kg/cm, imperial: lbs/inches). Returns JSON with output_type json containing bmi, category, healthy_weigh

def bmi_calculator_compute(weight='70', height='175', units='metric'):
    import json
    try:
        w, h = float(weight), float(height)
        if units == 'imperial':
            w_kg = w * 0.453592
            h_m = h * 0.0254
        else:
            w_kg = w
            h_m = h / 100
        if h_m <= 0: return json.dumps({'status': 'error', 'message': 'Height must be greater than 0'})
        bmi = round(w_kg / (h_m * h_m), 1)
        if bmi < 18.5: cat = 'Underweight'; note = 'Consider consulting a healthcare provider.'
        elif bmi < 25: cat = 'Normal weight'; note = 'You are in the healthy weight range.'
        elif bmi < 30: cat = 'Overweight'; note = 'Moderate changes to diet and activity may help.'
        else: cat = 'Obese'; note = 'Consult a healthcare provider for personalized guidance.'
        min_healthy = round(18.5 * h_m * h_m, 1)
        max_healthy = round(24.9 * h_m * h_m, 1)
        result = {'bmi': bmi, 'category': cat, 'note': note, 'healthy_weight_range_kg': {'min': min_healthy, 'max': max_healthy}}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
