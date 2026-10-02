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
VOICE = os.environ.get("TTS_VOICE") or "tr-TR-AhmetNeural"

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
STYLE_V2 = (
    "ultra detailed cinematic photorealistic scene, vivid rich saturated colors, bright dramatic key light "
    "with strong glowing highlights, high contrast, one clear eye-catching subject in the centre, epic scale, "
    "culture-specific objects, architecture and textures, volumetric god rays, all human figures are translucent "
    "frosted glass humanoid silhouettes, faceless, featureless, anonymous, expressive body posture only, shallow "
    "depth of field, sharp foreground, vertical cinematic composition, striking thumbnail-worthy frame, "
    "faces never visible, no text, no letters"
)
COLOR_MODES_V2 = {
    "WARM": "warm golden sunlight, fiery orange and amber accents, glowing lanterns and torches",
    "COLD": "icy blue and teal moonlight with bright silver highlights and glowing cyan accents",
    "INFO": "bold graphic composition on deep navy blue with bright gold and white accents",
}


def is_v2(job=None):
    return os.environ.get("STYLE_V2") == "1" or (job or {}).get("style") == "v2"


CAMERAS = ["PUSH", "ORBIT", "RISE", "DRIFT"]
# second shot per scene (shown in the second half) so every video has ~10 distinct images
ALT_SHOTS = [
    "extreme close-up macro detail of the single most important object in this scene",
    "wide establishing aerial shot of the whole location seen from far above",
    "dramatic low-angle view looking up at the scene",
    "over-the-shoulder view from behind a translucent frosted glass silhouette observing the scene",
    "detail of weathered hands-free still life: documents, tools and artifacts from this moment on a table",
]
# per-video visual "looks" so uploads do not all share one template
LOOKS = ["arsiv", "sinema", "belge"]


def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------- images
def build_prompt(scene, alt=None, v2=False):
    mode = str(scene.get("color_mode", "WARM")).upper()
    desc = str(scene.get("scene", "")).strip().replace('"', "'")[:420]
    if alt:
        desc = f"{alt}: {desc}"
    if v2:
        return f"{desc}, {COLOR_MODES_V2.get(mode, COLOR_MODES_V2['WARM'])}, {STYLE_V2}"
    return f"{desc}, {COLOR_MODES.get(mode, COLOR_MODES['WARM'])}, {STYLE}"


UA = "tarihin-karanligi-bot/1.0"
HORDE_NEG = "text, letters, watermark, logo, signature, blurry, deformed, extra fingers, cartoon, anime"
HORDE_MODELS = ["AlbedoBase XL (SDXL)", "Juggernaut XL", "ICBINP XL", "Deliberate",
                "Realistic Vision", "Dreamshaper", "stable_diffusion"]


def _save_image(data, path):
    if len(data) < 15000:
        raise RuntimeError(f"image too small ({len(data)} bytes)")
    import io
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.save(path, "JPEG", quality=94)
    return True


def _http(url, headers=None, data=None, timeout=60, method=None):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_pollinations(prompt, path, seed, tries=None):
    """Registered key (gen.pollinations.ai) first, then the old anonymous endpoint."""
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    q = {"width": 768, "height": 1344, "model": "flux", "nologo": "true",
         "seed": seed, "enhance": "false", "private": "true", "referrer": "tarihinkaranligi"}
    enc = urllib.parse.quote(prompt[:1500])
    targets = []
    if token:
        targets.append(("gen", "https://gen.pollinations.ai/image/" + enc + "?" + urllib.parse.urlencode(q),
                        {"Authorization": f"Bearer {token}"}))
    targets.append(("anon", "https://image.pollinations.ai/prompt/" + enc + "?" + urllib.parse.urlencode(q), {}))
    tries = tries or (2 if token else 1)   # anonymous access is mostly 402 now: one quick try, then Horde
    for attempt in range(tries):
        for name, url, hdr in targets:
            try:
                return _save_image(_http(url, hdr, timeout=120 if name == "gen" else 60), path)
            except Exception as e:  # noqa: BLE001
                log(f"  pollinations[{name}] try {attempt + 1}: {str(e)[:90]}")
        time.sleep(6 * (attempt + 1))
    return False


