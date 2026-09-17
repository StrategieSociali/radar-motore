#!/usr/bin/env python3
"""esplodi.py - legge i comandi N:tipo arrivati in reply al recap del Radar.
Tre sottocomandi:
  comandi  uscita.json [--da-file updates.json] [--ore N] [--max N]
  conferma UPDATE_ID
  nome     N TIPO "titolo della notizia"
Solo libreria standard. Scarica sempre con curl.

Token e chat id si leggono dall'ambiente, mai dalla riga di comando:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

"comandi" e' in SOLA LETTURA: non conferma niente, quindi si puo' rilanciare
quante volte serve e i comandi restano disponibili. Telegram li tiene 24 ore.
"conferma" e' l'unica operazione che li consuma: va chiamata solo dopo che il
contenuto e' stato consegnato.
"""
import sys, os, json, re, subprocess, unicodedata
from datetime import datetime, timezone

TIPI = ("short", "videolungo", "articolo", "newsletter")
MARCA_RECAP = "RISPONDI A QUESTO MESSAGGIO"
MAX_COMANDI = 5
ORE = 24


def api(metodo, query=""):
    """Chiama l'API del bot. Ritorna il campo result, o None."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("manca TELEGRAM_TOKEN nell'ambiente", file=sys.stderr)
        return None
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    if query:
        url += "?" + query
    cmd = ["curl", "-sS", "--max-time", "30", "--retry", "1", "--retry-delay", "2", url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
    except Exception:
        return None
    try:
        d = json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return None
    if not d.get("ok"):
        print("risposta non ok:", str(d)[:200], file=sys.stderr)
        return None
    return d.get("result")


def u16(s):
    """Lunghezza in unita' UTF-16, che e' come Telegram conta le posizioni."""
    return len((s or "").encode("utf-16-le")) // 2


def taglia16(s, inizio, quante):
    b = (s or "").encode("utf-16-le")
    return b[inizio * 2:(inizio + quante) * 2].decode("utf-16-le", "replace")


def righe_con_posizione(testo):
    """Ogni riga con il suo intervallo in unita' UTF-16."""
    fuori = []
    cursore = 0
    for riga in (testo or "").split("\n"):
        larghezza = u16(riga)
        fuori.append((riga, cursore, cursore + larghezza))
        cursore += larghezza + 1  # il \n conta uno
    return fuori


def link_della_riga(citato, n):
    """Titolo e link della notizia n, presi dal messaggio citato."""
    testo = citato.get("text") or citato.get("caption") or ""
    entita = citato.get("entities") or citato.get("caption_entities") or []
    attacco = re.compile(r"^\s*%d\s*[.)\-:]" % n)
    for riga, inizio, fine in righe_con_posizione(testo):
        if not attacco.match(riga):
            continue
        for e in entita:
            off = e.get("offset", -1)
            if off < inizio or off >= fine:
                continue
            if e.get("type") == "text_link" and e.get("url"):
                return taglia16(testo, off, e.get("length", 0)).strip(), e["url"]
            if e.get("type") == "url":
                u = taglia16(testo, off, e.get("length", 0)).strip()
                ripulita = re.sub(r"^\s*\d+\s*[.)\-:]\s*", "", riga).replace(u, "").strip()
                return ripulita[:200], u
        return None, None  # la riga c'e' ma non ha link: non inventarlo
    return None, None


def normalizza_tipo(t):
    t = re.sub(r"[^a-z]", "", (t or "").lower())
    if t in ("videolungo", "video", "lungo"):
        return "videolungo"
    return t if t in TIPI else None


