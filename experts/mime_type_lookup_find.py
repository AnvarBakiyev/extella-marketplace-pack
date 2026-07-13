# expert: mime_type_lookup_find
# description: Looks up MIME type for a file extension, or extensions for a MIME type. Params: query (extension like .pdf or MIME type like image/png), direction (ext_to_mime or mime_to_ext). Returns JSON with outpu

def mime_type_lookup_find(query='.pdf', direction='ext_to_mime'):
    import mimetypes, json
    try:
        mimetypes.init()
        query = query.strip()
        if direction == 'ext_to_mime':
            if not query.startswith('.'): query = '.' + query
            mime_type, encoding = mimetypes.guess_type('file' + query)
            if mime_type:
                category = mime_type.split('/')[0]
                result = {'extension': query, 'mime_type': mime_type, 'encoding': encoding or 'none', 'category': category}
            else:
                result = {'extension': query, 'mime_type': 'unknown', 'note': 'No MIME type found for this extension'}
        else:
            exts = mimetypes.guess_all_extensions(query)
            result = {'mime_type': query, 'extensions': exts if exts else [], 'note': '' if exts else 'No extensions found for this MIME type'}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
