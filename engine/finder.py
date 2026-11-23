"""מנוע טיסות סופ"ש מתל אביב.

שלב 1: סריקה רחבה וחינמית ב-Travelpayouts (מחירים שמורים מ-48 השעות האחרונות).
שלב 2: אימות חי של המועמדים הטובים ב-Google Flights דרך SerpApi (במגבלת תקציב חיפושים).
שלב 3: סינון לשתי רשימות - "כללי" ו"שומרי שבת" - דירוג, והשוואה למחיר של השבוע שעבר.

הרצה:
    python engine/finder.py            # הרצה אמיתית (צריך מפתחות בסביבה)
    python engine/finder.py --demo     # נתוני דמו, בלי אינטרנט

משתני סביבה:
    TRAVELPAYOUTS_TOKEN, TRAVELPAYOUTS_MARKER, SERPAPI_KEY
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun, dusk

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "site" / "data"
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
HE_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


# ---------------------------------------------------------------- data types
@dataclass
class Trip:
    """הצעת טיסה הלוך-חזור אחת, אחרי נרמול מכל מקור."""
    dest: str
    out_date: str            # YYYY-MM-DD
    ret_date: str
    price: float
    out_dep: datetime | None = None   # שעון מקומי של המוצא
    out_arr: datetime | None = None   # שעון מקומי של היעד
    ret_dep: datetime | None = None   # שעון מקומי של היעד
    airline: str = ""
    stops: int = 0
    source: str = "cached"   # cached = Travelpayouts, live = Google Flights
    link: str = ""
    ret_window_from_hour: int | None = None   # כשיש רק חלון שעות לחזרה (SerpApi)


@dataclass
class ShabbatTimes:
    candle_fri: datetime
    tzeit_sat: datetime
    land_by: datetime        # נחיתה אחרונה ביום שישי
    return_after: datetime   # המראה מוקדמת ביותר במוצ"ש


# ---------------------------------------------------------------- dates
def upcoming_weekends(today: date, weeks_ahead: list[int]) -> list[date]:
    """מחזיר את יום חמישי של כל סופ"ש מבוקש (1 = שבוע הבא)."""
    days_to_thu = (3 - today.weekday()) % 7
    this_thu = today + timedelta(days=days_to_thu)
    return [this_thu + timedelta(weeks=w) for w in weeks_ahead]


def date_combos(thu: date, long: bool = False) -> list[tuple[date, date]]:
    """סופ"ש רגיל: יציאה בחמישי/שישי, חזרה במוצ"ש/ראשון.
    long=True מוסיף סופ"ש ארוך: יציאה בשלישי/רביעי או חזרה בשני."""
    tue, wed = thu - timedelta(2), thu - timedelta(1)
    fri, sat, sun_, mon = thu + timedelta(1), thu + timedelta(2), thu + timedelta(3), thu + timedelta(4)
    combos = [(thu, sat), (thu, sun_), (fri, sat), (fri, sun_)]
    if long:
        combos += [(tue, sat), (tue, sun_), (wed, sat), (wed, sun_), (thu, mon), (wed, mon)]
    return combos


def is_long(out_date: str, ret_date: str) -> bool:
    """סופ"ש ארוך = יציאה לפני חמישי או חזרה ביום שני."""
    return date.fromisoformat(out_date).weekday() < 3 or date.fromisoformat(ret_date).weekday() == 0


def thu_of_date(iso: str) -> str:
    """יום חמישי של אותו שבוע (שלישי/רביעי שייכים לסופ"ש שאחריהם)."""
    d = date.fromisoformat(iso)
    return (d + timedelta(days=3 - d.weekday())).isoformat() if d.weekday() <= 4 else \
        (d - timedelta(days=d.weekday() - 3)).isoformat()


