# expert: cap_audio_resolver
# description: CLI Capability аудио-эффекты (Audacity/sox) — резолвер

def cap_audio_resolver(confirm_install="no") -> str:
    import os, subprocess, sys, json, shutil
    def rec(p):
        d=os.path.expanduser("~/.extella_cli"); os.makedirs(d, exist_ok=True); open(os.path.join(d,"audio"),"w").write(p)
    def probe():
        ca=shutil.which("cli-anything-audacity")
        sox=shutil.which("sox") or ("/opt/homebrew/bin/sox" if os.path.exists("/opt/homebrew/bin/sox") else None)
        return ca, sox
    ca,sox=probe()
    if ca and sox: rec(ca); return json.dumps({"status":"already","bin_path":ca,"sox":sox,"source":"detected"}, ensure_ascii=False)
    if not confirm_install or confirm_install.startswith("{{") or confirm_install.lower()!="yes":
        return json.dumps({"status":"missing","message":"Аудио-эффекты не установлены. confirm_install='yes' поставит обвязку+sox."}, ensure_ascii=False)
    subprocess.run([sys.executable,"-m","pip","install","-q","cli-anything-hub"], capture_output=True, text=True, timeout=200)
    hub=shutil.which("cli-hub")
    if hub: subprocess.run([hub,"install","audacity"], capture_output=True, text=True, timeout=200)
    brew=next((b for b in ["/opt/homebrew/bin/brew","/usr/local/bin/brew"] if os.path.exists(b)), None)
    if brew:
        env=dict(os.environ); env["NONINTERACTIVE"]="1"
        subprocess.run([brew,"install","sox"], capture_output=True, text=True, timeout=280, env=env)
    ca,sox=probe()
    if ca and sox: rec(ca); return json.dumps({"status":"installed","bin_path":ca,"sox":sox,"source":"composite"}, ensure_ascii=False)
    return json.dumps({"status":"failed","message":"Поставили части, но обвязка/sox не найдены"}, ensure_ascii=False)