def fetch_horde(prompt, path, seed, deadline):
    """Stable Horde (free, community GPUs). Anonymous key works; a free registered key is faster."""
    key = os.environ.get("HORDE_API_KEY", "").strip() or "0000000000"
    hdr = {"apikey": key, "Client-Agent": "tarihin-karanligi:1.0:github", "Content-Type": "application/json"}
    body = {"prompt": prompt[:850] + " ### " + HORDE_NEG,
            "params": {"width": 576, "height": 1024, "steps": 24, "cfg_scale": 6.5, "n": 1,
                       "sampler_name": "k_euler_a", "karras": True, "seed": str(seed)},
            "models": HORDE_MODELS, "nsfw": False, "censor_nsfw": True, "r2": False,
            "slow_workers": True, "trusted_workers": False}
    base = "https://aihorde.net/api/v2/generate/"
    jid = None
    for attempt in range(5):   # anonymous users may hit a parallel-request limit: wait and retry
        try:
            jid = json.loads(_http(base + "async", hdr, json.dumps(body).encode(), 40))["id"]
            break
        except Exception as e:  # noqa: BLE001
            log(f"  horde submit try {attempt + 1} failed: {str(e)[:120]}")
            if time.time() + 60 > deadline:
                return False
            time.sleep(20 + 10 * attempt)
    if not jid:
        return False
    while time.time() < deadline:
        time.sleep(8)
        try:
            chk = json.loads(_http(base + "check/" + jid, hdr, timeout=30))
        except Exception:  # noqa: BLE001
            continue
        if chk.get("faulted") or not chk.get("is_possible", True):
            log(f"  horde job impossible/faulted: {chk}")
            break
        if chk.get("done"):
            try:
                st = json.loads(_http(base + "status/" + jid, hdr, timeout=60))
                g = (st.get("generations") or [{}])[0]
                if g.get("censored"):
                    log("  horde image censored")
                    return False
                img = g.get("img", "")
                import base64
                data = _http(img, timeout=60) if img.startswith("http") else base64.b64decode(img)
                log(f"  horde ok ({g.get('model')})")
                return _save_image(data, path)
            except Exception as e:  # noqa: BLE001
                log(f"  horde fetch failed: {str(e)[:120]}")
                return False
    try:  # free the queue slot
        _http(base + "status/" + jid, hdr, timeout=20, method="DELETE")
    except Exception:  # noqa: BLE001
        pass
    log("  horde timed out")
    return False


def fetch_image(prompt, path, seed, deadline=None):
    deadline = deadline or (time.time() + 600)
    if fetch_pollinations(prompt, path, seed):
        return True
    return fetch_horde(prompt, path, seed, deadline)


def fetch_all_images(prompts, paths, seed, budget=900):
    """Fetch every scene image in parallel with one overall time budget (seconds)."""
    from concurrent.futures import ThreadPoolExecutor
    deadline = time.time() + budget

    def one(i):
        time.sleep(i * 1.5)  # stagger requests a little
        try:
            ok = fetch_image(prompts[i], paths[i], seed + i, deadline)
        except Exception as e:  # noqa: BLE001
            log(f"  image {i + 1} error: {e}")
            ok = False
        log(f"image {i + 1}/{len(prompts)}: {'ok' if ok else 'FALLBACK'}")
        return ok

    with ThreadPoolExecutor(max_workers=int(os.environ.get("IMAGE_WORKERS", "5"))) as ex:
        return list(ex.map(one, range(len(prompts))))


def cover_resize(img, w, h):
    iw, ih = img.size
    s = max(w / iw, h / ih)
    img = img.resize((max(w, round(iw * s)), max(h, round(ih * s))), Image.LANCZOS)
    iw, ih = img.size
    l, t = (iw - w) // 2, (ih - h) // 2
    return img.crop((l, t, l + w, t + h))