# ---------------------------------------------------------------- shabbat
def shabbat_times(dest: dict, thu: date, rules: dict) -> ShabbatTimes:
    tz = ZoneInfo(dest["tz"])
    obs = Observer(latitude=dest["lat"], longitude=dest["lon"])
    fri, sat = thu + timedelta(1), thu + timedelta(2)
    sunset_fri = sun(obs, date=fri, tzinfo=tz)["sunset"]
    candle = sunset_fri - timedelta(minutes=rules["candle_lighting_minutes_before_sunset"])
    tzeit = dusk(obs, date=sat, tzinfo=tz, depression=rules["tzeit_sun_depression_degrees"])
    drive = dest.get("to_center_min")
    if drive is not None and "airport_exit_minutes" in rules:
        # הלוך: יציאה מהשדה + נסיעה למרכז העיר + מרווח ביטחון, לפני הדלקת נרות
        land_by = candle - timedelta(minutes=rules["airport_exit_minutes"] + drive + rules["safety_minutes"])
        # חזור: אחרי צאת שבת צריך לנסוע לשדה ולהגיע לפני הטיסה (ולא פחות מהמינימום)
        after = max(timedelta(hours=rules["hours_after_tzeit_to_depart"]),
                    timedelta(minutes=drive + rules.get("checkin_minutes_before_flight", 90)))
    else:
        land_by = candle - timedelta(hours=rules["land_hours_before_candle_lighting"])
        after = timedelta(hours=rules["hours_after_tzeit_to_depart"])
    return ShabbatTimes(candle_fri=candle, tzeit_sat=tzeit, land_by=land_by, return_after=tzeit + after)


def ok_for_shabbat(trip: Trip, st: ShabbatTimes) -> bool:
    out_d, ret_d = date.fromisoformat(trip.out_date), date.fromisoformat(trip.ret_date)
    # הלוך: ביום שישי חייבים לנחות בזמן
    if out_d.weekday() == 4:
        if trip.out_arr is None or trip.out_arr > st.land_by:
            return False
    # חזור: במוצ"ש רק אחרי צאת שבת + מרווח
    if ret_d.weekday() == 5:
        if trip.ret_dep is not None:
            if trip.ret_dep < st.return_after:
                return False
        elif trip.ret_window_from_hour is None or trip.ret_window_from_hour < _ceil_hour(st.return_after):
            return False
    return True


def ok_for_general(trip: Trip, cfg: dict) -> bool:
    lo, hi = cfg["earliest_departure_hour"], cfg["latest_departure_hour"]
    for t in (trip.out_dep, trip.ret_dep):
        if t is not None and not (lo <= t.hour <= hi):
            return False
    return trip.stops <= cfg["max_stops"] and trip.price <= cfg["max_price"]


def _ceil_hour(t: datetime) -> int:
    return t.hour + (1 if (t.minute or t.second) else 0)


# ---------------------------------------------------------------- Travelpayouts
def travelpayouts_scan(cfg: dict, thursdays: list[date], token: str, marker: str) -> list[Trip]:
    import requests
    trips: list[Trip] = []
    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
    for dest in cfg["destinations"]:
        for thu in thursdays:
            for out_d, ret_d in date_combos(thu, cfg.get("long_weekends", False)):
                if out_d < datetime.now(ISRAEL_TZ).date():   # יום שכבר עבר
                    continue
                params = {
                    "origin": cfg["origin"], "destination": dest["code"],
                    "departure_at": out_d.isoformat(), "return_at": ret_d.isoformat(),
                    "one_way": "false", "direct": "false", "sorting": "price",
                    "unique": "false", "limit": 30, "currency": cfg["currency"].lower(),
                    "token": token,
                }
                time.sleep(0.1)   # לא להציף את ה-API עם הרבה יעדים
                try:
                    r = requests.get(url, params=params, timeout=30)
                    r.raise_for_status()
                    rows = r.json().get("data") or []
                except Exception as e:  # noqa: BLE001 - רשת לא יציבה, ממשיכים
                    print(f"  ! Travelpayouts {dest['code']} {out_d}: {e}", file=sys.stderr)
                    continue
                for row in rows:
                    trips.append(_trip_from_tp(row, dest, out_d, ret_d, marker))
    return trips


