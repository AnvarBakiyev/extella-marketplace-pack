# expert: pace_calculator_calc
# description: Running pace calculator — compute min/km, min/mile, and speed from distance and time. Essential for runners and fitness enthusiasts.

def pace_calculator_calc(distance_km='10', hours='0', minutes='52', seconds='0'):
    import json
    try:
        dist = float(distance_km)
        total_sec = int(hours)*3600 + int(minutes)*60 + int(seconds)
        pace_sec = total_sec / dist if dist else 0
        pm = int(pace_sec // 60); ps = int(pace_sec % 60)
        speed = round(dist / (total_sec/3600), 2) if total_sec else 0
        return json.dumps({'status':'success','output_type':'json','data':{'pace_min_km':str(pm)+':'+str(ps).zfill(2),'speed_kmh':speed,'time':str(int(hours))+'h '+str(int(minutes))+'m'}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
