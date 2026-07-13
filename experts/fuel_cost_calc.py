# expert: fuel_cost_calc
# description: Everyday fuel cost calculator — estimate how much a road trip will cost based on distance, fuel consumption, and current fuel price.

def fuel_cost_calc(distance_km='100', consumption='8', price_per_liter='1.5'):
    import json
    try:
        d, c, p = float(distance_km), float(consumption), float(price_per_liter)
        liters = d * c / 100; cost = round(liters * p, 2)
        return json.dumps({'status':'success','output_type':'json','data':{'distance_km':d,'liters':round(liters,2),'cost':cost,'currency':'(local)'}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
