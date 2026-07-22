# name: app_list
# description: Возвращает список реально установленных сторонних приложений из платформенного каталога Extella: {app_id, can_start}. Для кнопки «Открыть» в витрине. БЕЗ LLM.
import os, json

def app_list():
    try:
        from extella_expert_bridge import locations
        base = locations()["apps_root"]
    except Exception:
        return json.dumps({"status":"error","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}, ensure_ascii=False)
    out = []
    if not os.path.isdir(base):
        return json.dumps({"status": "success", "apps": []}, ensure_ascii=False)

    def is_app(d):
        # приложение = папка с рецептом Pinokio ИЛИ клоном приложения внутри (app/, start.js)
        for f in ("start.js", "pinokio.js", "install.js"):
            if os.path.isfile(os.path.join(d, f)):
                return True
        return False

    def can_start(d):
        return os.path.isfile(os.path.join(d, "start.js")) or os.path.isfile(os.path.join(d, "pinokio.js"))

    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        if is_app(d):
            out.append({"app_id": name, "can_start": can_start(d)})
            continue
        # глубина 2: владелец/приложение (напр. cocktailpeanut/fluxgym)
        try:
            for sub in sorted(os.listdir(d)):
                sd = os.path.join(d, sub)
                if os.path.isdir(sd) and is_app(sd):
                    out.append({"app_id": name + "/" + sub, "can_start": can_start(sd)})
        except Exception:
            pass

    return json.dumps({"status": "success", "apps": out}, ensure_ascii=False)
