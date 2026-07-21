# expert: cap_ffmpeg_resolver
# description: Установка и проверка инструмента «ffmpeg (видео и аудио)» через единый Extella runtime.

def cap_ffmpeg_resolver(confirm_install="no") -> str:
    import json, os
    try:
        from extella_expert_bridge import ensure
    except Exception:
        return json.dumps({"status":"failed","error_class":"client_runtime_missing","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}, ensure_ascii=False)
    repair = bool(confirm_install) and not str(confirm_install).startswith("{{") and str(confirm_install).lower() == "yes"
    result = ensure("ffmpeg", repair=repair)
    if result.get("ready") and result.get("path"):
        directory = os.path.expanduser("~/.extella_cli"); os.makedirs(directory, exist_ok=True)
        open(os.path.join(directory, "ffmpeg"), "w", encoding="utf-8").write(result["path"])
        result["bin_path"] = result["path"]
        result["status"] = "installed" if result.get("changed") else "already"
    return json.dumps(result, ensure_ascii=False)
