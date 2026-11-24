"""Downloads 2-4 real Wikimedia Commons photos per destination into site/img/gallery/<CODE>/.
Picks reviewed Quality / Featured / Valued photos of each city. Only free licenses (CC BY / CC BY-SA / CC0 / PD).
Credits go to site/data/gallery.json. Used for the Instagram reels. Runs from .github/workflows/photos.yml."""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "img" / "gallery"
DATA = ROOT / "site" / "data" / "gallery.json"
UA = "YGWeekendBot/1.0 (https://yg-weekend.github.io)"
PER_DEST = 4
WIDTH = 2048
VERSION = 2
BAD = re.compile(r"map|flag|logo|coat|arms|\bcoa\b|locator|diagram|seal|emblem|icon|chart|svg|banner|signature|"
                 r"portrait|bust|statue|coin|stamp|graph|montage|collage|airport|aircraft|airplane|air force|dornier|"
                 r"boeing|airbus|church|cathedral|basilica|chapel|mosque|tekke|minaret|monastery|temple|synagogue|"
                 r"ceiling|fresco|dome|interior|inside|altar|relief|crucifix|cross|gull|bird|insect|flower|door|"
                 r"shop|phone|administration|museum|painting|mural|tomb|grave|cemetery|memorial|police|military|"
                 r"protest|demonstration|\bcar\b|\bbus\b|tram|train|metro|station|food|dish|mezquita|moschee|kirche|glise|"
                 r"iglesia|chiesa|cerkiew|ko\u015bci|catedral|duomo|kapelle|sinagoga|\ba3\d\d\b|plane|\bp\d\d\b", re.I)
FREE = re.compile(r"^(cc[- ]by(-sa)?[- ]?\d|cc0|public domain|pd)", re.I)


def api(host, **params):
    params.update(format="json", formatversion="2")
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print("  retry", attempt, e)
            time.sleep(3 * (attempt + 1))
    return {}


def search(query, limit=50):
    j = api("commons.wikimedia.org", action="query", list="search", srnamespace=6, srlimit=limit, srsearch=query)
    return [x["title"] for x in j.get("query", {}).get("search", [])]


def candidates(dest):
    city = dest.get("city_en") or dest.get("name")
    titles = []
    for cat in ["Quality_images", "Featured_pictures_on_Wikimedia_Commons", "Valued_images_sorted_by_promotion_date"]:
        titles += search(f'"{city}" incategory:{cat} filetype:bitmap')
    if dest.get("photo"):
        j = api("en.wikipedia.org", action="query", titles=dest["photo"], redirects=1, prop="pageimages", piprop="name")
        for p in j.get("query", {}).get("pages", []):
            if p.get("pageimage"):
                titles.append("File:" + p["pageimage"])
    seen, stems, out = set(), set(), []
    for t in titles:
        stem = re.sub(r"[\d_().,-]+", " ", t.lower())[:28]
        if t in seen or stem in stems or not t.lower().endswith((".jpg", ".jpeg")) or BAD.search(t):
            continue
        seen.add(t)
        stems.add(stem)
        out.append(t)
    return out


def info(titles):
    res = {}
    for i in range(0, len(titles), 40):
        j = api("commons.wikimedia.org", action="query", titles="|".join(titles[i:i + 40]),
                prop="imageinfo", iiprop="url|size|extmetadata|mime", iiurlwidth=WIDTH)
        for p in j.get("query", {}).get("pages", []):
            ii = (p.get("imageinfo") or [None])[0]
            if ii:
                res[p["title"]] = ii
    return res


def clean(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    gallery = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}
    for d in cfg["destinations"]:
        code = d["code"]
        have = gallery.get(code, [])
        if len(have) >= 2 and all(x.get("v") == VERSION for x in have):
            continue
        print(code, d.get("city_en"))
        titles = candidates(d)
        meta = info(titles[:60])
        picked = []
        for t in titles:
            ii = meta.get(t)
            if not ii or ii.get("mime") != "image/jpeg":
                continue
            w, h = ii.get("width", 0), ii.get("height", 1)
            if w < 1800 or w < 1.2 * h:
                continue
            em = ii.get("extmetadata", {})
            lic = clean(em.get("LicenseShortName", {}).get("value"))
            if not FREE.search(lic):
                continue
            picked.append((t, ii, lic, clean(em.get("Artist", {}).get("value"))[:80]))
            if len(picked) >= PER_DEST:
                break
        if len(picked) < 2 and len(have) >= 2:
            print("   keeping the old photos")
            continue
        folder = OUT / code
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.jpg"):
            old.unlink()
        items = []
        for n, (t, ii, lic, artist) in enumerate(picked, 1):
            path = folder / f"{n}.jpg"
            req = urllib.request.Request(ii.get("thumburl") or ii["url"], headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    path.write_bytes(r.read())
            except Exception as e:
                print("  ! download", t, e)
                continue
            items.append({"file": f"img/gallery/{code}/{n}.jpg", "title": t, "credit": artist,
                          "license": lic, "source": ii.get("descriptionurl"), "v": VERSION})
            time.sleep(0.5)
        gallery[code] = items
        print("  ", len(items), "photos")
        DATA.write_text(json.dumps(gallery, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(1)


if __name__ == "__main__":
    main()
