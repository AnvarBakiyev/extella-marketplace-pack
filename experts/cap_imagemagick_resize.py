# expert: cap_imagemagick_resize
# description: Пакет картинок — Размер и формат тысяч изображений разом — локально Операция «Уменьшить», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_imagemagick_resize(input_path="", output_path="", size="50%") -> str:
    import os, subprocess, json, shutil, tempfile
    ALLOWED_size = ('25%', '50%', '75%')
    def binpath():
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error("imagemagick", repair=False)
            return path
        except Exception:
            return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    if not size or size.startswith("{{") or size not in ALLOWED_size: size = "50%"
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"ImageMagick (пакет картинок) не установлен — сначала cap_imagemagick_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + "_small.jpg"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["{input}", "-resize", "{size}", "{output}"]
    SUB = {"input": input_path, "output": output_path, "size": size}
    argv = [b]
    for tok in TMPL:
        for k, v in SUB.items():
            tok = tok.replace("{" + k + "}", str(v))
        argv.append(tok)
    _env = dict(os.environ)
    pass
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=_env)
    except Exception as e:
        return json.dumps({"status":"error","message":"вызов упал: " + str(e)[:100]}, ensure_ascii=False)
    if r.returncode != 0 or not os.path.exists(output_path):
        return json.dumps({"status":"error","message":"инструмент не создал файл","err":(r.stderr or "")[:140]}, ensure_ascii=False)
    after = os.path.getsize(output_path)
    pass
    return json.dumps({"status":"success","output_path":output_path,"in_kb":round(before/1024,1),"out_kb":round(after/1024,1)}, ensure_ascii=False)