def _trip_from_tp(row: dict, dest: dict, out_d: date, ret_d: date, marker: str) -> Trip:
    dest_tz = ZoneInfo(dest["tz"])
    out_dep = datetime.fromisoformat(row["departure_at"])
    out_arr = (out_dep + timedelta(minutes=row.get("duration_to") or 0)).astimezone(dest_tz) \
        if row.get("duration_to") else None
    ret_dep = datetime.fromisoformat(row["return_at"]).astimezone(dest_tz) if row.get("return_at") else None
    link = row.get("link") or ""
    if link:
        link = f"https://www.aviasales.com{link}{'&' if '?' in link else '?'}marker={marker}"
    return Trip(
        dest=dest["code"], out_date=out_d.isoformat(), ret_date=ret_d.isoformat(),
        price=float(row["price"]), out_dep=out_dep.astimezone(ISRAEL_TZ), out_arr=out_arr,
        ret_dep=ret_dep, airline=row.get("airline", ""),
        stops=max(row.get("transfers", 0), row.get("return_transfers", 0)),
        source="cached", link=link,
    )


# ---------------------------------------------------------------- SerpApi (Google Flights)
class SerpBudget:
    def __init__(self, limit: int):
        self.limit, self.used = limit, 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def serpapi_verify(cfg: dict, dest: dict, out_d: date, ret_d: date, key: str,
                   budget: SerpBudget, shabbat: ShabbatTimes | None) -> Trip | None:
    """חיפוש חי אחד. במצב שבת - מגבלות השעות נשלחות ל-Google כבר בבקשה."""
    if not budget.take():
        return None
    import requests
    params = {
        "engine": "google_flights", "api_key": key, "type": 1,
        "departure_id": cfg["origin"], "arrival_id": dest["serpapi_airports"],
        "outbound_date": out_d.isoformat(), "return_date": ret_d.isoformat(),
        "currency": cfg["currency"], "hl": "en", "gl": "il",
        "stops": 2 if cfg["max_stops"] >= 1 else 1,   # 1 = ישירות בלבד, 2 = עד עצירה אחת
    }
    ret_from = None
    if shabbat:
        if out_d.weekday() == 4:   # נחיתה עד שעה עגולה לפני הגבול
            params["outbound_times"] = f"0,23,0,{max(0, shabbat.land_by.hour - 1)}"
        if ret_d.weekday() == 5:
            ret_from = min(23, _ceil_hour(shabbat.return_after))
            params["return_times"] = f"{ret_from},23"
    else:
        lo, hi = cfg["earliest_departure_hour"], cfg["latest_departure_hour"]
        params["outbound_times"] = f"{lo},{hi}"
        params["return_times"] = f"{lo},{hi}"
        ret_from = lo
    try:
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
        r.raise_for_status()
        js = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"  ! SerpApi {dest['code']} {out_d}: {e}", file=sys.stderr)
        return None
    if js.get("error"):
        print(f"  ! SerpApi {dest['code']} {out_d}: {js['error']}", file=sys.stderr)
        return None
    options = (js.get("best_flights") or []) + (js.get("other_flights") or [])
    options = [o for o in options if o.get("price")]
    if not options:
        print(f"  SerpApi {dest['code']} {out_d}->{ret_d}: אין תוצאות")
        return None
    print(f"  SerpApi {dest['code']} {out_d}->{ret_d}: {min(o['price'] for o in options)}")
    best = min(options, key=lambda o: o["price"])
    legs = best["flights"]
    dest_tz = ZoneInfo(dest["tz"])
    out_dep = datetime.strptime(legs[0]["departure_airport"]["time"], "%Y-%m-%d %H:%M").replace(tzinfo=ISRAEL_TZ)
    out_arr = datetime.strptime(legs[-1]["arrival_airport"]["time"], "%Y-%m-%d %H:%M").replace(tzinfo=dest_tz)
    return Trip(
        dest=dest["code"], out_date=out_d.isoformat(), ret_date=ret_d.isoformat(),
        price=float(best["price"]), out_dep=out_dep, out_arr=out_arr, ret_dep=None,
        airline=legs[0].get("airline", ""), stops=len(legs) - 1, source="live",
        link=js.get("search_metadata", {}).get("google_flights_url", ""),
        ret_window_from_hour=ret_from,
    )


