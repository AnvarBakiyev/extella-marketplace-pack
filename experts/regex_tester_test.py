# expert: regex_tester_test
# description: Tests a regex pattern against text and returns all matches with their positions. Params: pattern (regex string), text (test string), flags (combination of i=ignorecase, m=multiline, s=dotall). Returns

def regex_tester_test(pattern='', text='', flags=''):
    import re, json
    try:
        f = 0
        if 'i' in flags.lower(): f |= re.IGNORECASE
        if 'm' in flags.lower(): f |= re.MULTILINE
        if 's' in flags.lower(): f |= re.DOTALL
        matches = re.findall(pattern, text, f)
        spans = [{'start': m.start(), 'end': m.end(), 'match': m.group()} for m in re.finditer(pattern, text, f)]
        result = {'is_match': bool(matches), 'count': len(matches), 'matches': matches[:50], 'spans': spans[:50]}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
