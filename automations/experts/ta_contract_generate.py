# expert: ta_contract_generate
# description: Travel Agency pack: generate a tour service contract (HTML, print-ready) from passport data (KV ta:client_doc:<doc_no>) and tour details. DEMO template with SPECIMEN watermark until agency provides their legal template. Params: doc_no (passport), tour_json (hotel/dates/price) or draft_phone (takes best pick from ta:draft:<phone>), out_dir, api_token.

def ta_contract_generate(doc_no="", tour_json="{}", draft_phone="", out_dir="~/extella-plugins/extella_travel_agency/contracts", api_token="") -> str:
    import json, os, ssl, time, urllib.request

    try:
        cfg = json.load(open(os.path.expanduser("~/extella_wizard/app/config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    tok = api_token if api_token and not str(api_token).startswith("{{") else cfg.get("auth_token", "")
    if not tok:
        return json.dumps({"status": "error", "error": "no_api_token"}, ensure_ascii=False)
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

    def kv_get(key):
        req = urllib.request.Request("https://api.extella.ai/api/kv/get",
            data=json.dumps({"key": key, "global": True}).encode("utf-8"),
            headers={"X-Auth-Token": tok, "Content-Type": "application/json", "X-Profile-Id": "default",
                     "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__")}, method="POST")
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return (json.loads(r.read().decode("utf-8")) or {}).get("value") or ""

    if not doc_no or str(doc_no).startswith("{{"):
        return json.dumps({"status": "error", "error": "doc_no required (номер паспорта из ta_passport_extract)"}, ensure_ascii=False)
    try:
        client = json.loads(kv_get("ta:client_doc:" + doc_no))
    except Exception:
        return json.dumps({"status": "error", "error": "нет данных паспорта в KV ta:client_doc:%s — сначала ta_passport_extract" % doc_no}, ensure_ascii=False)

    tour = {}
    try:
        tour = json.loads(tour_json) if tour_json and not str(tour_json).startswith("{{") else {}
    except Exception:
        tour = {}
    if not tour and draft_phone and not str(draft_phone).startswith("{{"):
        ph = "".join(c for c in str(draft_phone) if c.isdigit() or c == "+")
        try:
            draft = json.loads(kv_get("ta:draft:" + ph))
            picks = draft.get("picks") or []
            best = next((p for p in picks if p.get("bucket") == "in_budget"), picks[0] if picks else {})
            bt = best.get("bestTour") or {}
            tour = {"hotel": best.get("name", ""), "stars": best.get("stars", ""), "region": best.get("region", ""),
                    "country": draft.get("country", ""), "date": bt.get("date", ""), "nights": bt.get("nights", ""),
                    "price": bt.get("price") or best.get("price"), "currency": best.get("currency", "KZT")}
        except Exception:
            tour = {}
    try:
        ta_conf = json.loads(kv_get("ta:config") or "{}")
    except Exception:
        ta_conf = {}

    fio = ("%s %s" % (client.get("surname", ""), client.get("given_names", ""))).strip()
    agency = ta_conf.get("agency_name", "Турагентство")
    num = "TA-%s-%s" % (time.strftime("%Y%m%d"), (doc_no or "X")[-4:])
    today = time.strftime("%d.%m.%Y")

    def fmt(n):
        try:
            return "{:,.0f}".format(float(n)).replace(",", " ")
        except Exception:
            return str(n or "—")

    rows_client = [("ФИО (по паспорту)", fio), ("Документ", "Паспорт %s, %s" % (client.get("document_no", ""), client.get("issuing_state", ""))),
                   ("Дата рождения", client.get("birth_date", "")), ("Срок действия документа", client.get("expiry_date", "")),
                   ("ИИН / Personal No", client.get("personal_no", ""))]
    rows_tour = [("Направление", "%s, %s" % (tour.get("country", "—"), tour.get("region", "—"))),
                 ("Отель", "%s %s" % (tour.get("hotel", "—"), "★" * int(tour.get("stars") or 0))),
                 ("Дата вылета / ночей", "%s / %s" % (tour.get("date", "—"), tour.get("nights", "—"))),
                 ("Стоимость", "%s %s" % (fmt(tour.get("price")), tour.get("currency", "KZT")))]

    def table(rows):
        return "".join('<tr><td class="l">%s</td><td>%s</td></tr>' % (a, b) for a, b in rows)

    html = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Договор %s</title>
<style>body{font:14px/1.6 Georgia,serif;color:#1a1a1a;max-width:760px;margin:40px auto;padding:0 20px;position:relative}
h1{font-size:20px;text-align:center}h2{font-size:15px;margin:22px 0 8px}
table{width:100%%;border-collapse:collapse;margin:8px 0}td{border:1px solid #bbb;padding:7px 10px}td.l{width:42%%;color:#555}
.wm{position:fixed;top:38%%;left:8%%;font-size:64px;color:rgba(200,40,40,.13);transform:rotate(-18deg);font-weight:bold;pointer-events:none}
.sig{display:flex;gap:40px;margin-top:44px}.sig div{flex:1;border-top:1px solid #333;padding-top:6px;font-size:12.5px;color:#444}
.meta{color:#666;font-size:12.5px;text-align:center}.foot{margin-top:26px;font-size:11.5px;color:#888}</style></head><body>
<div class="wm">ОБРАЗЕЦ · ТЕСТ</div>
<h1>ДОГОВОР № %s<br>на оказание туристских услуг</h1>
<p class="meta">г. Алматы · %s</p>
<p><b>%s</b> (далее — «Агентство») и <b>%s</b> (далее — «Турист») заключили настоящий договор о нижеследующем.</p>
<h2>1. Турист</h2><table>%s</table>
<h2>2. Туристский продукт</h2><table>%s</table>
<h2>3. Условия (тестовый шаблон)</h2>
<p>3.1. Агентство бронирует и оплачивает туристский продукт у туроператора. 3.2. Стоимость включает перелёт, проживание и трансфер, если не указано иное. 3.3. Настоящий документ — <b>демонстрационный образец</b>: юридический текст заменяется шаблоном агентства при внедрении.</p>
<div class="sig"><div>Агентство: ______________ / %s /</div><div>Турист: ______________ / %s /</div></div>
<p class="foot">Сформировано автоматически платформой Extella · Travel Agency pack · %s. Данные извлечены из паспорта машиночитаемой зоной (MRZ) и подтверждены менеджером.</p>
</body></html>""" % (num, num, today, agency, fio, table(rows_client), table(rows_tour),
                     ta_conf.get("manager_name", agency), fio, today)

    od = os.path.expanduser(out_dir if out_dir and not str(out_dir).startswith("{{") else "~/extella-plugins/extella_travel_agency/contracts")
    os.makedirs(od, exist_ok=True)
    fname = "contract_%s.html" % num
    fpath = os.path.join(od, fname)
    open(fpath, "w", encoding="utf-8").write(html)
    return json.dumps({"status": "success", "contract_no": num, "file": fpath,
                       "url": "http://127.0.0.1:8766/contracts/" + fname,
                       "client": fio, "tour": tour, "note": "ОБРАЗЕЦ: юр. текст заменяется шаблоном агентства"}, ensure_ascii=False)