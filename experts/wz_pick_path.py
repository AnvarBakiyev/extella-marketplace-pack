# expert: wz_pick_path
# description: Открывает НАТИВНЫЙ диалог выбора папки/файла на устройстве (macOS osascript) и возвращает POSIX-путь. Для кнопки «Выбрать папку» в витрине.

def wz_pick_path(kind="folder") -> str:
    import subprocess, json
    scr = "POSIX path of (choose file)" if kind == "file" else "POSIX path of (choose folder)"
    try:
        r = subprocess.run(["osascript", "-e", scr], capture_output=True, text=True, timeout=180)
        p = (r.stdout or "").strip()
        if p:
            return json.dumps({"status": "ok", "path": p}, ensure_ascii=False)
        return json.dumps({"status": "cancel", "message": (r.stderr or "отменено")[:80]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)[:120]}, ensure_ascii=False)