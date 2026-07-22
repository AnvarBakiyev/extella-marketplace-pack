def mcp_list() -> str:
    """Отдаёт РЕАЛЬНОЕ состояние подключений MCP на этом устройстве.

    Правда живёт в платформенном каталоге данных Extella (его пишет mcp_connect).
    Тулбар раньше брал состояние из localStorage и захардкоженного списка,
    поэтому врал в обе стороны. Сопоставлять карточки каталога следует по pkg.
    """
    import json, os
    try:
        from extella_expert_bridge import locations
        fp = os.path.join(locations()["mcp_root"], "allowlist.json")
    except Exception:
        return json.dumps({"status":"error","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}, ensure_ascii=False)
    try:
        allow = json.load(open(fp))
    except Exception:
        allow = {}
    servers = []
    for k, v in (allow or {}).items():
        if not isinstance(v, dict):
            continue
        tools = v.get("tools") or []
        servers.append({
            "key": k,
            "title": v.get("title") or k,
            "pkg": v.get("pkg") or "",
            "count": len(tools),
            "tools": tools[:30],
        })
    servers.sort(key=lambda s: s["key"])
    return json.dumps({"status": "success", "count": len(servers), "servers": servers}, ensure_ascii=False)
