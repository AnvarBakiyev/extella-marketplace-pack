# expert: svc_github
# description: Сервис: сведения о репозитории GitHub (звёзды, язык, описание, форки). Параметр: repo (owner/name).

def svc_github(repo="torvalds/linux") -> str:
    import json, urllib.request, ssl
    repo = "torvalds/linux" if (not repo or str(repo).startswith("{{")) else str(repo).strip().strip("/")
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        d=json.loads(urllib.request.urlopen(urllib.request.Request("https://api.github.com/repos/"+repo,headers={"User-Agent":"ExtellaSvc/1.0","Accept":"application/vnd.github+json"}),timeout=20,context=ctx).read())
        return json.dumps({"status":"success","repo":d.get("full_name",repo),"stars":d.get("stargazers_count"),"forks":d.get("forks_count"),"language":d.get("language"),"desc":d.get("description"),"url":d.get("html_url")}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)