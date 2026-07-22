# expert: agent_forge
# description: Собирает агента из роли и выбранных сервисов. Параметры: agent_id, role_id, tools_csv

def agent_forge(agent_id="", role_id="universal", tools_csv="") -> str:
    import json, ssl, urllib.error, urllib.request
    def err(message):
        return json.dumps({"status":"error","message":message}, ensure_ascii=False)
    agent_id = "" if (not agent_id or str(agent_id).startswith("{{")) else str(agent_id).strip()
    role_id = "universal" if (not role_id or str(role_id).startswith("{{")) else str(role_id).strip()
    tools_csv = "" if (not tools_csv or str(tools_csv).startswith("{{")) else str(tools_csv).strip()
    if not agent_id.startswith("agent_"):
        return err("нужен ID агента-копии (agent_...). Создайте копию базового агента в Extella и вставьте её ID.")
    try:
        from extella_expert_bridge import account_config
        token = account_config().get("auth_token", "")
    except Exception:
        token = ""
    if not token:
        return err("нет токена текущего аккаунта (config.json)")

    services = {
        "svc_currency":"курсы валют и пересчёт сумм",
        "svc_crypto":"текущие цены криптовалют",
        "svc_weather":"погода в любом городе",
        "svc_translate":"перевод текста между языками",
        "svc_wiki":"справка из Википедии",
        "svc_github":"данные о репозитории GitHub",
        "svc_ipgeo":"страна, город и провайдер по IP-адресу",
        "svc_qr":"QR-код из ссылки или текста",
    }
    selected = [item.strip() for item in tools_csv.split(",") if item.strip()]
    service_names = [item for item in selected if item in services]
    mcp_keys = [item.split(":", 1)[1] for item in selected if item.startswith("mcpx:") and ":" in item]
    if role_id == "universal" and not service_names and not mcp_keys:
        return err("отметьте хотя бы одно умение")

    context = ssl.create_default_context()
    def api(path, payload, scope="__EXTELLA_AGENT__"):
        headers = {"Content-Type":"application/json","X-Auth-Token":token,"X-Profile-Id":"default","X-Agent-Id":scope}
        request = urllib.request.Request("https://api.extella.ai"+path, data=json.dumps(payload).encode(), headers=headers)
        try:
            return json.loads(urllib.request.urlopen(request, timeout=60, context=context).read())
        except urllib.error.HTTPError as error:
            return {"_http":error.code}
        except Exception as error:
            return {"_err":str(error)[:100]}

    role_name = "Универсальный помощник"
    if role_id != "universal":
        response = api("/api/expert/run", {"expert_name":"agent_flash_role","params":{"agent_id":agent_id,"role_id":role_id},"global":True})
        output = response.get("result") or response.get("output") or response
        if isinstance(output, str):
            try: output = json.loads(output)
            except Exception: pass
        if not (isinstance(output, dict) and output.get("status") == "success"):
            return err((output.get("message") if isinstance(output, dict) else "") or "не удалось назначить роль")
        role_name = output.get("name") or role_id
    else:
        abilities = ["- "+services[name] for name in service_names]
        if mcp_keys:
            abilities.append("- инструменты подключённых MCP-серверов ("+", ".join(mcp_keys)+") через mcp_call")
        instruction = (
            "Ты — универсальный AI-помощник на платформе Extella. Помогаешь по-русски: "
            "деловым, спокойным и уважительным тоном, без воды и выдумок.\n\n"
            "Используй подключённые инструменты только когда они подходят задаче и отвечай по "
            "их фактическим данным. Если данных не хватает или инструмент не отвечает — честно "
            "скажи об этом.\n"+"\n".join(abilities)
        )
        updated = api("/api/agent/update", {"agent_id":agent_id,"instructions":instruction})
        if isinstance(updated, dict) and updated.get("_http") == 404:
            return err("агент с таким ID не найден — проверьте ID копии агента")
        if isinstance(updated, dict) and (updated.get("_err") or updated.get("_http")):
            return err("не удалось настроить агента ("+str(updated.get("_err") or updated.get("_http"))+")")

    provisioned = 0
    to_copy = list(service_names) + (["mcp_call"] if mcp_keys else [])
    for name in to_copy:
        source = api("/api/expert/get", {"name":name,"global":True})
        code = source.get("expert_code") if isinstance(source, dict) else None
        if not code:
            continue
        saved = api("/api/expert/save", {"name":name,"description":source.get("expert_description",name),"code":code,"kwargs":{},"cspl":"fython"}, agent_id)
        if isinstance(saved, dict) and saved.get("status") == "success":
            provisioned += 1
    return json.dumps({"status":"success","agent_id":agent_id,"role":role_name,"tools":provisioned}, ensure_ascii=False)