# ---------------------------------------------------------------- pipeline
def best_per_slot(trips: list[Trip]) -> dict[tuple, Trip]:
    """לכל יעד+תאריכים: מחיר חי (Google) גובר תמיד על מחיר שמור, ואחרת הזול ביותר."""
    out: dict[tuple, Trip] = {}
    for t in trips:
        k = (t.dest, t.out_date, t.ret_date)
        cur = out.get(k)
        if cur is None:
            out[k] = t
        elif (t.source == "live") != (cur.source == "live"):
            if t.source == "live":
                out[k] = t
        elif t.price < cur.price:
            out[k] = t
    return out


def build_lists(cfg: dict, cached: list[Trip], thursdays: list[date],
                serp_key: str | None, today: date) -> dict:
    dests = {d["code"]: d for d in cfg["destinations"]}
    shabbat_by = {(d, thu.isoformat()): shabbat_times(dests[d], thu, cfg["shabbat"])
                  for d in dests for thu in thursdays}

    def thu_of(t: Trip) -> str:
        return thu_of_date(t.out_date)

    general = [t for t in cached if ok_for_general(t, cfg)]
    shabbat = [t for t in general if ok_for_shabbat(t, shabbat_by[(t.dest, thu_of(t))])]

    lists = {"general": general, "shabbat": shabbat}
    if serp_key:
        budget = SerpBudget(cfg["serpapi_max_calls_per_run"])
        per_list = math.ceil(budget.limit / 2)
        for name, pool in lists.items():
            ranked = sorted(best_per_slot(pool).values(), key=lambda t: t.price)
            seen_dest: set[str] = set()
            candidates = []
            for t in ranked:                       # מועמד אחד לכל יעד, כדי לגוון (רק סופ"ש רגיל)
                if t.dest not in seen_dest and not is_long(t.out_date, t.ret_date):
                    seen_dest.add(t.dest)
                    candidates.append(t)
            if not candidates:                     # אין נתוני מטמון: סורקים ישר ב-Google
                candidates = [Trip(d, a.isoformat(), b.isoformat(), 0)
                              for d in dests for thu in thursdays for a, b in date_combos(thu)][:per_list]
            for t in candidates[:per_list]:
                st = shabbat_by[(t.dest, thu_of(t))] if name == "shabbat" else None
                live = serpapi_verify(cfg, dests[t.dest], date.fromisoformat(t.out_date),
                                      date.fromisoformat(t.ret_date), serp_key, budget, st)
                if live and (st is None or ok_for_shabbat(live, st)):
                    if t.link and "aviasales" in t.link:
                        live.link = t.link             # שומרים קישור שותפים כשיש
                    pool.append(live)
        print(f"  SerpApi: {budget.used} חיפושים בהרצה הזו")

    prev = _load_json(DATA_DIR / "history.json", {})
    result, new_hist = {}, dict(prev)
    for name, pool in lists.items():
        slots = best_per_slot([t for t in pool if t.price <= cfg["max_price"]])
        # עדיפות למחיר חי, ואז הזול; דיל אחד לכל יעד בכל סופ"ש,
        # ובסופ"ש ארוך - אחד לכל יום יציאה (כדי שאפשר יהיה לבחור שלישי/רביעי/חמישי)
        by_key: dict[str, Trip] = {}
        for t in sorted(slots.values(), key=lambda t: (t.price, t.source != "live")):
            k = f"{t.dest}|{thu_of(t)}"
            if is_long(t.out_date, t.ret_date):
                k += f"|L|{t.out_date}"
            if k not in by_key:
                by_key[k] = t
        top = sorted(by_key.items(), key=lambda kv: kv[1].price)[: cfg["deals_per_list"]]
        result[name] = []
        for k, t in top:
            dj = _deal_json(t, dests[t.dest], shabbat_by[(t.dest, thu_of(t))], prev.get(name, {}).get(k))
            dj["weekend"] = thu_of(t)
            dj["long"] = is_long(t.out_date, t.ret_date)
            dj["days"] = (date.fromisoformat(t.ret_date) - date.fromisoformat(t.out_date)).days + 1
            result[name].append(dj)
        new_hist[name] = {**prev.get(name, {}),
                          **{k: {"price": t.price, "run": today.isoformat()} for k, t in by_key.items()}}
    _save_json(DATA_DIR / "history.json", new_hist)
    return result


