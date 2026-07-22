# expert: ci_run_pipeline
# description: Competitor Intelligence orchestrator: sources (GitHub releases + RSS + Reddit + Hacker News) -> ground on positioning -> synthesis by the platform Qwen -> digest -> delivery (Slack/email). Config from KV ci:config. Writes competitor_digest.md, lastrun:ci and ci:knowledge_gaps to KV.

def ci_run_pipeline(repos="", feeds="", subreddits="", agent_id="", positioning="",
                    deliver="", deliver_client="default", kb_name="",
                    api_token="", api_base="https://api.extella.ai", work_dir="",
                    client="", source_file="", source_key="", target="") -> dict:
    # source_file/source_key/target — tolerated for calls from wz_scheduler_tick (partially ignored).
    import json, urllib.request
    from pathlib import Path
    from datetime import datetime, timezone

    def _blank(v):
        return (not v) or str(v).startswith("{{")

    if _blank(api_base):
        api_base = "https://api.extella.ai"
    # The installer replaces the placeholder with the Qwen agent owned by the current account.
    if _blank(agent_id):
        agent_id = "__EXTELLA_AGENT__"
    if _blank(api_token):
        try:
            from extella_expert_bridge import account_config
            api_token = account_config().get("auth_token", "")
        except Exception:
            api_token = ""
    if not api_token:
        return {"status": "error", "message": "no api_token and no device bridge config"}

    if not _blank(work_dir):
        wd = Path(work_dir).expanduser()
    else:
        try:
            from extella_expert_bridge import locations
            wd = Path(locations()["data_root"]) / "ci-work"
        except Exception:
            return {"status": "error", "message": "device bridge unavailable"}
    wd.mkdir(parents=True, exist_ok=True)
    headers = {"X-Auth-Token": api_token, "Content-Type": "application/json",
               "X-Profile-Id": "default", "X-Agent-Id": agent_id or "__EXTELLA_AGENT__"}
    stages = []

    def _post(path, body, timeout=600):
        req = urllib.request.Request(api_base.rstrip("/") + path,
                                     data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # --- process config from KV ci:config: fills in params NOT passed explicitly (needed when run by the scheduler) ---
    _c = {}
    try:
        _cv = _post("/api/kv/get", {"key": "ci:config"}, timeout=60).get("value")
        if _cv:
            _c = json.loads(_cv)
    except Exception:
        _c = {}
    if _blank(repos):
        repos = _c.get("repos") or "anthropics/anthropic-sdk-python,openai/openai-python,langchain-ai/langchain"
    if _blank(feeds):
        feeds = _c.get("feeds") or "https://hnrss.org/frontpage"
    if _blank(subreddits):
        subreddits = _c.get("subreddits") or ""
    if _blank(positioning):
        positioning = _c.get("positioning") or "Extella turns internet AI primitives into running, in-contour business processes (compose > install)."
    if _blank(kb_name):
        kb_name = _c.get("kb_name") or ""
    if _blank(deliver):
        deliver = _c.get("deliver") or "none"
    if _blank(deliver_client) or deliver_client == "default":
        deliver_client = (client if not _blank(client) else _c.get("deliver_client")) or "default"

    def call_expert(expert, params, name, tgt=""):
        rec = {"name": name, "expert": expert, "status": "running"}
        stages.append(rec)
        body = {"expert_name": expert, "params": params, "global": True}
        if not _blank(tgt):
            body["target"] = tgt
        try:
            resp = _post("/api/expert/run", body)
        except Exception as e:
            rec["status"] = "error"; rec["error"] = str(e)[:200]; return None
        raw = resp.get("result", resp)
        out = raw
        if isinstance(raw, str):
            try:
                out = json.loads(raw)
            except Exception:
                try:
                    import ast
                    out = ast.literal_eval(raw)   # fython experts that return a dict arrive as a Python repr (single quotes)
                except Exception:
                    out = {"status": "unknown", "raw": raw[:300]}
        if isinstance(out, dict) and out.get("status") == "error":
            rec["status"] = "error"; rec["error"] = str(out.get("message", ""))[:200]; return None
        rec["status"] = "success"
        rec["count"] = out.get("count") if isinstance(out, dict) else None
        return out

    # 1. INSTALL/FETCH — sources (a partial failure doesn't kill the run)
    findings = []
    r_gh = call_expert("svc_github_releases", {"repos": repos, "per_repo": 1}, "GitHub releases")
    if isinstance(r_gh, dict):
        findings += r_gh.get("items", [])
    r_rss = call_expert("svc_rss", {"feeds": feeds, "per_feed": 3}, "RSS/blogs")
    if isinstance(r_rss, dict):
        findings += r_rss.get("items", [])
    if subreddits:
        r_rd = call_expert("svc_reddit", {"subreddits": subreddits, "sort": "top", "t": "day", "per_sub": 4}, "Reddit")
        if isinstance(r_rd, dict):
            findings += r_rd.get("items", [])
    r_hn = call_expert("svc_hackernews", {"count": 10}, "Hacker News")
    if isinstance(r_hn, dict):
        for it in (r_hn.get("items") or r_hn.get("stories") or []):
            if isinstance(it, dict):
                findings.append({"source": "hackernews", "title": it.get("title"), "url": it.get("url"), "text": ""})
    if not findings:
        return {"status": "error", "message": "no source returned any findings", "stages": stages}

    # 2. GROUND — positioning from local RAG (best-effort), else inline/config
    if kb_name and not str(kb_name).startswith("{{"):
        r_kp = call_expert("kp_ask", {"kb": kb_name, "question": "What is our product positioning and differentiators?"}, "Positioning (RAG)")
        if isinstance(r_kp, dict):
            positioning = r_kp.get("answer") or r_kp.get("result") or positioning

    # 3. COMPOSE — Qwen fine-tune synthesis (tool_choice=none, plain-text with ===GAPS===).
    digest_md = ""; gaps = []; digest_source = "raw"
    qwen_ok = bool(agent_id)
    if qwen_ok:
        msg = ("You are a competitor intelligence analyst. Work ONLY from the data below — do NOT call any tools, "
               "do NOT browse, do NOT create experts.\nOUR POSITIONING:\n" + positioning + "\n\n"
               "RAW FINDINGS (JSON — each has source/title/url/text):\n" + json.dumps(findings, ensure_ascii=False)[:14000] + "\n\n"
               "Produce a competitor-intelligence brief in MARKDOWN — plain text, no code fences, no preamble. "
               "Sections in this EXACT order:\n\n"
               "## Competitor Changes\n"
               "A markdown table: | Competitor | Change | Type | Why it matters | Source |\n"
               "Type is ONE of: Product, Pricing, Hiring, Funding, Partnership, Technical, Other. "
               "Deduplicate near-identical items. Source = the finding's url (as a link). Skip pure noise.\n\n"
               "## Founder brief\n"
               "3-4 sentences: the most important shifts and what they mean for us, tied to our positioning.\n\n"
               "## Suggested responses\n"
               "3-5 concrete actions we could take (update landing page, write a post, check a feature gap, "
               "adjust pricing, prep a sales objection, etc.). One per line, each starting with '- '.\n\n"
               "Then a line with EXACTLY ===GAPS=== and after it one line per finding you couldn't tie to our positioning.")
        stages.append({"name": "Digest synthesis (Qwen)", "agent": agent_id, "status": "running"})
        try:
            resp = _post("/api/agent/run", {"agent_id": agent_id, "input": msg, "store": False,
                                            "temperature": 0, "run_timeout": 180,
                                            "tool_choice": "none", "max_output_tokens": 4000})
            # Responses API: output=[...]; pull the text from elements where type=="message".
            agent_text = ""
            out = resp.get("output") if isinstance(resp, dict) else None
            if isinstance(out, list):
                parts = []
                for it in out:
                    if isinstance(it, dict) and it.get("type") == "message":
                        for c in it.get("content", []):
                            if isinstance(c, dict) and c.get("text"):
                                parts.append(c["text"])
                agent_text = "\n".join(parts)
            if not agent_text and isinstance(resp, dict):
                agent_text = resp.get("output_text") or ""
            stages[-1]["status"] = "success"
            digest_source = "qwen"
            agent_text = (agent_text or "").strip()
            if "===GAPS===" in agent_text:
                dpart, gpart = agent_text.split("===GAPS===", 1)
                digest_md = dpart.strip() or "(empty synthesis response)"
                gaps = [g.strip().lstrip("-•* ").strip() for g in gpart.splitlines() if g.strip()]
            else:
                digest_md = agent_text or "(empty synthesis response)"
            _h = digest_md.find("\n## ")  # trim the model preamble up to the first heading
            if 0 < _h < 400:
                digest_md = digest_md[_h:].lstrip("\n").strip()
        except Exception as e:
            stages[-1]["status"] = "error"; stages[-1]["error"] = str(e)[:200]
            qwen_ok = False

    if not qwen_ok:
        lines = ["# Competitor Intelligence — raw findings", "",
                 "> Qwen synthesis skipped because the current-account agent was unavailable.", ""]
        for it in findings:
            lines.append("- **[%s]** %s%s" % (it.get("source", "?"), (it.get("title") or "")[:120],
                                              ("  —  " + it["url"]) if it.get("url") else ""))
        digest_md = "\n".join(lines)
        digest_source = "raw"

    digest_path = wd / "competitor_digest.md"
    digest_path.write_text(digest_md, encoding="utf-8")

    # 4. LEARN — knowledge gaps into KV (heuristic, not training)
    try:
        _post("/api/kv/set", {"key": "ci:knowledge_gaps", "value": json.dumps(gaps, ensure_ascii=False)}, timeout=60)
    except Exception:
        pass

    # 5. ACT — deliver the full digest. Connector: (api_token, client, mode='send', text). Pinned to the target device.
    delivered = False
    deliver = str(deliver or "").lower().strip()
    if deliver in ("slack", "email"):
        exp = "wz_connector_slack" if deliver == "slack" else "wz_connector_email"
        d = call_expert(exp, {"api_token": api_token, "client": deliver_client, "mode": "send",
                              "text": digest_md[:38000]}, "Delivery (" + deliver + ")", tgt=target)
        delivered = bool(isinstance(d, dict) and d.get("ok"))
        if isinstance(d, dict) and not d.get("ok"):
            stages[-1]["deliver_err"] = str(d.get("err", ""))[:160]

    # lastrun for the scheduler tick
    try:
        _post("/api/kv/set", {"key": "lastrun:ci",
                              "value": json.dumps({"at": datetime.now(timezone.utc).isoformat(), "status": "success",
                                                   "findings": len(findings), "gaps": len(gaps),
                                                   "delivered": delivered}, ensure_ascii=False)}, timeout=60)
    except Exception:
        pass

    manifest = wd / "pipeline_manifest.json"
    manifest.write_text(json.dumps({"pipeline": "ci_run_pipeline", "stages": stages,
                                    "finished_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "success", "findings": len(findings), "knowledge_gaps": len(gaps),
            "digest_source": digest_source, "delivered": delivered, "digest_path": str(digest_path),
            "digest_md": digest_md[:20000], "digest_preview": digest_md[:600], "stages": stages}
