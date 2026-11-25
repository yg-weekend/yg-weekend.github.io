"""עמודי יעד קבועים למנועי חיפוש.

קורא את site/data/deals.json ואת config.json ובונה:
  site/dest/<slug>/index.html  - עמוד לכל יעד ("טיסות זולות ללרנקה לסופ"ש")
  site/dest/index.html         - רשימת כל היעדים
  site/sitemap.xml             - מפת אתר עם כל העמודים

רץ אחרי engine/finder.py בכל עדכון דילים. בלי ספריות חיצוניות.
הרצה ידנית: python engine/pages.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SUB_ID = "dest"          # SubID ב-Travelpayouts: קליקים שהגיעו מעמודי היעד
MAX_DEALS = 10           # כמה דילים להציג בכל רשימה בעמוד

AIRLINES = {"W6": "Wizz Air", "W4": "Wizz Air", "W9": "Wizz Air", "5W": "Wizz Air", "IZ": "ארקיע", "6H": "ישראייר",
            "LY": "אל על", "GQ": "Sky Express", "A3": "Aegean", "3F": "FlyOne", "5F": "FlyOne", "BZ": "Blue Bird",
            "U8": "TUS Airways", "CY": "Cyprus Airways", "J2": "Azerbaijan Airlines", "TO": "Transavia",
            "HV": "Transavia", "FR": "Ryanair", "U2": "easyJet", "RO": "Tarom", "LO": "LOT", "OS": "Austrian",
            "LH": "Lufthansa", "LX": "SWISS", "SN": "Brussels Airlines", "UX": "Air Europa", "QS": "Smartwings",
            "FB": "Bulgaria Air", "TK": "Turkish Airlines", "PC": "Pegasus", "FZ": "flydubai", "EY": "Etihad",
            "H4": "HiSky"}


def nis(n) -> str:
    return f"{round(n):,} ₪"


def dm(iso: str) -> str:
    _, m, d = iso.split("-")
    return f"{int(d)}/{int(m)}"


def aff(url: str) -> str:
    """מוסיף SubID למספר השותף, כמו הפונקציה aff באתר."""
    return re.sub(r"((?:sh)?marker=)(\d+)(?=&|$)", rf"\g<1>\g<2>.{SUB_ID}", url or "")


def slug_of(dest: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", dest["city_en"].lower()).strip("-")


def ret_text(d: dict, shabbat: bool) -> str:
    if d.get("ret_dep"):
        return d["ret_dep"]
    sat = datetime.fromisoformat(d["ret_date"]).weekday() == 5
    if shabbat and sat and d.get("ret_from_hour") is not None:
        return f"אחרי {int(d['ret_from_hour']):02d}:00"
    return "השעה באתר ההזמנה"


CSS = """
:root{--bg:#f4f6f9;--paper:#fff;--ink:#0b1f3a;--ink-2:#51627a;--line:#dfe5ec;--brand:#c2410c;--brand-dark:#9a3412;--ok:#0f7a4b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16.5px/1.55 "Assistant",system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
a{color:inherit}
:focus-visible{outline:3px solid #ffb703;outline-offset:2px}
.skip{position:absolute;top:-60px;right:12px;z-index:20;background:#fff;font-weight:800;padding:10px 16px;border-radius:8px;text-decoration:none}
.skip:focus{top:12px}
.top{background:linear-gradient(to bottom,#050d1c,#081a33);color:#fff}
.top .in{max-width:860px;margin:0 auto;padding:16px 18px 26px}
.logo{display:inline-flex;align-items:center;gap:9px;font:400 20px "Secular One","Assistant",sans-serif;text-decoration:none}
.logo svg{width:30px;height:30px}
.crumbs{margin:18px 0 6px;font-size:14px;font-weight:600;opacity:.85}
h1{font:400 clamp(28px,6vw,44px)/1.1 "Secular One","Assistant",sans-serif;margin:0 0 8px}
.lede{margin:0;font-size:17px;font-weight:600;opacity:.93;max-width:620px}
main{max-width:860px;margin:0 auto;padding:20px 16px 90px}
h2{font-size:22px;font-weight:800;margin:26px 0 10px}
.hero{display:block;width:100%;height:220px;object-fit:cover;border-radius:12px;background:#dfe5ec}
.credit{margin:4px 0 0;font-size:12px;color:var(--ink-2)}
.list{display:grid;gap:10px;margin:0;padding:0;list-style:none}
.deal{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:7px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.when{margin:0;font-size:18px;font-weight:800;line-height:1.25}
.price{white-space:nowrap;text-align:left;font-size:23px;font-weight:800;line-height:1.1;color:var(--brand)}
.price small{display:block;margin-top:2px;font-size:12px;font-weight:600;color:var(--ink-2)}
.legs{margin:0;display:grid;grid-template-columns:auto 1fr;gap:1px 8px;font-size:14.5px}
.legs dt{color:var(--ink-2);font-weight:600}.legs dd{margin:0;font-weight:600}
.meta{display:flex;flex-wrap:wrap;gap:2px 12px;font-size:13px;font-weight:600;color:var(--ink-2)}
.meta .good{color:var(--ok)}.meta .sh{color:var(--ink)}
.book{display:block;text-align:center;background:var(--brand);color:#fff;text-decoration:none;font-weight:800;font-size:15.5px;padding:9px 12px;border-radius:8px}
.book:hover{background:var(--brand-dark)}
.box{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:12px 14px;font-size:15px}
.box p{margin:0 0 6px}.box p:last-child{margin:0}
.all{display:inline-block;margin-top:14px;font-weight:800}
.dests{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.dests a{display:block;background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px 12px;font-weight:600;font-size:14.5px;text-decoration:none}
.dests a:hover{border-color:var(--ink-2)}
.dests small{color:var(--brand);font-weight:800}
footer{color:var(--ink-2);font-size:13.5px;text-align:center;margin-top:34px}
"""

LOGO = ('<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#c2410c"/>'
        '<path fill="#fff" d="M54 12c-3-3-8-2-11 1l-8 8-22-6-4 4 18 10-8 9-7-1-3 3 9 4 4 9 3-3-1-7 9-8 10 18 4-4-6-22 '
        '8-8c3-3 4-8 1-11z"/></svg>')

FOOT = ("המחירים לאדם, בשקלים, הלוך-חזור. השעות לפי השעון המקומי. המחיר נכון לזמן העדכון ועשוי להשתנות, "
        "כדאי לוודא אותו בזמן ההזמנה. זמני שבת מחושבים לפי השקיעה ביעד, כדאי לוודא מול לוח מקומי. "
        "חלק מהקישורים הם קישורי שותפים: אנחנו עשויים לקבל עמלה, בלי עלות נוספת עבורכם.")


def page(*, title: str, desc: str, canonical: str, depth: int, crumbs: str, h1: str, lede: str, body: str,
         ld: dict) -> str:
    up = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="{up}favicon.svg" type="image/svg+xml">
<meta name="theme-color" content="#0a2342">
<meta property="og:type" content="website">
<meta property="og:locale" content="he_IL">
<meta property="og:site_name" content="YG Weekend">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://yg-weekend.github.io/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Secular+One&family=Assistant:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">דלג לתוכן</a>
<header class="top"><div class="in">
  <a class="logo" href="{up}" aria-label="YG Weekend, לעמוד הבית">{LOGO}<span dir="ltr">YG Weekend</span></a>
  <nav class="crumbs" aria-label="מיקום באתר">{crumbs}</nav>
  <h1>{escape(h1)}</h1>
  <p class="lede">{escape(lede)}</p>
</div></header>
<main id="main" tabindex="-1">
{body}
<footer><p>{FOOT}</p><p><a href="{up}accessibility.html">הצהרת נגישות</a></p></footer>
</main>
<script src="{up}a11y.js"></script>
</body>
</html>
"""


def deal_li(d: dict, shabbat: bool) -> str:
    out = f"{d['out_day']} {dm(d['out_date'])} · {d.get('out_dep') or ''}"
    if d.get("out_arr"):
        out += f" (נוחת {d['out_arr']})"
    meta = [f"<span>{'עצירה אחת' if d.get('stops') else 'טיסה ישירה'}</span>"]
    if d.get("airline"):
        meta.append(f"<span>{escape(AIRLINES.get(d['airline'], d['airline']))}</span>")
    if d.get("long"):
        meta.append(f"<span>סופ״ש ארוך, {d['days']} ימים</span>")
    meta.append('<span class="good">מחיר חי</span>' if d.get("source") == "live"
                else "<span>מחיר מ-48 השעות האחרונות, עשוי להשתנות</span>")
    if shabbat:
        meta.append(f"<span class=\"sh\">נרות {d['candle_lighting']} · צאת שבת {d['havdalah']}</span>")
    book = ""
    if d.get("link"):
        book = (f'<a class="book" href="{escape(aff(d["link"]))}" target="_blank" rel="noopener nofollow sponsored" '
                f'aria-label="לבדוק ולהזמין טיסה ל{escape(d["name"])} ב-{nis(d["price"])}, '
                f'יציאה {dm(d["out_date"])} (נפתח בחלון חדש)">לבדוק ולהזמין</a>')
    return f"""<li class="deal">
  <div class="head">
    <h3 class="when">{dm(d['out_date'])} עד {dm(d['ret_date'])}</h3>
    <div class="price">{nis(d['price'])}<small>הלוך-חזור לאדם</small></div>
  </div>
  <dl class="legs"><dt>הלוך</dt><dd>{escape(out)}</dd><dt>חזור</dt><dd>{escape(d['ret_day'])} {dm(d['ret_date'])} · {escape(ret_text(d, shabbat))}</dd></dl>
  <div class="meta">{''.join(meta)}</div>
  {book}
</li>"""


def updated_text(gen: datetime) -> str:
    return f"עודכן {gen.day}.{gen.month} בשעה {gen:%H:%M}"


def build(data: dict, cfg: dict) -> dict[str, str]:
    """מחזיר {נתיב יחסי בתוך site: תוכן הקובץ}."""
    base = (data.get("site_url") or cfg["site_url"]).rstrip("/")
    gen = datetime.fromisoformat(data["generated_at"])
    general, shabbat = data["lists"].get("general", []), data["lists"].get("shabbat", [])
    photos = data.get("photos", {})
    dests = cfg["destinations"]
    slugs = {d["code"]: slug_of(d) for d in dests}
    min_price = {}
    for x in general:
        min_price[x["dest"]] = min(min_price.get(x["dest"], x["price"]), x["price"])
    out: dict[str, str] = {}

    def others(skip: str | None) -> str:
        items = []
        for d in sorted(dests, key=lambda d: (d["code"] not in min_price, min_price.get(d["code"], 0))):
            if d["code"] == skip:
                continue
            price = f' <small>מ-{nis(min_price[d["code"]])}</small>' if d["code"] in min_price else ""
            href = ("../" if skip else "") + slugs[d["code"]] + "/"
            items.append(f'<li><a href="{href}">{escape(d["name"])}{price}</a></li>')
        return f'<ul class="dests">{"".join(items)}</ul>'

    for dest in dests:
        code, name, slug = dest["code"], dest["name"], slugs[dest["code"]]
        mine = sorted((x for x in general if x["dest"] == code), key=lambda x: (bool(x.get("long")), x["price"]))  # סופ"ש רגיל קודם
        mine_sh = sorted((x for x in shabbat if x["dest"] == code), key=lambda x: (bool(x.get("long")), x["price"]))
        url = f"{base}/dest/{slug}/"
        title = f"טיסות זולות ל{name} לסופ״ש מתל אביב | YG Weekend"
        if mine:
            lede = (f"הדילים הזולים ביותר לסופ״ש ב{name}, החל מ-{nis(min_price[code])} הלוך-חזור לאדם. "
                    f"{updated_text(gen)}.")
            desc = (f"טיסות זולות ל{name} לסופ״ש מתל אביב, החל מ-{nis(min_price[code])} הלוך-חזור. "
                    f"מתעדכן פעמיים ביום, כולל רשימה לשומרי שבת.")
        else:
            lede = f"כרגע אין דיל זול ל{name} בסופ״שים הקרובים. הרשימה מתעדכנת פעמיים ביום."
            desc = f"טיסות זולות ל{name} לסופ״ש מתל אביב. הדילים מתעדכנים פעמיים ביום, כולל רשימה לשומרי שבת."
        parts = []
        p = photos.get(code) or {}
        if p.get("url"):
            credit = escape(p.get("credit") or "ויקישיתוף") + (", " + escape(p["license"]) if p.get("license") else "")
            parts.append(f'<img class="hero" src="{escape(p["url"])}" alt="צילום מ{escape(name)}" width="960" height="540">'
                         f'<p class="credit"><a href="{escape(p.get("source", ""))}" target="_blank" rel="noopener">'
                         f'צילום: {credit}</a></p>')
        if mine:
            parts.append(f"<h2>הדילים הזולים ל{escape(name)}</h2>")
            parts.append('<ul class="list">' + "".join(deal_li(x, False) for x in mine[:MAX_DEALS]) + "</ul>")
        if mine_sh:
            parts.append(f"<h2>טיסות ל{escape(name)} לשומרי שבת</h2>")
            parts.append('<ul class="list">' + "".join(deal_li(x, True) for x in mine_sh[:MAX_DEALS]) + "</ul>")
        info = []
        if dest.get("to_center_min"):
            pt = f", כ-{dest['pt_min']} דק׳ בתחבורה ציבורית" if dest.get("pt_min") else ""
            info.append(f"<p><b>מהשדה למרכז העיר</b> ({dest['to_center_km']} ק״מ): כ-{dest['to_center_min']} דק׳ "
                        f"ברכב או במונית{pt} (זמן משוער).</p>")
        if (dest.get("kosher") or {}).get("note"):
            info.append(f"<p><b>כשרות ושבת:</b> {escape(dest['kosher']['note'])}</p>")
        if info:
            parts.append(f"<h2>טוב לדעת על {escape(name)}</h2>")
            parts.append('<div class="box">' + "".join(info) + "</div>")
        parts.append(f'<a class="all" href="../../">לכל הדילים לסופ״ש, מכל היעדים</a>')
        parts.append("<h2>יעדים נוספים</h2>")
        parts.append(others(code))
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "YG Weekend", "item": base + "/"},
            {"@type": "ListItem", "position": 2, "name": "יעדים", "item": base + "/dest/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url}]}
        crumbs = f'<a href="../../">דילים לסופ״ש</a> › <a href="../">יעדים</a> › {escape(name)}'
        out[f"dest/{slug}/index.html"] = page(
            title=title, desc=desc, canonical=url, depth=2, crumbs=crumbs,
            h1=f"טיסות זולות ל{name} לסופ״ש", lede=lede, body="\n".join(parts), ld=ld)

    # עמוד כל היעדים
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "YG Weekend", "item": base + "/"},
        {"@type": "ListItem", "position": 2, "name": "יעדים", "item": base + "/dest/"}]}
    out["dest/index.html"] = page(
        title="יעדים לסופ״ש מתל אביב: טיסות זולות | YG Weekend",
        desc="כל היעדים שאליהם אנחנו מוצאים טיסות זולות לסופ״ש מתל אביב, עם המחיר הזול ביותר לכל יעד. מתעדכן פעמיים ביום.",
        canonical=base + "/dest/", depth=1, crumbs='<a href="../">דילים לסופ״ש</a> › יעדים',
        h1="יעדים לסופ״ש מתל אביב",
        lede=f"המחיר הזול ביותר לכל יעד, הלוך-חזור לאדם. {updated_text(gen)}.",
        body=others(None) + '\n<a class="all" href="../">לכל הדילים לסופ״ש</a>', ld=ld)

    # מפת אתר
    day = gen.date().isoformat()
    urls = [(base + "/", "daily"), (base + "/dest/", "daily")]
    urls += [(f"{base}/dest/{slugs[d['code']]}/", "daily") for d in dests]
    rows = "".join(f"  <url><loc>{u}</loc><lastmod>{day}</lastmod><changefreq>{f}</changefreq></url>\n" for u, f in urls)
    rows += f"  <url><loc>{base}/accessibility.html</loc><changefreq>yearly</changefreq></url>\n"
    out["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "</urlset>\n")
    return out


def main() -> int:
    data = json.loads((SITE / "data" / "deals.json").read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    files = build(data, cfg)
    for rel, text in files.items():
        p = SITE / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    print(f"  עמודי יעד: {len(files) - 2} עמודים + מפת אתר")
    return 0


if __name__ == "__main__":
    sys.exit(main())