def _deal_json(t: Trip, dest: dict, st: ShabbatTimes, prev: dict | None) -> dict:
    def hm(x): return x.strftime("%H:%M") if x else None
    out_d, ret_d = date.fromisoformat(t.out_date), date.fromisoformat(t.ret_date)
    return {
        "dest": t.dest, "name": dest["name"], "flag": dest["flag"],
        "price": round(t.price), "prev_price": round(prev["price"]) if prev else None,
        "out_date": t.out_date, "out_day": HE_DAYS[out_d.weekday()],
        "ret_date": t.ret_date, "ret_day": HE_DAYS[ret_d.weekday()],
        "out_dep": hm(t.out_dep), "out_arr": hm(t.out_arr), "ret_dep": hm(t.ret_dep),
        "ret_from_hour": t.ret_window_from_hour,
        "airline": t.airline, "stops": t.stops, "source": t.source, "link": t.link,
        "candle_lighting": hm(st.candle_fri), "havdalah": hm(st.tzeit_sat),
        "land_by": hm(st.land_by),
        "to_center_km": dest.get("to_center_km"), "to_center_min": dest.get("to_center_min"),
        "pt_min": dest.get("pt_min"),
    }


# ---------------------------------------------------------------- photos (Wikimedia Commons)
WIKI_HEADERS = {"User-Agent": "weekend-flights-tlv/1.0 (personal deals page)"}


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _wiki_get(url: str, params: dict) -> dict:
    """בקשה לוויקיפדיה עם המתנה וניסיון חוזר כשהיא חוסמת (429 או תשובה ריקה)."""
    import requests
    for wait in (0, 15, 45):
        time.sleep(wait)
        try:
            r = requests.get(url, headers=WIKI_HEADERS, timeout=30, params={**params, "format": "json"})
            if r.status_code == 200:
                return r.json()
        except Exception:  # noqa: BLE001
            pass
    raise RuntimeError("ויקיפדיה לא ענתה")


