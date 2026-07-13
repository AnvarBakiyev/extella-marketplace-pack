# expert: tdee_calculator_compute
# description: Calculates BMR and TDEE using Mifflin-St Jeor equation. Params: age (int), gender (male/female), weight_kg (float), height_cm (float), activity (sedentary/light/moderate/active/very_active). Returns J

def tdee_calculator_compute(age='30', gender='male', weight_kg='75', height_cm='175', activity='moderate'):
    import json
    try:
        w, h, a = float(weight_kg), float(height_cm), int(age)
        if gender.lower() == 'female':
            bmr = 10 * w + 6.25 * h - 5 * a - 161
        else:
            bmr = 10 * w + 6.25 * h - 5 * a + 5
        factors = {'sedentary': 1.2, 'light': 1.375, 'moderate': 1.55, 'active': 1.725, 'very_active': 1.9}
        factor = factors.get(activity.lower(), 1.55)
        tdee = round(bmr * factor)
        result = {'bmr': round(bmr), 'tdee': tdee, 'goals': {'weight_loss_500': tdee - 500, 'weight_loss_250': tdee - 250, 'maintenance': tdee, 'weight_gain_250': tdee + 250, 'weight_gain_500': tdee + 500}, 'macros_moderate_protein': {'protein_g': round(w * 2), 'fat_g': round(tdee * 0.25 / 9), 'carbs_g': round((tdee - w * 2 * 4 - tdee * 0.25) / 4)}}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
