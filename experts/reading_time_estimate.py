# expert: reading_time_estimate
# description: Estimates reading and speaking time for a text. Params: text (input text), wpm (reading speed, default 200). Returns JSON with output_type json containing reading_time_min, speaking_time_min, word_cou

def reading_time_estimate(text='', wpm='200'):
    import json
    try:
        words = len(text.split())
        speed = max(1, int(wpm))
        reading_sec = words / speed * 60
        reading_min = reading_sec / 60
        speaking_sec = words / 130 * 60
        def fmt(seconds):
            m = int(seconds // 60)
            s = int(seconds % 60)
            if m == 0: return str(s) + ' sec'
            return str(m) + ' min ' + (str(s) + ' sec' if s else '')
        result = {'word_count': words, 'reading_speed_wpm': speed, 'reading_time': fmt(reading_sec), 'reading_time_seconds': round(reading_sec), 'speaking_time': fmt(speaking_sec), 'speaking_time_seconds': round(speaking_sec), 'pages_approx': round(words / 250, 1)}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
