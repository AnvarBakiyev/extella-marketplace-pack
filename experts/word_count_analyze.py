# expert: word_count_analyze
# description: Analyzes text and returns word count, character counts, sentence count, paragraph count, unique words, reading time and top frequent words. Param: text (string). Returns JSON with output_type json.

def word_count_analyze(text=''):
    import re, json
    try:
        words = text.split()
        sentences = [s for s in re.split(r'[.!?]+', text) if s.strip()]
        paragraphs = [p for p in text.split('\n\n') if p.strip()]
        chars_no_space = len(text.replace(' ', '').replace('\n', '').replace('\t', ''))
        freq = {}
        for w in words:
            k = re.sub(r'[^\w]', '', w.lower())
            if k: freq[k] = freq.get(k, 0) + 1
        top = sorted(freq.items(), key=lambda x: -x[1])[:10]
        reading_min = max(1, round(len(words) / 200))
        result = {'words': len(words), 'characters': len(text), 'characters_no_spaces': chars_no_space, 'sentences': len(sentences), 'paragraphs': len(paragraphs), 'unique_words': len(freq), 'reading_time': str(reading_min) + ' min', 'top_words': [{'word': w, 'count': c} for w, c in top]}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
