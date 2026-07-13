# expert: csv_json_converter_convert
# description: Converts CSV to JSON array or JSON array to CSV. Params: input_text (CSV or JSON string), direction (csv_to_json or json_to_csv). Returns JSON with output_type text containing the converted data.

def csv_json_converter_convert(input_text='', direction='csv_to_json'):
    import csv, json, io
    try:
        if direction == 'csv_to_json':
            reader = csv.DictReader(io.StringIO(input_text.strip()))
            rows = list(reader)
            result = json.dumps(rows, indent=2, ensure_ascii=False)
        else:
            data = json.loads(input_text)
            if not isinstance(data, list): data = [data]
            output = io.StringIO()
            if data:
                writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
                writer.writeheader()
                writer.writerows(data)
            result = output.getvalue()
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
