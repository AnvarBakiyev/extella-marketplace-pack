# expert: text_case_converter_convert
# description: Converts text to the specified case convention. Params: text (input string), target_case (camelCase/PascalCase/snake_case/kebab-case/SCREAMING_SNAKE/lowercase/UPPERCASE/Title Case/dot.case). Returns J

def text_case_converter_convert(text='', target_case='camelCase'):
    import re, json
    try:
        s = re.sub(r'([A-Z])', r' \1', text)
        words = [w for w in re.split(r'[\s_\-\.]+', s.strip()) if w]
        if not words:
            return json.dumps({'status': 'success', 'output_type': 'text', 'data': ''})
        if target_case == 'camelCase':
            result = words[0].lower() + ''.join(w.capitalize() for w in words[1:])
        elif target_case == 'PascalCase':
            result = ''.join(w.capitalize() for w in words)
        elif target_case == 'snake_case':
            result = '_'.join(w.lower() for w in words)
        elif target_case == 'kebab-case':
            result = '-'.join(w.lower() for w in words)
        elif target_case == 'SCREAMING_SNAKE':
            result = '_'.join(w.upper() for w in words)
        elif target_case == 'lowercase':
            result = ' '.join(w.lower() for w in words)
        elif target_case == 'UPPERCASE':
            result = ' '.join(w.upper() for w in words)
        elif target_case == 'dot.case':
            result = '.'.join(w.lower() for w in words)
        else:
            result = ' '.join(w.capitalize() for w in words)
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
