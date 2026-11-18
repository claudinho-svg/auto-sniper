#!/usr/bin/env python3
"""
Auto-sniper: meldt nieuwe auto-zoekertjes van 2dehands, Marktplaats en
AutoScout24 in Telegram, met foto, dealscore en scamfilter.

Bediening via Telegram:
  volkswagen golf     -> knoppen: brandstof, carrosserie, schakelbak,
                         bouwjaar, km-stand, prijs, afstand, platformen
  alle merken         -> zoeken zonder merk (bv. alleen SUV's tot 10.000)
  lijst / stop 2 / help

Draaien:
  python3 autobot.py --duur 14   (GitHub Actions: 14 min, check elke minuut)
  python3 autobot.py --loop 60   (eigen computer)

Omgevingsvariabelen: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, POSTCODE,
LOCATIE="lat,lon", optioneel AS24_LAND (standaard "B" = Belgie).
Alleen de standaardbibliotheek van Python, niets te installeren.
"""
import argparse
import html
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "state.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
CHECK_EVERY = 60                 # seconden tussen twee zoekrondes
MAX_ALERTS_PER_ROUND = 20
ERROR_NOTIFY_EVERY = 24 * 3600
DELETE_AFTER = 24 * 3600

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
POSTCODE = os.environ.get("POSTCODE", "").strip()
AS24_LAND = os.environ.get("AS24_LAND", "B").strip() or "B"
try:
    HOME = tuple(float(x) for x in os.environ.get("LOCATIE", "").split(","))[:2] or None
except ValueError:
    HOME = None

SITES = {"2dehands": "https://www.2dehands.be", "marktplaats": "https://www.marktplaats.nl",
         "autoscout24": "https://www.autoscout24.be"}
SITE_NAMES = {"2dehands": "2dehands", "marktplaats": "Marktplaats", "autoscout24": "AutoScout24"}

# merk -> categorie-id op 2dehands en Marktplaats (zelfde nummers)
BRANDS = {
    "Abarth": 2932, "Aiways": 3217, "Aixam": 2152, "Alfa Romeo": 92, "Alpina": 2937,
    "Alpine": 2936, "Aston Martin": 2153, "Audi": 93, "Austin": 2154, "Bentley": 2148,
    "BMW": 96, "Buick": 97, "Bugatti": 2938, "BYD": 3213, "Cadillac": 98, "Chery": 3243,
    "Chevrolet": 99, "Chrysler": 100, "Citroën": 101, "Cupra": 3051, "Dacia": 2660,
    "Daewoo": 103, "Daihatsu": 105, "DFSK": 3239, "Dodge": 108, "Dongfeng": 3227,
    "Donkervoort": 109, "DS": 2933, "Ferrari": 110, "Fiat": 111, "Fisker": 2829, "Ford": 112,
    "Geely": 3242, "Genesis": 3223, "GMC": 2949, "Honda": 114, "Hummer": 2149,
    "Hongqi": 3221, "Hyundai": 115, "Infiniti": 2659, "Isuzu": 3212, "Jaecoo": 3240,
    "Jaguar": 117, "Jeep": 118, "Kia": 119, "Lada": 2155, "Lamborghini": 122, "Lancia": 123,
    "Land Rover": 124, "Leapmotor": 3226, "Lexus": 125, "Lincoln": 2150, "Lotus": 127,
    "Lucid": 3218, "Lynk & Co": 3211, "Maserati": 128, "Maxus": 3238, "Mazda": 129,
    "McLaren": 2935, "Mercedes-Benz": 130, "MG": 132, "Mini": 133, "Mitsubishi": 134,
    "NIO": 3214, "Nissan": 135, "Omoda": 3241, "Opel": 138, "Peugeot": 140, "Polestar": 2934,
    "Porsche": 144, "Renault": 146, "Rolls-Royce": 2156, "Rover": 147, "Saab": 148,
    "Seat": 150, "Skoda": 151, "Smart": 152, "SsangYong": 2151, "Subaru": 153, "Suzuki": 154,
    "Tesla": 2830, "Toyota": 155, "Triumph": 156, "Vinfast": 3216, "Volkswagen": 157,
    "Volvo": 158, "XPENG": 3215, "ZEEKR": 3224,
}
BRAND_ALIASES = {"vw": "Volkswagen", "volkswagen": "Volkswagen", "mercedes": "Mercedes-Benz",
                 "merc": "Mercedes-Benz", "benz": "Mercedes-Benz", "alfa": "Alfa Romeo",
                 "landrover": "Land Rover", "range rover": "Land Rover", "citroen": "Citroën",
                 "rolls royce": "Rolls-Royce", "lynk": "Lynk & Co", "ds": "DS"}

