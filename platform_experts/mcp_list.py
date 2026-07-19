def mcp_list() -> str:
    """Отдаёт РЕАЛЬНОЕ состояние подключений MCP на этом устройстве.

    Правда живёт в ~/.extella_mcp/allowlist.json (его пишет mcp_connect).
    Тулбар раньше брал состояние из localStorage и захардкоженного списка,
    поэтому врал в обе стороны. Сопоставлять карточки каталога следует по pkg.
    """
    import json, os
    fp = os.path.expanduser("~/.extella_mcp/allowlist.json")
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