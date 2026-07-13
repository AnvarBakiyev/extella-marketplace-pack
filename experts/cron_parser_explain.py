# expert: cron_parser_explain
# description: Inspired by node-cron and crontab.guru — parse, validate, and explain cron expressions used in schedulers, GitHub Actions, and Linux crontab.

def cron_parser_explain(expression=''):
    import json
    parts = {'minute':'0-59','hour':'0-23','day':'1-31','month':'1-12','weekday':'0-6 (Sun=0)'}
    labels = ['Minute','Hour','Day of month','Month','Day of week']
    try:
        fields = expression.strip().split()
        if len(fields) != 5: return json.dumps({'status':'error','message':'Cron needs 5 fields: min hour dom month dow'})
        desc = []
        for i, (f, lbl) in enumerate(zip(fields, labels)):
            desc.append({'field': lbl, 'value': f, 'range': list(parts.values())[i]})
        human = 'At minute '+fields[0]+' of hour '+fields[1]+', day '+fields[2]+', month '+fields[3]+', weekday '+fields[4]
        return json.dumps({'status':'success','output_type':'json','data':{'expression':expression,'human':human,'fields':desc}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
