"""Pilot scene for a Turkish kids cartoon series (free tools only).

AI still images (Pollinations / Horde) + slow camera moves + several character voices (edge-tts)
+ gentle music + subtitles -> 16:9 MP4, plus a cover image.
Run: python tools/cizgi_ornek.py [--offline] --out sample_cizgi
"""
import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

W, H, FPS, SR = 1280, 720, 24, 24000

STYLE = ("high quality 3D animated family movie still, cute stylized cartoon characters with big expressive eyes, "
         "soft warm cinematic lighting, vibrant pastel colors, rich detailed background, wide 16:9 shot, "
         "child friendly, no text, no letters, no watermark")
MINA = ("Mina, a cute 6 year old Turkish girl with long wavy dark brown hair, big brown eyes, "
        "wearing a sunny yellow dress with a white collar")
EFE = ("Efe, her little 4 year old brother with short curly light brown hair, big brown eyes, "
       "wearing a green t-shirt with a white star and blue shorts")
DEDE = "Hasan Dede, a kind smiling elderly park gardener with a white mustache, a flat cap and green overalls"

VOICES = {   # name -> (edge voice, rate, pitch, subtitle colour)
    "Anlatıcı": ("tr-TR-AhmetNeural", "+0%", "+0Hz", (255, 255, 255)),
    "Mina": ("tr-TR-EmelNeural", "+6%", "+18Hz", (255, 214, 64)),
    "Efe": ("tr-TR-EmelNeural", "+10%", "+42Hz", (140, 230, 120)),
    "Hasan Dede": ("tr-TR-AhmetNeural", "-6%", "-6Hz", (150, 200, 255)),
}

SHOTS = [
    {"img": f"wide shot of a sunny green park in a Turkish town with tulips and a big plane tree, {MINA} and {EFE} "
            "running happily holding a red kite", "cam": (1.0, 1.12, -0.03, 0.03),
     "lines": [("Anlatıcı", "Güneşli bir sabah, Mina ile kardeşi Efe parka gitti.")]},
    {"img": f"{EFE} laughing and holding a kite string, a red kite high in the blue sky behind him, {MINA} clapping",
     "cam": (1.12, 1.0, 0.02, -0.02),
     "lines": [("Efe", "Abla bak! Uçurtmam çok yükseklere çıktı!"), ("Mina", "Vay canına, kuş gibi uçuyor!")]},
    {"img": f"strong wind blowing leaves, a broken kite string, the red kite flying away, {MINA} and {EFE} "
            "looking up surprised with open mouths", "cam": (1.0, 1.15, 0.0, -0.04),
     "lines": [("Anlatıcı", "Ama birden sert bir rüzgâr esti..."), ("Efe", "Eyvah! Uçurtmam gidiyor!")]},
    {"img": f"a red kite stuck high in the branches of a huge plane tree, {MINA} pointing up at it and {EFE} "
            "looking sad", "cam": (1.05, 1.18, 0.0, 0.05),
     "lines": [("Mina", "Üzülme Efe, bak! Uçurtma şu büyük ağaca takıldı."),
               ("Efe", "Ama çok yüksek... Nasıl alacağız?")]},
    {"img": f"close up of {MINA} thinking with a finger on her chin, {EFE} next to her, park background",
     "cam": (1.0, 1.1, -0.02, 0.0),
     "lines": [("Mina", "Hmm... Hadi düşünelim. Bir büyükten yardım isteyebiliriz!")]},
    {"img": f"{DEDE} walking towards {MINA} and {EFE} carrying a long wooden ladder in the park, smiling",
     "cam": (1.12, 1.0, 0.03, 0.0),
     "lines": [("Anlatıcı", "Parkın bahçıvanı Hasan Dede, uzun merdiveniyle hemen geldi."),
               ("Hasan Dede", "Merak etmeyin çocuklar, şimdi alırız!")]},
    {"img": f"{DEDE} handing the red kite to a very happy {EFE}, {MINA} smiling beside them, warm light",
     "cam": (1.0, 1.12, 0.0, 0.03),
     "lines": [("Efe", "Teşekkür ederim Hasan Dede!"), ("Hasan Dede", "Rica ederim evlat. Yardımlaşmak güzeldir!")]},
    {"img": f"{MINA} and {EFE} holding the kite string together, the red kite flying in an orange sunset sky, "
            "golden hour, joyful", "cam": (1.15, 1.0, 0.0, -0.03),
     "lines": [("Mina", "Bu sefer ipi birlikte tutalım!"),
               ("Anlatıcı", "Ve o gün Mina ile Efe, yardımlaşmanın ne kadar güzel olduğunu öğrendi.")]},
]
TITLE = "Mina ile Efe"
EPISODE = "Kayıp Uçurtma"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def font(size):
    for f in ("assets/Baloo2-Bold.ttf", "assets/Oswald-Bold.ttf"):
        p = ROOT / f
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


