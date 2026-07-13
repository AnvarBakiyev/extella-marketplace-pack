# expert: file_size_converter_convert
# description: Converts file sizes between all units. Params: value (number), unit (B/KB/MB/GB/TB/PB/KiB/MiB/GiB). Returns JSON with output_type json showing all equivalent values.

def file_size_converter_convert(value='1024', unit='MB'):
    import json
    try:
        v = float(value)
        to_bytes = {'B':1,'KB':1e3,'MB':1e6,'GB':1e9,'TB':1e12,'PB':1e15,'KiB':1024,'MiB':1024**2,'GiB':1024**3,'TiB':1024**4}
        u = unit.strip()
        if u not in to_bytes: return json.dumps({'status':'error','message':'Unknown unit '+unit})
        bytes_val = v * to_bytes[u]
        def fmt(x):
            if x >= 1e15: return round(x/1e15, 4)
            if x >= 1e12: return round(x/1e12, 4)
            if x >= 1e9: return round(x/1e9, 4)
            if x >= 1e6: return round(x/1e6, 4)
            if x >= 1e3: return round(x/1e3, 4)
            return round(x, 4)
        result = {'bytes': round(bytes_val), 'kilobytes': round(bytes_val/1e3,4), 'megabytes': round(bytes_val/1e6,6), 'gigabytes': round(bytes_val/1e9,9), 'terabytes': round(bytes_val/1e12,12), 'kibibytes': round(bytes_val/1024,4), 'mebibytes': round(bytes_val/1024**2,6), 'gibibytes': round(bytes_val/1024**3,9)}
        return json.dumps({'status':'success','output_type':'json','data':result})
    except Exception as e:
        return json.dumps({'status':'error','message':str(e)})
