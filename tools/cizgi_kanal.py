"""Channel setup for 'Mina ile Efe': banner + profile picture, description, keywords, country, made-for-kids.

usage: python tools/cizgi_kanal.py LIB_DIR OUT_DIR [--apply]
--apply needs YT_CLIENT_ID, YT_CLIENT_SECRET, MINA_REFRESH_TOKEN (the profile picture cannot be set by the API;
it is saved as profil.png for a manual upload).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DESCRIPTION = """Mina ile Efe'ye hoş geldiniz! 🌷

Mina, meraklı ve yardımsever bir abla. Efe ise neşeli, biraz sakar ve bol soru soran küçük kardeşi. Bilge Hasan Dede de onların en büyük yardımcısı. Her bölümde birlikte yeni bir şey öğreniyor, sorunları el ele çözüyorlar.

📚 Okul öncesi (3-7 yaş) çocuklar için eğitici, sakin ve neşeli çizgi dizi
🤝 Paylaşmak, yardımlaşmak, temizlik, renkler, sayılar, duygular, doğa sevgisi ve güvenlik
🎬 Her gün yeni bir bölüm

Çocuklarımız güvenle izleyebilsin diye bölümlerde şiddet, korku ve reklam amaçlı ürün yer almaz.

Yeni bölümleri kaçırmamak için abone olun! 🔔"""
KEYWORDS = ['"Mina ile Efe"', '"çizgi film"', '"çocuk çizgi filmi"', '"eğitici çizgi film"', '"türkçe çizgi film"',
            '"okul öncesi"', '"çocuklar için"', '"masal"', '"çizgi dizi"', '"eğitici video"', '"değerler eğitimi"',
            '"renkleri öğreniyorum"', '"sayıları öğreniyorum"', '"Hasan Dede"']


def font(size):
    for f in ("assets/Baloo2-Bold.ttf", "assets/Oswald-Bold.ttf"):
        if (ROOT / f).exists():
            return ImageFont.truetype(str(ROOT / f), size)
    return ImageFont.load_default()


def sprite(lib, choice, ch, pose, height):
    name = choice.get(ch, {}).get(pose) or f"{ch}_{pose}_1.png"
    p = lib / "png" / name
    if not p.exists():
        p = lib / "png" / f"{ch}_happy_1.png"
    im = Image.open(p).convert("RGBA")
    return im.resize((int(im.width * height / im.height), height), Image.LANCZOS)


def cover(im, w, h):
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def text(d, xy, txt, size, fill, stroke=10, anchor="mm"):
    d.text(xy, txt, font=font(size), fill=fill, stroke_width=stroke, stroke_fill=(70, 30, 110), anchor=anchor)


def banner(lib, choice, out):
    W, H = 2560, 1440
    src = Image.open(lib / "bg" / choice.get("bg", {}).get("park_wide", "park_wide_1.jpg")).convert("RGB")
    bg = cover(src, W, int(H * 1.25)).crop((0, int(H * 0.25), W, int(H * 1.25)))   # grass line up to the feet
    img = bg.convert("RGBA")
    # soft light band behind the safe area (1546x423 in the middle is visible everywhere)
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(band).rounded_rectangle([W / 2 - 700, H / 2 - 190, W / 2 + 700, H / 2 + 190], radius=60,
                                           fill=(255, 255, 255, 120))
    img.alpha_composite(band.filter(ImageFilter.GaussianBlur(18)))
    cy = H // 2
    m = sprite(lib, choice, "mina", "wave", 430)
    e = sprite(lib, choice, "efe", "happy", 350)
    dd = sprite(lib, choice, "dede", "happy", 470)
    img.alpha_composite(m, (W // 2 - 760 - m.width // 2, cy + 215 - m.height))
    img.alpha_composite(e, (W // 2 + 760 - e.width // 2, cy + 215 - e.height))
    img.alpha_composite(dd, (W // 2 + 1000 - dd.width // 2, cy + 230 - dd.height))
    d = ImageDraw.Draw(img)
    text(d, (W // 2, cy - 50), "Mina ile Efe", 190, (255, 214, 64), 14)
    pill = "Her gün yeni bölüm!  •  Eğitici çizgi dizi"
    f = font(64)
    tw = d.textlength(pill, font=f)
    d.rounded_rectangle([W / 2 - tw / 2 - 36, cy + 75, W / 2 + tw / 2 + 36, cy + 165], radius=45, fill=(255, 90, 120, 240))
    d.text((W // 2, cy + 120), pill, font=f, fill=(255, 255, 255), anchor="mm")
    img.convert("RGB").save(out / "banner.jpg", quality=90)


def profile(lib, choice, out):
    S = 800
    img = Image.new("RGBA", (S, S))
    g = ImageDraw.Draw(img)
    for y in range(S):   # sunny sky gradient
        t = y / S
        g.line([(0, y), (S, y)], fill=(int(255 - 60 * t), int(222 - 40 * t), int(120 + 100 * t), 255))
    ImageDraw.Draw(img).ellipse([40, 40, S - 40, S - 40], fill=(255, 255, 255, 70))
    m = sprite(lib, choice, "mina", "happy", 900)
    e = sprite(lib, choice, "efe", "happy", 800)
    gap = max(0, (S - 20 - m.width - e.width) // 3)
    img.alpha_composite(m, (gap + 10, 90))
    img.alpha_composite(e, (S - 10 - gap - e.width, 190))
    img.convert("RGB").save(out / "profil.png")


def api(tok, url, body=None, method="GET", ctype="application/json", raw=None):
    req = urllib.request.Request(url if url.startswith("http") else "https://www.googleapis.com/youtube/v3/" + url,
                                 data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None),
                                 method=method, headers={"Authorization": f"Bearer {tok}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read()[:400]!r}")


def apply(out):
    body = json.dumps({"client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
                       "refresh_token": os.environ["MINA_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tok = json.loads(r.read())["access_token"]
    ch = api(tok, "channels?part=snippet,brandingSettings,status&mine=true")["items"][0]
    name = ch["snippet"]["title"]
    res = {"channel": name, "id": ch["id"]}
    print("channel:", name, ch["id"], flush=True)
    if "minaileefe" not in name.lower().replace(" ", ""):
        raise SystemExit("wrong channel: " + name)
    try:
        b = api(tok, "https://www.googleapis.com/upload/youtube/v3/channelBanners/insert?uploadType=media",
                raw=(out / "banner.jpg").read_bytes(), method="POST", ctype="image/jpeg")
        res["banner_url"] = b.get("url")
    except Exception as e:  # noqa: BLE001
        res["banner_error"] = str(e)[:300]
    bs = ch.get("brandingSettings", {})
    chan = bs.get("channel", {})
    chan.update({"description": DESCRIPTION, "keywords": " ".join(KEYWORDS), "country": "TR", "defaultLanguage": "tr"})
    chan.pop("title", None)
    new_bs = {"channel": chan}
    if res.get("banner_url"):
        new_bs["image"] = {"bannerExternalUrl": res["banner_url"]}
    try:
        api(tok, "channels?part=brandingSettings", {"id": ch["id"], "brandingSettings": new_bs}, "PUT")
        res["branding"] = "ok"
    except Exception as e:  # noqa: BLE001
        res["branding_error"] = str(e)[:300]
        try:   # retry without the banner (in case only the banner was rejected)
            new_bs.pop("image", None)
            api(tok, "channels?part=brandingSettings", {"id": ch["id"], "brandingSettings": new_bs}, "PUT")
            res["branding"] = "ok (no banner)"
        except Exception as e2:  # noqa: BLE001
            res["branding_error2"] = str(e2)[:300]
    try:
        api(tok, "channels?part=status", {"id": ch["id"], "status": {"selfDeclaredMadeForKids": True}}, "PUT")
        res["made_for_kids"] = "ok"
    except Exception as e:  # noqa: BLE001
        res["made_for_kids_error"] = str(e)[:300]
    try:   # the series playlist, so the channel page has a shelf from day one
        items = api(tok, "playlists?part=snippet&mine=true&maxResults=50").get("items", [])
        if not any(i["snippet"]["title"] == "Mina ile Efe - Tüm Bölümler" for i in items):
            api(tok, "playlists?part=snippet,status", {
                "snippet": {"title": "Mina ile Efe - Tüm Bölümler", "defaultLanguage": "tr",
                            "description": "Mina ile Efe çizgi dizisinin bütün bölümleri. Okul öncesi çocuklar için eğitici, neşeli hikâyeler."},
                "status": {"privacyStatus": "public"}}, "POST")
        res["playlist"] = "ok"
    except Exception as e:  # noqa: BLE001
        res["playlist_error"] = str(e)[:300]
    after = api(tok, "channels?part=brandingSettings,status&mine=true")["items"][0]
    res["now"] = {"country": after["brandingSettings"]["channel"].get("country"),
                  "keywords": after["brandingSettings"]["channel"].get("keywords", "")[:80],
                  "madeForKids": after.get("status", {}).get("madeForKids"),
                  "banner": bool(after["brandingSettings"].get("image", {}).get("bannerExternalUrl"))}
    return res


if __name__ == "__main__":
    lib, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    cp = lib / "choice.json"
    choice = json.loads(cp.read_text()) if cp.exists() else {}
    banner(lib, choice, out)
    profile(lib, choice, out)
    result = {"images": "ok"}
    if "--apply" in sys.argv:
        result.update(apply(out))
    (out / "sonuc.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=1))
