# expert: cap_img2pdf_resolver
# description: Установка и проверка инструмента «img2pdf (картинки → PDF)» (brew). Зови ПЕРЕД первым использованием этой способности.

def cap_img2pdf_resolver(confirm_install="no") -> str:
    import json
    try:
        from extella_expert_bridge import ensure
    except Exception:
        return json.dumps({"status":"failed","error_class":"client_runtime_missing","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}, ensure_ascii=False)
    repair = bool(confirm_install) and not str(confirm_install).startswith("{{") and str(confirm_install).lower() == "yes"
    result = ensure("img2pdf", repair=repair)
    if result.get("ready") and result.get("path"):
        result["bin_path"] = result["path"]
        result["source"] = "extella_runtime"
        result["status"] = "installed" if result.get("changed") else "already"
    elif not repair and result.get("status") == "action_required":
        result["status"] = "missing"
    return json.dumps(result, ensure_ascii=False)
