# expert: http_status_lookup_find
# description: Returns information about an HTTP status code: name, category, description and when to use it. Param: code (HTTP status code as string or integer). Returns JSON with output_type json.

def http_status_lookup_find(code='200'):
    import json
    descriptions = {
        '100': ('Continue','1xx Informational','The client should continue sending the request body.'),
        '101': ('Switching Protocols','1xx Informational','Server agrees to upgrade the protocol.'),
        '200': ('OK','2xx Success','The request succeeded. Standard response for GET/POST.'),
        '201': ('Created','2xx Success','The request succeeded and a new resource was created (POST/PUT).'),
        '204': ('No Content','2xx Success','Success with no response body (DELETE, update).'),
        '206': ('Partial Content','2xx Success','Partial response for range requests (video streaming).'),
        '301': ('Moved Permanently','3xx Redirection','Resource permanently moved to a new URL.'),
        '302': ('Found','3xx Redirection','Temporary redirect to another URL.'),
        '304': ('Not Modified','3xx Redirection','Resource not changed since last request (cache hit).'),
        '307': ('Temporary Redirect','3xx Redirection','Temporary redirect preserving the HTTP method.'),
        '308': ('Permanent Redirect','3xx Redirection','Permanent redirect preserving the HTTP method.'),
        '400': ('Bad Request','4xx Client Error','Invalid request syntax or parameters.'),
        '401': ('Unauthorized','4xx Client Error','Authentication required or failed.'),
        '403': ('Forbidden','4xx Client Error','Server understood but refuses to authorize.'),
        '404': ('Not Found','4xx Client Error','The requested resource does not exist.'),
        '405': ('Method Not Allowed','4xx Client Error','HTTP method not supported for this resource.'),
        '409': ('Conflict','4xx Client Error','Request conflicts with current state of the resource.'),
        '410': ('Gone','4xx Client Error','Resource permanently deleted.'),
        '422': ('Unprocessable Entity','4xx Client Error','Request well-formed but contains semantic errors.'),
        '429': ('Too Many Requests','4xx Client Error','Rate limit exceeded.'),
        '500': ('Internal Server Error','5xx Server Error','Unexpected server-side error.'),
        '501': ('Not Implemented','5xx Server Error','Server does not support the requested functionality.'),
        '502': ('Bad Gateway','5xx Server Error','Upstream server returned invalid response.'),
        '503': ('Service Unavailable','5xx Server Error','Server temporarily unavailable or overloaded.'),
        '504': ('Gateway Timeout','5xx Server Error','Upstream server did not respond in time.')
    }
    code_str = str(code).strip()
    if code_str in descriptions:
        name, cat, desc = descriptions[code_str]
        result = {'code': int(code_str), 'name': name, 'category': cat, 'description': desc}
    else:
        n = int(code_str)
        cats = {1: '1xx Informational', 2: '2xx Success', 3: '3xx Redirection', 4: '4xx Client Error', 5: '5xx Server Error'}
        cat = cats.get(n // 100, 'Unknown')
        result = {'code': n, 'name': 'Unknown', 'category': cat, 'description': 'No description available for this code.'}
    return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
