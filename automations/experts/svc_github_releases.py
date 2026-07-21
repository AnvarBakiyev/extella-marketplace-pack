# expert: svc_github_releases
# description: Service: latest releases from competitors' GitHub repos (tag, date, notes). Params: repos (comma-separated owner/name), per_repo (releases per repo, default 1).

def svc_github_releases(repos="anthropics/anthropic-sdk-python,openai/openai-python", per_repo=1) -> str:
    import json, urllib.request, ssl
    if not repos or str(repos).startswith("{{"):
        repos = "anthropics/anthropic-sdk-python,openai/openai-python"
    try:
        per = int(per_repo)
    except Exception:
        per = 1
    per = max(1, min(per, 5))
    repo_list = [r.strip().strip("/") for r in (repos if isinstance(repos, list) else str(repos).split(",")) if str(r).strip()]
    ctx = ssl.create_default_context()
    items = []; errors = []
    for repo in repo_list[:25]:
        try:
            url = "https://api.github.com/repos/%s/releases?per_page=%d" % (repo, per)
            req = urllib.request.Request(url, headers={"User-Agent": "ExtellaSvc/1.0",
                                                       "Accept": "application/vnd.github+json"})
            data = json.loads(urllib.request.urlopen(req, timeout=20, context=ctx).read())
            if not isinstance(data, list):
                data = []
            for rel in data[:per]:
                items.append({
                    "source": "github_release",
                    "repo": repo,
                    "tag": rel.get("tag_name"),
                    "title": rel.get("name") or rel.get("tag_name"),
                    "date": rel.get("published_at"),
                    "url": rel.get("html_url"),
                    "text": (rel.get("body") or "")[:800],
                })
            if not data:
                errors.append({"repo": repo, "note": "no published releases (possibly tags only)"})
        except Exception as e:
            errors.append({"repo": repo, "error": str(e)[:120]})
    return json.dumps({"status": "success", "count": len(items), "items": items, "errors": errors}, ensure_ascii=False)