def fetch_photos(cfg: dict, cache: dict) -> dict:
    """תמונה חופשית לכל יעד: התמונה הראשית של ערך הוויקיפדיה, רק אם היא מוויקישיתוף.
    נשמר במטמון. כל היעדים החסרים נמשכים יחד בשתי בקשות בלבד, כדי לא להיחסם."""
    todo = [d for d in cfg["destinations"]
            if not (d["code"] in cache and cache[d["code"]].get("article") == d.get("photo"))]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        try:
            q = _wiki_get("https://en.wikipedia.org/w/api.php", {
                "action": "query", "titles": "|".join(d["photo"] for d in chunk),
                "prop": "pageimages", "piprop": "name", "redirects": 1})["query"]
            alias = {}
            for m in q.get("normalized", []) + q.get("redirects", []):
                alias[m["from"]] = m["to"]
            images = {p["title"]: p.get("pageimage") for p in q.get("pages", {}).values()}

            def image_for(title: str):
                while title in alias:
                    title = alias[title]
                return images.get(title)

            names = {d["code"]: image_for(d["photo"]) for d in chunk}
            files = sorted({n for n in names.values() if n})
            if not files:
                continue
            time.sleep(1.5)
            cq = _wiki_get("https://commons.wikimedia.org/w/api.php", {
                "action": "query", "titles": "|".join(f"File:{n}" for n in files),
                "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 900})["query"]
            calias = {m["from"]: m["to"] for m in cq.get("normalized", [])}
            infos = {p["title"]: p.get("imageinfo") for p in cq.get("pages", {}).values()}
            for d in chunk:
                name = names.get(d["code"])
                if not name:
                    print(f"  ! תמונה ל-{d['code']}: אין תמונה בערך {d['photo']}", file=sys.stderr)
                    continue
                t = f"File:{name}"
                info = infos.get(calias.get(t, t))
                if not info:          # לא בוויקישיתוף = לא תמונה חופשית, מדלגים
                    print(f"  ! תמונה ל-{d['code']}: לא בוויקישיתוף", file=sys.stderr)
                    continue
                meta = info[0].get("extmetadata", {})
                cache[d["code"]] = {
                    "article": d.get("photo"),
                    "url": info[0].get("thumburl") or info[0]["url"],
                    "credit": _strip_html(meta.get("Artist", {}).get("value", ""))[:60],
                    "license": meta.get("LicenseShortName", {}).get("value", ""),
                    "source": info[0].get("descriptionurl", ""),
                }
        except Exception as e:  # noqa: BLE001
            print(f"  ! תמונות: {e}", file=sys.stderr)
    return cache


# ---------------------------------------------------------------- hotel + eSIM partner links
def extra_urls(deal: dict, dest: dict) -> dict:
    """קישורים רגילים למלונות ול-eSIM ליעד ולתאריכים של הדיל (לפני המרה לקישורי שותפים)."""
    from urllib.parse import urlencode
    hotel = "https://www.booking.com/searchresults.html?" + urlencode({
        "ss": dest["city_en"], "checkin": deal["out_date"], "checkout": deal["ret_date"],
        "group_adults": 2, "no_rooms": 1, "lang": "he"})
    slug = dest.get("esim_slug")
    esim = f"https://yesim.app/country/{slug}/" if slug else "https://yesim.app/"
    return {"hotel": hotel, "esim": esim}


def partner_links(urls: list[str], token: str, trs: int, marker: str, cache: dict) -> dict:
    """ממיר קישורים רגילים לקישורי שותפים דרך ה-API של Travelpayouts (עד 10 בבקשה). שומר במטמון."""
    import requests
    todo = [u for u in dict.fromkeys(urls) if u not in cache]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        try:
            r = requests.post("https://api.travelpayouts.com/links/v1/create", timeout=30,
                              headers={"X-Access-Token": token, "Content-Type": "application/json"},
                              json={"trs": int(trs), "marker": int(marker), "shorten": False,
                                    "links": [{"url": u} for u in chunk]})
            js = r.json()
            for item in (js.get("result") or {}).get("links", []):
                if item.get("code") == "success" and item.get("partner_url"):
                    cache[item["url"]] = item["partner_url"]
                else:
                    print(f"  ! קישור שותפים נכשל: {item.get('message', item.get('code'))} | {item.get('url', '')[:60]}",
                          file=sys.stderr)
            if r.status_code != 200:
                print(f"  ! Links API {r.status_code}: {js}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  ! Links API: {e}", file=sys.stderr)
    return cache


def add_extras(lists: dict, cfg: dict, token: str | None, marker: str) -> None:
    """מוסיף לכל דיל כפתור מלון וכפתור eSIM - רק אם הצלחנו לייצר קישור שותפים (כלומר יש עמלה)."""
    for deals in lists.values():
        for d in deals:
            d["hotel_link"] = d["esim_link"] = None
    if not token or not marker or not cfg.get("travelpayouts_trs"):
        return
    dests = {x["code"]: x for x in cfg["destinations"]}
    wanted = {}
    for deals in lists.values():
        for d in deals:
            wanted[id(d)] = (d, extra_urls(d, dests[d["dest"]]))
    cache = _load_json(DATA_DIR / "links.json", {})
    cache = partner_links([u for _, ex in wanted.values() for u in ex.values()],
                          token, cfg["travelpayouts_trs"], marker, cache)
    # מטמון קטן: שומרים רק את מה שבשימוש עכשיו + קישורי ה-eSIM הקבועים
    in_use = {u for _, ex in wanted.values() for u in ex.values()}
    _save_json(DATA_DIR / "links.json", {u: v for u, v in cache.items() if u in in_use or "yesim" in u})
    for d, ex in wanted.values():
        d["hotel_link"] = cache.get(ex["hotel"])
        d["esim_link"] = cache.get(ex["esim"])


# ---------------------------------------------------------------- demo data
def demo_trips(cfg: dict, thursdays: list[date]) -> list[Trip]:
    rnd = random.Random(42)
    base = {"LCA": 380, "PFO": 420, "ATH": 520, "RHO": 560, "SKG": 590, "BUS": 650, "TBS": 700,
            "SOF": 610, "OTP": 640, "BUD": 720, "PRG": 780, "VIE": 800, "ROM": 760, "MIL": 840, "BER": 880}
    airlines = ["LY", "6H", "IZ", "W6", "FR", "A3", "U2"]
    trips = []
    for d in cfg["destinations"]:
        tz = ZoneInfo(d["tz"])
        for thu in thursdays:
            for out_d, ret_d in date_combos(thu, cfg.get("long_weekends", False)):
                for _ in range(4):
                    dep_h = rnd.choice([1, 4, 6, 8, 9, 11, 13, 16, 19, 22])
                    out_dep = datetime.combine(out_d, datetime.min.time(), ISRAEL_TZ) + timedelta(hours=dep_h, minutes=rnd.choice([0, 15, 40]))
                    out_arr = (out_dep + timedelta(minutes=rnd.randint(70, 260))).astimezone(tz)
                    ret_dep = datetime.combine(ret_d, datetime.min.time(), tz) + timedelta(hours=rnd.choice([6, 10, 14, 18, 20, 21, 22, 23]), minutes=rnd.choice([0, 30, 50]))
                    trips.append(Trip(d["code"], out_d.isoformat(), ret_d.isoformat(),
                                      base.get(d["code"], 850) * rnd.uniform(0.8, 1.6), out_dep, out_arr, ret_dep,
                                      rnd.choice(airlines), rnd.choice([0, 0, 0, 1]), "cached",
                                      "https://www.aviasales.com/"))
    return trips


# ---------------------------------------------------------------- io
def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="נתוני דמו בלי אינטרנט")
    ap.add_argument("--today", help="תאריך הרצה לבדיקה, YYYY-MM-DD")
    args = ap.parse_args(argv)

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    today = date.fromisoformat(args.today) if args.today else datetime.now(ISRAEL_TZ).date()
    thursdays = upcoming_weekends(today, cfg["weekends_ahead"])
    print(f"מחפש סופ\"שים: {', '.join(t.isoformat() for t in thursdays)}")

    offline = args.demo           # --demo ביד = בלי אינטרנט בכלל
    if not args.demo:
        tp_token, serp_key = os.getenv("TRAVELPAYOUTS_TOKEN"), os.getenv("SERPAPI_KEY")
        if not tp_token and not serp_key:   # עוד אין מפתחות: מעלים אתר דמו כדי שיהיה משהו באוויר
            print("אין מפתחות עדיין - מריץ במצב דמו", file=sys.stderr)
            args.demo = True
        cached = travelpayouts_scan(cfg, thursdays, tp_token, os.getenv("TRAVELPAYOUTS_MARKER", "")) if tp_token else []
        if not args.demo:
            print(f"  Travelpayouts: {len(cached)} הצעות")
    if args.demo:
        cached, serp_key = demo_trips(cfg, thursdays), None

    lists = build_lists(cfg, cached, thursdays, serp_key, today)
    if args.demo:   # בדמו ממציאים "מחיר שבוע שעבר" כדי לראות את ההשוואה
        rnd = random.Random(7)
        for deals in lists.values():
            for d in deals:
                d["prev_price"] = round(d["price"] * rnd.uniform(0.95, 1.35))
        (DATA_DIR / "history.json").unlink(missing_ok=True)
    if not args.demo:
        add_extras(lists, cfg, os.getenv("TRAVELPAYOUTS_TOKEN"), os.getenv("TRAVELPAYOUTS_MARKER", ""))
    photos = _load_json(DATA_DIR / "photos.json", {})
    if not offline:
        photos = fetch_photos(cfg, photos)
        _save_json(DATA_DIR / "photos.json", photos)
    out = {
        "photos": photos,
        "site_url": cfg.get("site_url", ""),
        "generated_at": datetime.now(ISRAEL_TZ).isoformat(timespec="minutes"),
        "demo": bool(args.demo),
        "weekends": [t.isoformat() for t in thursdays],
        "currency": cfg["currency"],
        "price_filters": cfg["price_filters"],
        "kiwi_link": cfg.get("kiwi_link"),
        "dests": {d["code"]: {"city_en": d["city_en"], "kosher": d.get("kosher")} for d in cfg["destinations"]},
        "lists": lists,
    }
    _save_json(DATA_DIR / "deals.json", out)
    print(f"נשמר: {len(lists['general'])} דילים כלליים, {len(lists['shabbat'])} לשומרי שבת")
    return 0


if __name__ == "__main__":
    sys.exit(main())