def leggi_comandi(aggiornamenti, chat_atteso, ore, massimo):
    adesso = datetime.now(timezone.utc).timestamp()
    trovati, scartati = [], []
    schema = re.compile(r"^\s*(\d{1,2})\s*:\s*([A-Za-z \-]{3,20})\s*$")
    for u in aggiornamenti:
        m = u.get("message") or u.get("edited_message")
        if not m:
            continue
        uid = u.get("update_id")
        chat = str((m.get("chat") or {}).get("id", ""))
        testo = (m.get("text") or "").strip()
        if chat_atteso and chat != str(chat_atteso):
            scartati.append({"update_id": uid, "motivo": "chat estranea", "testo": testo[:60]})
            continue
        if ore and (adesso - m.get("date", 0)) > ore * 3600:
            scartati.append({"update_id": uid, "motivo": "fuori finestra", "testo": testo[:60]})
            continue
        s = schema.match(testo)
        if not s:
            continue  # chiacchiere normali, non un comando: non e' uno scarto
        citato = m.get("reply_to_message")
        if not citato:
            scartati.append({"update_id": uid, "motivo": "non e' una risposta al recap",
                             "testo": testo[:60]})
            continue
        if MARCA_RECAP not in (citato.get("text") or ""):
            scartati.append({"update_id": uid, "motivo": "risponde a un messaggio che non e' un recap",
                             "testo": testo[:60]})
            continue
        tipo = normalizza_tipo(s.group(2))
        if not tipo:
            scartati.append({"update_id": uid, "motivo": "tipo sconosciuto, ammessi " + ", ".join(TIPI),
                             "testo": testo[:60]})
            continue
        n = int(s.group(1))
        titolo, link = link_della_riga(citato, n)
        if not link:
            scartati.append({"update_id": uid, "motivo": "numero %d non trovato nel recap citato" % n,
                             "testo": testo[:60]})
            continue
        trovati.append({"update_id": uid, "n": n, "tipo": tipo, "titolo": titolo, "link": link,
                        "data": datetime.fromtimestamp(m.get("date", 0), timezone.utc).isoformat(),
                        "recap_message_id": citato.get("message_id")})
    trovati.sort(key=lambda c: c["update_id"])
    unici, visti = [], set()
    for c in trovati:
        chiave = (c["n"], c["tipo"], c["recap_message_id"])
        if chiave in visti:
            scartati.append({"update_id": c["update_id"], "motivo": "ripetizione dello stesso comando",
                             "testo": "%d:%s" % (c["n"], c["tipo"])})
            continue
        visti.add(chiave)
        unici.append(c)
    return unici[:massimo], scartati


def comandi(percorso_uscita, da_file, ore, massimo):
    if da_file:
        with open(da_file, encoding="utf-8") as f:
            grezzo = json.load(f)
        aggiornamenti = grezzo.get("result", grezzo) if isinstance(grezzo, dict) else grezzo
    else:
        aggiornamenti = api("getUpdates", "limit=100&timeout=0")
        if aggiornamenti is None:
            print("Telegram non risponde: nessun comando letto", file=sys.stderr)
            sys.exit(1)
    trovati, scartati = leggi_comandi(aggiornamenti, os.environ.get("TELEGRAM_CHAT_ID", ""),
                                      ore, massimo)
    fuori = {"generato": datetime.now(timezone.utc).isoformat(),
             "finestra_ore": ore, "totale": len(trovati),
             "comandi": trovati, "scartati": scartati}
    with open(percorso_uscita, "w", encoding="utf-8") as f:
        json.dump(fuori, f, ensure_ascii=False, indent=1)
    print("trovati %d comandi, %d scartati (sola lettura, niente confermato)"
          % (len(trovati), len(scartati)))


def conferma(update_id):
    r = api("getUpdates", "offset=%d&limit=1&timeout=0" % (int(update_id) + 1))
    if r is None:
        print("conferma fallita: i comandi restano disponibili", file=sys.stderr)
        sys.exit(1)
    print("confermato fino a %s compreso" % update_id)


def nome(n, tipo, titolo):
    t = unicodedata.normalize("NFKD", (titolo or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    oggi = datetime.now().strftime("%Y-%m-%d")
    print("%s-%02d-%s-%s.md" % (oggi, int(n), tipo, t[:60] or "senza-titolo"))


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "comandi":
        da_file = a[a.index("--da-file") + 1] if "--da-file" in a else None
        ore = int(a[a.index("--ore") + 1]) if "--ore" in a else ORE
        massimo = int(a[a.index("--max") + 1]) if "--max" in a else MAX_COMANDI
        comandi(a[1], da_file, ore, massimo)
    elif len(a) == 2 and a[0] == "conferma":
        conferma(a[1])
    elif len(a) == 4 and a[0] == "nome":
        nome(a[1], a[2], a[3])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
