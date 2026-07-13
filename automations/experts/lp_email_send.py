# expert: lp_email_send
# description: Contract agent: send an email via SMTP on the user's behalf (negotiation letters, summaries). Config (~/extella_wizard/app/config.json): smtp_host, smtp_port, smtp_user, smtp_pass, email_from. Params: to, subject, body, cc. Human-triggered from the panel.

def lp_email_send(to="", subject="", body="", cc="") -> str:
    import json, os, smtplib, ssl
    from email.mime.text import MIMEText
    from email.utils import formataddr, make_msgid

    try:
        cfg = json.load(open(os.path.expanduser("~/extella_wizard/app/config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}

    def fb(v, d=""):
        s = str(v or "")
        return d if (not s or s.startswith("{{")) else s

    host = fb(cfg.get("smtp_host"))
    port = int(fb(cfg.get("smtp_port"), "465") or "465")
    user = fb(cfg.get("smtp_user"))
    pw = fb(cfg.get("smtp_pass"))
    frm = fb(cfg.get("email_from")) or user
    to = fb(to); subject = fb(subject); body = fb(body); cc = fb(cc)

    if not host or not user or not pw:
        return json.dumps({"status": "error", "error": "no_smtp_credentials",
                           "hint": "укажите SMTP-сервер, логин и пароль (app-password) во вкладке «Настройка»"}, ensure_ascii=False)
    if not to or not body:
        return json.dumps({"status": "error", "error": "to and body required"}, ensure_ascii=False)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject or "(без темы)"
    msg["From"] = formataddr(("", frm))
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Message-ID"] = make_msgid()
    rcpts = [a.strip() for a in (to + ("," + cc if cc else "")).split(",") if a.strip()]

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, pw)
                s.sendmail(frm, rcpts, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo(); s.starttls(context=ctx); s.ehlo()
                s.login(user, pw)
                s.sendmail(frm, rcpts, msg.as_string())
        return json.dumps({"status": "success", "to": rcpts, "subject": subject}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)[:220]}, ensure_ascii=False)