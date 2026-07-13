# expert: sleep_calculator_compute
# description: Calculates optimal sleep/wake times based on 90-minute cycles plus 14-minute fall-asleep time. Params: mode (bedtime_to_wakeup / wakeup_to_bedtime), time (HH:MM). Returns JSON with output_type json co

def sleep_calculator_compute(mode='bedtime_to_wakeup', time='23:00'):
    import datetime, json
    try:
        h, m = map(int, time.strip().split(':'))
        base = datetime.datetime(2000, 1, 1, h, m)
        cycle = 90
        fall_asleep = 14
        times = []
        if mode == 'bedtime_to_wakeup':
            start = base + datetime.timedelta(minutes=fall_asleep)
            for cycles in range(3, 7):
                wake = start + datetime.timedelta(minutes=cycles * cycle)
                times.append({'cycles': cycles, 'sleep_hours': cycles * 1.5, 'time': wake.strftime('%H:%M'), 'quality': 'ideal' if cycles >= 5 else ('good' if cycles == 4 else 'short')})
        else:
            for cycles in range(6, 2, -1):
                bed = base - datetime.timedelta(minutes=cycles * cycle + fall_asleep)
                times.append({'cycles': cycles, 'sleep_hours': cycles * 1.5, 'time': bed.strftime('%H:%M'), 'quality': 'ideal' if cycles >= 5 else ('good' if cycles == 4 else 'short')})
        result = {'input_time': time, 'mode': mode, 'fall_asleep_minutes': fall_asleep, 'recommendations': times, 'note': 'Each sleep cycle is 90 minutes. Ideal sleep is 5-6 cycles (7.5-9 hours).'}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
