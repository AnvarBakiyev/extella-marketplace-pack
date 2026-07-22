#!/usr/bin/env python3
"""Статическая классификация приложений каталога по совместимости — БЕЗ установки.
Тянет сырые файлы рецепта (install.js/torch.js/requirements.txt) через raw.githubusercontent,
ищет маркеры платформы/GPU → метит каждое приложение {platforms, gpu, note}.
Обновляет _mkt_apps (shard) полем compat. Клиент показывает релевантное своей ОС."""
import re, json, os, urllib.request, concurrent.futures as cf

TOK = os.environ.get("EXTELLA_TOKEN", "").strip()
AGENT = os.environ.get("EXTELLA_SCOPE_AGENT", "").strip()
if not TOK or not AGENT.startswith("agent_"):
    raise SystemExit("EXTELLA_TOKEN and the current account EXTELLA_SCOPE_AGENT are required")
H = {"X-Auth-Token": TOK, "X-Profile-Id": "default", "X-Agent-Id": AGENT, "Content-Type": "application/json"}

def kv_get(k):
    req = urllib.request.Request("https://api.extella.ai/api/kv/get", data=json.dumps({"key": k, "global": True}).encode(), headers=H)
    try: return json.loads(json.load(urllib.request.urlopen(req, timeout=30)).get("value") or "{}")
    except Exception: return None

def kv_set(k, v):
    req = urllib.request.Request("https://api.extella.ai/api/kv/set", data=json.dumps({"key": k, "value": json.dumps(v, ensure_ascii=False), "description": "apps directory + compat", "global": True}).encode(), headers=H)
    return json.load(urllib.request.urlopen(req, timeout=30)).get("status")

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "extella"})
        return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    except Exception:
        return ""

def repo_files(repo):
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", repo or "")
    if not m: return ""
    owner, name = m.group(1), m.group(2).replace(".git", "")
    blob = ""
    for br in ("main", "master"):
        for f in ("torch.js", "install.js", "pinokio.js", "requirements.txt"):
            blob += fetch("https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner, name, br, f))
        if blob.strip():
            break
    return blob.lower()

# маркеры
CUDA = ("cu118", "cu121", "cu124", "cu126", "+cu", "nvidia", "xformers", "bitsandbytes",
        "flash-attn", "flash_attn", "cuda_visible_devices", "--index-url https://download.pytorch.org/whl/cu")
MAC  = ("darwin", "apple", "mps", "arm64", "metal", "silicon", "macos")
WIN  = ("win32", "windows")

def classify(app):
    repo = (app.get("run") or {}).get("repo") or ""
    blob = repo_files(repo)
    has_cuda = any(x in blob for x in CUDA)
    has_mac  = any(x in blob for x in MAC)
    if not blob:
        compat = {"platforms": ["darwin", "linux", "win32"], "gpu": "unknown", "note": "рецепт не прочитан — совместимость не проверена"}
    elif has_mac:
        # рецепт ветвит установку под платформу (есть mac/apple/mps ветка) → кроссплатформенно
        compat = {"platforms": ["darwin", "linux", "win32"], "gpu": "any", "note": "кроссплатформенно (есть Mac/Apple-ветка)"}
    elif has_cuda:
        # cuda-маркеры и НИ одной mac-ветки → скорее NVIDIA/Linux+Win
        compat = {"platforms": ["linux", "win32"], "gpu": "nvidia", "note": "нужна NVIDIA/CUDA — на Mac не встанет"}
    else:
        compat = {"platforms": ["darwin", "linux", "win32"], "gpu": "cpu", "note": "лёгкое, без GPU-требований"}
    return compat

PER = 25  # приложений на шард (~13KB value — с запасом под лимит эмбеддинга)

def main():
    # собрать все 178 из текущих шардов
    flat = []
    for k in ("_mkt_apps", "_mkt_apps_2", "_mkt_apps_3"):
        d = kv_get(k)
        if d: flat += d.get("shelf", [])
    print("классифицирую", len(flat), "приложений…")
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        compats = list(ex.map(classify, flat))
    for a, c in zip(flat, compats):
        a["compat"] = c
    from collections import Counter
    cc = Counter(c["gpu"] for c in compats)
    print("по GPU:", dict(cc))
    # переразбить на мелкие шарды (влезают в эмбеддинг даже с compat)
    chunks = [flat[i:i+PER] for i in range(0, len(flat), PER)]
    n = len(chunks)
    result = {}
    for idx, ch in enumerate(chunks):
        key = "_mkt_apps" if idx == 0 else "_mkt_apps_%d" % (idx+1)
        shard = {"v": 1, "shelf": ch}
        if idx == 0:
            shard["shards"] = n
        val = json.dumps(shard, ensure_ascii=False)
        print(key, "(%d карточек, %dБ) →" % (len(ch), len(val)), kv_set(key, shard))
        result[key] = shard
    # сохранить обновлённый каталог для пака (install.py)
    json.dump(result, open("/tmp/apps_catalog_compat.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("шардов:", n, "· каталог для пака: /tmp/apps_catalog_compat.json")

if __name__ == "__main__":
    main()
