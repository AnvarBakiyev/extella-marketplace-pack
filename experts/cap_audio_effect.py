# expert: cap_audio_effect
# description: Аудио-эффекты: темп/тон/эхо/шумоподавление/громкость (через Audacity-обвязку+sox)

def cap_audio_effect(input_path="", output_path="", effect="change_tempo", amount="") -> str:
    import os, subprocess, json, shutil, tempfile
    EFFECTS={"change_tempo":("factor","1.5"),"change_pitch":("semitones","2"),"amplify":("db","6"),
             "normalize":("level","-3"),"echo":(None,None),"noise_reduction":(None,None)}
    if not effect or effect.startswith("{{") or effect not in EFFECTS: effect="change_tempo"
    key,default=EFFECTS[effect]
    if key and (not amount or str(amount).startswith("{{")): amount=default
    def ca_path():
        f=os.path.expanduser("~/.extella_cli/audio")
        if os.path.exists(f):
            p=open(f).read().strip()
            if p and os.path.exists(p): return p
        return shutil.which("cli-anything-audacity")
    ca=ca_path()
    if not ca: return json.dumps({"status":"error","message":"не установлено — сначала cap_audio_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    base,ext=os.path.splitext(input_path)
    if not ext: ext=".wav"
    if not output_path or output_path.startswith("{{"): output_path=base+"_fx"+ext
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    env=dict(os.environ); env["PATH"]="/opt/homebrew/bin"+os.pathsep+env.get("PATH","")
    d=tempfile.mkdtemp(prefix="_aud_"); proj=os.path.join(d,"p.json")
    def run(args, t=120):
        r=subprocess.run([ca]+args, capture_output=True, text=True, timeout=t, env=env)
        return r.returncode,(r.stdout or r.stderr)
    run(["project","new","-o",proj])
    run(["--project",proj,"track","add"])
    rc,o=run(["--project",proj,"clip","add","0",input_path])
    if rc!=0: return json.dumps({"status":"error","message":"clip add: "+o[:120]}, ensure_ascii=False)
    fx=["--project",proj,"effect","add","-t","0",effect]
    if key: fx+=["-p",key+"="+str(amount)]
    rc,o=run(fx)
    if rc!=0: return json.dumps({"status":"error","message":"effect: "+o[:120]}, ensure_ascii=False)
    rc,o=run(["--project",proj,"export","render",output_path,"--overwrite"], t=180)
    if rc!=0 or not os.path.exists(output_path):
        return json.dumps({"status":"error","message":"export: "+o[:120]}, ensure_ascii=False)
    return json.dumps({"status":"success","output_path":output_path,"effect":effect,"amount":(amount if key else None),"out_kb":round(os.path.getsize(output_path)/1024,1)}, ensure_ascii=False)