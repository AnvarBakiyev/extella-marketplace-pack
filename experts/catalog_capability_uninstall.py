# expert: catalog_capability_uninstall
# description: Безопасно удаляет установленную из каталога модель Ollama или подключение MCP; посторонние процессы не останавливает.
# params: kind, ref, method

def catalog_capability_uninstall(kind="", ref="", method="") -> str:
    import json
    import os
    import urllib.error
    import urllib.request
    from pathlib import Path

    kind = str(kind or "").strip().lower()
    ref = str(ref or "").strip()
    method = str(method or "").strip().lower()
    if not kind or not ref:
        return json.dumps({"status": "error", "device_removed": False, "message": "Нужны kind и ref."}, ensure_ascii=False)
    if not method:
        method = {"model": "ollama", "mcp": "mcp_connect", "service": "mcp_connect"}.get(kind, "")

    if method == "ollama":
        if "nomic-embed-text" in ref.lower():
            return json.dumps({
                "status": "error",
                "device_removed": False,
                "message": "nomic-embed-text используется базами знаний Extella; автоматически не удаляю.",
            }, ensure_ascii=False)

        def names():
            try:
                with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=6) as opened:
                    return [str(item.get("name") or "") for item in json.load(opened).get("models", [])]
            except Exception:
                return None

        installed = names()
        if installed is None:
            return json.dumps({
                "status": "error",
                "device_removed": False,
                "message": "Ollama не отвечает; удаление модели не подтверждено.",
            }, ensure_ascii=False)
        exact = ref if ref in installed else next(
            (name for name in installed if name.startswith(ref + ":") or name.split(":", 1)[0] == ref),
            "",
        )
        if not exact:
            return json.dumps({
                "status": "success",
                "device_removed": True,
                "removed": False,
                "message": "Модели уже нет на устройстве.",
            }, ensure_ascii=False)
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/delete",
            data=json.dumps({"model": exact, "name": exact}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as opened:
                opened.read()
        except Exception:
            return json.dumps({
                "status": "error",
                "device_removed": False,
                "message": "Ollama не подтвердил удаление модели.",
            }, ensure_ascii=False)
        remaining = names()
        if remaining is None or exact in remaining:
            return json.dumps({
                "status": "error",
                "device_removed": False,
                "message": "После удаления модель всё ещё видна; запись сохранена.",
            }, ensure_ascii=False)
        return json.dumps({
            "status": "success",
            "device_removed": True,
            "removed": True,
            "message": "Модель удалена из Ollama.",
        }, ensure_ascii=False)

    if method == "mcp_connect":
        try:
            from extella_expert_bridge import locations
            allowlist = Path(locations()["mcp_root"]) / "allowlist.json"
        except Exception:
            return json.dumps({
                "status": "error",
                "device_removed": False,
                "message": "Системный runtime Extella недоступен.",
            }, ensure_ascii=False)
        if not allowlist.exists():
            return json.dumps({"status": "success", "device_removed": True, "removed": False, "message": "Подключения уже нет."}, ensure_ascii=False)
        try:
            payload = json.loads(allowlist.read_text(encoding="utf-8"))
            servers = payload.get("servers", payload) if isinstance(payload, dict) else None
        except (OSError, ValueError):
            servers = None
            payload = None
        if not isinstance(servers, dict):
            return json.dumps({"status": "error", "device_removed": False, "message": "Неожиданный формат MCP allowlist; файл сохранён."}, ensure_ascii=False)
        matches = [key for key, value in servers.items() if key == ref or (isinstance(value, dict) and ref in {value.get("id"), value.get("pkg"), value.get("title")})]
        if len(matches) > 1:
            return json.dumps({"status": "error", "device_removed": False, "message": "Найдено несколько MCP-подключений; удаление остановлено."}, ensure_ascii=False)
        if matches:
            servers.pop(matches[0], None)
            if isinstance(payload, dict) and "servers" in payload:
                payload["servers"] = servers
            else:
                payload = servers
            temporary = allowlist.with_name(".%s.%s.tmp" % (allowlist.name, os.getpid()))
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, allowlist)
        return json.dumps({"status": "success", "device_removed": True, "removed": bool(matches), "message": "MCP-подключение отключено."}, ensure_ascii=False)

    return json.dumps({
        "status": "error",
        "device_removed": False,
        "message": "Эта способность не имеет безопасного обработчика удаления.",
    }, ensure_ascii=False)