FUELS = {"benzine": "⛽ Benzine", "diesel": "🛢️ Diesel", "elektrisch": "🔌 Elektrisch",
         "hybride": "🔋 Hybride", "lpg": "LPG/CNG"}
AS24_FUEL = {"benzine": "B", "diesel": "D", "elektrisch": "E", "hybride": "2,3", "lpg": "L,C"}
BODIES = {"hatchback": "Hatchback", "break": "Break", "suv": "SUV/4x4", "sedan": "Sedan",
          "coupe": "Coupé", "cabrio": "Cabrio", "mpv": "MPV", "bestel": "Bestelwagen"}
AS24_BODY = {"hatchback": "1", "cabrio": "2", "coupe": "3", "suv": "4", "break": "5",
             "sedan": "6", "mpv": "12", "bestel": "13"}
GEARS = {"manueel": "Manueel", "automaat": "Automaat"}

SCAM_WORDS = [
    "whatsapp", "whats app", "wa.me", "telegram", "vooruitbetal", "vooraf betal",
    "voorschot", "western union", "moneygram", "friends and family", "vrienden en familie",
    "gestolen", "zonder papieren", "geen papieren", "export only", "alleen export",
]

SENT_LOG = []


# ================================================================ status

def load_state():
    state = {"searches": [], "seen": {}, "maxid": {}, "alerted": [], "fingerprints": {},
             "update_offset": 0, "next_id": 1, "last_error_notice": 0, "sent": [], "draft": None}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            state.update(json.load(f))
    renumber(state)
    return state


def save_state(state):
    state["sent"].extend(SENT_LOG)
    SENT_LOG.clear()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def renumber(state):
    for n, s in enumerate(state["searches"], 1):
        s["id"] = n


# ================================================================ http / telegram

def http_get(url, accept="application/json", timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Accept-Language": "nl-BE,nl;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def tg(method, **params):
    for k, v in list(params.items()):
        if isinstance(v, (dict, list)):
            params[k] = json.dumps(v)
    data = urllib.parse.urlencode(params).encode()
    wait = int(params.get("timeout", 0))
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=wait + 30) as r:
        return json.load(r)


def _log_sent(res):
    mid = res["result"]["message_id"]
    SENT_LOG.append([mid, time.time()])
    return mid


def send(text, buttons=None, preview=False):
    params = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": not preview}}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    try:
        return _log_sent(tg("sendMessage", **params))
    except urllib.error.HTTPError as e:
        print(f"Telegram-fout: {e} {e.read()[:300]!r}", file=sys.stderr)
    except Exception as e:
        print(f"Telegram-fout: {e}", file=sys.stderr)
    return None


def send_photo(photo, caption, buttons=None):
    params = {"chat_id": CHAT_ID, "photo": photo, "caption": caption, "parse_mode": "HTML"}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    try:
        return _log_sent(tg("sendPhoto", **params))
    except Exception as e:  # foto niet bereikbaar: dan als gewoon bericht
        print(f"Foto lukte niet ({e}), stuur tekst", file=sys.stderr)
        return send(caption, buttons, preview=True)


