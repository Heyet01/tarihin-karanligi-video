"""Tarihin Karanligi - free Shorts renderer.

Turns a job (cover text + scenes) into a 9:16 documentary-thriller Short:
AI still per scene -> cinematic camera move (PUSH / ORBIT / RISE / DRIFT) with
handheld micro-shake, 24 fps, drifting dust, sliding shadows, film grain,
parchment texture, edge darkening, red GIZLI stamp, 2-word cover, captions,
Edge TTS narration and a low drone bed.
"""
import argparse
import asyncio
import json
import math
import os
import random
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 720, 1280          # output
SW, SH = 1080, 1920       # working source size
FPS = 24
SR = 48000
ROOT = Path(__file__).resolve().parent
FONT = str(ROOT / "assets" / "Oswald-Bold.ttf")
VOICE = "tr-TR-AhmetNeural"

STYLE = (
    "ultra detailed cinematic 3D render, photorealistic hyper detailed environment with "
    "culture-specific objects and weathered textures, all human figures are translucent frosted "
    "glass humanoid silhouettes reflecting the environment through them, faceless, featureless, "
    "anonymous ghost-like, expressive body posture only, shallow depth of field, sharp foreground, "
    "softly blurred background, dramatic single-source directional side lighting casting long deep "
    "shadows across textured surfaces, subtle analog film grain, suspended dust particles catching "
    "the light, subtle aged parchment texture, red classified stamp mark partially visible at the "
    "frame edge, vertical cinematic composition, faces never visible, documentary thriller, "
    "Unreal Engine photorealism, still frame aesthetic, no text, no letters"
)
COLOR_MODES = {
    "WARM": "warm desaturated golden-amber haze, slightly faded vintage film color grade, "
            "sand-colored walls, earthy shadow tones",
    "COLD": "deep cold teal-black atmosphere, glowing neon cyan or green accents, sharp-edged "
            "lighting, near-dark environment with precise spot lighting",
    "INFO": "pure matte black background, bright white icon illustrations, gear and network node "
            "visual elements, red glow from an off-screen source at the top corners, floating data "
            "visualization elements",
}
CAMERAS = ["PUSH", "ORBIT", "RISE", "DRIFT"]


def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------- images
def build_prompt(scene):
    mode = str(scene.get("color_mode", "WARM")).upper()
    desc = str(scene.get("scene", "")).strip().replace('"', "'")[:420]
    return f"{desc}, {COLOR_MODES.get(mode, COLOR_MODES['WARM'])}, {STYLE}"


def fetch_image(prompt, path, seed):
    token = os.environ.get("POLLINATIONS_TOKEN", "")
    q = {"width": 768, "height": 1344, "model": "flux", "nologo": "true",
         "seed": seed, "enhance": "false", "private": "true", "referrer": "tarihinkaranligi"}
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
           + "?" + urllib.parse.urlencode(q))
    headers = {"User-Agent": "tarihin-karanligi-bot/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) < 20000:
                raise RuntimeError(f"image too small ({len(data)} bytes)")
            Path(path).write_bytes(data)
            Image.open(path).verify()
            return True
        except Exception as e:  # noqa: BLE001
            wait = 10 * (attempt + 1)
            log(f"  image attempt {attempt + 1} failed: {e}; retry in {wait}s")
            time.sleep(wait)
    return False


def cover_resize(img, w, h):
    iw, ih = img.size
    s = max(w / iw, h / ih)
    img = img.resize((max(w, round(iw * s)), max(h, round(ih * s))), Image.LANCZOS)
    iw, ih = img.size
    l, t = (iw - w) // 2, (ih - h) // 2
    return img.crop((l, t, l + w, t + h))


def grade(img, mode):
    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
    lum = (a @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
    a = lum + (a - lum) * 0.82                      # gentle desaturation
    a = np.clip((a - 0.5) * 1.08 + 0.5, 0, 1)       # a touch of contrast
    if mode == "COLD":
        tint_s, tint_h = np.array([0.00, 0.035, 0.05]), np.array([-0.01, 0.01, 0.02])
    elif mode == "INFO":
        tint_s, tint_h = np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])
    else:
        tint_s, tint_h = np.array([0.045, 0.025, -0.005]), np.array([0.03, 0.01, -0.03])
    a = a + tint_s * (1 - lum) + tint_h * lum
    a = 0.035 + a * 0.95                              # faded film blacks
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def fallback_image(seed):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:SH, 0:SW].astype(np.float32)
    base = 0.08 + 0.18 * np.exp(-(((x - SW * 0.3) / 700) ** 2 + ((y - SH * 0.4) / 900) ** 2))
    n = rng.standard_normal((SH // 16, SW // 16)).astype(np.float32)
    n = np.asarray(Image.fromarray(n).resize((SW, SH), Image.BICUBIC))
    a = np.clip(base + 0.03 * n, 0, 1)
    rgb = np.stack([a * 1.15, a * 0.95, a * 0.7], -1)
    return Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))