def grade(img, mode, v2=False):
    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
    lum = (a @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
    if v2:   # bright, punchy, saturated: stands out while scrolling
        a = lum + (a - lum) * 1.18
        a = np.clip((a - 0.5) * 1.12 + 0.5, 0, 1)
        a = np.power(np.clip(a, 0, 1), 0.86)
        return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
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
            words = asyncio.run(_tts(text, str(mp3), os.environ.get("TTS_RATE", "+2%"),
                                     os.environ.get("TTS_PITCH", "-3Hz")))
            audio = decode_wav(str(mp3), str(wav))
            if len(audio) > SR * 0.5:
                return audio, words
        except Exception as e:  # noqa: BLE001
            log(f"  tts attempt {attempt + 1} failed: {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("TTS failed")


DRONE_ROOTS = [55.0, 49.0, 61.74, 46.25, 51.91, 58.27]
DRONE_CHORDS = [(1.0, 1.498, 2.005, 2.997), (1.0, 1.189, 1.498, 2.0), (1.0, 1.335, 2.0, 2.67), (1.0, 1.498, 1.782, 2.0)]


def drone(n, seed, pulse=False):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * (0.04 + 0.04 * rng.random()) * t + rng.uniform(0, 6))
    root = DRONE_ROOTS[int(rng.integers(len(DRONE_ROOTS)))]
    ch = DRONE_CHORDS[int(rng.integers(len(DRONE_CHORDS)))]
    s = (0.55 * np.sin(2 * np.pi * root * ch[0] * t) + 0.35 * np.sin(2 * np.pi * root * ch[1] * t + 1.3)
         + 0.25 * np.sin(2 * np.pi * root * ch[2] * t + 0.4) + 0.12 * np.sin(2 * np.pi * root * ch[3] * t))
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
    if pulse:   # slow low heartbeat under the narration
        bpm = 62 + int(rng.integers(0, 14))
        beat = int(SR * 60 / bpm)
        k = np.arange(int(SR * 0.22)) / SR
        thump = (np.sin(2 * np.pi * 48 * k) * np.exp(-k * 22)).astype(np.float32) * 0.09
        for b0 in range(int(SR * 1.6), n - len(thump), beat):
            out[b0:b0 + len(thump)] += thump
            b1 = b0 + int(SR * 0.24)
            if b1 + len(thump) < n:
                out[b1:b1 + len(thump)] += thump * 0.6
    return out.astype(np.float32)


def whoosh(seed, dur=0.42, amp=0.16):
    """Short airy swoosh for cuts: band-limited noise with a rising pitch and a fast swell."""
    rng = np.random.default_rng(seed)
    m = int(SR * dur)
    x = rng.standard_normal(m).astype(np.float32)
    # crude band-pass: difference of two moving averages whose width shrinks over time (rising sweep)
    cs = np.concatenate([[0.0], np.cumsum(x)])
    idx = np.arange(m)
    out = np.zeros(m, np.float32)
    for k0, k1 in ((40, 8), ):
        kk = (k0 + (k1 - k0) * idx / m).astype(int) + 1
        lo, hi = np.clip(idx - kk, 0, m), np.clip(idx + kk, 0, m)
        out += ((cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)).astype(np.float32)
    env = np.sin(np.pi * np.clip(idx / m, 0, 1)) ** 2
    out = out / (np.abs(out).max() + 1e-6) * env * amp
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


def make_archive_tag(seed):
    """Typewriter style archive label used by the 'belge' look instead of the GIZLI stamp."""
    font = ImageFont.truetype(FONT, 30)
    red = (186, 30, 30, 255)
    txt = f"ARŞİV NO {1000 + seed % 9000} / {chr(65 + seed % 26)}"
    l, t, r, b = font.getbbox(txt)
    im = Image.new("RGBA", (r - l + 36, b - t + 26), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((2, 2, im.width - 3, im.height - 3), outline=red, width=3)
    d.text((18 - l, 13 - t), txt, font=font, fill=red)
    return im.rotate(4, expand=True, resample=Image.BICUBIC)


def make_badge(label, look):
    font = ImageFont.truetype(FONT, 34)
    l, t, r, b = font.getbbox(label)
    fill = {"sinema": (214, 168, 64, 255), "belge": (150, 24, 24, 235)}.get(look, (178, 22, 28, 235))
    im = Image.new("RGBA", (r - l + 40, b - t + 22), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=8, fill=fill)
    d.text((20 - l, 11 - t), label, font=font, fill=(255, 255, 255, 255) if look != "sinema" else (20, 14, 6, 255))
    return im


def make_info_card(place, era, look):
    """Lower-third style card: where + when, shown at the start of scene 2."""
    lines = [x for x in (tr_upper(place or ""), tr_upper(era or "")) if x.strip()]
    if not lines:
        return None
    f1 = ImageFont.truetype(FONT, 44)
    f2 = ImageFont.truetype(FONT, 32)
    fonts = [f1, f2][:len(lines)]
    widths = [f.getlength(x) for f, x in zip(fonts, lines)]
    w = int(min(W - 60, max(widths) + 70))
    h = 30 + sum(f.getmetrics()[0] + f.getmetrics()[1] + 6 for f in fonts) + 16
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bg = {"belge": (236, 222, 190, 225), "sinema": (8, 8, 10, 200)}.get(look, (10, 8, 6, 190))
    fg = (40, 24, 12, 255) if look == "belge" else (255, 255, 255, 255)
    acc = {"sinema": (214, 168, 64, 255)}.get(look, (196, 28, 32, 255))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=10, fill=bg)
    d.rectangle((0, 0, 9, h - 1), fill=acc)
    y = 16
    for k, (f, x) in enumerate(zip(fonts, lines)):
        d.text((30, y), x, font=f, fill=fg if k == 0 else (acc if look != "belge" else (120, 30, 20, 255)))
        a, b2 = f.getmetrics()
        y += a + b2 + 6
    return im


def make_cta(text):
    font = ImageFont.truetype(FONT, 58)
    l, t, r2, b = font.getbbox(text)
    im = Image.new("RGBA", (r2 - l + 70, b - t + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=(b - t + 40) // 2, fill=(214, 34, 34, 240))
    d.text((35 - l, 20 - t), text, font=font, fill=(255, 255, 255, 255))
    return im


def make_letterbox(look):
    if look != "sinema":
        return None
    bar = 118
    m = np.ones((H, W), np.float32)
    m[:bar] = 0.0
    m[-bar:] = 0.0
    edge = np.linspace(0, 1, 14, dtype=np.float32)
    m[bar:bar + 14] = edge[:, None]
    m[H - bar - 14:H - bar] = edge[::-1, None]
    return m


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
    V2 = is_v2(job)
    if V2:   # faster, livelier narration
        os.environ.setdefault("TTS_RATE", "+14%")
        os.environ.setdefault("TTS_PITCH", "+0Hz")

    # 1) images
    imgs, images_ok = [], 0
    paths = [Path(sc["image_path"]) if sc.get("image_path") else workdir / f"img{i}.jpg"
             for i, sc in enumerate(scenes)]
    need = [i for i, sc in enumerate(scenes) if not sc.get("image_path")]
    got = {i: True for i in range(len(scenes)) if i not in need}
    alt_paths = [Path(sc["image2_path"]) if sc.get("image2_path") else workdir / f"alt{i}.jpg"
                 for i, sc in enumerate(scenes)]
    alt_got = {i: True for i, sc in enumerate(scenes) if sc.get("image2_path")}
    alt_need = [i for i in need if os.environ.get("ALT_IMAGES", "1") == "1"]
    if need and not offline:
        prompts = [build_prompt(scenes[i], v2=V2) for i in need] + \
                  [build_prompt(scenes[i], ALT_SHOTS[(i + seed) % len(ALT_SHOTS)], v2=V2) for i in alt_need]
        res = fetch_all_images(prompts, [paths[i] for i in need] + [alt_paths[i] for i in alt_need],
                               seed + need[0], budget=int(os.environ.get("IMAGE_BUDGET", "900")))
        got.update(dict(zip(need, res[:len(need)])))
        alt_got.update(dict(zip(alt_need, res[len(need):])))
    for i, sc in enumerate(scenes):
        p, ok = paths[i], got.get(i, False)
        mode = str(sc.get("color_mode", "WARM")).upper()
        good = [j for j in range(len(scenes)) if got.get(j)]
        if ok:
            images_ok += 1
            im = cover_resize(Image.open(p).convert("RGB"), SW, SH)
        elif good:   # reuse the nearest real image (mirrored + cropped) instead of a blank dark frame
            j = min(good, key=lambda k: (abs(k - i), k))
            im = cover_resize(Image.open(paths[j]).convert("RGB"), SW, SH).transpose(Image.FLIP_LEFT_RIGHT)
            im = cover_resize(im.crop((SW // 10, SH // 10, SW - SW // 10, SH - SH // 10)), SW, SH)
        else:
            im = fallback_image(seed)
        imgs.append(grade(im, mode, V2))
    alts = []
    for i, sc in enumerate(scenes):
        a_im = None
        if alt_got.get(i):
            try:
                a_im = grade(cover_resize(Image.open(alt_paths[i]).convert("RGB"), SW, SH),
                             str(sc.get("color_mode", "WARM")).upper(), V2)
            except Exception as e:  # noqa: BLE001
                log(f"  alt image {i + 1} unreadable: {e}")
        alts.append(a_im)
    look = os.environ.get("LOOK") or str(job.get("look") or LOOKS[seed % len(LOOKS)])
    if look not in LOOKS:
        look = LOOKS[0]
    if V2:
        look = "parlak"
    log(f"look: {look}, alt images: {sum(a is not None for a in alts)}/{len(scenes)}")

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

    gap, tail = 0.25, 1.0
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
    sfx = np.zeros(n, np.float32)
    if os.environ.get("TRANSITION_SFX") == "1":   # off by default (channel owner asked for no swoosh)
        for k, st in enumerate(starts):
            for tt in ([st] if k else []) + [st + durs[k] * 0.5]:
                w_ = whoosh(seed + 97 * k + int(tt * 10))
                i0 = max(0, int((tt - 0.28) * SR))
                seg = w_[: max(0, min(len(w_), n - i0))]
                sfx[i0:i0 + len(seg)] += seg
    mix = voice_track + drone(n, seed, pulse=(look == "sinema")) + sfx
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
    stamp = make_stamp() if look == "arsiv" else (make_archive_tag(seed) if look == "belge" else None)
    if look == "sinema":
        parch = np.ones_like(parch)
    elif look == "belge":
        parch = parch * np.array([1.03, 0.97, 0.86], np.float32)
    letterbox = make_letterbox(look)
    if V2:
        parch = np.ones_like(parch)
        vig0 = np.clip(1.04 - 0.32 * np.power(vig_d, 2.2), 0.0, 1.0)
    title_txt = str(job.get("title") or "")
    cta = None
    if V2:
        cta = make_cta("2. BÖLÜM AKŞAM • TAKİP ET" if "1. Bölüm" in title_txt else "CEVABINI YORUMA YAZ")
    part = "BÖLÜM 1" if "1. Bölüm" in title_txt else ("BÖLÜM 2" if "2. Bölüm" in title_txt else "")
    badge = make_badge(part, look) if part else None
    info = make_info_card(job.get("place"), job.get("era"), look)
    info_t0 = starts[1] if len(starts) > 1 else 2.6
    words2 = (job.get("cover_text") or "").split()
    w1, w2 = (words2[0], " ".join(words2[1:])) if len(words2) >= 2 else ((words2 or [""])[0], "")
    cov1 = fit_text(tr_upper(w1), W - 70, 168, fill=(255, 255, 255, 255), stroke=5)
    if look == "sinema":
        cov2 = fit_text(tr_upper(w2), W - 70, 168, fill=(232, 182, 72, 255), stroke=5, glow=(232, 160, 40, 170)) if w2 else None
    elif look == "belge" and w2:
        c2 = fit_text(tr_upper(w2), W - 110, 150, fill=(255, 255, 255, 255), stroke=0)
        box = Image.new("RGBA", (c2.width - 30, c2.height - 40), (0, 0, 0, 0))
        ImageDraw.Draw(box).rectangle((0, 0, box.width - 1, box.height - 1), fill=(176, 24, 26, 245))
        cov2 = Image.new("RGBA", c2.size, (0, 0, 0, 0))
        cov2.alpha_composite(box, (15, 20))
        cov2.alpha_composite(c2)
    else:
        cov2 = fit_text(tr_upper(w2), W - 70, 168, fill=(224, 32, 27, 255), stroke=5, glow=(224, 32, 27, 200)) if w2 else None
    lx, ly = np.mgrid[0:H * 2, 0:W * 2].astype(np.float32)

    # 6) frames -> ffmpeg
    raw = workdir / "video.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-",   # no frame blending: it ghosted the karaoke captions
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
        src = imgs[si]
        if u >= 0.5 and alts[si] is not None:   # second shot of the same scene
            cam2 = CAMERAS[(CAMERAS.index(cams[si]) + 2) % len(CAMERAS)]
            s, tx, ty, rot = camera(cam2, (u - 0.5) * 2, t, d / 2, phases[si])
            src = alts[si]
        else:
            s, tx, ty, rot = camera(cams[si], u, t, d, phases[si])
            if u >= 0.5:   # no second image: mid-scene punch-in as a hard "new shot"
                s *= 1.14
                tx *= 0.6
                ty = ty * 0.6 + (-40 if si % 2 else 40)
        if V2 and si == 0 and lt < 0.5:   # hook: fast pull-back zoom in the first half second
            s *= 1.0 + 0.28 * (1.0 - ease(lt / 0.5))
        fr = src.transform((W, H), Image.AFFINE, affine(s, tx, ty, rot), resample=Image.BICUBIC)
        frame = np.asarray(fr).astype(np.float32)
        # sliding shadows
        sh = int(W * 0.5 + 70 * (u - 0.5) * (1 if si % 2 else -1))
        light = lights[si][H // 2:H // 2 + H, sh:sh + W]
        frame *= ((0.9 + 0.18 * light) if V2 else (0.72 + 0.4 * light))[..., None]
        dusts[si].draw(frame, lt, light)
        frame *= parch
        # vignette + slow darkening toward all edges at scene end, dark crossfade
        end = ease((lt - (d - 0.9)) / 0.9) if lt > d - 0.9 else 0.0
        begin = 1.0 - ease(lt / 0.45) if si > 0 else 1.0 - ease(lt / 0.25)
        if V2:   # no dark dips: full brightness from frame one, quick light flash on every cut
            end, begin = 0.0, 0.0
        vig = vig0 if end == 0.0 else np.clip(1.05 - (0.55 + 0.35 * end) * np.power(vig_d, 1.8 - 0.6 * end), 0.0, 1.0)
        frame *= vig[..., None]
        frame *= (1.0 - 0.85 * max(end * 0.7, begin))
        if V2 and si > 0 and lt < 0.16:
            frame *= 1.0 + 0.55 * (1.0 - lt / 0.16)
        # film grain (luma, clumped)
        if f % 2 == 0:
            g = np.random.standard_normal((H // 2, W // 2)).astype(np.float32)
            g = g.repeat(2, 0).repeat(2, 1)[..., None] * (3.5 if V2 else 6.0)
        frame += g
        if letterbox is not None:
            frame *= letterbox[..., None]
        # stamp / archive tag
        if stamp is not None:
            if look == "belge":
                blend(frame, stamp, W - stamp.width - 26, 132, 0.85)
            else:
                blend(frame, stamp, W - stamp.width + 95, 118, 0.82)
        # series badge (part 1 / part 2)
        if badge is not None:
            blend(frame, badge, 28, 132 if letterbox is None else 36, 0.95)
        # where + when card at the start of scene 2
        if info is not None and info_t0 <= t < info_t0 + 2.8:
            ia = min(1.0, (t - info_t0) / 0.25, (info_t0 + 2.8 - t) / 0.3)
            blend(frame, info, 30 - int(40 * (1 - min(1.0, (t - info_t0) / 0.3))), int(H * 0.2), max(0.0, ia))
        # call to action during the last scene
        if cta is not None and si == len(scenes) - 1 and lt > 0.25:
            pa = min(1.0, (lt - 0.25) / 0.2)
            pulse = 1.0 + 0.04 * math.sin(2 * math.pi * 1.6 * lt)
            ci2 = cta if abs(pulse - 1) < 0.005 else cta.resize((int(cta.width * pulse), int(cta.height * pulse)), Image.BILINEAR)
            blend(frame, ci2, (W - ci2.width) // 2, int(H * 0.30) - ci2.height // 2, pa)
        # progress line (helps retention): top edge for sinema/belge
        if look != "arsiv":
            py = 8 if letterbox is None else 104
            pw = int(W * min(1.0, t / total))
            col = np.array([214, 168, 64] if look == "sinema" else ([255, 210, 63] if V2 else [176, 24, 26]), np.float32)
            frame[py:py + 6, :] *= 0.45
            frame[py:py + 6, :pw] = col
        # cover (first 2.2 s)
        if t < 2.4 and cov1:
            ca = 1.0 if t < 1.9 else max(0.0, 1 - (t - 1.9) / 0.5)
            scrim = np.exp(-((np.arange(H) - H * 0.44) / 260.0) ** 2).astype(np.float32)
            frame *= (1 - 0.55 * ca * scrim)[:, None, None]
            gap_y = 12
            total_h = cov1.height + (cov2.height if cov2 else 0) - 80 - gap_y
            y0 = int(H * 0.44 - total_h / 2) - 40
            blend(frame, cov1, (W - cov1.width) // 2, y0, ca)
            cov_bottom = y0 + cov1.height - 40
            if cov2:
                blend(frame, cov2, (W - cov2.width) // 2, y0 + cov1.height - 80 + gap_y, ca)
                cov_bottom = y0 + cov1.height - 80 + gap_y + cov2.height - 40
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
                cy = int(H * 0.585)
                if t < 2.4 and cov1:   # keep the caption clear of the big cover title
                    cy = max(cy, cov_bottom + ci.height // 2 - 10)
                blend(frame, ci, (W - ci.width) // 2, cy - ci.height // 2, ca)
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
    return {"duration": round(total, 2), "cameras": cams, "images_ok": images_ok, "scenes": len(scenes), "look": look,
            "alt_ok": sum(a is not None for a in alts), "last_start": round(float(starts[-1]), 3), "starts": [round(float(s), 3) for s in starts],
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