def edit(message_id, text, buttons=None):
    params = {"chat_id": CHAT_ID, "message_id": message_id, "text": text,
              "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
    if buttons is not None:
        params["reply_markup"] = {"inline_keyboard": buttons}
    try:
        tg("editMessageText", **params)
    except Exception as e:
        print(f"Bewerken mislukt: {e}", file=sys.stderr)


def cleanup_messages(state):
    now, keep = time.time(), []
    for mid, ts in state.get("sent", []):
        if now - ts < DELETE_AFTER:
            keep.append([mid, ts])
        elif now - ts < 47 * 3600:
            try:
                tg("deleteMessage", chat_id=CHAT_ID, message_id=mid)
            except Exception:
                pass
    state["sent"] = keep


# ================================================================ normaliseren

def norm_fuel(v):
    v = (v or "").lower()
    if not v:
        return None
    if "hybr" in v or "/" in v or "plug-in" in v:
        return "hybride"
    if "elektr" in v or "electr" in v:
        return "elektrisch"
    if "diesel" in v:
        return "diesel"
    if "benzine" in v or "petrol" in v:
        return "benzine"
    if "lpg" in v or "cng" in v or "aardgas" in v:
        return "lpg"
    return None


def norm_body(v):
    v = (v or "").lower()
    for key, words in (("cabrio", ("cabrio", "roadster")), ("coupe", ("coup",)),
                       ("suv", ("suv", "terrein", "4x4", "pick-up", "pickup")),
                       ("break", ("break", "station")), ("sedan", ("sedan", "berline", "limousine")),
                       ("mpv", ("mpv", "monovolume")), ("bestel", ("bestel", "transporter")),
                       ("hatchback", ("hatch", "stads", "compact"))):
        if any(w in v for w in words):
            return key
    return None


def norm_gear(v):
    v = (v or "").lower()
    if "auto" in v:
        return "automaat"
    if "hand" in v or "manu" in v:
        return "manueel"
    return None


def to_int(v):
    digits = re.sub(r"\D", "", str(v or ""))
    return int(digits) if digits else None


def slug(s):
    s = (s or "").lower().replace("ë", "e").replace("é", "e").replace("&", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + \
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# ================================================================ sites

def search_lrp(site, s):
    """2dehands en Marktplaats (zelfde systeem)."""
    query = " ".join(x for x in (s.get("make"), s.get("model")) if x)
    base = [("l1CategoryId", 91), ("query", query), ("limit", 100),
            ("sortBy", "SORT_INDEX"), ("sortOrder", "DECREASING"), ("viewOptions", "list-view")]
    if s.get("year_min") or s.get("year_max"):
        base.append(("attributeRanges[]", f"constructionYear:{s.get('year_min') or 'null'}:"
                                          f"{s.get('year_max') or 'null'}"))
    if s.get("km_max"):
        base.append(("attributeRanges[]", f"mileage:null:{s['km_max']}"))
    if s.get("dist") and POSTCODE and site == "2dehands":
        base += [("postcode", POSTCODE), ("distanceMeters", int(s["dist"] * 1000))]
    items, regular = [], 0
    for offset in (0, 100):
        url = SITES[site] + "/lrp/api/search?" + urllib.parse.urlencode(base + [("offset", offset)])
        data = json.loads(http_get(url))
        listings = data.get("listings", [])
        for l in listings:
            if not l.get("itemId"):
                continue
            attrs = {a.get("key"): a.get("value") for a in l.get("attributes") or []}
            pi = l.get("priceInfo") or {}
            loc = l.get("location") or {}
            pics = l.get("pictures") or []
            dist = None
            if site == "2dehands" and (loc.get("distanceMeters") or -1) >= 0 and s.get("dist"):
                dist = loc["distanceMeters"] / 1000
            elif HOME and loc.get("latitude"):
                dist = haversine(HOME, (loc["latitude"], loc["longitude"]))
            top = (l.get("priorityProduct") or "NONE") != "NONE"
            regular += not top
            items.append({
                "id": l["itemId"], "site": site, "cat": l.get("categoryId"),
                "title": (l.get("title") or "").strip(), "desc": l.get("description") or "",
                "model": attrs.get("model") or "",
                "price": (pi.get("priceCents") or 0) / 100 or None, "price_type": pi.get("priceType", ""),
                "year": to_int(attrs.get("constructionYear")), "km": to_int(attrs.get("mileage")),
                "fuel": norm_fuel(attrs.get("fuel")), "body": norm_body(attrs.get("body")),
                "gear": norm_gear(attrs.get("transmission")),
                "city": loc.get("cityName", ""), "dist": dist,
                "url": SITES[site] + l.get("vipUrl", ""),
                "photo": pics[0].get("largeUrl") if pics else None,
                "deal": None, "skip_new": False,
            })
        if regular >= 25 or len(listings) < 100:
            break  # genoeg gewone (niet-betaalde) zoekertjes gezien
    return items


AS24_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def search_as24(s):
    params = [("sort", "age"), ("desc", 1), ("atype", "C"), ("cy", AS24_LAND), ("ustate", "N,U")]
    if s.get("year_min"):
        params.append(("fregfrom", s["year_min"]))
    if s.get("year_max"):
        params.append(("fregto", s["year_max"]))
    if s.get("km_max"):
        params.append(("kmto", s["km_max"]))
    if s.get("price_min"):
        params.append(("pricefrom", int(s["price_min"])))
    if s.get("price_max"):
        params.append(("priceto", int(s["price_max"])))
    if s.get("fuels"):
        params.append(("fuel", ",".join(AS24_FUEL[f] for f in s["fuels"])))
    if s.get("bodies"):
        params.append(("body", ",".join(AS24_BODY[b] for b in s["bodies"])))
    if s.get("gear"):
        params.append(("gear", "A" if s["gear"] == "automaat" else "M"))
    if s.get("dist") and POSTCODE:
        params += [("zip", POSTCODE), ("zipr", int(s["dist"]))]
    q = "?" + urllib.parse.urlencode(params)
    paths = []
    if s.get("make"):
        if s.get("model"):
            paths.append(f"/nl/lst/{slug(s['make'])}/{slug(s['model'])}")
        paths.append(f"/nl/lst/{slug(s['make'])}")
    else:
        paths.append("/nl/lst")
    page = None
    for p in paths:  # model-naam onbekend bij AutoScout24? dan alleen merk + zelf filteren
        try:
            page = http_get(SITES["autoscout24"] + p + q, accept="text/html")
            break
        except urllib.error.HTTPError as e:
            if e.code != 404 or p == paths[-1]:
                raise
    m = AS24_NEXT.search(page or "")
    if not m:
        raise RuntimeError("geen resultaten gevonden in de pagina")
    listings = json.loads(m.group(1))["props"]["pageProps"].get("listings") or []
    items = []
    for l in listings:
        v = l.get("vehicle") or {}
        tr = l.get("tracking") or {}
        loc = l.get("location") or {}
        sponsored = any(t.get("key") == "relevance_adjustment" and t.get("value") == "sponsored"
                        for t in l.get("trackingParameters") or [])
        imgs = l.get("images") or []
        photo = re.sub(r"/\d+x\d+\.webp$", "/720x540.jpg", imgs[0]) if imgs else None
        reg = tr.get("firstRegistration") or ""
        items.append({
            "id": "as" + l["id"], "site": "autoscout24", "cat": None,
            "title": " ".join(x for x in (v.get("make"), v.get("model"),
                                          v.get("modelVersionInput")) if x).strip(),
            "desc": v.get("subtitle") or "",
            "model": " ".join(x for x in (v.get("model"), v.get("modelGroup"), v.get("variant")) if x),
            "price": (l.get("price") or {}).get("priceRaw"), "price_type": "",
            "year": to_int(reg[-4:]) if reg else None, "km": to_int(tr.get("mileage")),
            "fuel": norm_fuel(v.get("fuel")), "body": None, "gear": norm_gear(v.get("transmission")),
            "city": loc.get("city", ""), "dist": loc.get("distanceToSearchLocationInKm"),
            "url": SITES["autoscout24"] + (l.get("url") or ""), "photo": photo,
            "deal": tr.get("priceLabel"), "skip_new": sponsored,
            "seller": (l.get("seller") or {}).get("type"),
        })
    return items


def search_site(site, s):
    return search_as24(s) if site == "autoscout24" else search_lrp(site, s)


# ================================================================ filteren

def words_ok(words, text):
    t = (text or "").lower()
    for w in (words or "").lower().split():
        if not re.search(r"(?<![0-9])" + re.escape(w) + (r"(?![0-9])" if w[-1].isdigit() else ""), t):
            return False
    return True


def matches(s, i):
    text = f"{i['title']} {i['model']}"
    if s.get("make"):
        if i["cat"] is not None and BRANDS.get(s["make"]) and i["cat"] != BRANDS[s["make"]]:
            return False
        if i["site"] == "autoscout24" and not words_ok(s["make"].split()[0], i["title"]):
            return False
    if s.get("model") and not words_ok(s["model"], text):
        return False
    t = i["title"].lower()
    if any(w in t for w in s.get("exclude") or []):
        return False
    if s.get("fuels") and i["fuel"] and i["fuel"] not in s["fuels"]:
        return False
    if s.get("bodies") and i["body"] and i["body"] not in s["bodies"]:
        return False
    if s.get("gear") and i["gear"] and i["gear"] != s["gear"]:
        return False
    if s.get("year_min") and i["year"] and i["year"] < s["year_min"]:
        return False
    if s.get("year_max") and i["year"] and i["year"] > s["year_max"]:
        return False
    if s.get("km_max") and i["km"] and i["km"] > s["km_max"]:
        return False
    p = i["price"]
    if s.get("price_max") and p and p > s["price_max"]:
        return False
    if s.get("price_min") and p and p < s["price_min"]:
        return False
    if s.get("dist") and i["site"] != "2dehands":  # 2dehands filtert zelf al op afstand
        if i["dist"] is None or i["dist"] > s["dist"]:
            return False
    return True


def scam_word(i):
    text = f"{i['title']} {i['desc']}".lower()
    return next((w for w in SCAM_WORDS if w in text), None)


def typical_price(i, pool):
    """Mediaanprijs van vergelijkbare auto's (bouwjaar +-2) uit dezelfde zoekopdracht."""
    if not i["price"] or not i["year"]:
        return None
    prices = [x["price"] for x in pool if x["price"] and x["year"] and abs(x["year"] - i["year"]) <= 2]
    return statistics.median(prices) if len(prices) >= 5 else None


def euro(p):
    return f"€ {p:,.0f}".replace(",", ".")


def deal_line(i, pool):
    normal = typical_price(i, pool)
    if normal and i["price"] < normal * 0.45:
        return f"⚠️ Verdacht goedkoop (normaal ± {euro(normal)}) — mogelijk scam, opgelet!"
    if normal and i["price"] < normal * 0.8:
        pct = round((1 - i["price"] / normal) * 100)
        return f"🔥 Topdeal: {pct}% onder vergelijkbare auto's (± {euro(normal)})"
    if i.get("deal") == "top-price":
        return "🔥 AutoScout24: topprijs"
    if i.get("deal") == "good-price":
        return "👍 AutoScout24: goede prijs"
    return ""


def format_car(i, s, pool):
    if i["price"]:
        price = euro(i["price"])
        if i["price_type"] == "MIN_BID":
            price = f"Bieden vanaf {price}"
    else:
        price = {"FAST_BID": "Bieden", "BID": "Bieden", "SEE_DESCRIPTION": "Zie omschrijving",
                 "RESERVED": "Gereserveerd"}.get(i["price_type"], "Prijs op aanvraag")
    specs = [f"💶 {price}"]
    if i["year"]:
        specs.append(f"📅 {i['year']}")
    if i["km"] is not None:
        specs.append(f"🛣️ {i['km']:,} km".replace(",", "."))
    if i["fuel"]:
        specs.append(FUELS[i["fuel"]].split(" ", 1)[-1])
    if i["gear"]:
        specs.append(GEARS[i["gear"]])
    if i["body"]:
        specs.append(BODIES[i["body"]])
    where = html.escape(i["city"] or "")
    if i["dist"] is not None:
        where += f" ({i['dist']:.0f} km)"
    seller = " · handelaar" if i.get("seller") == "Dealer" else ""
    lines = [f"🚗 <b>{html.escape(i['title'][:90])}</b>",
             " · ".join(specs),
             f"📍 {where} · {SITE_NAMES[i['site']]}{seller}"]
    d = deal_line(i, pool)
    if d:
        lines.append(d)
    lines.append(f"🔎 {html.escape(s['label'])}")
    return "\n".join(lines)


def item_number(i):
    return to_int(i["id"]) or 0


def check_searches(state):
    sent, errors = 0, []
    alerted = state.setdefault("alerted", [])
    alerted_set = set(alerted)
    fps = state.setdefault("fingerprints", {})
    now = time.time()
    for k in [k for k, t in fps.items() if now - t > 7 * 86400]:
        del fps[k]
    for s in state["searches"]:
        key = str(s["uid"])
        seen = state["seen"].setdefault(key, [])
        seen_set = set(seen)
        top = state["maxid"].setdefault(key, {})
        before = dict(top)
        found = []
        for site in s["sites"]:
            try:
                found.extend(search_site(site, s))
            except Exception as e:
                errors.append(f"{site}: {e}")
                print(f"Fout bij {site} '{s['label']}': {e}", file=sys.stderr)
        new = []
        for i in found:
            if i["id"] in seen_set:
                continue
            seen_set.add(i["id"])
            seen.append(i["id"])
            if i["site"] == "autoscout24":
                fresh = s.get("primed") and not i["skip_new"]
            else:  # oplopende nummers: alleen hoger dan alles wat we al zagen is echt nieuw
                n = item_number(i)
                fresh = i["site"] in before and n > before[i["site"]]
            if fresh:
                new.append(i)
        for i in found:
            if i["site"] != "autoscout24":
                top[i["site"]] = max(top.get(i["site"], 0), item_number(i))
        state["seen"][key] = seen[-1500:]
        if not s.get("primed"):
            if found:
                s["primed"] = True
            continue
        pool = [i for i in found if matches(s, i) and not scam_word(i)]
        for i in new:
            if sent >= MAX_ALERTS_PER_ROUND or i["id"] in alerted_set or not matches(s, i):
                continue
            w = scam_word(i)
            if w:
                print(f"Scamfilter: '{i['title']}' overgeslagen ({w})")
                continue
            fp = f"{i['year']}-{i['km']}-{int(i['price'] or 0)}"
            if i["year"] and i["km"] and fp in fps:
                continue  # zelfde auto op een ander platform al gemeld
            alerted_set.add(i["id"])
            alerted.append(i["id"])
            if i["year"] and i["km"]:
                fps[fp] = now
            btns = [[{"text": f"🔗 Bekijk op {SITE_NAMES[i['site']]}", "url": i["url"]}]]
            caption = format_car(i, s, pool)
            if i["photo"]:
                send_photo(i["photo"], caption, btns)
            else:
                send(caption, btns)
            sent += 1
    state["alerted"] = alerted[-2000:]
    return sent, errors


# ================================================================ tekst & wizard

HELP = (
    "<b>🚗 Auto-sniper</b>\n"
    "Typ gewoon merk en model, bv. <code>volkswagen golf</code> of <code>bmw 3 reeks</code>. "
    "Daarna kies je met knoppen: brandstof, carrosserie, schakelbak, bouwjaar, km-stand, "
    "prijs, afstand en platformen.\n"
    "Zonder merk? Typ <code>alle merken</code>.\n"
    "Woorden uitsluiten: <code>golf -schade -export</code>\n\n"
    "<code>lijst</code> — je zoekopdrachten\n"
    "<code>stop 2</code> — zoekopdracht 2 verwijderen\n\n"
    "Je krijgt alleen auto's die er net bijkomen, met foto en 🔥 als de prijs duidelijk "
    "onder die van vergelijkbare auto's ligt. Verdachte zoekertjes filter ik eruit. "
    "Mijn berichten verdwijnen na 24 uur."
)


def parse_car(text):
    """'vw golf -schade' -> (merk, model, uitsluiten)."""
    words = text.split()
    excl = [w[1:].lower() for w in words if w.startswith("-") and len(w) > 1]
    t = " ".join(w for w in words if not (w.startswith("-") and len(w) > 1)).strip()
    low = t.lower()
    if low in ("alle merken", "alles", "alle", "*"):
        return None, None, excl
    names = {b.lower(): b for b in BRANDS}
    names.update(BRAND_ALIASES)
    for name in sorted(names, key=len, reverse=True):
        if low == name or low.startswith(name + " "):
            model = t[len(name):].strip() or None
            return names[name], model, excl
    return None, t or None, excl  # onbekend merk: alles als model/zoekwoord


def label_of(s):
    return " ".join(x for x in (s.get("make"), s.get("model")) if x) or "Alle merken"


def describe(s, with_nr=True):
    parts = []
    if s.get("fuels"):
        parts.append("/".join(FUELS[f].split(" ", 1)[-1] for f in s["fuels"]))
    if s.get("bodies"):
        parts.append("/".join(BODIES[b] for b in s["bodies"]))
    if s.get("gear"):
        parts.append(GEARS[s["gear"]])
    if s.get("year_min") or s.get("year_max"):
        parts.append(f"{s.get('year_min') or '…'}–{s.get('year_max') or 'nu'}")
    if s.get("km_max"):
        parts.append(f"max {s['km_max']:,} km".replace(",", "."))
    if s.get("price_min") or s.get("price_max"):
        lo = euro(s["price_min"]) if s.get("price_min") else ""
        hi = euro(s["price_max"]) if s.get("price_max") else ""
        parts.append(f"{lo}–{hi}" if lo and hi else (f"tot {hi}" if hi else f"vanaf {lo}"))
    if s.get("dist"):
        parts.append(f"binnen {s['dist']:g} km")
    if s.get("exclude"):
        parts.append("zonder " + ", ".join(s["exclude"]))
    sites = " + ".join(SITE_NAMES[x] for x in s["sites"])
    head = f"{s['id']}. " if with_nr else ""
    extra = (" · " + " · ".join(parts)) if parts else ""
    return f"{head}<b>{html.escape(label_of(s))}</b>{html.escape(extra)} ({sites})"


def run_command(state, text):
    if not text:
        return None
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""
    d = state.get("draft")
    if d and d.get("step") in ("year", "km", "price") and cmd not in ("lijst", "stop", "help"):
        if typed_answer(state, d, text):
            return None
    if cmd in ("start", "help"):
        return HELP
    if cmd == "lijst":
        if not state["searches"]:
            return "Nog geen zoekopdrachten. Typ bv. <code>volkswagen golf</code>"
        return "<b>Je zoekopdrachten</b>\n" + "\n".join(describe(s) for s in state["searches"])
    if cmd == "stop":
        if not arg.isdigit():
            return "Welke? Bv. <code>stop 2</code> (nummers zie je met <code>lijst</code>)"
        gone = [s for s in state["searches"] if s["id"] == int(arg)]
        if not gone:
            return f"Zoekopdracht {arg} bestaat niet. Zie <code>lijst</code>."
        state["searches"].remove(gone[0])
        for k in ("seen", "maxid"):
            state[k].pop(str(gone[0]["uid"]), None)
        renumber(state)
        rest = "\n".join(describe(s) for s in state["searches"]) or "Geen zoekopdrachten meer."
        return f"🗑️ {html.escape(label_of(gone[0]))} verwijderd.\n\n<b>Je zoekopdrachten</b>\n{rest}"
    make, model, excl = parse_car(text)
    start_draft(state, make, model, excl)
    return None


def btn(text, data):
    return {"text": text, "callback_data": data}


STEPS = ["fuel", "body", "gear", "year", "km", "price", "dist", "sites"]


def nav_row(d):
    return [btn("⏭️ Rest overslaan", "done"), btn("✖️ Annuleer", "cancel")]


def toggle_rows(options, chosen, prefix, per_row=2):
    rows, row = [], []
    for k, label in options.items():
        row.append(btn(("✅ " if k in chosen else "⬜ ") + label, f"{prefix}:{k}"))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def render(d):
    nr = STEPS.index(d["step"]) + 1
    head = f"🚗 <b>{html.escape(label_of(d))}</b>\nStap {nr}/{len(STEPS)} — "
    st = d["step"]
    if st == "fuel":
        rows = toggle_rows(FUELS, d["fuels"], "f")
        rows.append([btn("Verder ➡️", "next")])
        text = head + "Welke brandstof? (niets aangevinkt = alles)"
    elif st == "body":
        rows = toggle_rows(BODIES, d["bodies"], "b")
        rows.append([btn("Verder ➡️", "next")])
        text = head + "Welk type auto? (niets aangevinkt = alles)"
    elif st == "gear":
        rows = [[btn("Maakt niet uit", "g:"), btn("Manueel", "g:manueel"), btn("Automaat", "g:automaat")]]
        text = head + "Schakelbak?"
    elif st == "year":
        rows = [[btn(str(y), f"y:{y}") for y in (2005, 2010, 2013)],
                [btn(str(y), f"y:{y}") for y in (2015, 2018, 2020)],
                [btn("2022", "y:2022"), btn("Maakt niet uit", "y:0")]]
        text = head + ("Bouwjaar vanaf? Of typ zelf, bv. <code>2015</code> of "
                       "<code>2012-2018</code>.")
    elif st == "km":
        rows = [[btn("50.000", "k:50000"), btn("100.000", "k:100000"), btn("150.000", "k:150000")],
                [btn("200.000", "k:200000"), btn("250.000", "k:250000"), btn("Maakt niet uit", "k:0")]]
        text = head + "Maximale kilometerstand? Of typ zelf, bv. <code>120000</code>."
    elif st == "price":
        rows = [[btn("tot 2.500", "p:0-2500"), btn("tot 5.000", "p:0-5000"), btn("tot 7.500", "p:0-7500")],
                [btn("tot 10.000", "p:0-10000"), btn("tot 15.000", "p:0-15000"), btn("tot 20.000", "p:0-20000")],
                [btn("tot 30.000", "p:0-30000"), btn("Geen limiet", "p:0-0")]]
        text = head + "Prijs? Of typ zelf, bv. <code>3000-8000</code>, <code>tot 6000</code>."
    elif st == "dist":
        rows = [[btn("10 km", "d:10"), btn("25 km", "d:25"), btn("50 km", "d:50")],
                [btn("100 km", "d:100"), btn("200 km", "d:200"), btn("🌍 Overal", "d:0")]]
        text = head + "Hoe ver van je postcode mag de auto staan?"
    else:
        rows = toggle_rows(SITE_NAMES, d["sites"], "s", per_row=1)
        rows.append([btn("✅ Klaar", "done")])
        text = head + "Op welke sites zoeken?"
    if st != "sites":
        rows.append(nav_row(d))
    else:
        rows.append([btn("✖️ Annuleer", "cancel")])
    return text, rows


def start_draft(state, make, model, excl):
    d = {"make": make, "model": model, "exclude": excl, "fuels": [], "bodies": [], "gear": None,
         "year_min": None, "year_max": None, "km_max": None, "price_min": None, "price_max": None,
         "dist": None, "sites": list(SITES), "step": "fuel"}
    d["msg"] = send(*render(d))
    state["draft"] = d


def go_next(state, d):
    i = STEPS.index(d["step"]) + 1
    if i >= len(STEPS):
        finish(state, d)
        return
    d["step"] = STEPS[i]
    edit(d["msg"], *render(d))


def typed_answer(state, d, text):
    t = text.lower().replace(".", "").replace("€", "").replace("km", "").strip()
    m = re.fullmatch(r"(?:(tot|max|vanaf|min)\s*)?(\d+)\s*(?:-\s*(\d+))?", t)
    if not m:
        return False
    word, a, b = m.group(1), int(m.group(2)), int(m.group(3)) if m.group(3) else None
    if d["step"] == "year":
        if word in ("tot", "max"):
            d["year_max"] = a
        else:
            d["year_min"], d["year_max"] = (min(a, b), max(a, b)) if b else (a, None)
    elif d["step"] == "km":
        d["km_max"] = max(a, b or 0)
    elif d["step"] == "price":
        if b:
            d["price_min"], d["price_max"] = min(a, b) or None, max(a, b)
        elif word in ("vanaf", "min"):
            d["price_min"] = a
        else:
            d["price_max"] = a
    go_next(state, d)
    return True


def finish(state, d):
    state["draft"] = None
    s = {k: d[k] for k in ("make", "model", "exclude", "fuels", "bodies", "gear", "year_min",
                           "year_max", "km_max", "price_min", "price_max", "dist", "sites")}
    s["label"] = label_of(s)
    for old in state["searches"]:
        if all(old.get(k) == s[k] for k in s if k != "label"):
            edit(d["msg"], "ℹ️ Die zoekopdracht staat al in je lijst:\n" + describe(old), [])
            return
    s.update({"uid": state["next_id"], "id": len(state["searches"]) + 1, "primed": False})
    state["next_id"] += 1
    state["searches"].append(s)
    edit(d["msg"], "✅ Toegevoegd:\n" + describe(s) +
         "\n\nJe krijgt vanaf nu elke auto die er nieuw bijkomt.", [])


def handle_button(state, cq):
    data = cq.get("data", "")
    try:
        tg("answerCallbackQuery", callback_query_id=cq["id"])
    except Exception:
        pass
    d = state.get("draft")
    mid = (cq.get("message") or {}).get("message_id")
    if not d or mid != d.get("msg"):
        edit(mid, "⌛ Deze keuze is verlopen. Typ je zoekopdracht opnieuw.", [])
        return
    kind, _, val = data.partition(":")
    if data == "cancel":
        state["draft"] = None
        edit(mid, f"🚗 <b>{html.escape(label_of(d))}</b>\n✖️ Geannuleerd.", [])
    elif data == "done":
        finish(state, d)
    elif data == "next":
        go_next(state, d)
    elif kind in ("f", "b", "s"):
        lst = {"f": d["fuels"], "b": d["bodies"], "s": d["sites"]}[kind]
        if val in lst:
            if kind != "s" or len(lst) > 1:
                lst.remove(val)
        else:
            lst.append(val)
        edit(mid, *render(d))
    elif kind == "g":
        d["gear"] = val or None
        go_next(state, d)
    elif kind == "y":
        d["year_min"] = int(val) or None
        go_next(state, d)
    elif kind == "k":
        d["km_max"] = int(val) or None
        go_next(state, d)
    elif kind == "p":
        lo, hi = (int(x) for x in val.split("-"))
        d["price_min"], d["price_max"] = lo or None, hi or None
        go_next(state, d)
    elif kind == "d":
        d["dist"] = int(val) or None
        go_next(state, d)


def handle_updates(state, wait=0):
    res = tg("getUpdates", offset=state["update_offset"], timeout=wait,
             allowed_updates=["message", "callback_query"])
    for u in res.get("result", []):
        state["update_offset"] = u["update_id"] + 1
        if "callback_query" in u:
            cq = u["callback_query"]
            if str(((cq.get("message") or {}).get("chat") or {}).get("id")) == CHAT_ID:
                handle_button(state, cq)
            continue
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != CHAT_ID:
            continue
        reply = run_command(state, (msg.get("text") or "").strip())
        if reply:
            send(reply)
    return bool(res.get("result"))


# ================================================================ hoofdlus

def report(state, errors):
    if errors and time.time() - state.get("last_error_notice", 0) > ERROR_NOTIFY_EVERY:
        lines = list(dict.fromkeys(errors))[:5]
        send("⚠️ Zoeken lukte niet overal:\n" + html.escape("\n".join(lines)))
        state["last_error_notice"] = time.time()


def round_(state):
    sent, errors = check_searches(state)
    report(state, errors)
    cleanup_messages(state)
    print(f"{time.strftime('%H:%M:%S')} {len(state['searches'])} zoekopdracht(en), "
          f"{sent} melding(en), {len(errors)} fout(en)")


def run_for(minutes):
    end = time.time() + minutes * 60
    state = load_state()
    last = 0
    while time.time() < end:
        try:
            changed = handle_updates(state, wait=min(20, max(1, int(end - time.time()))))
        except Exception as e:
            print(f"Telegram: {e}", file=sys.stderr)
            changed = False
            time.sleep(5)
        fresh = any(not s.get("primed") for s in state["searches"])
        if (changed and fresh) or time.time() - last >= CHECK_EVERY:
            last = time.time()
            round_(state)
        save_state(state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duur", type=float, help="minuten blijven draaien (GitHub)")
    ap.add_argument("--loop", type=int, help="eindeloos, met deze pauze in seconden")
    args = ap.parse_args()
    if not TOKEN or not CHAT_ID:
        sys.exit("TELEGRAM_TOKEN en TELEGRAM_CHAT_ID moeten ingesteld zijn.")
    if args.duur:
        run_for(args.duur)
    elif args.loop:
        global CHECK_EVERY
        CHECK_EVERY = max(30, args.loop)
        while True:
            run_for(60)
    else:
        state = load_state()
        handle_updates(state)
        round_(state)
        save_state(state)


if __name__ == "__main__":
    main()