# ----------------------------------------------------------------- voice
async def _tts(text, mp3, rate, pitch):
    import edge_tts
    words = []
    com = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return words


def decode_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", str(SR), dst],
                   check=True)
    with wave.open(dst) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def synth_voice(text, workdir, idx, offline):
    mp3, wav = workdir / f"v{idx}.mp3", workdir / f"v{idx}.wav"
    if offline:
        toks = text.split()
        words, t = [], 0.15
        for tk in toks:
            d = 0.16 + 0.055 * len(tk)
            words.append((t, t + d, tk))
            t += d + 0.05
        return np.zeros(int((t + 0.2) * SR), np.float32), words
    for attempt in range(4):
        try:
            words = asyncio.run(_tts(text, str(mp3), "+2%", "-3Hz"))
            audio = decode_wav(str(mp3), str(wav))
            if len(audio) > SR * 0.5:
                return audio, words
        except Exception as e:  # noqa: BLE001
            log(f"  tts attempt {attempt + 1} failed: {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("TTS failed")


def drone(n, seed):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * 0.06 * t + rng.uniform(0, 6))
    s = (0.55 * np.sin(2 * np.pi * 55 * t) + 0.35 * np.sin(2 * np.pi * 82.41 * t + 1.3)
         + 0.25 * np.sin(2 * np.pi * 110.3 * t + 0.4) + 0.12 * np.sin(2 * np.pi * 164.8 * t))
    noise = np.cumsum(rng.standard_normal(n)).astype(np.float64)
    cs = np.concatenate([[0.0], np.cumsum(noise)])
    k = 4801
    idx = np.arange(n)
    lo, hi = np.clip(idx - k // 2, 0, n), np.clip(idx + k // 2 + 1, 0, n)
    noise = (noise - (cs[hi] - cs[lo]) / (hi - lo)).astype(np.float32)
    noise /= (np.abs(noise).max() + 1e-6)
    out = (s * lfo + 0.35 * noise) * 0.05
    fade_in, fade_out = int(SR * 1.2), int(SR * 2.0)
    out[:fade_in] *= np.linspace(0, 1, fade_in)
    out[-fade_out:] *= np.linspace(1, 0, fade_out)
    # low boom on the hook
    bt = t[: int(SR * 1.6)]
    boom = np.sin(2 * np.pi * (58 * bt - 9 * bt ** 2)) * np.exp(-bt * 2.6) * 0.32
    boom[: int(SR * 0.01)] *= np.linspace(0, 1, int(SR * 0.01))
    out[: len(boom)] += boom
    return out.astype(np.float32)


# ----------------------------------------------------------------- overlays
def gauss_sprite(r):
    k = int(r * 3) + 1
    y, x = np.mgrid[-k:k + 1, -k:k + 1]
    return np.exp(-(x * x + y * y) / (2 * r * r)).astype(np.float32)


def make_parchment(seed):
    rng = np.random.default_rng(seed)
    acc = np.zeros((H, W), np.float32)
    for sc, amp in [(8, 0.5), (32, 0.3), (128, 0.2)]:
        n = rng.standard_normal((max(2, H // sc), max(2, W // sc))).astype(np.float32)
        acc += amp * np.asarray(Image.fromarray(n).resize((W, H), Image.BICUBIC))
    fib = rng.standard_normal((H, W // 3)).astype(np.float32)
    fib = np.asarray(Image.fromarray(fib).resize((W, H), Image.BILINEAR))
    acc = acc / (np.abs(acc).max() + 1e-6)
    return (1.0 + 0.045 * acc + 0.012 * fib)[..., None] * np.array([1.0, 0.99, 0.965], np.float32)


def make_vignette():
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 * 0.9 + ((y - H / 2) / (H / 2)) ** 2)
    return d


def make_stamp():
    font_big = ImageFont.truetype(FONT, 96)
    font_small = ImageFont.truetype(FONT, 26)
    im = Image.new("RGBA", (460, 230), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    red = (178, 22, 28, 255)
    d.rounded_rectangle((8, 8, 452, 222), radius=10, outline=red, width=9)
    d.rounded_rectangle((24, 24, 436, 206), radius=6, outline=red, width=3)
    d.text((230, 108), "GİZLİ", font=font_big, fill=red, anchor="mm")
    d.text((230, 178), "TARİHİN KARANLIĞI · ARŞİV", font=font_small, fill=red, anchor="mm")
    rng = np.random.default_rng(7)
    a = np.asarray(im).astype(np.float32)
    wear = rng.random(a.shape[:2]) > 0.22
    blotch = np.asarray(Image.fromarray((rng.random((23, 46)) * 255).astype(np.uint8))
                        .resize((460, 230), Image.BICUBIC)) > 70
    a[..., 3] *= wear * blotch * 0.8
    im = Image.fromarray(a.astype(np.uint8)).rotate(-13, expand=True, resample=Image.BICUBIC)
    return im


def text_img(text, size, fill, stroke=6, glow=None):
    font = ImageFont.truetype(FONT, size)
    l, t, r, b = font.getbbox(text, stroke_width=stroke)
    pad = 40
    im = Image.new("RGBA", (r - l + pad * 2, b - t + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((pad - l, pad - t), text, font=font, fill=fill, stroke_width=stroke,
           stroke_fill=(0, 0, 0, 255))
    if glow:
        g = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text((pad - l, pad - t), text, font=font, fill=glow)
        g = g.filter(ImageFilter.GaussianBlur(14))
        im = Image.alpha_composite(g, im)
    return im


def fit_text(text, max_w, size, **kw):
    while size > 40:
        im = text_img(text, size, **kw)
        if im.width - 80 <= max_w:
            return im
        size -= 6
    return text_img(text, size, **kw)


CAP_WHITE = (255, 255, 255, 255)
CAP_YELLOW = (255, 214, 10, 255)


def karaoke_img(words, active, max_w, size=74, stroke=7):
    """One caption line; the word being spoken (index `active`) is yellow and slightly bigger."""
    while True:
        font = ImageFont.truetype(FONT, size)
        big = ImageFont.truetype(FONT, int(size * 1.12))
        fonts = [big if i == active else font for i in range(len(words))]
        space = font.getlength(" ")
        widths = [f.getlength(w) for f, w in zip(fonts, words)]
        total = sum(widths) + space * (len(words) - 1) + stroke * 2
        if total <= max_w or size <= 40:
            break
        size -= 4
    asc, desc = big.getmetrics()
    pad = 30
    im = Image.new("RGBA", (int(total) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = pad + stroke
    for i, (f, w) in enumerate(zip(fonts, words)):
        a2, _ = f.getmetrics()
        y = pad + (asc - a2)
        d.text((x, y), w, font=f, fill=CAP_YELLOW if i == active else CAP_WHITE,
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        x += widths[i] + space
    return im


def blend(frame, rgba, x, y, alpha=1.0):
    a = np.asarray(rgba).astype(np.float32)
    h, w = a.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    sub = a[y0 - y:y1 - y, x0 - x:x1 - x]
    al = sub[..., 3:4] / 255.0 * alpha
    frame[y0:y1, x0:x1] = frame[y0:y1, x0:x1] * (1 - al) + sub[..., :3] * al


# ----------------------------------------------------------------- camera
def ease(u):
    u = min(max(u, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * u)


def camera(kind, u, t, dur, rng_ph):
    e = ease(u)
    s, tx, ty, rot = 1.06, 0.0, 0.0, 0.0
    if kind == "PUSH":        # slow dolly toward subject, ~0.3x zoom speed
        s = 1.06 + min(0.14, 0.018 * dur) * e
        ty = -18 * e
    elif kind == "ORBIT":     # 15-degree arc feel: rotation + lateral slide
        s = 1.19
        rot = math.radians(-1.6 + 3.2 * e)
        tx = -48 + 96 * e
    elif kind == "RISE":      # low to high reveal
        s = 1.15 + 0.03 * e
        ty = 95 - 190 * e
        rot = math.radians(0.7 * (1 - e))
    elif kind == "DRIFT":     # lateral parallax slide
        s = 1.16
        tx = 62 - 124 * e
    # organic handheld micro-stabilisation (2-3 px)
    p = rng_ph
    jx = (1.4 * math.sin(2 * math.pi * 0.21 * t + p[0]) + 0.8 * math.sin(2 * math.pi * 0.53 * t + p[1])
          + 0.4 * math.sin(2 * math.pi * 1.07 * t + p[2]))
    jy = (1.3 * math.sin(2 * math.pi * 0.17 * t + p[3]) + 0.8 * math.sin(2 * math.pi * 0.61 * t + p[4])
          + 0.4 * math.sin(2 * math.pi * 1.23 * t + p[5]))
    jr = math.radians(0.07 * math.sin(2 * math.pi * 0.29 * t + p[6]))
    return s, tx + jx * 1.5, ty + jy * 1.5, rot + jr


def affine(s, tx, ty, rot):
    k = W / SW
    m = 1.0 / (k * s)
    c, sn = math.cos(rot), math.sin(rot)
    cxs, cys, cxo, cyo = SW / 2, SH / 2, W / 2, H / 2
    return (m * c, m * sn, cxs - m * c * cxo - m * sn * cyo - tx,
            -m * sn, m * c, cys + m * sn * cxo - m * c * cyo - ty)


# ----------------------------------------------------------------- render
class Dust:
    def __init__(self, seed, direction):
        rng = np.random.default_rng(seed)
        self.p = []
        for _ in range(55):   # small specks catching the light
            self.p.append(dict(x=rng.uniform(0, W), y=rng.uniform(0, H), vx=rng.uniform(-5, 5) + 6 * direction,
                               vy=rng.uniform(-3, 7), r=rng.uniform(0.7, 1.8), a=rng.uniform(0.25, 0.8),
                               tw=rng.uniform(0.3, 1.2), ph=rng.uniform(0, 6), fg=False))
        for _ in range(7):    # big blurred foreground motes drifting past
            self.p.append(dict(x=rng.uniform(0, W), y=rng.uniform(0, H), vx=rng.uniform(10, 26) * (direction or 1),
                               vy=rng.uniform(-4, 6), r=rng.uniform(9, 22), a=rng.uniform(0.05, 0.13),
                               tw=rng.uniform(0.1, 0.3), ph=rng.uniform(0, 6), fg=True))
        self.sprites = {}

    def sprite(self, r):
        key = round(r * 2) / 2
        if key not in self.sprites:
            self.sprites[key] = gauss_sprite(max(0.6, key))
        return self.sprites[key]

    def draw(self, frame, t, light):
        for q in self.p:
            x = (q["x"] + q["vx"] * t + 6 * math.sin(0.4 * t + q["ph"])) % (W + 80) - 40
            y = (q["y"] + q["vy"] * t + 5 * math.cos(0.33 * t + q["ph"])) % (H + 80) - 40
            ix, iy = int(x), int(y)
            spr = self.sprite(q["r"])
            k = spr.shape[0] // 2
            x0, y0, x1, y1 = max(0, ix - k), max(0, iy - k), min(W, ix + k + 1), min(H, iy + k + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            lit = 1.0 if q["fg"] else 0.35 + 1.4 * float(light[min(H - 1, max(0, iy)), min(W - 1, max(0, ix))])
            inten = q["a"] * lit * (0.6 + 0.4 * math.sin(2 * math.pi * q["tw"] * t + q["ph"])) * 255
            tint = np.array([1.0, 0.95, 0.85], np.float32)
            frame[y0:y1, x0:x1] += spr[y0 - iy + k:y1 - iy + k, x0 - ix + k:x1 - ix + k, None] * inten * tint


def render(job, workdir, out_ig, out_yt, offline=False, fast=False):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    scenes = job["scenes"]
    seed = int(job.get("seed", random.randint(1, 10 ** 6)))
    rng = random.Random(seed)

    # 1) images
    imgs, images_ok = [], 0
    for i, sc in enumerate(scenes):
        p = workdir / f"img{i}.jpg"
        if sc.get("image_path"):
            ok = True
            p = Path(sc["image_path"])
        else:
            log(f"image {i + 1}/{len(scenes)}")
            ok = (not offline) and fetch_image(build_prompt(sc), p, seed + i)
            time.sleep(3)
        mode = str(sc.get("color_mode", "WARM")).upper()
        if ok:
            images_ok += 1
            im = cover_resize(Image.open(p).convert("RGB"), SW, SH)
        elif imgs:
            im = imgs[-1].transpose(Image.FLIP_LEFT_RIGHT)
        else:
            im = fallback_image(seed)
        imgs.append(grade(im, mode))

    # 2) voice
    voices, words = [], []
    for i, sc in enumerate(scenes):
        log(f"voice {i + 1}/{len(scenes)}")
        a, w = synth_voice(sc["text"], workdir, i, offline)
        if not w:   # no word timings: spread words evenly over the clip
            toks, dur = sc["text"].split(), len(a) / SR
            step = dur / max(1, len(toks))
            w = [(j * step, (j + 1) * step, tk) for j, tk in enumerate(toks)]
        voices.append(a)
        words.append(w)

    gap, tail = 0.35, 1.3
    durs = [len(a) / SR + gap for a in voices]
    durs[-1] += tail
    starts = np.cumsum([0] + durs[:-1]).tolist()
    total = sum(durs)
    nfr = int(math.ceil(total * FPS))
    log(f"total {total:.1f}s, {nfr} frames")

    # 3) audio mix
    n = int(total * SR) + SR
    voice_track = np.zeros(n, np.float32)
    for a, st in zip(voices, starts):
        i0 = int(st * SR)
        voice_track[i0:i0 + len(a)] += a
    peak = np.abs(voice_track).max()
    if peak > 0:
        voice_track *= 0.89 / peak
    mix = voice_track + drone(n, seed)
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    wav_path = workdir / "mix.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())

    # 4) captions (max 3 words per chunk, karaoke: spoken word turns yellow)
    chunks = []
    for wl, st in zip(words, starts):
        buf = []
        for (a, b, tx) in wl:
            buf.append((a + st, b + st, tx))
            if len(buf) == 3 or tx.endswith((".", ",", "?", "!", ":", ";")):
                chunks.append((buf[0][0], buf[-1][1], list(buf)))
                buf = []
        if buf:
            chunks.append((buf[0][0], buf[-1][1], list(buf)))
    cap_cache = {}

    # 5) static overlays
    parch = make_parchment(seed)
    vig_d = make_vignette()
    vig0 = np.clip(1.05 - 0.55 * np.power(vig_d, 1.8), 0.0, 1.0)
    stamp = make_stamp()
    words2 = (job.get("cover_text") or "").split()
    w1, w2 = (words2[0], " ".join(words2[1:])) if len(words2) >= 2 else ((words2 or [""])[0], "")
    cov1 = fit_text(tr_upper(w1), W - 70, 168, fill=(255, 255, 255, 255), stroke=5)
    cov2 = fit_text(tr_upper(w2), W - 70, 168, fill=(224, 32, 27, 255), stroke=5, glow=(224, 32, 27, 200)) if w2 else None
    lx, ly = np.mgrid[0:H * 2, 0:W * 2].astype(np.float32)

    # 6) frames -> ffmpeg
    raw = workdir / "video.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-vf", "tmix=frames=2:weights='1 1'",
         "-c:v", "libx264", "-preset", "veryfast" if fast else "medium", "-crf", "14",
         "-pix_fmt", "yuv420p", str(raw)], stdin=subprocess.PIPE)
    cams = [str(sc.get("camera", "")).upper() for sc in scenes]
    prev = None
    for i in range(len(cams)):
        if cams[i] not in CAMERAS or cams[i] == prev:
            cams[i] = rng.choice([c for c in CAMERAS if c != prev])
        prev = cams[i]
    phases = [[rng.uniform(0, 6.28) for _ in range(7)] for _ in scenes]
    dusts = [Dust(seed + 11 * i, {"DRIFT": -1, "ORBIT": 1}.get(c, 0.4)) for i, c in enumerate(cams)]
    lights = []
    for i in range(len(scenes)):   # soft directional light band that slowly slides
        ang = math.radians(rng.uniform(15, 55)) * rng.choice([-1, 1])
        band = (lx * math.cos(ang) + ly * math.sin(ang))
        band = (band - band.min()) / (band.max() - band.min())
        lights.append((1 / (1 + np.exp(-(band - 0.5) * 7))).astype(np.float32))
    t0 = time.time()
    for f in range(nfr):
        t = f / FPS
        si = max(k for k in range(len(starts)) if starts[k] <= t + 1e-6)
        lt, d = t - starts[si], durs[si]
        u = lt / d
        s, tx, ty, rot = camera(cams[si], u, t, d, phases[si])
        fr = imgs[si].transform((W, H), Image.AFFINE, affine(s, tx, ty, rot), resample=Image.BICUBIC)
        frame = np.asarray(fr).astype(np.float32)
        # sliding shadows
        sh = int(W * 0.5 + 70 * (u - 0.5) * (1 if si % 2 else -1))
        light = lights[si][H // 2:H // 2 + H, sh:sh + W]
        frame *= (0.72 + 0.4 * light)[..., None]
        dusts[si].draw(frame, lt, light)
        frame *= parch
        # vignette + slow darkening toward all edges at scene end, dark crossfade
        end = ease((lt - (d - 0.9)) / 0.9) if lt > d - 0.9 else 0.0
        begin = 1.0 - ease(lt / 0.45) if si > 0 else 1.0 - ease(lt / 0.25)
        vig = vig0 if end == 0.0 else np.clip(1.05 - (0.55 + 0.35 * end) * np.power(vig_d, 1.8 - 0.6 * end), 0.0, 1.0)
        frame *= vig[..., None]
        frame *= (1.0 - 0.85 * max(end * 0.7, begin))
        # film grain (luma, clumped)
        if f % 2 == 0:
            g = np.random.standard_normal((H // 2, W // 2)).astype(np.float32)
            g = g.repeat(2, 0).repeat(2, 1)[..., None] * 6.0
        frame += g
        # stamp
        blend(frame, stamp, W - stamp.width + 95, 118, 0.82)
        # cover (first 2.2 s)
        if t < 2.4 and cov1:
            ca = 1.0 if t < 1.9 else max(0.0, 1 - (t - 1.9) / 0.5)
            scrim = np.exp(-((np.arange(H) - H * 0.44) / 260.0) ** 2).astype(np.float32)
            frame *= (1 - 0.55 * ca * scrim)[:, None, None]
            gap_y = 12
            total_h = cov1.height + (cov2.height if cov2 else 0) - 80 - gap_y
            y0 = int(H * 0.44 - total_h / 2) - 40
            blend(frame, cov1, (W - cov1.width) // 2, y0, ca)
            if cov2:
                blend(frame, cov2, (W - cov2.width) // 2, y0 + cov1.height - 80 + gap_y, ca)
        # captions
        for ck, (a, b, wlist) in enumerate(chunks):
            if a - 0.04 <= t <= b + 0.12:
                act = 0
                for k, (wa, _wb, _w) in enumerate(wlist):
                    if wa <= t + 0.02:
                        act = k
                key = (ck, act)
                if key not in cap_cache:
                    cap_cache[key] = karaoke_img([tr_upper(w[2]) for w in wlist], act, W - 80)
                ci = cap_cache[key]
                ca = min(1.0, (t - a + 0.04) / 0.08)
                # centred, just below the cover title and above the Shorts UI (title/channel name)
                blend(frame, ci, (W - ci.width) // 2, int(H * 0.585) - ci.height // 2, ca)
                break
        ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        if f % 120 == 0:
            log(f"  frame {f}/{nfr} ({(time.time() - t0) / max(1, f):.3f}s/frame)")
    ff.stdin.close()
    ff.wait()

    # 7) final encodes
    base = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-i", str(wav_path), "-map", "0:v", "-map", "1:a",
            "-shortest"]
    # Instagram / TikTok master: <= 5 Mbps, AAC 48k stereo
    subprocess.run(base + ["-c:v", "libx264", "-preset", "slow", "-tune", "film", "-crf", "21", "-maxrate", "4500k",
                           "-bufsize", "9000k", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
                           "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000", "-movflags", "+faststart",
                           str(out_ig)], check=True)
    # YouTube copy sized to pass through Make's file limit
    limit_mb = float(os.environ.get("YT_MAX_MB", "4.6"))
    kbps = max(450, int(limit_mb * 8 * 1000 / total * 0.93) - 96)
    log(f"yt target {kbps} kbps")
    common = ["-c:v", "libx264", "-preset", "slow", "-tune", "film", "-b:v", f"{kbps}k", "-pix_fmt", "yuv420p",
              "-r", str(FPS)]
    passlog = str(workdir / "x264pass")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw)] + common +
                   ["-pass", "1", "-passlogfile", passlog, "-an", "-f", "null", os.devnull], check=True)
    subprocess.run(base + common + ["-pass", "2", "-passlogfile", passlog, "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                                    "-ar", "48000", "-movflags", "+faststart", str(out_yt)], check=True)
    # cover still
    cover = Path(out_ig).with_name("cover.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.9", "-i", str(out_ig), "-frames:v", "1",
                    "-q:v", "3", str(cover)], check=True)
    return {"duration": round(total, 2), "cameras": cams, "images_ok": images_ok, "scenes": len(scenes),
            "ig_mb": round(os.path.getsize(out_ig) / 1e6, 2), "yt_mb": round(os.path.getsize(out_yt) / 1e6, 2)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    job = json.loads(Path(a.job).read_text(encoding="utf-8"))
    info = render(job, out / "work", out / "video_ig.mp4", out / "video_yt.mp4", a.offline, a.fast)
    print(json.dumps(info))
    sys.exit(0)
