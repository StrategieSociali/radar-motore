#!/usr/bin/env python3
"""radar.py - raccolta feed RSS/Atom e rendering della rassegna.
Due sottocomandi:
  raccogli fonti.json candidati.json [--con-b] [--ore N]
  render   rassegna.json rassegna.html
Solo libreria standard. Scarica sempre con curl.
"""
import sys, os, json, re, html, subprocess, unicodedata
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
MAX_PER_FEED = 40
MAX_TOTALE = 80
MAX_ESTRATTO = 350


def scarica(url):
    """Ritorna il corpo della risposta, o None se la fonte non collabora."""
    cmd = ["curl", "-sSL", "-A", UA,
           "-H", "Accept: application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
           "-H", "Accept-Language: it-IT,it;q=0.9",
           "--max-time", "20", "--retry", "1", "--retry-delay", "2",
           "-w", "\n%{http_code}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception:
        return None
    corpo = r.stdout.decode("utf-8", "replace")
    taglio = corpo.rfind("\n")
    if taglio < 0:
        return None
    testo, codice = corpo[:taglio], corpo[taglio + 1:].strip()
    if codice != "200" or ("<item" not in testo and "<entry" not in testo):
        return None
    return testo


def pulisci(t):
    if not t:
        return ""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def leggi_data(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def tag(e):
    return e.tag.split("}")[-1].lower()


def campo(nodo, nomi):
    for f in nodo:
        if tag(f) in nomi and (f.text or "").strip():
            return f.text.strip()
    return ""


def link_di(nodo):
    for f in nodo:
        if tag(f) == "link":
            if (f.text or "").strip():
                return f.text.strip()
            href = f.get("href")
            rel = (f.get("rel") or "alternate").lower()
            if href and rel == "alternate":
                return href.strip()
    for f in nodo:
        if tag(f) in ("guid", "id") and (f.text or "").strip().startswith("http"):
            return f.text.strip()
    return ""


def normalizza(u):
    u = re.sub(r"[?#].*$", "", (u or "").strip().lower())
    return u.rstrip("/")


def chiave_titolo(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return " ".join(t.split())[:70]


def analizza(xml_testo, url):
    try:
        radice = ET.fromstring(xml_testo.encode("utf-8", "replace"))
    except ET.ParseError:
        ripulito = re.sub(r"^[^<]+", "", xml_testo)
        try:
            radice = ET.fromstring(ripulito.encode("utf-8", "replace"))
        except ET.ParseError:
            return None, []
    nome = ""
    for n in radice.iter():
        if tag(n) == "channel" or tag(n) == "feed":
            nome = campo(n, {"title"})
            break
    if not nome:
        nome = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])
    voci = []
    for n in radice.iter():
        if tag(n) not in ("item", "entry"):
            continue
        titolo = pulisci(campo(n, {"title"}))
        collegamento = link_di(n)
        data = leggi_data(campo(n, {"pubdate", "published", "updated", "date"}))
        testo = pulisci(campo(n, {"description", "summary", "encoded", "content"}))
        if not titolo or not collegamento:
            continue
        voci.append({"fonte": pulisci(nome), "titolo": titolo,
                     "link": collegamento, "data": data, "estratto": testo})
        if len(voci) >= MAX_PER_FEED:
            break
    return nome, voci


def raccogli(percorso_fonti, percorso_uscita, con_b, ore):
    fonti = json.load(open(percorso_fonti, encoding="utf-8"))
    adesso = datetime.now(timezone.utc)
    if ore is None:
        ore = 72 if adesso.weekday() == 0 else 24
    limite = adesso - timedelta(hours=ore)

    lavoro = [(u, None) for u in fonti.get("A", [])]
    lavoro += [(f["url"], [p.lower() for p in f.get("parole", [])])
               for f in fonti.get("A_filtrate", [])]
    if con_b:
        lavoro += [(u, None) for u in fonti.get("B", [])]

    tenuti, falliti, visti_url, visti_titolo = [], [], set(), set()
    for url, parole in lavoro:
        corpo = scarica(url)
        if corpo is None:
            falliti.append(url)
            continue
        _, voci = analizza(corpo, url)
        if not voci:
            falliti.append(url)
            continue
        for v in voci:
            if v["data"] is None or v["data"] < limite or v["data"] > adesso + timedelta(hours=6):
                continue
            nu, nt = normalizza(v["link"]), chiave_titolo(v["titolo"])
            if nu in visti_url or (nt and nt in visti_titolo):
                continue
            if parole:
                campo_testo = (v["titolo"] + " " + v["estratto"]).lower()
                if not any(p in campo_testo for p in parole):
                    continue
            visti_url.add(nu)
            if nt:
                visti_titolo.add(nt)
            tenuti.append({"fonte": v["fonte"], "titolo": v["titolo"],
                           "link": v["link"],
                           "data": v["data"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                           "estratto": v["estratto"][:MAX_ESTRATTO]})

    tenuti.sort(key=lambda x: x["data"], reverse=True)
    tenuti = tenuti[:MAX_TOTALE]
    for i, v in enumerate(tenuti, 1):
        v["id"] = i
    uscita = {"generato": adesso.strftime("%Y-%m-%d %H:%M UTC"),
              "finestra_ore": ore, "totale": len(tenuti),
              "items": tenuti, "fonti_fallite": falliti}
    json.dump(uscita, open(percorso_uscita, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"raccolte {len(tenuti)} voci nelle ultime {ore} ore, "
          f"{len(falliti)} fonti fallite")
    if falliti:
        print("fallite: " + ", ".join(falliti))


STILE = """
:root{--sf:#fbfaf7;--ca:#fff;--te:#1c1c1a;--se:#5f5c55;--bo:#e4e0d7;--ac:#1f6f5c;--op:#8a5a1f}
@media (prefers-color-scheme:dark){:root{--sf:#16181a;--ca:#1e2124;--te:#e9e7e2;--se:#a3a099;--bo:#32363a;--ac:#5fbfa3;--op:#d9a34a}}
*{box-sizing:border-box}
body{margin:0;padding:18px 14px 60px;background:var(--sf);color:var(--te);
 font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 max-width:760px;margin-inline:auto;-webkit-text-size-adjust:100%}
h1{font-size:1.35rem;margin:0 0 2px;letter-spacing:-.01em}
.meta{color:var(--se);font-size:.82rem;margin-bottom:18px}
.filo{background:var(--ca);border:1px solid var(--bo);border-left:3px solid var(--ac);
 border-radius:8px;padding:12px 14px;margin-bottom:22px}
.filo b{display:block;font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;
 color:var(--ac);margin-bottom:5px}
article{background:var(--ca);border:1px solid var(--bo);border-radius:8px;
 padding:14px 15px;margin-bottom:14px;overflow-wrap:anywhere}
.n{color:var(--se);font-size:.8rem}
h2{font-size:1.03rem;margin:3px 0 6px;line-height:1.3}
h2 a{color:var(--te);text-decoration:none;border-bottom:1px solid var(--bo)}
.fonte{color:var(--se);font-size:.78rem;margin-bottom:9px}
.tg{display:inline-block;font-size:.66rem;letter-spacing:.07em;padding:2px 7px;
 border-radius:99px;border:1px solid var(--bo);color:var(--se);vertical-align:2px}
.perche{margin:0 0 11px}
.box{border-top:1px solid var(--bo);padding-top:10px;font-size:.93rem}
.box b{display:block;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;
 color:var(--ac);margin-bottom:4px}
.box.opp b{color:var(--op)}
.box.opp .k{font-weight:600}
.fmt{color:var(--se);font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
.tit{font-weight:600;margin:2px 0 4px}
footer{color:var(--se);font-size:.78rem;margin-top:26px;border-top:1px solid var(--bo);
 padding-top:12px}
details{margin-top:8px}summary{cursor:pointer}
"""


def render(percorso_dati, percorso_html):
    d = json.load(open(percorso_dati, encoding="utf-8"))
    e = html.escape
    p = ['<meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>Rassegna {e(d.get("data",""))}</title>',
         f"<style>{STILE}</style>",
         f'<h1>Rassegna del {e(d.get("data",""))}</h1>',
         f'<div class="meta">{len(d.get("items",[]))} notizie, '
         f'finestra {e(str(d.get("finestra_ore","24")))} ore</div>']
    filo = (d.get("argomento_trovato") or "").strip()
    if filo:
        p.append(f'<div class="filo"><b>Argomento trovato</b>{e(filo)}</div>')
    for it in d.get("items", []):
        p.append("<article>")
        p.append(f'<div class="n">{e(str(it.get("n","")))}. '
                 f'<span class="tg">{e(it.get("tag",""))}</span></div>')
        p.append(f'<h2><a href="{e(it.get("link","#"))}">{e(it.get("titolo",""))}</a></h2>')
        p.append(f'<div class="fonte">{e(it.get("fonte",""))} · {e(it.get("data",""))}</div>')
        p.append(f'<p class="perche">{e(it.get("perche_conta",""))}</p>')
        idea = it.get("idea") or {}
        if any(idea.values()):
            p.append('<div class="box"><b>Idea</b>'
                     f'<div class="fmt">{e(idea.get("formato",""))}</div>'
                     f'<div class="tit">{e(idea.get("titolo",""))}</div>'
                     f'<div>{e(idea.get("angolo",""))}</div></div>')
        opp = it.get("opportunita") or {}
        if any(opp.values()):
            righe = [("Ente", opp.get("ente","")), ("Cosa cerca", opp.get("cosa_cerca","")),
                     ("Scadenza", opp.get("scadenza","")), ("Primo passo", opp.get("primo_passo",""))]
            corpo = "".join(f'<div><span class="k">{e(k)}:</span> {e(v)}</div>'
                        for k, v in righe if v)
            p.append(f'<div class="box opp"><b>Opportunità</b>{corpo}</div>')
        p.append("</article>")
    coda = []
    if d.get("fonti_fallite"):
        coda.append("Fonti non raggiungibili: " + e(", ".join(d["fonti_fallite"])))
    if d.get("anomalie"):
        coda.append("Anomalie: " + e("; ".join(d["anomalie"])))
    coda.append("Per esplodere una notizia, rispondi al messaggio del recap su "
                "Telegram con il numero seguito da : e dal tipo di contenuto.")
    p.append("<footer>" + "<br>".join(coda) +
             "<details><summary>dati grezzi</summary><pre>" +
             e(json.dumps(d, ensure_ascii=False, indent=1)) + "</pre></details></footer>")
    open(percorso_html, "w", encoding="utf-8").write("\n".join(p))
    print(f"scritto {percorso_html} ({len(d.get('items',[]))} notizie)")


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "raccogli":
        ore = None
        if "--ore" in a:
            ore = int(a[a.index("--ore") + 1])
        raccogli(a[1], a[2], "--con-b" in a, ore)
    elif len(a) >= 3 and a[0] == "render":
        render(a[1], a[2])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
