# expert: ci_configure
# description: NL-config: turns a plain-language description ("watch OpenAI, Anthropic, LangChain, post daily to #intel") into ci:config via a Qwen fine-tune. Writes KV ci:config (merges, without wiping out positioning). Returns the parsed config.

def ci_configure(text="", agent_id="", config_key="ci:config",
                 api_token="", api_base="https://api.extella.ai") -> dict:
    import json, urllib.request
    from pathlib import Path

    def _blank(v):
        return (not v) or str(v).startswith("{{")

    if _blank(text):
        return {"status": "error", "message": "empty request text"}
    if _blank(agent_id):
        agent_id = "__EXTELLA_AGENT__"
    if _blank(api_base):
        api_base = "https://api.extella.ai"
    if _blank(config_key):
        config_key = "ci:config"
    if _blank(api_token):
        try:
            from extella_expert_bridge import account_config
            api_token = account_config().get("auth_token", "")
        except Exception:
            api_token = ""
    if not api_token:
        return {"status": "error", "message": "no api_token"}

    headers = {"X-Auth-Token": api_token, "Content-Type": "application/json",
               "X-Profile-Id": "default", "X-Agent-Id": agent_id}

    def _post(path, body, t=180):
        req = urllib.request.Request(api_base.rstrip("/") + path,
                                     data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=t) as r:
            return json.loads(r.read().decode("utf-8"))

    prompt = (
        "You configure a competitor-intelligence monitoring process. From the user's request, extract what to monitor.\n"
        "USER REQUEST:\n" + str(text) + "\n\n"
        "Rules: infer GitHub repos as owner/name (e.g. OpenAI→openai/openai-python, Anthropic→anthropics/anthropic-sdk-python, "
        "LangChain→langchain-ai/langchain). Infer relevant subreddit names (no r/). Infer official blog/changelog RSS urls if you know them. "
        "If a Slack channel or 'slack' is mentioned set deliver=slack, else none.\n"
        "Return EXACTLY one JSON object and NOTHING else — no prose, no markdown fences, no comments:\n"
        '{"repos":[".../..."],"subreddits":["..."],"feeds":["https://..."],"deliver":"slack|email|none","deliver_client":"default"}'
    )
    try:
        resp = _post("/api/agent/run", {"agent_id": agent_id, "input": prompt, "store": False,
                                        "temperature": 0, "tool_choice": "none", "max_output_tokens": 1200})
    except Exception as e:
        return {"status": "error", "message": "agent/run: " + str(e)[:160]}

    # Responses API: output=[{type:message, content:[{text}]}]
    out_text = ""
    out = resp.get("output") if isinstance(resp, dict) else None
    if isinstance(out, list):
        parts = []
        for it in out:
            if isinstance(it, dict) and it.get("type") == "message":
                for c in it.get("content", []):
                    if isinstance(c, dict) and c.get("text"):
                        parts.append(c["text"])
        out_text = "\n".join(parts)
    if not out_text and isinstance(resp, dict):
        out_text = resp.get("output_text") or ""
    out_text = (out_text or "").strip()

    understood = {}
    try:
        s = out_text.find("{"); e = out_text.rfind("}")
        understood = json.loads(out_text[s:e + 1])
    except Exception:
        return {"status": "error", "message": "could not parse the model response", "raw": out_text[:300]}

    def _csv(v):
        if isinstance(v, list):
            return ",".join(str(x).strip() for x in v if str(x).strip())
        return str(v or "").strip()

    conf = {"repos": _csv(understood.get("repos")), "subreddits": _csv(understood.get("subreddits")),
            "feeds": _csv(understood.get("feeds")), "deliver": (understood.get("deliver") or "none"),
            "deliver_client": (understood.get("deliver_client") or "default")}

    # merge with the existing ci:config (don't overwrite positioning or non-empty prior values with empty ones)
    existing = {}
    try:
        cur = _post("/api/kv/get", {"key": config_key}, t=60).get("value")
        if cur:
            existing = json.loads(cur)
    except Exception:
        existing = {}
    merged = dict(existing)
    for k, v in conf.items():
        if v:
            merged[k] = v
    try:
        _post("/api/kv/set", {"key": config_key, "value": json.dumps(merged, ensure_ascii=False),
                              "description": "competitor-intel config (NL)"}, t=60)
    except Exception as e:
        return {"status": "error", "message": "kv/set: " + str(e)[:160], "understood": understood}

    return {"status": "success", "config_key": config_key, "config": merged, "understood": understood}
