# expert: hash_calculator_compute
# description: Computes a cryptographic hash of the given text using the specified algorithm. Params: text (string to hash), algorithm (md5/sha1/sha256/sha512, default sha256). Returns JSON with output_type text and

def hash_calculator_compute(text='', algorithm='sha256'):
    import hashlib, json
    try:
        h = hashlib.new(algorithm)
        h.update(text.encode('utf-8'))
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': h.hexdigest(), 'label': algorithm.upper() + ' Hash'})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
