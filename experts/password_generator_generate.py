# expert: password_generator_generate
# description: Generates a cryptographically secure password. Params: length (int, default 16), uppercase (true/false), numbers (true/false), symbols (true/false). Returns JSON with output_type text and the password

def password_generator_generate(length='16', uppercase='true', numbers='true', symbols='true'):
    import secrets, string, json
    try:
        chars = string.ascii_lowercase
        if str(uppercase).lower() in ('true', '1', 'yes'): chars += string.ascii_uppercase
        if str(numbers).lower() in ('true', '1', 'yes'): chars += string.digits
        if str(symbols).lower() in ('true', '1', 'yes'): chars += '!@#$%^&*()_+-=[]{}|;:,.<>?'
        pwd = ''.join(secrets.choice(chars) for _ in range(int(length)))
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': pwd})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
