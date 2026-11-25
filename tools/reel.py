"""YG Weekend reel template: real destination photos with slow zoom/pan (Ken Burns), crossfades,
animated Hebrew text from live deals.json, original music.  Usage: python3 reel.py LCA [shabbat|general] [photo indexes, e.g. 0,1]"""
import json, math, os, subprocess, sys, urllib.request
from datetime import date
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H, FPS = 1080, 1920, 30
RAW = 'https://raw.githubusercontent.com/yg-weekend/yg-weekend.github.io/main/'
FD = '/tmp/ayvideo/.claude/skills/hebrew-captions/fonts/'  # Heebo / Rubik (OFL) from AY Video Editor
if not os.path.isdir(FD):
    subprocess.run(['git', 'clone', '-q', '--depth', '1', 'https://github.com/Amiryaco/ay-video-editor.git', '/tmp/ayvideo'], check=True)
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = '/tmp/ygreel'
OUTDIR = os.environ.get('OUTDIR', '/mnt/user-data/outputs')
os.makedirs(WORK, exist_ok=True)
def F(name, size): return ImageFont.truetype(FD + name, size)
BLACK, BOLD, MED = 'Heebo-Black.ttf', 'Heebo-Bold.ttf', 'Heebo-Medium.ttf'
CX = 470
ORANGE, NAVY = (255, 122, 60), (18, 45, 90)
DAYS = {'ראשון': 'ראשון', 'שני': 'שני', 'שלישי': 'שלישי', 'רביעי': 'רביעי', 'חמישי': 'חמישי', 'שישי': 'שישי', 'מוצאי שבת': 'מוצ״ש'}

def get(path):
    with urllib.request.urlopen(RAW + path, timeout=60) as r: return r.read()

def ease(t): t = max(0, min(1, t)); return 1 - (1 - t) ** 3
def ddmm(s): y, m, d = s.split('-'); return f'{int(d)}.{int(m)}'

# ---------------------------------------------------------------- photos
def load_photo(rel):
    p = os.path.join(WORK, rel.replace('/', '_'))
    if not os.path.exists(p):
        open(p, 'wb').write(get('site/' + rel))
    im = Image.open(p).convert('RGB')
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.3)).enhance(1.12)
    # cover-crop to 9:16 at 1.2x so there is room to move
    tw, th = int(W * 1.2), int(H * 1.2)
    s = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * s + 1), int(im.height * s + 1)), Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    return im.crop((l, t, l + tw, t + th))

def kenburns(img, t, dur, mode):
    z = 1.0 + 0.16 * (t / dur) if mode % 2 == 0 else 1.16 - 0.16 * (t / dur)
    cw, ch = img.width / z / 1.2 * 1.2, img.height / z / 1.2 * 1.2
    cw, ch = img.width / (z * 1.0), img.height / (z * 1.0)
    cw, ch = min(cw, img.width), min(ch, img.height)
    k = t / dur
    dx = (img.width - cw) * (k if mode in (1, 2) else 1 - k) if mode != 3 else (img.width - cw) / 2
    dy = (img.height - ch) / 2
    return img.crop((int(dx), int(dy), int(dx + cw), int(dy + ch))).resize((W, H), Image.BILINEAR)

SHADE = None
def shade():
    global SHADE
    if SHADE is None:
        g = Image.new('L', (1, H))
        for y in range(H):
            # darker band behind the text area (y 380-1250) and at the very top/bottom
            v = 70 + int(90 * math.exp(-((y - 820) / 520) ** 2))
            g.putpixel((0, y), v)
        SHADE = Image.merge('RGBA', [Image.new('L', (W, H), 8), Image.new('L', (W, H), 18), Image.new('L', (W, H), 40), g.resize((W, H))])
    return SHADE

# ---------------------------------------------------------------- text
def text(img, s, y, font, fill=(255, 255, 255), alpha=1.0, dx=0, box=None):
    if alpha <= 0: return img
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = CX + dx
    if box:
        bb = d.textbbox((x, y), s, font=font, anchor='mm', direction='rtl')
        d.rounded_rectangle([bb[0] - 34, bb[1] - 22, bb[2] + 34, bb[3] + 22], 28, fill=box + (int(235 * alpha),))
    else:
        d.text((x + 3, y + 4), s, font=font, fill=(0, 0, 0, int(140 * alpha)), anchor='mm', direction='rtl')
    d.text((x, y), s, font=font, fill=fill + (int(255 * alpha),), anchor='mm', direction='rtl')
    return Image.alpha_composite(img, layer)

