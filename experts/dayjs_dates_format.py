# expert: dayjs_dates_format
# description: Inspired by Day.js — a 2KB immutable date library used in millions of JavaScript projects. Format dates, parse strings, and compute relative time.

def dayjs_dates_format(date_str='', format='full'):
    import datetime, json
    try:
        dt = datetime.date.fromisoformat(date_str.strip()) if date_str.strip() else datetime.date.today()
        fmts = {'full': dt.strftime('%a, %b %d %Y'), 'iso': dt.isoformat(), 'us': dt.strftime('%m/%d/%Y'), 'eu': dt.strftime('%d/%m/%Y')}
        return json.dumps({'status':'success','output_type':'json','data':{'formatted':fmts.get(format,fmts['full']),'iso':dt.isoformat()}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
