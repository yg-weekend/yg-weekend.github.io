"""Downloads 2-4 real Wikimedia Commons photos per destination into site/img/gallery/<CODE>/.
Used for the Instagram reels and for the site. Only free licenses (CC BY / CC BY-SA / CC0 / public domain).
Credits go to site/data/gallery.json. Runs from .github/workflows/photos.yml."""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "img" / "gallery"
DATA = ROOT / "site" / "data" / "gallery.json"
UA = "YGWeekendBot/1.0 (https://yg-weekend.github.io)"
PER_DEST = 4
WIDTH = 1280
BAD = re.compile(r"map|flag|logo|coat|arms|locator|diagram|seal|emblem|icon|chart|plan|svg|banner|signature|"
                 r"portrait|bust|statue of|coin|stamp|graph|location|montage|collage|panorama", re.I)
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


def candidates(dest):
    """File titles: lead image of the photo article first, then images used in the city article."""
    titles = []
    for article in [dest.get("photo"), dest.get("city_en")]:
        if not article:
            continue
        j = api("en.wikipedia.org", action="query", titles=article, redirects=1,
                prop="pageimages|images", piprop="name", imlimit=60)
        for p in j.get("query", {}).get("pages", []):
            if p.get("pageimage"):
                titles.append("File:" + p["pageimage"])
            for im in p.get("images", []):
                titles.append(im["title"])
    seen, out = set(), []
    for t in titles:
        if t not in seen and t.lower().endswith((".jpg", ".jpeg")) and not BAD.search(t):
            seen.add(t)
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
        if len(gallery.get(code, [])) >= 2:
            continue
        print(code, d.get("city_en"))
        titles = candidates(d)
        meta = info(titles)
        picked = []
        for t in titles:
            ii = meta.get(t)
            if not ii or ii.get("mime") != "image/jpeg" or ii.get("width", 0) < 1200:
                continue
            em = ii.get("extmetadata", {})
            lic = clean(em.get("LicenseShortName", {}).get("value"))
            if not FREE.search(lic):
                continue
            picked.append((t, ii, lic, clean(em.get("Artist", {}).get("value"))[:80]))
            if len(picked) >= PER_DEST:
                break
        folder = OUT / code
        folder.mkdir(parents=True, exist_ok=True)
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
                          "license": lic, "source": ii.get("descriptionurl")})
            time.sleep(0.5)
        gallery[code] = items
        print("  ", len(items), "photos")
        DATA.write_text(json.dumps(gallery, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(1)


if __name__ == "__main__":
    main()
