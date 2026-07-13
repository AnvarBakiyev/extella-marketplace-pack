# expert: fake_data_generator_generate
# description: Generates realistic fake user profiles using randomuser.me. Params: count (1-10), nationality (optional 2-letter code), gender (male/female/any). Returns JSON with output_type json containing user pro

def fake_data_generator_generate(count='3', nationality='', gender=''):
    import urllib.request, urllib.parse, json
    try:
        params = {'results': min(max(int(count), 1), 10)}
        if nationality.strip(): params['nat'] = nationality.strip()
        if gender.strip(): params['gender'] = gender.strip()
        url = 'https://randomuser.me/api/?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        users = []
        for u in data.get('results', []):
            name = u['name']
            loc = u['location']
            users.append({'name': name['first'] + ' ' + name['last'], 'gender': u['gender'], 'email': u['email'], 'phone': u['phone'], 'nationality': u.get('nat', ''), 'username': u['login']['username'], 'age': u['dob']['age'], 'address': loc['street']['number'].__str__() + ' ' + loc['street']['name'] + ', ' + loc['city'] + ', ' + loc['country'], 'avatar': u['picture']['large']})
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': {'users': users, 'count': len(users)}})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
