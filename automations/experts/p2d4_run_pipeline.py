$extens("include.py")
include("import json", [])
include("import urllib.request", [])

def p2d4_run_pipeline(input_path: str = "", output_dir: str = "") -> dict:
    """Оркестратор разбора договоров: p2d4_evaluate_contract_batch (ИИ-анализ по чек-листу + стандарты + Гражданский
    кодекс) → p2d4_generate_document_package (Реестр рисков xlsx + Протокол разногласий docx + Сводка руководителю).
    Вход: JSON-файл со списком договоров. Выход: пути к документам, счётчики риска и СПОРНЫЕ ПУНКТЫ (deviations)
    для передачи в согласование (p2d5_negotiate). Секреты — из ~/extella_wizard/app/config.json."""
    import json, os, urllib.request
    from pathlib import Path

    cfg = {}
    wizard_root = Path(os.environ.get("EXTELLA_WIZARD_ROOT") or (Path.home() / "extella_wizard"))
    plugins_root = Path(os.environ.get("EXTELLA_PLUGIN_ROOT") or (Path.home() / "extella-plugins"))
    cf = wizard_root / "app" / "config.json"
    if cf.exists():
        try: cfg = json.loads(cf.read_text(encoding="utf-8"))
        except Exception: cfg = {}
    token = cfg.get("auth_token", "")
    api = (cfg.get("api_base") or "https://api.extella.ai").rstrip("/")
    agent_id = cfg.get("agent_id", "__EXTELLA_AGENT__")
    if not token:
        return {"status": "error", "message": "нет auth_token в config.json"}
    if not input_path or not Path(str(input_path)).expanduser().exists():
        return {"status": "error", "message": "input_path не найден: " + str(input_path)}
    outdir = str(Path(str(output_dir)) if str(output_dir) else (plugins_root / "extella_contract_agent" / "out"))

    def run(expert, params, timeout=600):
        body = json.dumps({"expert_name": expert, "params": params, "global": True}).encode()
        req = urllib.request.Request(api + "/api/expert/run", data=body,
                                     headers={"X-Auth-Token": token, "Content-Type": "application/json",
                                              "X-Profile-Id": "default", "X-Agent-Id": agent_id}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
        res = out.get("result", out)
        if isinstance(res, str):
            try: res = json.loads(res)
            except Exception:
                import ast
                try: res = ast.literal_eval(res)
                except Exception: res = {"raw": res}
        return res

    ip = str(Path(str(input_path)).expanduser())
    eval_out = str(Path(outdir) / "analysis.json")
    # 1) анализ
    a = run("p2d4_evaluate_contract_batch", {"input_path": ip, "output_path": eval_out}, 900)
    if not isinstance(a, dict) or a.get("status") == "error":
        return {"status": "error", "message": "анализ не удался: " + str(a)[:200]}
    # 2) документы
    d = run("p2d4_generate_document_package", {"input_path": eval_out, "output_dir": outdir}, 300)
    # 3) собрать спорные пункты для согласования
    disputed = []
    try:
        adoc = json.loads(Path(eval_out).read_text(encoding="utf-8"))
        for rec in (adoc.get("records") or []):
            for dv in ((rec.get("ai_analysis") or {}).get("deviations") or []):
                disputed.append({"clause": dv.get("condition", ""), "standard": dv.get("standard", ""),
                                 "our_ask": "привести к стандарту компании", "severity": dv.get("severity", "")})
    except Exception:
        disputed = []

    return {"status": "success",
            "analysis_path": eval_out,
            "high_risk_contracts": a.get("high_risk_contracts", 0),
            "total_count": a.get("total_count", 0),
            "gk_grounded": a.get("gk_grounded", False),
            "registry_xlsx": (d or {}).get("registry_xlsx", ""),
            "protocol_docx": (d or {}).get("protocol_docx", ""),
            "summary_txt": (d or {}).get("summary_txt", ""),
            "disputed_points": disputed}
