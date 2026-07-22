#!/usr/bin/env python3
"""Сторож каталогов Extella.

Зачем: часть каталогов витрины НЕ имеет харвестера и живёт «статикой» — их
засевает версионированный установщик. Если такой ключ пропадает из KV
с _mkt_apps 16.07), вернуть его некому: раздел витрины просто пустеет молча.

Что делает: раз в сутки проверяет, что охраняемые ключи на месте и не пустые.
Пропал/пуст — заливает обратно из эталонного пак-файла рядом и пишет в лог.
Каталоги с харвестером (models/programs/skills) НЕ трогает — их чинит харвест.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("EXTELLA_TOKEN", "").strip()
AGENT = os.environ.get("EXTELLA_SCOPE_AGENT", "").strip()
if not TOKEN or not AGENT.startswith("agent_"):
    raise SystemExit("EXTELLA_TOKEN and the current account EXTELLA_SCOPE_AGENT are required")
H = {"Content-Type": "application/json", "X-Auth-Token": TOKEN,
     "X-Profile-Id": "default", "X-Agent-Id": AGENT}
BASE = os.environ.get("EXTELLA_API_BASE", "https://api.extella.ai").rstrip("/")

# ключ-эталон: пак-файл вида {"_mkt_x": {...}, "_mkt_x_2": {...}}
GUARDED = {
    "_mkt_apps": "apps_catalog.json",   # харвестера нет — только install.py
    "_mkt_mcp":  "mcp_catalog.json",    # харвестера нет
    "_mkt_loc":  "loc_catalog.json",    # переводы: их не создаёт никто, кроме нас
}


def post(ep, body, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(BASE + ep, data=json.dumps(body).encode(), headers=H)
            return json.loads(urllib.request.urlopen(r, timeout=60).read())
        except Exception as e:
            # kv/get отдаёт HTTP 500 и на «ключа нет» — отличаем по kv/list, не по коду
            if i == tries - 1:
                raise
            time.sleep(3)


def kv_get(key):
    try:
        d = post("/api/kv/get", {"key": key}, tries=1)
    except Exception:
        return None
    v = d.get("value", d)
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return None
    return v


def count(v):
    if not isinstance(v, dict):
        return 0
    return len(v.get("shelf") or v.get("items") or v.get("map") or [])


def reseed(base, packfile, log):
    p = os.path.join(HERE, packfile)
    if not os.path.exists(p):
        log.append("  !! эталон %s не найден — вернуть не могу" % packfile)
        return 0
    cat = json.load(open(p, encoding="utf-8"))
    order = lambda k: 1 if k == base else int(k.split("_")[-1])
    n = 0
    for key in sorted(cat, key=order):
        val = cat[key]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                pass
        post("/api/kv/set", {"key": key, "value": json.dumps(val, ensure_ascii=False),
                             "global": True, "description": "restored by catalog_guard"})
        n += count(val)
    return n


def main():
    log = ["[%s] сторож каталогов" % time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())]
    broken = 0
    for base, packfile in GUARDED.items():
        head = kv_get(base)
        n = count(head)
        if head and n:
            shards = head.get("shards") or 1
            total = n
            miss = []
            for i in range(2, shards + 1):
                s = kv_get("%s_%d" % (base, i))
                if not s or not count(s):
                    miss.append(i)
                else:
                    total += count(s)
            if miss:
                broken += 1
                log.append("  ЧИНЮ %s: нет шардов %s" % (base, miss))
                got = reseed(base, packfile, log)
                log.append("  -> восстановлено, записей: %d" % got)
            else:
                log.append("  ok %-12s записей: %d (шардов %d)" % (base, total, shards))
        else:
            broken += 1
            log.append("  ЧИНЮ %s: ключ пропал или пуст" % base)
            got = reseed(base, packfile, log)
            log.append("  -> восстановлено, записей: %d" % got)

    if broken:
        log.append("  ИТОГ: восстановлено каталогов: %d" % broken)
    out = "\n".join(log)
    print(out)
    # видимая строка для ops-сводки, если что-то чинили
    if broken:
        with open(os.path.join(HERE, "ALERT.log"), "a") as f:
            f.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
