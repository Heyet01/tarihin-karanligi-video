"""Episode renderer for the 'Mina ile Efe' cartoon series.

Characters are FIXED transparent sprites from the pose library (every pose is an edit of one approved master
image), placed on scene backgrounds, so they look identical in every scene.  Each scene is laid out so the
characters never overlap; nothing is cross-faded (cuts inside a location, an iris wipe between locations).
usage: python tools/cizgi_bolum.py EPISODE.json LIB_DIR OUT_DIR [--offline]
"""
import asyncio
import json
import math
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS, SR = 1280, 720, 24, 24000
GROUND = 0.94                     # feet line (fraction of frame height)
SLOTS = {"left": 0.22, "midleft": 0.38, "center": 0.5, "midright": 0.62, "right": 0.78}
BODY = {"mina": 0.56, "efe": 0.47, "dede": 0.74}     # head-to-feet height as fraction of frame height
GAP = 24                          # minimum pixels between two characters
VOICES = {
    "tr": {"anlatici": ("tr-TR-AhmetNeural", "+0%", "+0Hz"), "mina": ("tr-TR-EmelNeural", "+6%", "+18Hz"),
           "efe": ("tr-TR-EmelNeural", "+10%", "+42Hz"), "dede": ("tr-TR-AhmetNeural", "-6%", "-6Hz")},
    "en": {"anlatici": ("en-US-AndrewNeural", "+0%", "+0Hz"), "mina": ("en-US-AnaNeural", "+0%", "+0Hz"),
           "efe": ("en-US-AnaNeural", "+8%", "+30Hz"), "dede": ("en-US-GuyNeural", "-6%", "-8Hz")},
}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def font(size):
    for f in ("assets/Baloo2-Bold.ttf", "assets/Oswald-Bold.ttf"):
        if (ROOT / f).exists():
            return ImageFont.truetype(str(ROOT / f), size)
    return ImageFont.load_default()


def body_height(im):
    """Height from the top of the head to the feet, ignoring thin things (raised arms, hands) above the head."""
    a = np.asarray(im.getchannel("A")) > 40
    runs = []
    for row in a:
        best = cur = 0
        for v in row[::2]:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        runs.append(best * 2)
    runs = np.array(runs)
    if runs.max() == 0:
        return im.height
    top = int(np.argmax(runs > 0.30 * runs.max()))
    return max(10, im.height - top)


