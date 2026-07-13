# expert: unit_converter_convert
# description: Converts a value between units of length, weight, temperature, area, speed, or volume. Params: value (number), from_unit (unit name), to_unit (unit name). Returns JSON with output_type json.

def unit_converter_convert(value='100', from_unit='km', to_unit='miles'):
    import json
    v = float(value)
    fu = from_unit.lower().strip().replace(' ', '')
    tu = to_unit.lower().strip().replace(' ', '')
    to_m = {'km':1000,'m':1,'cm':0.01,'mm':0.001,'miles':1609.344,'mile':1609.344,'ft':0.3048,'feet':0.3048,'foot':0.3048,'in':0.0254,'inch':0.0254,'inches':0.0254,'yd':0.9144,'yard':0.9144,'yards':0.9144,'nm':1852,'nauticalmile':1852}
    to_kg = {'kg':1,'g':0.001,'mg':0.000001,'lbs':0.453592,'lb':0.453592,'oz':0.0283495,'t':1000,'tonne':1000,'ton':907.185,'stone':6.35029}
    to_m2 = {'m2':1,'sqm':1,'km2':1e6,'sqkm':1e6,'cm2':0.0001,'sqcm':0.0001,'ft2':0.092903,'sqft':0.092903,'in2':0.00064516,'sqin':0.00064516,'acre':4046.86,'ha':10000,'hectare':10000}
    to_ms = {'ms':1,'m/s':1,'kmh':1/3.6,'km/h':1/3.6,'mph':0.44704,'knot':0.514444,'mach':340.29,'fps':0.3048,'ft/s':0.3048}
    to_l = {'l':1,'liter':1,'litre':1,'ml':0.001,'milliliter':0.001,'cl':0.01,'dl':0.1,'m3':1000,'gal':3.78541,'gallon':3.78541,'qt':0.946353,'quart':0.946353,'pt':0.473176,'pint':0.473176,'floz':0.0295735,'cup':0.236588}
    temp_units = {'celsius','c','fahrenheit','f','kelvin','k','rankine','r'}
    def convert_temp(v, f, t):
        in_c = v if f in ('celsius','c') else (v-32)*5/9 if f in ('fahrenheit','f') else v-273.15 if f in ('kelvin','k') else (v-491.67)*5/9
        if t in ('celsius','c'): return in_c
        if t in ('fahrenheit','f'): return in_c*9/5+32
        if t in ('kelvin','k'): return in_c+273.15
        return in_c*9/5+491.67
    try:
        if fu in temp_units or tu in temp_units:
            res = round(convert_temp(v, fu, tu), 4)
            cat = 'temperature'
        elif fu in to_m and tu in to_m:
            res = round(v * to_m[fu] / to_m[tu], 6); cat = 'length'
        elif fu in to_kg and tu in to_kg:
            res = round(v * to_kg[fu] / to_kg[tu], 6); cat = 'weight'
        elif fu in to_m2 and tu in to_m2:
            res = round(v * to_m2[fu] / to_m2[tu], 6); cat = 'area'
        elif fu in to_ms and tu in to_ms:
            res = round(v * to_ms[fu] / to_ms[tu], 6); cat = 'speed'
        elif fu in to_l and tu in to_l:
            res = round(v * to_l[fu] / to_l[tu], 6); cat = 'volume'
        else:
            return json.dumps({'status': 'error', 'message': 'Unknown units: ' + from_unit + ' → ' + to_unit + '. Supported: km/miles/m/ft/in, kg/lbs/oz/g, celsius/fahrenheit/kelvin, m²/ft²/acre/ha, km/h/mph/m/s, l/ml/gal/floz'})
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': {'value': v, 'from': from_unit, 'to': to_unit, 'result': res, 'category': cat}})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
