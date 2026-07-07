# expert: kp_ask
# description: База знаний: отвечает на вопрос ПО загруженным документам (RAG, локальный поиск + синтез). Параметры: name, question.

def kp_ask(name="", question="") -> str:
    import os, re, json, math, urllib.request
    if not name or name.startswith("{{"): return json.dumps({"status":"error","message":"нужно имя базы"}, ensure_ascii=False)
    if not question or question.startswith("{{"): return json.dumps({"status":"error","message":"нужен вопрос"}, ensure_ascii=False)
    d=os.path.expanduser("~/.extella_kp"); safe=re.sub(r"[^a-zA-Z0-9_]","_",name)
    fp=os.path.join(d,safe+".json")
    if not os.path.exists(fp): return json.dumps({"status":"error","message":"база не найдена — сначала загрузи документы"}, ensure_ascii=False)
    store=json.load(open(fp))["chunks"]
    def embed(t):
        req=urllib.request.Request("http://localhost:11434/api/embeddings", data=json.dumps({"model":"nomic-embed-text","prompt":"search_query: "+t}).encode(), headers={"Content-Type":"application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=60).read())["embedding"]
    try: qe=embed(question)
    except Exception: return json.dumps({"status":"error","message":"Ollama/эмбеддинг недоступен"}, ensure_ascii=False)
    def cos(a,b):
        s=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
        return s/(na*nb) if na and nb else 0.0
    ranked=sorted(store, key=lambda c: cos(qe,c["emb"]), reverse=True)[:8]
    ctx="\n\n".join("["+c["src"]+"] "+c["text"] for c in ranked)
    prompt="Ответь на вопрос ТОЛЬКО по этим фрагментам документов. Если ответа в них нет — честно скажи, что в документах этого нет. Кратко.\n\nФРАГМЕНТЫ:\n"+ctx+"\n\nВОПРОС: "+question
    tok=""
    try: tok=json.load(open(os.path.expanduser("~/extella_wizard/app/config.json"))).get("auth_token","")
    except Exception: pass
    if not tok: return json.dumps({"status":"error","message":"нет токена для синтеза (config.json)"}, ensure_ascii=False)
    H={"Content-Type":"application/json","X-Auth-Token":tok,"X-Profile-Id":"default","X-Agent-Id":"agent_extella_default"}
    try:
        req=urllib.request.Request("https://api.extella.ai/api/agent/run", data=json.dumps({"input":prompt,"agent_id":"agent_XwZBKvd8dD70jKvW4WrZm","run_timeout":120}).encode(), headers=H)
        r=json.loads(urllib.request.urlopen(req, timeout=150).read())
        parts=[]
        for it in (r.get("output") or []):
            if it.get("type")=="message":
                for c in (it.get("content") or []):
                    if c.get("type") in ("output_text","text") and c.get("text"): parts.append(c["text"])
        ans="\n".join(parts) or "Не удалось получить ответ."
        for _pat in ["[\ue000-\uf8ff]", "\\\\u[0-9a-fA-F]{4}", "turn\\d+\\w*"]: ans=re.sub(_pat, "", ans)
        ans=ans.strip()
    except Exception as e:
        return json.dumps({"status":"error","message":"синтез не удался: "+str(e)[:80]}, ensure_ascii=False)
    srcs=[]
    for c in ranked:
        if c["src"] not in srcs: srcs.append(c["src"])
    return json.dumps({"status":"success","answer":ans,"sources":srcs}, ensure_ascii=False)