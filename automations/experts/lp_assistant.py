# expert: lp_assistant
# description: Contract agent helper: answers the user's questions about how the contract agent works and how to customize it. Knows the pack architecture (experts, config, flow) and guides simple changes in the panel or deeper changes via the main Extella chat / Builder. Uses the platform Qwen agent.

def lp_assistant(question: str = "", history: str = "") -> str:
    import json, os, urllib.request

    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    token = cfg.get("auth_token", "")
    agent_id = cfg.get("llm_agent_id") or cfg.get("agent_id", "")
    api = (cfg.get("api_base") or "https://api.extella.ai").rstrip("/")
    if not token or not agent_id:
        return json.dumps({"status": "error", "answer": "Не настроен доступ к Extella (auth_token/agent_id)."}, ensure_ascii=False)

    q = question if question and not str(question).startswith("{{") else ""
    if not q:
        return json.dumps({"status": "error", "answer": "Задайте вопрос."}, ensure_ascii=False)
    hist = history if history and not str(history).startswith("{{") else ""

    std = cfg.get("contract_standards") or {}
    parties = cfg.get("contract_parties") or {}

    ARCH = (
        "КАК УСТРОЕНА ПАНЕЛЬ (это форма, а НЕ чат-анализ — не описывай несуществующий чат-флоу):\n"
        "5 вкладок: «Настройка», «Клиенты», «Разбор договора», «Согласование», «Помощник».\n"
        "  • «Разбор договора»: пользователь ВСТАВЛЯЕТ текст договора или загружает файл (.txt/.docx) и жмёт «Разобрать договор». "
        "Появляется блок «Результат разбора»: статус риска, число отклонений, СПОРНЫЕ ПУНКТЫ и КНОПКИ скачивания "
        "«⬇ Реестр рисков (Excel)», «⬇ Протокол разногласий (Word)», «⬇ Сводка (txt)» + кнопка «📂 Открыть папку с документами».\n"
        "  • «Согласование»: по спорным пунктам агент готовит письмо контрагенту (кнопка «Подготовить письмо»); на возражения — раунд 2.\n"
        "ИЗВЕСТНЫЕ РЕШЕНИЯ (используй их, не выдумывай другие причины):\n"
        "  • Документы не скачиваются: файлы формируются ЛОКАЛЬНО в папке документов плагина Extella Contract Agent. "
        "Нажми кнопку «📂 Открыть папку с документами» под кнопками скачивания — откроется папка с готовыми Excel/Word/txt. "
        "Кнопки ⬇ активны только ПОСЛЕ того, как разбор завершился и показал результат.\n\n"
        "УСТРОЙСТВО АГЕНТА «Юрист по договорам» (Extella), чтобы ты мог точно подсказать пользователю, как его изменить:\n"
        "Два контура:\n"
        "1) РАЗБОР договора. Оркестратор p2d4_run_pipeline вызывает:\n"
        "   • p2d4_evaluate_contract_batch — ИИ-анализ по 10-пунктному чек-листу (стороны, предмет, цена/оплата, сроки, "
        "санкции, расторжение, интеллектуальная собственность, конфиденциальность, применимое право, подписи), сверка со "
        "стандартами компании и с Гражданским кодексом РК (через kp_ask, база знаний). Внутри — CHECKLIST и STANDARDS.\n"
        "   • p2d4_generate_document_package — собирает Реестр рисков (Excel), Протокол разногласий (Word), Сводку (txt).\n"
        "2) СОГЛАСОВАНИЕ. p2d5_negotiate — готовит письмо контрагенту по спорным пунктам со ссылками на статьи ГК; "
        "раунд>1 — ответ на возражения (компромисс где уместно, твёрдость где на кону интересы). Черновик — отправляет человек.\n"
        "Уведомления: lp_notify (Telegram руководителю). Модель — платформенный Qwen (config.agent_id).\n"
        "КАНАЛЫ СВЯЗИ (агент сам отправляет — человек подтверждает кнопкой «Отправить»):\n"
        "   • Почта: lp_email_send (SMTP; config smtp_host/smtp_port/smtp_user/smtp_pass/email_from). Агент шлёт письма контрагенту и сводки.\n"
        "   • WhatsApp: lp_wa_send + lp_wa_state (GreenAPI; config greenapi_id/greenapi_token).\n"
        "   • Telegram: lp_notify (config telegram_bot_token/telegram_chat_id).\n"
        "КЛИЕНТЫ/КОНТРАГЕНТЫ: config.contract_clients (имя/почта/телефон/компания), вкладка «Клиенты» — агент шлёт им письма и сообщения.\n"
        "ПОЛИТИКИ КОМПАНИИ: config.company_policies — загруженные документы (.txt/.docx), которым агент следует при разборе (вместе с ГК). Загрузка — вкладка «Настройка».\n"
        "НАСТРОЙКИ (меняются в панели, вкладка «Настройка», без программирования):\n"
        "   • Стандарты компании: config.contract_standards = {pay, pen, war, jur} (срок оплаты, неустойка, гарантия, подсудность).\n"
        "   • Стороны: config.contract_parties = {our_side, counterparty}.\n"
        "   • Каналы (почта/WhatsApp/Telegram), клиенты, политики-файлы — см. выше.\n"
        "   • База знаний «Гражданский кодекс РК» — ставится в один клик в разделе «Базы знаний».\n"
        "ГЛУБОКИЕ ИЗМЕНЕНИЯ (логика: пункты чек-листа, тон писем, новые виды документов, новые шаги процесса) — "
        "делаются в ОСНОВНОМ ЧАТЕ Extella через Строителя процессов: пользователь открывает главный чат, называет нужный "
        "эксперт (например p2d4_evaluate_contract_batch или p2d5_negotiate) и описывает желаемое изменение словами; "
        "Строитель правит эксперта и перепрошивает его. Продовые изменения — только так (безопасно).\n"
        "Текущие стандарты пользователя: " + json.dumps(std, ensure_ascii=False) + "; стороны: " + json.dumps(parties, ensure_ascii=False) + "."
    )
    SYS = (
        "Ты — встроенный помощник по агенту «Юрист по договорам» на платформе Extella. Отвечай кратко, по-деловому, по-русски, "
        "конкретными шагами. ТВОИ ГРАНИЦЫ (соблюдай строго):\n"
        "1) Умеешь: объяснить, как агент работает, и как его настроить/изменить (настройки в панели vs логика через Строителя).\n"
        "2) НЕ выдумывай. Если чего-то не знаешь точно или это технический сбой, который ты не можешь проверить в рантайме — "
        "честно скажи, что не видишь этого, и направь: известное решение из инструкции ниже, либо в основной чат Extella / поддержку. "
        "НИКОГДА не описывай флоу, которого нет (у панели ФОРМА во вкладке «Разбор», а не чат-анализ).\n"
        "3) Настройка (стандарты, стороны, каналы, база знаний, клиенты, политики) → вкладка «Настройка»/«Клиенты» этой панели.\n"
        "4) Логика (чек-лист, тон писем, новые документы/шаги) → основной чат Extella, Строитель; подскажи, какой эксперт назвать.\n"
        "Верни СТРОГО JSON: "
        '{"answer":"...", "action":"panel|builder|folder|none", "expert":"имя эксперта или пусто"}. '
        "action=folder — если ответ про «открыть папку с документами»."
        "\n\n" + ARCH
    )
    user = (("Предыдущий диалог:\n" + hist + "\n\n") if hist else "") + "Вопрос пользователя: " + q

    body = json.dumps({"agent_id": agent_id, "input": SYS + "\n\n" + user,
                       "run_timeout": 120, "store": False, "max_output_tokens": 1200}).encode()
    req = urllib.request.Request(api + "/api/agent/run", data=body,
                                 headers={"X-Auth-Token": token, "Content-Type": "application/json",
                                          "X-Profile-Id": "default", "X-Agent-Id": agent_id}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            out = json.loads(r.read().decode())
        content = "".join(c.get("text", "") for it in (out.get("output") or []) if it.get("type") == "message"
                          for c in (it.get("content") or []) if c.get("type") == "output_text")
        import re
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                res = json.loads(m.group(0))
                res.setdefault("status", "success")
                return json.dumps(res, ensure_ascii=False)
            except Exception:
                pass
        return json.dumps({"status": "success", "answer": content.strip()[:1500] or "—", "action": "none", "expert": ""}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "answer": "Ошибка обращения к модели: " + str(e)[:150]}, ensure_ascii=False)
