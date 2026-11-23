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


def date_combos(thu: date) -> list[tuple[date, date]]:
    fri, sat, sun_ = thu + timedelta(1), thu + timedelta(2), thu + timedelta(3)
    return [(thu, sat), (thu, sun_), (fri, sat), (fri, sun_)]


# ---------------------------------------------------------------- shabbat
def shabbat_times(dest: dict, thu: date, rules: dict) -> ShabbatTimes:
    tz = ZoneInfo(dest["tz"])
    obs = Observer(latitude=dest["lat"], longitude=dest["lon"])
    fri, sat = thu + timedelta(1), thu + timedelta(2)
    sunset_fri = sun(obs, date=fri, tzinfo=tz)["sunset"]
    candle = sunset_fri - timedelta(minutes=rules["candle_lighting_minutes_before_sunset"])
    tzeit = dusk(obs, date=sat, tzinfo=tz, depression=rules["tzeit_sun_depression_degrees"])
    return ShabbatTimes(
        candle_fri=candle,
        tzeit_sat=tzeit,
        land_by=candle - timedelta(hours=rules["land_hours_before_candle_lighting"]),
        return_after=tzeit + timedelta(hours=rules["hours_after_tzeit_to_depart"]),
    )


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
            for out_d, ret_d in date_combos(thu):
                params = {
                    "origin": cfg["origin"], "destination": dest["code"],
                    "departure_at": out_d.isoformat(), "return_at": ret_d.isoformat(),
                    "one_way": "false", "direct": "false", "sorting": "price",
                    "unique": "false", "limit": 30, "currency": cfg["currency"].lower(),
                    "token": token,
                }
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
    options = (js.get("best_flights") or []) + (js.get("other_flights") or [])
    options = [o for o in options if o.get("price")]
    if not options:
        return None
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
    """הזול ביותר לכל יעד+תאריכים."""
    out: dict[tuple, Trip] = {}
    for t in trips:
        k = (t.dest, t.out_date, t.ret_date)
        if k not in out or t.price < out[k].price:
            out[k] = t
    return out


def build_lists(cfg: dict, cached: list[Trip], thursdays: list[date],
                serp_key: str | None, today: date) -> dict:
    dests = {d["code"]: d for d in cfg["destinations"]}
    shabbat_by = {(d, thu.isoformat()): shabbat_times(dests[d], thu, cfg["shabbat"])
                  for d in dests for thu in thursdays}

    def thu_of(t: Trip) -> str:
        d = date.fromisoformat(t.out_date)
        return (d - timedelta(days=(d.weekday() - 3) % 7)).isoformat()

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
            for t in ranked:                       # מועמד אחד לכל יעד, כדי לגוון
                if t.dest not in seen_dest:
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
        # עדיפות למחיר חי, ואז הזול; יעד אחד פעם אחת
        by_dest: dict[str, Trip] = {}
        for t in sorted(slots.values(), key=lambda t: (t.price, t.source != "live")):
            if t.dest not in by_dest:
                by_dest[t.dest] = t
        top = sorted(by_dest.values(), key=lambda t: t.price)[: cfg["deals_per_list"]]
        result[name] = [_deal_json(t, dests[t.dest], shabbat_by[(t.dest, thu_of(t))],
                                   prev.get(name, {}).get(t.dest)) for t in top]
        new_hist[name] = {**prev.get(name, {}),
                          **{t.dest: {"price": t.price, "run": today.isoformat()} for t in by_dest.values()}}
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
    }


# ---------------------------------------------------------------- photos (Wikimedia Commons)
WIKI_HEADERS = {"User-Agent": "weekend-flights-tlv/1.0 (personal deals page)"}


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s or "").strip()


def fetch_photos(cfg: dict, cache: dict) -> dict:
    """תמונה חופשית לכל יעד: התמונה הראשית של ערך הוויקיפדיה, רק אם היא מוויקישיתוף.
    נשמר במטמון, כך שכל תמונה נמשכת פעם אחת בלבד."""
    import requests
    for d in cfg["destinations"]:
        if d["code"] in cache and cache[d["code"]].get("article") == d.get("photo"):
            continue
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", headers=WIKI_HEADERS, timeout=30, params={
                "action": "query", "titles": d["photo"], "prop": "pageimages", "piprop": "name",
                "redirects": 1, "format": "json"})
            page = next(iter(r.json()["query"]["pages"].values()))
            name = page.get("pageimage")
            if not name:
                continue
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_HEADERS, timeout=30, params={
                "action": "query", "titles": f"File:{name}", "prop": "imageinfo",
                "iiprop": "url|extmetadata", "iiurlwidth": 900, "format": "json"})
            info = next(iter(r.json()["query"]["pages"].values())).get("imageinfo")
            if not info:          # לא בוויקישיתוף = לא תמונה חופשית, מדלגים
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
            print(f"  ! תמונה ל-{d['code']}: {e}", file=sys.stderr)
    return cache


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
            for out_d, ret_d in date_combos(thu):
                for _ in range(4):
                    dep_h = rnd.choice([1, 4, 6, 8, 9, 11, 13, 16, 19, 22])
                    out_dep = datetime.combine(out_d, datetime.min.time(), ISRAEL_TZ) + timedelta(hours=dep_h, minutes=rnd.choice([0, 15, 40]))
                    out_arr = (out_dep + timedelta(minutes=rnd.randint(70, 260))).astimezone(tz)
                    ret_dep = datetime.combine(ret_d, datetime.min.time(), tz) + timedelta(hours=rnd.choice([6, 10, 14, 18, 20, 21, 22, 23]), minutes=rnd.choice([0, 30, 50]))
                    trips.append(Trip(d["code"], out_d.isoformat(), ret_d.isoformat(),
                                      base[d["code"]] * rnd.uniform(0.8, 1.6), out_dep, out_arr, ret_dep,
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
        "lists": lists,
    }
    _save_json(DATA_DIR / "deals.json", out)
    print(f"נשמר: {len(lists['general'])} דילים כלליים, {len(lists['shabbat'])} לשומרי שבת")
    return 0


if __name__ == "__main__":
    sys.exit(main())
