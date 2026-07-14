# name: app_list
# description: Возвращает список реально установленных приложений (рецепты Pinokio) из ~/extella-apps: {app_id, root, can_start}. Для кнопки «Открыть» в витрине. Сканирует папки с рецептом (start.js/pinokio.js), глубина до 2 (владелец/приложение). БЕЗ LLM.
import os, json

def app_list():
    base = os.path.expanduser("~/extella-apps")
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
            out.append({"app_id": name, "root": d, "can_start": can_start(d)})
            continue
        # глубина 2: владелец/приложение (напр. cocktailpeanut/fluxgym)
        try:
            for sub in sorted(os.listdir(d)):
                sd = os.path.join(d, sub)
                if os.path.isdir(sd) and is_app(sd):
                    out.append({"app_id": name + "/" + sub, "root": sd, "can_start": can_start(sd)})
        except Exception:
            pass

    return json.dumps({"status": "success", "apps": out}, ensure_ascii=False)
