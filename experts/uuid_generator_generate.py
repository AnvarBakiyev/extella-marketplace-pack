# expert: uuid_generator_generate
# description: Generates one or more UUIDs. Params: version (1 or 4, default 4), count (1-20, default 1). Returns JSON with output_type text containing one UUID per line.

def uuid_generator_generate(version='4', count='1'):
    import uuid, json
    try:
        n = min(max(int(count), 1), 20)
        ids = []
        for _ in range(n):
            if version == '1':
                ids.append(str(uuid.uuid1()))
            else:
                ids.append(str(uuid.uuid4()))
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': '\n'.join(ids)})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
