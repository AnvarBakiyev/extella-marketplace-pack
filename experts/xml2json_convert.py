# expert: xml2json_convert
# description: Inspired by xml2js — the standard Node.js XML-to-JSON converter. Parses XML into a nested JSON structure instantly.

def xml2json_convert(xml_text=''):
    import xml.etree.ElementTree as ET, json
    def elem_to_dict(el):
        d = dict(el.attrib)
        children = list(el)
        if children:
            for c in children:
                v = elem_to_dict(c)
                k = c.tag.split('}')[-1]
                d.setdefault(k, []).append(v) if isinstance(d.get(k), list) or k in d else d.update({k: v})
                if k in d and isinstance(d[k], list) is False and not isinstance(d[k], dict):
                    d[k] = [d[k], v] if not isinstance(d[k], list) else d[k]
        text = (el.text or '').strip()
        if text and not children: return text
        if text: d['_text'] = text
        return d if d else text or ''
    try:
        root = ET.fromstring(xml_text.strip())
        result = {root.tag.split('}')[-1]: elem_to_dict(root)}
        return json.dumps({'status':'success','output_type':'text','data':json.dumps(result, indent=2)})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
