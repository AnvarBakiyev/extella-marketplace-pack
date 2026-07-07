# expert: cap_local_ask
# description: Спросить локальную модель через Ollama (данные не уходят в облако)

def cap_local_ask(model="", question="", system="") -> str:
    # Агент спрашивает ЛОКАЛЬНУЮ модель (через API Ollama на устройстве). Данные не уходят в облако.
    import json, urllib.request
    if not model or model.startswith("{{"): return json.dumps({"status":"error","message":"нужен model"}, ensure_ascii=False)
    if not question or question.startswith("{{"): return json.dumps({"status":"error","message":"нужен question"}, ensure_ascii=False)
    body = {"model": model, "prompt": question, "stream": False, "options": {"num_predict": 512}}
    if system and not system.startswith("{{"): body["system"] = system
    try:
        req = urllib.request.Request("http://localhost:11434/api/generate", data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=180).read())
        return json.dumps({"status":"success","model":model,"answer":(r.get("response") or "").strip()[:4000]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status":"error","message":"локальная модель не ответила (запущен ли Ollama?): "+str(e)[:120]}, ensure_ascii=False)