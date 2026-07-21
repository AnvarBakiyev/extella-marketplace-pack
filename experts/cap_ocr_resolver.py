# expert: cap_ocr_resolver
# description: Установка и проверка инструмента «OCR (поиск по сканам)» (brew). Зови ПЕРЕД первым использованием этой способности.

def cap_ocr_resolver(confirm_install="no") -> str:
    import json, os
    try:
        from extella_expert_bridge import ensure
    except Exception:
        return json.dumps({"status":"failed","error_class":"client_runtime_missing","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}, ensure_ascii=False)
    repair = bool(confirm_install) and not str(confirm_install).startswith("{{") and str(confirm_install).lower() == "yes"
    dependencies = ('ocrmypdf', 'tesseract')
    results = {name: ensure(name, repair=repair) for name in dependencies}
    ready = all(result.get("ready") and result.get("path") for result in results.values())
    if ready:
        path = results["ocrmypdf"]["path"]
        directory = os.path.expanduser("~/.extella_cli")
        os.makedirs(directory, exist_ok=True)
        marker = os.path.join(directory, "ocr")
        temporary = marker + ".tmp"
        open(temporary, "w", encoding="utf-8").write(path)
        os.replace(temporary, marker)
        return json.dumps({
            "status": "installed" if any(item.get("changed") for item in results.values()) else "already",
            "bin_path": path,
            "source": "extella_runtime",
            "dependencies": results,
        }, ensure_ascii=False)
    missing = [name for name, result in results.items() if not result.get("ready")]
    return json.dumps({
        "status": "missing" if not repair else "action_required",
        "error_class": "dependency_missing",
        "message": "Не готовы зависимости: " + ", ".join(missing),
        "dependencies": results,
    }, ensure_ascii=False)