# ------------------------------------------------------------------ images
def fetch_image(prompt, path, seed):
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    q = {"width": 1344, "height": 768, "model": "flux", "nologo": "true", "seed": seed,
         "enhance": "false", "private": "true", "referrer": "tarihinkaranligi"}
    enc = urllib.parse.quote(prompt[:1500])
    targets = []
    if token:
        targets.append(("https://gen.pollinations.ai/image/" + enc + "?" + urllib.parse.urlencode(q),
                        {"Authorization": f"Bearer {token}"}))
    targets.append(("https://image.pollinations.ai/prompt/" + enc + "?" + urllib.parse.urlencode(q), {}))
    for attempt in range(3):
        for url, hdr in targets:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "tarihin-karanligi-bot/1.0", **hdr})
                with urllib.request.urlopen(req, timeout=150) as r:
                    data = r.read()
                if len(data) > 15000:
                    path.write_bytes(data)
                    Image.open(path).convert("RGB").save(path, "JPEG", quality=94)
                    return True
            except Exception as e:  # noqa: BLE001
                log("  image try failed:", str(e)[:120])
        time.sleep(8 * (attempt + 1))
    try:   # last resort: Stable Horde through the main renderer
        import render
        return render.fetch_horde(prompt, path, seed, time.time() + 600)
    except Exception as e:  # noqa: BLE001
        log("  horde failed:", e)
        return False


def placeholder(path, i):
    g = np.linspace(0, 1, W)[None, :, None] * np.ones((H, 1, 1))
    col = np.array([[90, 160, 230], [250, 190, 90], [120, 200, 140]][i % 3]) / 255
    img = (0.5 + 0.5 * g) * col
    Image.fromarray((img * 255).astype(np.uint8)).save(path)


# ------------------------------------------------------------------ voices
async def _tts(text, voice, rate, pitch, mp3):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await com.save(str(mp3))


def voice_clip(who, text, work, idx, offline):
    if offline:
        return np.zeros(int((0.35 + 0.075 * len(text)) * SR), np.float32)
    v, rate, pitch, _ = VOICES[who]
    mp3, wav = work / f"v{idx}.mp3", work / f"v{idx}.wav"
    for attempt in range(4):
        try:
            asyncio.run(_tts(text, v, rate, pitch, mp3))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR),
                            str(wav)], check=True)
            with wave.open(str(wav)) as w:
                return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        except Exception as e:  # noqa: BLE001
            log("  tts retry", attempt, e)
            time.sleep(4)
    raise RuntimeError("tts failed")


def music(n, seed=7):
    """Soft, simple kids tune (pluck + pad) looping under the dialogue."""
    t = np.arange(n) / SR
    notes = [0, 4, 7, 4, 5, 9, 7, 4, 2, 5, 9, 5, 4, 7, 12, 7]
    root = 261.63
    out = np.zeros(n, np.float32)
    beat = 0.5
    for k in range(int(n / SR / beat) + 1):
        f = root * 2 ** (notes[k % len(notes)] / 12)
        i0 = int(k * beat * SR)
        seg = np.arange(min(int(0.45 * SR), n - i0)) / SR
        if len(seg) <= 0:
            break
        env = np.exp(-seg * 6.0)
        out[i0:i0 + len(seg)] += (0.5 * np.sin(2 * np.pi * f * seg) + 0.2 * np.sin(4 * np.pi * f * seg)) * env
    pad = 0.15 * np.sin(2 * np.pi * root / 2 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.1 * t))
    return (out + pad) * 0.09


# ------------------------------------------------------------------ drawing
def text_box(lines_rgb, width):
    """lines_rgb: list of (text, rgb). Rounded dark box with coloured speaker text."""
    f = font(38)
    pad, gap = 22, 8
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    rows = []
    for txt, rgb in lines_rgb:
        words, cur = txt.split(), ""
        for w_ in words:
            test = (cur + " " + w_).strip()
            if d0.textlength(test, font=f) > width - 2 * pad and cur:
                rows.append((cur, rgb))
                cur = w_
            else:
                cur = test
        rows.append((cur, rgb))
    lh = 46
    h = pad * 2 + lh * len(rows) + gap * (len(rows) - 1)
    box = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(box)
    d.rounded_rectangle([0, 0, width - 1, h - 1], radius=26, fill=(20, 16, 40, 170))
    y = pad - 4
    for txt, rgb in rows:
        tw = d.textlength(txt, font=f)
        d.text(((width - tw) / 2, y), txt, font=f, fill=rgb, stroke_width=3, stroke_fill=(20, 10, 40))
        y += lh + gap
    return box


def title_card(base, title, episode):
    img = base.convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, H], fill=(10, 20, 60, 70))
    f1, f2 = font(120), font(64)
    for txt, f, y, fill in ((title, f1, H * 0.30, (255, 214, 64)), (episode, f2, H * 0.52, (255, 255, 255))):
        tw = d.textlength(txt, font=f)
        d.text(((W - tw) / 2, y), txt, font=f, fill=fill, stroke_width=8, stroke_fill=(70, 30, 110))
    img.alpha_composite(ov)
    return img.convert("RGB")


