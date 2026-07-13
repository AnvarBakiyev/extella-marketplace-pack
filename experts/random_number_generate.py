# expert: random_number_generate
# description: Generates random numbers or picks/shuffles items. Params: mode (integer/float/pick/shuffle), min_val, max_val, count, items (comma-separated for pick/shuffle). Returns JSON with output_type json.

def random_number_generate(mode='integer', min_val='1', max_val='100', count='5', items=''):
    import random, json
    try:
        n = min(max(int(count), 1), 100)
        if mode == 'integer':
            lo, hi = int(min_val), int(max_val)
            if lo > hi: lo, hi = hi, lo
            nums = [random.randint(lo, hi) for _ in range(n)]
            result = {'numbers': nums, 'count': n, 'range': str(lo) + ' – ' + str(hi)}
        elif mode == 'float':
            nums = [round(random.random(), 8) for _ in range(n)]
            result = {'numbers': nums, 'count': n}
        elif mode in ('pick', 'shuffle'):
            lst = [x.strip() for x in items.split(',') if x.strip()]
            if not lst: return json.dumps({'status': 'error', 'message': 'Provide a comma-separated list of items'})
            if mode == 'pick':
                picked = random.choices(lst, k=n)
                result = {'picked': picked, 'from': lst, 'count': n}
            else:
                shuffled = lst[:]
                random.shuffle(shuffled)
                result = {'shuffled': shuffled, 'original': lst}
        else:
            return json.dumps({'status': 'error', 'message': 'Unknown mode'})
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
