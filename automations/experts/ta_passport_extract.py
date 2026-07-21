# expert: ta_passport_extract
# description: Travel Agency pack: extract passport data from a scan image via OCR (tesseract) + ICAO TD3 MRZ parsing with check-digit validation. Writes client doc card to KV ta:client_doc:<passport_no>. Params: image_path (scan file), mrz_text (fallback: paste 2 MRZ lines directly), api_token.

def ta_passport_extract(image_path="", mrz_text="", api_token="") -> str:
    import json, os, re, ssl, subprocess, time, urllib.request

    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    tok = api_token if api_token and not str(api_token).startswith("{{") else cfg.get("auth_token", "")

    def cd(s):
        vals = {c: i for i, c in enumerate("0123456789")}
        vals.update({c: i + 10 for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")})
        vals["<"] = 0
        return str(sum(vals.get(c, 0) * [7, 3, 1][i % 3] for i, c in enumerate(s)) % 10)

    raw = mrz_text if mrz_text and not str(mrz_text).startswith("{{") else ""
    ocr_used = ""
    if not raw:
        path = os.path.expanduser(image_path) if image_path and not str(image_path).startswith("{{") else ""
        if not path or not os.path.exists(path):
            return json.dumps({"status": "error", "error": "image_path not found and no mrz_text given"}, ensure_ascii=False)
        tess = next((t for t in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract") if os.path.exists(t)), "tesseract")
        try:
            out = subprocess.run([tess, path, "stdout", "--psm", "6"], capture_output=True, text=True, timeout=60)
            raw = out.stdout or ""
            ocr_used = tess
        except Exception as e:
            return json.dumps({"status": "error", "error": "tesseract failed: " + str(e)[:150],
                               "hint": "передайте mrz_text напрямую или установите tesseract"}, ensure_ascii=False)

    # find TD3 MRZ: two ~44-char lines of A-Z0-9<
    cand = []
    for line in raw.splitlines():
        s = re.sub(r"[^A-Z0-9<]", "", line.strip().upper().replace(" ", ""))
        if len(s) >= 40 and s.count("<") >= 3:
            cand.append(s[:44].ljust(44, "<"))
    l1 = next((s for s in cand if s.startswith("P<")), "")
    l2 = next((s for s in cand if not s.startswith("P<") and re.match(r"^[A-Z0-9<]{9}[0-9]", s)), "")
    if not l1 or not l2:
        return json.dumps({"status": "error", "error": "MRZ not found in OCR output",
                           "ocr_sample": raw[-200:], "hint": "нужен скан с видимой машиночитаемой зоной"}, ensure_ascii=False)

    issuing = l1[2:5].replace("<", "")
    names = l1[5:].split("<<")
    surname = names[0].replace("<", " ").strip()
    given = names[1].replace("<", " ").strip() if len(names) > 1 else ""
    doc_no = l2[0:9].replace("<", "")
    doc_cd_ok = cd(l2[0:9]) == l2[9]
    nationality = l2[10:13].replace("<", "")
    dob_raw = l2[13:19]; dob_cd_ok = cd(dob_raw) == l2[19]
    sex = l2[20]
    exp_raw = l2[21:27]; exp_cd_ok = cd(exp_raw) == l2[27]
    personal = l2[28:42].replace("<", "")

    def dt(yymmdd, future=False):
        try:
            yy, mm, dd = int(yymmdd[0:2]), yymmdd[2:4], yymmdd[4:6]
            century = 2000 if (future or yy <= int(time.strftime("%y"))) else 1900
            if future and yy > 60:
                century = 1900
            return "%04d-%s-%s" % (century + yy, mm, dd)
        except Exception:
            return yymmdd

    data = {"surname": surname, "given_names": given, "document_no": doc_no,
            "issuing_state": issuing, "nationality": nationality,
            "birth_date": dt(dob_raw), "sex": sex, "expiry_date": dt(exp_raw, future=True),
            "personal_no": personal,
            "mrz_valid": {"document": doc_cd_ok, "birth": dob_cd_ok, "expiry": exp_cd_ok},
            "ocr": bool(ocr_used), "extracted_at": time.strftime("%Y-%m-%d %H:%M")}

    saved = ""
    if tok and doc_no:
        try:
            ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request("https://api.extella.ai/api/kv/set",
                data=json.dumps({"key": "ta:client_doc:" + doc_no, "value": json.dumps(data, ensure_ascii=False),
                                 "description": "TA passport data %s %s (doc %s)" % (surname, given, doc_no),
                                 "global": True}).encode("utf-8"),
                headers={"X-Auth-Token": tok, "Content-Type": "application/json", "X-Profile-Id": "default",
                         "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__")}, method="POST")
            urllib.request.urlopen(req, timeout=30, context=ctx)
            saved = "ta:client_doc:" + doc_no
        except Exception as e:
            data["kv_error"] = str(e)[:120]
    return json.dumps({"status": "success", "data": data, "saved_kv": saved,
                       "note": "Проверьте данные глазами перед занесением в CRM (ПДн!)"}, ensure_ascii=False)