# expert: sentiment_analyze
# description: Inspired by Sentiment NLP library.

def sentiment_analyze(text=''):
    import re, json
    pos={'good','great','love','happy','best','amazing'}; neg={'bad','terrible','hate','worst','awful','sad'}
    try: w=set(re.findall(r'[a-zA-Z]+',text.lower())); s=len(w&pos)-len(w&neg); return json.dumps({'status':'success','output_type':'json','data':{'score':s,'label':'positive' if s>0 else 'negative' if s<0 else 'neutral'}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
