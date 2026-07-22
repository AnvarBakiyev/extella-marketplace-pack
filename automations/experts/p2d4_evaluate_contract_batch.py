$extens("include.py")
include("import json", [])
include("import re", [])
include("import urllib.request", [])
include("import concurrent.futures", [])

def p2d4_evaluate_contract_batch(input_path: str = "", output_path: str = "") -> dict:
    """Настоящий ИИ-анализ договоров: на КАЖДЫЙ договор зовёт платформенную Qwen (config.agent_id)
    и просит разбор по 10-пунктному чек-листу с ДОСЛОВНЫМИ цитатами, отклонениями от стандартных
    условий, уровнем риска и предлагаемыми правками. Параллельно (concurrent.futures), cspl=fython
    (без parallel_task-обработчика). Секреты — из the current device's platform-native Extella account config (не хардкод).
    Вход: JSON-список записей договоров (или {records:[...]}). Выход: JSON {summary, records:[... + ai_analysis]}."""
    import json, re, os, urllib.request, concurrent.futures
    from pathlib import Path

    # 1) вход
    p = Path(str(input_path)).expanduser()
    if not str(input_path) or not p.exists():
        return {"status": "error", "message": "input_path не найден: " + str(input_path)}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "message": "вход не JSON: " + str(e)[:120]}
    records = raw if isinstance(raw, list) else (raw.get("records") or [])
    if not records:
        return {"status": "error", "message": "нет записей договоров во входе"}

    # 2) токен + Qwen-агент из конфига (секреты не хардкодим; честный fail при отсутствии)
    try:
        from extella_expert_bridge import account_config
        cfg = account_config()
    except Exception:
        cfg = {}
    token = cfg.get("auth_token", "")
    agent_id = cfg.get("llm_agent_id") or cfg.get("agent_id", "")   # Qwen клиента; НИКОГДА Claude
    api_base = (cfg.get("api_base") or "https://api.extella.ai").rstrip("/")
    if not token or not agent_id:
        return {"status": "error", "message": "нет auth_token/agent_id в config.json — ИИ-анализ невозможен"}

    CHECKLIST = [
        {"id": "parties", "name": "Стороны договора"},
        {"id": "subject", "name": "Предмет договора"},
        {"id": "price", "name": "Цена и порядок оплаты"},
        {"id": "terms", "name": "Сроки исполнения"},
        {"id": "penalties", "name": "Санкции и штрафы"},
        {"id": "termination", "name": "Расторжение договора"},
        {"id": "ip", "name": "Интеллектуальная собственность"},
        {"id": "conf", "name": "Конфиденциальность"},
        {"id": "law", "name": "Применимое право и подсудность"},
        {"id": "signatures", "name": "Подписи и реквизиты"},
    ]
    STANDARDS = {
        "Срок оплаты": "не более 30 дней с момента приёмки",
        "Неустойка": "не менее 0,1% в день от суммы просрочки",
        "Гарантийный срок": "не менее 12 месяцев",
        "Уведомление о расторжении": "не менее 30 дней",
        "Конфиденциальность": "срок не менее 3 лет",
        "Подсудность": "суд по месту нахождения заказчика",
    }
    # стандарты из панели (config.contract_standards) переопределяют дефолты
    _cs = cfg.get("contract_standards") or {}
    if isinstance(_cs, dict):
        if _cs.get("pay"): STANDARDS["Срок оплаты"] = _cs["pay"]
        if _cs.get("pen"): STANDARDS["Неустойка"] = _cs["pen"]
        if _cs.get("war"): STANDARDS["Гарантийный срок"] = _cs["war"]
        if _cs.get("jur"): STANDARDS["Подсудность"] = _cs["jur"]
    # политики/стандарты компании из загруженных файлов (config.company_policies) — доп. контекст
    policies_ctx = ""
    _pol = cfg.get("company_policies") or []
    try:
        if isinstance(_pol, list):
            policies_ctx = "\n\n".join((str(p.get("name", "")) + ":\n" + str(p.get("text", "")))
                                       for p in _pol if isinstance(p, dict))[:4000]
        elif isinstance(_pol, str):
            policies_ctx = _pol[:4000]
    except Exception:
        policies_ctx = ""
    # ── ТРЕТИЙ ИСТОЧНИК: базы знаний (kp_ask) — законы + свои базы пользователя ──
    # Список берём из config: legal_bases (готовые базы законов) + knowledge_bases (свои).
    # graceful: база недоступна → пропускаем; работаем с тем, что ответило.
    bases = list(cfg.get("legal_bases") or ["Гражданский кодекс РК"])
    for _b in (cfg.get("knowledge_bases") or []):
        nm = _b.get("name") if isinstance(_b, dict) else _b
        if nm and nm not in bases:
            bases.append(nm)
    QUESTION = ("Нормы и правила по договорам поставки и услуг: сроки оплаты, неустойка за просрочку, гарантийные "
                "обязательства, порядок расторжения, подсудность, ответственность сторон. Приведи конкретику "
                "(номера статей/пунктов и краткое содержание).")
    def _ask_base(base):
        try:
            kb = json.dumps({"expert_name": "kp_ask", "params": {"name": base, "question": QUESTION},
                             "global": True}).encode()
            kreq = urllib.request.Request(api_base + "/api/expert/run", data=kb,
                                          headers={"X-Auth-Token": token, "Content-Type": "application/json",
                                                   "X-Profile-Id": "default", "X-Agent-Id": "__EXTELLA_AGENT__"}, method="POST")
            with urllib.request.urlopen(kreq, timeout=120) as r:
                kres = json.loads(r.read().decode())
            kraw = kres.get("result", "")
            if isinstance(kraw, str):
                try: kraw = json.loads(kraw)
                except Exception:
                    import ast as _ast
                    try: kraw = _ast.literal_eval(kraw)
                    except Exception: kraw = {}
            ans = (kraw or {}).get("answer", "") if isinstance(kraw, dict) else ""
            if ans and "не найден" not in str(ans).lower() and len(str(ans).strip()) > 40:
                return str(ans)[:2500]
        except Exception:
            pass
        return ""
    parts = []; bases_used = []
    for base in bases[:4]:
        a = _ask_base(base)
        if a:
            parts.append("[" + str(base) + "]\n" + a)
            bases_used.append(str(base))
    gk_context = ("\n\n".join(parts))[:5000]

    SYS = (
        "Ты — юридический аналитик. Проанализируй ОДИН договор по чек-листу, стандартным условиям компании"
        + (" и выдержкам из баз знаний (законы, стандарты)" if gk_context else "") + ". "
        "Верни СТРОГО один JSON-объект без markdown и пояснений:\n"
        '{"criteria":[{"id":"<id из чек-листа>","status":"ok|risk|missing",'
        '"quote":"ДОСЛОВНАЯ цитата из текста договора (или пусто)","section":"№ пункта/раздел или —",'
        '"comment":"кратко в чём риск/что ок"}],'
        '"deviations":[{"condition":"<название>","standard":"<стандарт>","found":"что в договоре",'
        '"severity":"low|medium|high","law_ref":"статья ГК если применима, иначе пусто"}],'
        '"risk_level":"low|medium|high","summary":"1-2 предложения итога",'
        '"suggested_edits":["конкретная правка формулировки (со ссылкой на статью ГК, если есть основание)", "..."]}\n'
        "ЦИТАТЫ бери ДОСЛОВНО из текста, ничего не выдумывай; если пункта нет — status=missing, quote пустая. "
        "Ссылайся на статьи ГК ТОЛЬКО из предоставленных выдержек — не выдумывай номера статей."
    )

    def analyze_one(rec):
        text = " ".join(str(v) for v in rec.values() if isinstance(v, str) and len(str(v)) > 20)[:14000]
        if not text.strip():
            return {"_rec": rec, "analysis": {}, "error": "пустой текст договора"}
        user = ("ЧЕК-ЛИСТ:\n" + json.dumps(CHECKLIST, ensure_ascii=False)
                + "\n\nСТАНДАРТНЫЕ УСЛОВИЯ КОМПАНИИ:\n" + json.dumps(STANDARDS, ensure_ascii=False)
                + (("\n\nПОЛИТИКИ И СТАНДАРТЫ КОМПАНИИ (загруженные документы):\n" + policies_ctx) if policies_ctx else "")
                + (("\n\nВЫДЕРЖКИ ИЗ БАЗ ЗНАНИЙ (законы и стандарты; в квадратных скобках — название базы):\n" + gk_context) if gk_context else "")
                + "\n\nТЕКСТ ДОГОВОРА:\n" + text)
        body = json.dumps({"agent_id": agent_id, "input": SYS + "\n\n" + user,
                           "run_timeout": 200, "store": False, "max_output_tokens": 4000}).encode()
        req = urllib.request.Request(api_base + "/api/agent/run", data=body,
                                     headers={"X-Auth-Token": token, "Content-Type": "application/json",
                                              "X-Profile-Id": "default", "X-Agent-Id": agent_id}, method="POST")
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=230) as r:
                    out = json.loads(r.read().decode())
                content = "".join(c.get("text", "") for it in (out.get("output") or [])
                                  if it.get("type") == "message"
                                  for c in (it.get("content") or []) if c.get("type") == "output_text")
                m = re.search(r"\{.*\}", content, re.S)
                blob = m.group(0) if m else content
                try:
                    analysis = json.loads(blob)
                except Exception:
                    import ast
                    analysis = ast.literal_eval(blob)
                if isinstance(analysis, dict):
                    return {"_rec": rec, "analysis": analysis, "error": None}
                return {"_rec": rec, "analysis": {}, "error": "ответ не JSON-объект"}
            except Exception as e:
                last = str(e)[:150]
        return {"_rec": rec, "analysis": {}, "error": "LLM: " + last}

    # 3) параллельно по договорам
    results = []
    workers = min(4, max(1, len(records)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(analyze_one, records):
            results.append(res)

    # 4) агрегаты + запись
    out_records, risk_counts, errors = [], {"low": 0, "medium": 0, "high": 0}, 0
    for res in results:
        a = res.get("analysis") or {}
        rl = str(a.get("risk_level", "")).lower()
        if rl in risk_counts: risk_counts[rl] += 1
        if res.get("error"): errors += 1
        rec = dict(res.get("_rec") or {})
        rec["ai_analysis"] = a
        if res.get("error"): rec["ai_error"] = res["error"]
        out_records.append(rec)

    doc = {"summary": {"total_count": len(records), "risk_breakdown": risk_counts,
                       "high_risk_contracts": risk_counts["high"], "errors": errors},
           "records": out_records}
    Path(str(output_path)).write_text(json.dumps(doc, ensure_ascii=False, default=str), encoding="utf-8")
    return {"status": "success", "output_path": str(output_path), "total_count": len(records),
            "high_risk_contracts": risk_counts["high"], "analysis_errors": errors,
            "gk_grounded": bool(gk_context), "bases_used": bases_used}
