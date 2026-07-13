# expert: number_base_converter_convert
# description: Converts an integer from one base to all other bases. Params: number (string representation of number), from_base (2/8/10/16, default 10). Returns JSON with output_type json showing decimal, binary, o

def number_base_converter_convert(number='0', from_base='10'):
    import json
    try:
        n = int(number.strip(), int(from_base))
        result = {
            'decimal':     str(n),
            'binary':      bin(n)[2:],
            'octal':       oct(n)[2:],
            'hexadecimal': hex(n)[2:].upper()
        }
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