def cover(base, title, episode, out):
    img = base.resize((W, H)).convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f1, f2 = font(110), font(54)
    txt = episode.upper() + "!"
    tw = d.textlength(txt, font=f1)
    d.text(((W - tw) / 2, H - 200), txt, font=f1, fill=(255, 214, 64), stroke_width=10, stroke_fill=(70, 30, 110))
    d.rounded_rectangle([30, 30, 60 + d.textlength(title, font=f2), 112], radius=22, fill=(255, 90, 120, 235))
    d.text((45, 34), title, font=f2, fill=(255, 255, 255))
    img.alpha_composite(ov)
    img.convert("RGB").save(out, quality=92)


def kenburns(img, p, cam):
    z0, z1, dx, dy = cam
    e = 0.5 - 0.5 * math.cos(math.pi * p)
    z = z0 + (z1 - z0) * e
    cw, ch = W / z, H / z
    cx = W / 2 + dx * W * (e - 0.5) * 2
    cy = H / 2 + dy * H * (e - 0.5) * 2
    x0 = min(max(cx - cw / 2, 0), W - cw)
    y0 = min(max(cy - ch / 2, 0), H - ch)
    return img.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default="sample_cizgi")
    a = ap.parse_args()
    out = Path(a.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    # 1) images
    imgs = []
    for i, s in enumerate(SHOTS):
        p = work / f"shot{i}.jpg"
        ok = (not a.offline) and fetch_image(f"{s['img']}, {STYLE}", p, 4242 + i)
        if not ok:
            placeholder(p, i)
        log(f"image {i + 1}/{len(SHOTS)}", "ok" if ok else "placeholder")
        imgs.append(Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS))

    # 2) voices + timeline
    gap, lead, tail = 0.35, 0.6, 0.9
    clips, timeline, t = [], [], 3.0     # 3 s title card first
    shot_times = []
    k = 0
    for i, s in enumerate(SHOTS):
        st = t
        t += lead
        for who, txt in s["lines"]:
            a_ = voice_clip(who, txt, work, k, a.offline)
            k += 1
            clips.append((t, a_))
            timeline.append((t, t + len(a_) / SR, who, txt))
            t += len(a_) / SR + gap
        t += tail - gap
        shot_times.append((st, t))
    total = t + 0.8
    n = int(total * SR) + SR
    voice = np.zeros(n, np.float32)
    for st, a_ in clips:
        i0 = int(st * SR)
        voice[i0:i0 + len(a_)] += a_
    if np.abs(voice).max() > 0:
        voice *= 0.9 / np.abs(voice).max()
    mix = voice + music(n)
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)
    wav = work / "mix.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())

    # 3) frames
    nfr = int(total * FPS)
    tc = title_card(imgs[0].filter(ImageFilter.GaussianBlur(6)), TITLE, EPISODE)
    boxes = {}
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav),
                             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
                             str(out / "cizgi_ornek.mp4")], stdin=subprocess.PIPE)
    for fi in range(nfr):
        tt = fi / FPS
        if tt < 3.0:
            frame = tc
            if tt > 2.5:
                frame = Image.blend(tc, kenburns(imgs[0], 0, SHOTS[0]["cam"]), (tt - 2.5) / 0.5)
        else:
            si = next((j for j, (a0, b0) in enumerate(shot_times) if a0 <= tt < b0), len(SHOTS) - 1)
            a0, b0 = shot_times[si]
            frame = kenburns(imgs[si], (tt - a0) / max(0.1, b0 - a0), SHOTS[si]["cam"])
            if si + 1 < len(SHOTS) and tt > b0 - 0.45:   # cross-fade into the next shot
                nxt = kenburns(imgs[si + 1], 0, SHOTS[si + 1]["cam"])
                frame = Image.blend(frame, nxt, (tt - (b0 - 0.45)) / 0.45)
            cur = [(who, txt) for (s0, s1, who, txt) in timeline if s0 - 0.1 <= tt <= s1 + 0.25]
            if cur:
                who, txt = cur[-1]
                key = (who, txt)
                if key not in boxes:
                    label = txt if who == "Anlatıcı" else f"{who}: {txt}"
                    boxes[key] = text_box([(label, VOICES[who][3])], 1040)
                b = boxes[key]
                frame = frame.convert("RGBA")
                frame.alpha_composite(b, ((W - b.width) // 2, H - b.height - 28))
                frame = frame.convert("RGB")
        proc.stdin.write(np.asarray(frame, dtype=np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()
    cover(imgs[2], TITLE, EPISODE, out / "kapak.jpg")
    (out / "info.json").write_text(json.dumps({"duration": round(total, 1), "shots": len(SHOTS)}, indent=1))
    log("done", round(total, 1), "s")


if __name__ == "__main__":
    main()
