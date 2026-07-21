$extens("include.py")
include("import json", [])
include("import re", [])
include("import urllib.request", [])

def p2d5_negotiate(disputed_json: str = "", counterparty_reply: str = "", round_no: int = 1,
                   our_side: str = "", counterparty: str = "", contract_subject: str = "") -> dict:
    """Готовит ЧЕРНОВИК аргументированного письма контрагенту для согласования договора.
    Вход: спорные пункты (JSON) и — для раундов >1 — последнее письмо контрагента.
    Зовёт платформенную Qwen (config.llm_agent_id/agent_id) + Гражданский кодекс из базы знаний (kp_ask).
    Отстаивает позицию нашей стороны (обычно малый бизнес/Заказчик) по каждому пункту со ссылками на статьи ГК.
    Возвращает {draft_email:{subject,body}, points:[...], is_draft:True}. Письмо ОТПРАВЛЯЕТ ЧЕЛОВЕК (контур согласования)."""
    import json, os, re, urllib.request
    from pathlib import Path

    # секреты — из config.json (не хардкод), честный fail при отсутствии
    cfg = {}
    wizard_root = Path(os.environ.get("EXTELLA_WIZARD_ROOT") or (Path.home() / "extella_wizard"))
    cf = wizard_root / "app" / "config.json"
    if cf.exists():
        try: cfg = json.loads(cf.read_text(encoding="utf-8"))
        except Exception: cfg = {}
    token = cfg.get("auth_token", "")
    agent_id = cfg.get("llm_agent_id") or cfg.get("agent_id", "")   # Qwen клиента; НИКОГДА Claude
    api = (cfg.get("api_base") or "https://api.extella.ai").rstrip("/")
    if not token or not agent_id:
        return {"status": "error", "message": "нет auth_token/agent_id в config.json"}

    # nohup-канон: {{placeholder}} подставляются только для явно переданных; фолбэки в коде
    def fb(v, d):
        s = str(v or "")
        return d if (not s or s.startswith("{{")) else s
    our  = fb(our_side, "наша компания (Заказчик, малый бизнес)")
    cp   = fb(counterparty, "Контрагент (Поставщик)")
    subj = fb(contract_subject, "договор поставки")
    reply = fb(counterparty_reply, "")
    try: rn = int(round_no)
    except Exception: rn = 1

    dj = fb(disputed_json, "")
    points = []
    if dj:
        try:
            pj = json.loads(dj)
            points = pj if isinstance(pj, list) else (pj.get("deviations") or pj.get("points") or [])
        except Exception:
            points = []

    # ── Гражданский кодекс из базы знаний (grounding) ──
    gk = ""
    try:
        topics = ("сроки оплаты по договору поставки; неустойка (пеня) за просрочку; гарантия качества товара и "
                  "гарантийный срок; подсудность и место рассмотрения споров; порядок и уведомление о расторжении; "
                  "ответственность сторон за нарушение обязательств")
        kb = json.dumps({"expert_name": "kp_ask",
                         "params": {"name": "Гражданский кодекс РК",
                                    "question": "Приведи применимые нормы и номера статей: " + topics},
                         "global": True}).encode()
        kreq = urllib.request.Request(api + "/api/expert/run", data=kb,
                                      headers={"X-Auth-Token": token, "Content-Type": "application/json",
                                               "X-Profile-Id": "default", "X-Agent-Id": "__EXTELLA_AGENT__"}, method="POST")
        with urllib.request.urlopen(kreq, timeout=120) as r:
            kr = json.loads(r.read().decode())
        ans = kr.get("result", "")
        if isinstance(ans, str):
            try: ans = json.loads(ans)
            except Exception: ans = {"answer": ans}
        a = (ans or {}).get("answer", "") if isinstance(ans, dict) else str(ans)
        if a and "база не найдена" not in str(a).lower() and len(str(a).strip()) > 40:
            gk = str(a)[:3500]
    except Exception:
        gk = ""

    SYS = ("Ты — представитель стороны «" + our + "» в переговорах по договору. Твоя задача — отстоять интересы этой "
           "стороны (часто это малый бизнес, не юристы) в переписке с контрагентом «" + cp + "». Пиши ДЕЛОВОЕ письмо: "
           "вежливо, но твёрдо и по существу. По каждому спорному пункту поясни, зачем условие нужно нашей стороне и на "
           "чём основана позиция"
           + (", со ссылкой на конкретные статьи Гражданского кодекса из предоставленных выдержек" if gk else "") + ". "
           "Не выдумывай номера статей — используй ТОЛЬКО предоставленные. Верни СТРОГО один JSON без markdown:\n"
           '{"draft_email":{"subject":"тема письма","body":"полный текст письма, готовый к отправке, с приветствием и подписью"},'
           '"points":[{"clause":"пункт","our_ask":"что просим","rationale":"почему кратко","law_ref":"статья ГК или пусто"}],'
           '"tone":"характер письма","is_draft":true}')

    if rn > 1 and reply:
        task = ("РАУНД " + str(rn) + ". Контрагент прислал возражения:\n\"" + reply[:3000] + "\"\n\n"
                "Наши спорные пункты и позиция:\n" + json.dumps(points, ensure_ascii=False)[:3000] + "\n\n"
                "Напиши письмо-ОТВЕТ: разбери возражения контрагента по пунктам. Где требование контрагента обоснованно — "
                "предложи разумный компромисс; где нет — твёрдо отстой позицию нашей стороны с опорой на закон. "
                "Цель: защитить интересы нашей стороны и при этом сохранить сделку.")
    else:
        task = ("РАУНД 1. Предмет: " + subj + ". Наши спорные пункты и желаемые условия:\n"
                + json.dumps(points, ensure_ascii=False)[:3500] + "\n\n"
                "Напиши ПЕРВОЕ письмо контрагенту: по каждому пункту изложи нашу позицию и обоснование. "
                "Тон — конструктивный, но принципиальный.")
    if gk:
        task += "\n\nВЫДЕРЖКИ ИЗ ГРАЖДАНСКОГО КОДЕКСА (база знаний):\n" + gk

    body = json.dumps({"agent_id": agent_id, "input": SYS + "\n\n" + task,
                       "run_timeout": 200, "store": False, "max_output_tokens": 3500}).encode()
    req = urllib.request.Request(api + "/api/agent/run", data=body,
                                 headers={"X-Auth-Token": token, "Content-Type": "application/json",
                                          "X-Profile-Id": "default", "X-Agent-Id": agent_id}, method="POST")
    last = ""
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
                res = json.loads(blob)
            except Exception:
                import ast
                res = ast.literal_eval(blob)
            if isinstance(res, dict):
                res.setdefault("is_draft", True)
                res["round"] = rn
                res["gk_grounded"] = bool(gk)
                return {"status": "success", **res}
        except Exception as e:
            last = str(e)[:160]
    return {"status": "error", "message": "LLM: " + last}