def fit(s, font_name, size, maxw=820):
    while size > 30 and ImageDraw.Draw(Image.new('RGB', (1, 1))).textlength(s, font=F(font_name, size), direction='rtl') > maxw:
        size -= 4
    return F(font_name, size)

# ---------------------------------------------------------------- build
def main():
    code = sys.argv[1]
    lst = sys.argv[2] if len(sys.argv) > 2 else 'shabbat'
    deals = json.loads(get('site/data/deals.json'))
    cfg = json.loads(get('config.json'))
    gallery = json.loads(get('site/data/gallery.json'))
    dest = next(d for d in cfg['destinations'] if d['code'] == code)
    deal = min((x for x in deals['lists'][lst] if x['dest'] == code), key=lambda x: x['price'])
    pick = [int(x) for x in sys.argv[3].split(',')] if len(sys.argv) > 3 else range(4)
    photos = [gallery[code][i] for i in pick if i < len(gallery[code])]
    imgs = [load_photo(p['file']) for p in photos]
    imgs = [imgs[i % len(imgs)] for i in range(4)]
    checked = deals['generated_at'][:10]
    country = {'🇨🇾': 'קפריסין', '🇬🇷': 'יוון', '🇮🇹': 'איטליה', '🇭🇺': 'הונגריה', '🇨🇿': 'צ׳כיה', '🇷🇴': 'רומניה', '🇧🇬': 'בולגריה',
               '🇦🇹': 'אוסטריה', '🇩🇪': 'גרמניה', '🇫🇷': 'צרפת', '🇪🇸': 'ספרד', '🇵🇱': 'פולין', '🇬🇪': 'גאורגיה', '🇲🇪': 'מונטנגרו',
               '🇭🇷': 'קרואטיה', '🇵🇹': 'פורטוגל', '🇳🇱': 'הולנד', '🇬🇧': 'אנגליה', '🇦🇪': 'איחוד האמירויות', '🇹🇭': 'תאילנד'}.get(deal['flag'], deal['name'])
    nights = (date.fromisoformat(deal['ret_date']) - date.fromisoformat(deal['out_date'])).days
    direct = 'טיסה ישירה' if deal['stops'] == 0 else 'עם עצירה אחת'
    shabbat_rows = ['נוחתים לפני שבת, בלי לחץ' if lst == 'shabbat' else f'כ-{deal["to_center_min"]} דקות מהשדה למרכז']
    kn = (dest.get('kosher') or {}).get('tier')
    if lst == 'shabbat':
        week = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']
        arr_day = deal['out_day']
        if deal.get('out_arr') and deal['out_arr'] < deal['out_dep'] and arr_day in week:
            arr_day = week[(week.index(arr_day) + 1) % 7]
        land = f'נוחתים ב{arr_day} ב-{deal["out_arr"]}' if deal.get('out_arr') else f'נוחתים עד {deal["land_by"]}'
        shabbat_rows = [land + (f' · שבת ב-{deal["candle_lighting"]}' if arr_day == 'שישי' else ', הרבה לפני שבת'),
                        'בית חב״ד עם ארוחות שבת' if kn in ('full', 'chabad', 'seasonal') else 'יש אפשרויות כשרות באזור',
                        f'{deal["to_center_min"]} דקות מהשדה למרכז']
    # Photo credit line for the END OF THE CAPTION (under the hashtags), not for the video itself:
    # names grouped by licence, only for the photos used in this reel, nothing truncated.
    by_lic = {}
    for p in photos:
        names = by_lic.setdefault(p.get('license') or '', [])
        name = p.get('credit') or 'Wikimedia'
        if name not in names: names.append(name)
    credit_line = '📷 ' + ', '.join(', '.join(n) + (f' ({lic})' if lic else '') for lic, n in sorted(by_lic.items(), key=lambda kv: kv[0] == '')) + ' · Wikimedia Commons'

    def s1(t, dur):
        img = text(Image.new('RGBA', (W, H)), 'YG Weekend · דיל היום', 300, F(BOLD, 46), fill=(255, 240, 200))
        img = text(img, f'סופ״ש ב{country}', 560, fit(f'סופ״ש ב{country}', BLACK, 118))
        pop = 1 + 0.12 * math.sin(math.pi * min(1, t / 0.5)) if t < 0.5 else 1
        img = text(img, f'{deal["price"]} ש״ח', 800, F(BLACK, int(180 * pop)), box=ORANGE)
        img = text(img, f'הלוך-חזור לאדם · {direct}', 1010, F(BOLD, 58), alpha=ease((t - 0.3) / 0.4))
        return img

    def rows(title, rr):
        def f(t, dur):
            img = text(Image.new('RGBA', (W, H)), 'YG Weekend', 300, F(BOLD, 46), fill=(255, 240, 200))
            img = text(img, title, 520, fit(title, BLACK, 100), alpha=ease(t / 0.4))
            for i, r in enumerate(rr):
                tt = t - 0.5 - i * 0.55
                if tt > 0:
                    e = ease(tt / 0.4)
                    img = text(img, r, 720 + i * 175, fit(r, BOLD, 62, 760), alpha=e, dx=int(80 * (1 - e)), box=NAVY)
            return img
        return f

    def s4(t, dur):
        img = text(Image.new('RGBA', (W, H)), 'YG Weekend · דיל היום', 300, F(BOLD, 46), fill=(255, 240, 200))
        img = text(img, 'רוצים את הדיל?', 540, F(BLACK, 104), alpha=ease(t / 0.4))
        if t > 0.4: img = text(img, 'תכתבו סופש בתגובות', 760, F(BLACK, 84), alpha=ease((t - 0.4) / 0.4), box=ORANGE)
        if t > 0.9: img = text(img, 'ונשלח לכם את הקישור בפרטי', 950, F(BOLD, 60), alpha=ease((t - 0.9) / 0.4))
        if t > 1.3: img = text(img, 'yg-weekend.github.io', 1100, F(BOLD, 48), alpha=0.9 * ease((t - 1.3) / 0.4))
        img = text(img, f'מחיר שנבדק ב-{ddmm(checked)}.{checked[:4]} ועשוי להשתנות', 1330, F(MED, 34), alpha=0.95)
        return img

    od, rd = DAYS.get(deal['out_day'], deal['out_day']), DAYS.get(deal['ret_day'], deal['ret_day'])
    if deal['ret_day'] == 'שבת': rd = 'מוצ״ש'
    scenes = [(s1, 3.6), (rows(f'{deal["name"]}, {country}', [f'יוצאים: {od} {ddmm(deal["out_date"])} · {deal["out_dep"]}',
                                                           f'חוזרים: {rd} {ddmm(deal["ret_date"])} · {deal["ret_dep"]}',
                                                           f'{nights} לילות של חופש']), 4.4),
              (rows('שומרי שבת?' if lst == 'shabbat' else 'מה עוד חשוב לדעת', shabbat_rows), 4.2), (s4, 4.0)]
    XF = 0.5
    files = []
    for i, (fn, dur) in enumerate(scenes):
        out = f'{WORK}/{code}_{i}.mp4'; tmp = out[:-4] + '.tmp.mp4'
        n = int(round(dur * FPS))
        p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
        for k in range(n):
            t = k / FPS
            bg = kenburns(imgs[i], t + XF, dur + XF, i)
            if i > 0 and t < XF:  # crossfade from previous scene's photo (its continued motion)
                pd = scenes[i - 1][1]
                prev = kenburns(imgs[i - 1], pd + XF + t, pd + XF + XF, i - 1)
                bg = Image.blend(prev, bg, ease(t / XF))
            fr = Image.alpha_composite(bg.convert('RGBA'), shade())
            ov = fn(t, dur)
            if t > dur - 0.35:  # text fades out before the cut
                a = ov.getchannel('A').point(lambda v, m=max(0, (dur - t) / 0.35): int(v * m)); ov.putalpha(a)
            fr = Image.alpha_composite(fr, ov)
            if i == 0 and k < 8: fr = Image.blend(Image.new('RGBA', (W, H), (0, 0, 0, 255)), fr, k / 8)
            p.stdin.write(fr.convert('RGB').tobytes())
        p.stdin.close()
        if p.wait() == 0: os.replace(tmp, out); files.append(out)
    total = sum(d for _, d in scenes)
    lst_txt = f'{WORK}/{code}_list.txt'
    open(lst_txt, 'w').write(''.join(f"file '{f}'\n" for f in files))
    subprocess.run([sys.executable, os.path.join(HERE, 'music.py'), str(total), f'{WORK}/music.wav'], check=True)
    os.makedirs(OUTDIR, exist_ok=True)
    final = f'{OUTDIR}/yg-weekend-{code.lower()}-reel.mp4'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst_txt, '-c', 'copy', f'{WORK}/{code}_v.mp4'], check=True)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', f'{WORK}/{code}_v.mp4', '-i', f'{WORK}/music.wav', '-map', '0:v', '-map', '1:a',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', final], check=True)
    print(final, total, deal['price'], deal['out_date'], [p['file'] for p in photos])
    open(final[:-4] + '.credit.txt', 'w', encoding='utf-8').write(credit_line + '\n')
    print(credit_line)

if __name__ == '__main__':
    main()
