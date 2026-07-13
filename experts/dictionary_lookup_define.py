# expert: dictionary_lookup_define
# description: Looks up an English word definition using dictionaryapi.dev. Param: word (English word to define). Returns JSON with output_type json containing definitions, phonetics and examples.

def dictionary_lookup_define(word='hello'):
    import urllib.request, urllib.parse, json
    try:
        url = 'https://api.dictionaryapi.dev/api/v2/entries/en/' + urllib.parse.quote(word.strip().lower())
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        if isinstance(data, dict) and 'message' in data:
            return json.dumps({'status': 'error', 'message': 'Word not found: ' + word})
        entry = data[0]
        phonetic = entry.get('phonetic', '')
        if not phonetic:
            for p in entry.get('phonetics', []):
                if p.get('text'): phonetic = p['text']; break
        meanings = []
        for m in entry.get('meanings', [])[:4]:
            defs = []
            for d in m.get('definitions', [])[:3]:
                defs.append({'definition': d.get('definition', ''), 'example': d.get('example', '')})
            meanings.append({'part_of_speech': m.get('partOfSpeech', ''), 'definitions': defs, 'synonyms': m.get('synonyms', [])[:5]})
        result = {'word': entry.get('word', word), 'phonetic': phonetic, 'meanings': meanings}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