# ------------------------------------------------------------------ assets
class Lib:
    def __init__(self, lib_dir, choice, offline=False):
        self.dir, self.choice, self.offline = Path(lib_dir), choice, offline
        self.cache, self.raw, self.bgs = {}, {}, {}

    def _load(self, ch, pose):
        if (ch, pose) in self.raw:
            return self.raw[(ch, pose)]
        p = None
        for name in (self.choice.get(ch, {}).get(pose), f"{ch}_{pose}_1.png",
                     self.choice.get(ch, {}).get("happy"), f"{ch}_happy_1.png"):
            if name and (self.dir / "png" / name).exists():
                p = self.dir / "png" / name
                break
        if p and p.exists() and not self.offline:
            im = Image.open(p).convert("RGBA")
        else:   # placeholder figure for offline tests
            im = Image.new("RGBA", (300, 600), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            col = {"mina": (250, 210, 60), "efe": (90, 200, 90), "dede": (60, 120, 70)}.get(ch, (200, 200, 200))
            d.ellipse([60, 20, 240, 200], fill=(250, 220, 190, 255))
            d.rounded_rectangle([70, 190, 230, 590], radius=40, fill=col + (255,))
            if pose in ("wave", "point", "laugh"):
                d.rectangle([228, 0, 250, 230], fill=col + (255,))
            d.text((110, 90), pose[:6], fill=(0, 0, 0, 255))
        self.raw[(ch, pose)] = (im, body_height(im))
        return self.raw[(ch, pose)]

    def sprite(self, ch, pose, scale=1.0, flip=False):
        key = (ch, pose, scale, flip)
        if key not in self.cache:
            im, bh = self._load(ch, pose)
            s = H * BODY.get(ch, 0.55) * scale / bh
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
            if flip:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            self.cache[key] = im
        return self.cache[key]

    def background(self, name):
        if name in self.bgs:
            return self.bgs[name]
        p = self.dir / "bg" / (self.choice.get("bg", {}).get(name, name + "_1.jpg"))
        if not p.exists():
            p = self.dir / "bg" / (name + ".jpg")
        if p.exists() and not self.offline:
            im = Image.open(p).convert("RGB")
        else:
            g = np.linspace(0, 1, H)[:, None, None] * np.ones((1, W, 1))
            im = Image.fromarray(((0.4 + 0.6 * g) * np.array([120, 190, 240])).astype(np.uint8))
        self.bgs[name] = im.resize((int(W * 1.06), int(H * 1.06)), Image.LANCZOS)
        return self.bgs[name]


def shadow(w):
    sh = Image.new("RGBA", (w, max(8, w // 6)), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([0, 0, w - 1, sh.height - 1], fill=(30, 25, 15, 95))
    return sh.filter(ImageFilter.GaussianBlur(7))


def layout(sc, lib):
    """Fixed x position per character for a whole scene: slot order kept, never overlapping, inside the frame."""
    chars = sorted(sc["chars"].items(), key=lambda kv: SLOTS.get(kv[1], 0.5))
    poses = {c: {sc.get("start_pose", {}).get(c, "happy")} for c, _ in chars}
    for ln in sc["lines"]:
        for c, p in (ln.get("pose") or {}).items():
            poses.setdefault(c, set()).add(p)
    width = {c: max(lib.sprite(c, p, sc.get("scale", 1.0)).width for p in poses[c]) for c, _ in chars}
    xs = []
    for c, slot in chars:
        x = W * SLOTS.get(slot, 0.5)
        if xs:
            pc, px = xs[-1]
            x = max(x, px + width[pc] / 2 + GAP + width[c] / 2)
        xs.append((c, x))
    if not xs:
        return {}
    over = xs[-1][1] + width[xs[-1][0]] / 2 - (W - 16)
    if over > 0:
        xs = [(c, x - over) for c, x in xs]
    under = 16 - (xs[0][1] - width[xs[0][0]] / 2)
    if under > 0:   # too crowded: shrink the scene a little and try again
        sc["scale"] = round(sc.get("scale", 1.0) * 0.9, 3)
        return layout(sc, lib)
    return dict(xs)


# ------------------------------------------------------------------ audio
async def _tts(text, voice, rate, pitch, mp3):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(mp3))


def say(lang, who, text, work, idx, offline):
    if offline:
        n = int((0.4 + 0.06 * len(text)) * SR)
        t = np.arange(n) / SR
        return (0.3 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype(np.float32)
    v, rate, pitch = VOICES[lang][who]
    mp3, wav = work / f"v{idx}.mp3", work / f"v{idx}.wav"
    for attempt in range(5):
        try:
            asyncio.run(_tts(text, v, rate, pitch, mp3))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR),
                            "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                                   "silenceremove=start_periods=1:start_threshold=-45dB,areverse", str(wav)],
                           check=True)
            with wave.open(str(wav)) as w:
                return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        except Exception as e:  # noqa: BLE001
            log("  tts retry", attempt, e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("tts failed")


def music(n, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    scale = [0, 2, 4, 7, 9, 12]
    root, beat = 261.63 * 2 ** (int(rng.integers(-3, 3)) / 12), 0.5
    pattern = [int(rng.choice(scale)) for _ in range(16)]
    out = np.zeros(n, np.float32)
    for k in range(int(n / SR / beat) + 1):
        f = root * 2 ** (pattern[k % 16] / 12)
        i0 = int(k * beat * SR)
        seg = np.arange(max(0, min(int(0.45 * SR), n - i0))) / SR
        if not len(seg):
            break
        out[i0:i0 + len(seg)] += (0.5 * np.sin(2 * np.pi * f * seg) + 0.15 * np.sin(4 * np.pi * f * seg)) * np.exp(-seg * 6)
    pad = 0.12 * np.sin(2 * np.pi * root / 2 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.1 * t))
    return (out + pad) * 0.07


# ------------------------------------------------------------------ cards
def outlined(d, xy, txt, f, fill, stroke=8):
    d.text(xy, txt, font=f, fill=fill, stroke_width=stroke, stroke_fill=(70, 30, 110))


def card(bg, big, small, lib, chars=None):
    img = bg.resize((W, H)).convert("RGBA")
    if chars:
        for i, (c, p) in enumerate(chars.items()):
            spr = lib.sprite(c, p, 1.0)
            x = int(W * (0.15 if i == 0 else 0.85) - spr.width / 2)
            img.alpha_composite(spr, (x, int(H * 0.97 - spr.height)))
    d = ImageDraw.Draw(img)
    f1, s1 = font(122), 122
    while d.textlength(big, font=f1) > W * 0.56 and s1 > 40:
        s1 -= 6
        f1 = font(s1)
    f2, s2 = font(64), 64
    while small and d.textlength(small, font=f2) > W * 0.56 and s2 > 30:
        s2 -= 4
        f2 = font(s2)
    w1 = d.textlength(big, font=f1)
    outlined(d, ((W - w1) / 2, H * 0.14), big, f1, (255, 214, 64), 10)
    if small:
        w2 = d.textlength(small, font=f2)
        y2 = H * 0.14 + s1 * 1.25
        d.rounded_rectangle([(W - w2) / 2 - 30, y2 - 4, (W + w2) / 2 + 30, y2 + s2 * 1.25], radius=30,
                            fill=(255, 90, 120, 235))
        d.text(((W - w2) / 2, y2 - s2 * 0.08), small, font=f2, fill=(255, 255, 255))
    return img.convert("RGB")


def iris(frame, k):
    """k=1 fully open, k=0 closed."""
    if k >= 1:
        return frame
    m = Image.new("L", (W, H), 0)
    r = max(0.0, k) * math.hypot(W, H) / 2
    ImageDraw.Draw(m).ellipse([W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r], fill=255)
    return Image.composite(frame, Image.new("RGB", (W, H), (25, 15, 45)), m)


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ------------------------------------------------------------------ main render
def render(ep, lib, out, offline=False):
    lang = ep.get("lang", "tr")
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    TITLE, IRIS, PAUSE, END = 4.0, 0.35, 0.3, 5.0
    sc_list = ep["scenes"]
    tr_in = ["iris" if i == 0 or sc["bg"] != sc_list[i - 1]["bg"] else "cut" for i, sc in enumerate(sc_list)]
    t, idx = TITLE, 0
    clips, scenes, srt = [], [], []
    for i, sc in enumerate(sc_list):
        out_iris = i + 1 == len(sc_list) or tr_in[i + 1] == "iris"
        st = t
        t += (IRIS if tr_in[i] == "iris" else 0) + 0.4
        lines = []
        for ln in sc["lines"]:
            a = say(lang, ln["who"], ln["text"], work, idx, offline)
            idx += 1
            lines.append({"t0": t, "t1": t + len(a) / SR, "ln": ln})
            clips.append((t, a))
            srt.append((t, t + len(a) / SR, ln["text"]))
            t += len(a) / SR + PAUSE
        t += 0.5 + (IRIS if out_iris else 0)
        scenes.append({"t0": st, "t1": t, "sc": sc, "lines": lines, "in": tr_in[i] == "iris", "out": out_iris,
                       "x": layout(sc, lib)})
    total = t + END
    n = int(total * SR) + SR
    voice = np.zeros(n, np.float32)
    for st, a in clips:
        voice[int(st * SR):int(st * SR) + len(a)] += a
    voice *= 0.92 / max(1e-6, np.abs(voice).max())
    mix = voice + music(n, ep.get("music_seed", 1))
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)
    wav = work / "mix.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    with open(out / f"altyazi_{lang}.srt", "w", encoding="utf-8") as f:
        for i, (a, b, txt) in enumerate(srt, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n\n")

    first, last = scenes[0]["sc"]["bg"], scenes[-1]["sc"]["bg"]
    title = card(lib.background(first), ep["series"], ep["title"], lib, {"mina": "wave", "efe": "happy"})
    end = card(lib.background(last), ep.get("end_big", ep["series"]), ep.get("end_small", ""), lib,
               {"mina": "wave", "efe": "wave"})
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264",
                             "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                             "-shortest", "-movflags", "+faststart", str(out / "bolum.mp4")], stdin=subprocess.PIPE)
    end_t = scenes[-1]["t1"]
    for fi in range(int(total * FPS)):
        tt = fi / FPS
        if tt < TITLE:
            frame = iris(title, (TITLE - tt) / IRIS)
        elif tt >= end_t:
            frame = iris(end, (tt - end_t) / IRIS)
        else:
            s = next(x for x in scenes if x["t0"] <= tt < x["t1"])
            frame = draw_scene(s, tt, lib)
            k = 1.0
            if s["in"]:
                k = min(k, (tt - s["t0"]) / IRIS)
            if s["out"]:
                k = min(k, (s["t1"] - tt) / IRIS)
            frame = iris(frame, k)
        proc.stdin.write(np.asarray(frame, dtype=np.uint8).tobytes())
        if fi % (FPS * 60) == 0:
            log("  frame", fi, "/", int(total * FPS))
    proc.stdin.close()
    proc.wait()
    cover(ep, lib, lib.background(ep.get("cover_bg", first)), out)
    (out / "info.json").write_text(json.dumps({"duration": round(total, 1), "scenes": len(scenes),
                                               "layout": [{c: round(x) for c, x in s["x"].items()} for s in scenes]}))
    log("done", round(total, 1), "s")


def draw_scene(s, tt, lib):
    sc = s["sc"]
    p = (tt - s["t0"]) / max(0.1, s["t1"] - s["t0"])
    z0, z1, dx = sc.get("cam", [1.0, 1.03, 0.0])
    e = 0.5 - 0.5 * math.cos(math.pi * p)
    z = z0 + (z1 - z0) * e
    bg = lib.background(sc["bg"])
    cw, chh = W / z, H / z
    cx = bg.width / 2 + dx * W * (e - 0.5)
    cy = bg.height / 2
    frame = bg.resize((W, H), Image.BILINEAR, box=(cx - cw / 2, cy - chh / 2, cx + cw / 2, cy + chh / 2)).convert("RGBA")
    cur = next((l for l in s["lines"] if l["t0"] <= tt <= l["t1"]), None)
    poses = dict(sc.get("start_pose", {}))
    changed = {}
    for l in s["lines"]:     # a pose stays until a later line changes it
        if l["t0"] - 0.08 <= tt:
            for c, pz in (l["ln"].get("pose") or {}).items():
                poses[c] = pz
                changed[c] = l["t0"] - 0.08
    for c, x in s["x"].items():
        spr = lib.sprite(c, poses.get(c, "happy"), sc.get("scale", 1.0), bool(sc.get("flip", {}).get(c)))
        bob = 2.0 * math.sin(2 * math.pi * 0.4 * tt + (sum(map(ord, c)) % 7))
        if cur is not None and cur["ln"]["who"] == c:
            bob -= 7 * abs(math.sin(2 * math.pi * 1.6 * (tt - cur["t0"])))
        since = tt - changed.get(c, -9)
        if since < 0.18:      # tiny pop when a pose changes
            pop = 1.0 + 0.04 * (1 - since / 0.18)
            spr = spr.resize((int(spr.width * pop), int(spr.height * pop)), Image.BILINEAR)
        gy = H * GROUND
        sh = shadow(int(spr.width * 0.75))
        frame.alpha_composite(sh, (int(x - sh.width / 2), int(gy - sh.height * 0.55)))
        frame.alpha_composite(spr, (int(x - spr.width / 2), int(gy - spr.height + bob)))
    return frame.convert("RGB")


def cover(ep, lib, bg, out):
    cv = bg.resize((W, H)).convert("RGBA")
    chars = ep.get("cover_chars", {"mina": "surprised", "efe": "happy"})
    xs = [0.24, 0.76, 0.5]
    for i, (c, pz) in enumerate(chars.items()):
        spr = lib.sprite(c, pz, 1.75)
        cv.alpha_composite(spr, (int(W * xs[i % 3] - spr.width / 2), int(H * 1.22 - spr.height)))
    d = ImageDraw.Draw(cv)
    txt = ep.get("cover_text", ep["title"]).upper()
    size = 112
    f = font(size)
    while d.textlength(txt, font=f) > W * 0.92:
        size -= 6
        f = font(size)
    outlined(d, ((W - d.textlength(txt, font=f)) / 2, 22), txt, f, (255, 214, 64), 11)
    f2 = font(46)
    lab = ep["series"]
    d.rounded_rectangle([24, H - 88, 56 + d.textlength(lab, font=f2), H - 22], radius=22, fill=(255, 90, 120, 240))
    d.text((40, H - 90), lab, font=f2, fill=(255, 255, 255))
    cv.convert("RGB").save(out / "kapak.jpg", quality=92)


if __name__ == "__main__":
    ep = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    lib_dir, out = Path(sys.argv[2]), Path(sys.argv[3])
    cp = lib_dir / "choice.json"
    choice = json.loads(cp.read_text()) if cp.exists() else {}
    out.mkdir(parents=True, exist_ok=True)
    off = "--offline" in sys.argv
    render(ep, Lib(lib_dir, choice, off), out, off or "--notts" in sys.argv)
