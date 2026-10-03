"""Character consistency lab for the 'Mina ile Efe' cartoon series.

stage a: master character images (flux) on a plain background, several seeds each
stage b: pose edits from one master image with Pollinations 'kontext' and Gemini image models,
         plus background removal (rembg) so a character can be placed on any scene unchanged.
Results + report.json go to the given folder.
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

STYLE = ("high quality 3D animated family movie character, cute stylized cartoon proportions, big expressive eyes, "
         "soft studio lighting, vibrant pastel colors, highly detailed")
CHARS = {
    "mina": "a cute 6 year old Turkish girl named Mina, long wavy dark brown hair with a small yellow hair clip on the "
            "left side, big brown eyes, wearing a sunny yellow knee-length dress with a round white collar, white "
            "socks and red shoes",
    "efe": "a cute 4 year old Turkish boy named Efe, short curly dark brown hair, big brown eyes, wearing a green "
           "t-shirt with one white star on the chest, blue shorts and white sneakers",
    "dede": "a kind elderly Turkish park gardener named Hasan Dede, white mustache, grey flat cap, green overalls over a "
            "beige shirt, brown boots",
}
REPORT = {}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http(url, headers=None, data=None, timeout=180):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "tarihin-karanligi-bot/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def poll(prompt, path, seed, model="flux", image=None, w=1024, h=1024):
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    q = {"width": w, "height": h, "model": model, "nologo": "true", "seed": seed, "enhance": "false",
         "private": "true", "referrer": "tarihinkaranligi"}
    if image:
        q["image"] = image
    url = "https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt[:1500]) + "?" + urllib.parse.urlencode(q)
    err = None
    for attempt in range(3):
        try:
            data = http(url, {"Authorization": f"Bearer {token}"} if token else {})
            if len(data) > 10000:
                path.write_bytes(data)
                return "ok"
            err = f"small response: {data[:200]!r}"
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:300]!r}"
        except Exception as e:  # noqa: BLE001
            err = str(e)[:300]
        log("  ", model, "try", attempt + 1, err)
        if err.startswith("HTTP 4") and "429" not in err:
            break
        time.sleep(10 * (attempt + 1))
    return err


def gemini_edit(src, prompt, path):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    out = {}
    img = base64.b64encode(Path(src).read_bytes()).decode()
    for model in ["gemini-2.5-flash-image", "gemini-2.5-flash-image-preview", "gemini-3-pro-image-preview",
                  "gemini-2.0-flash-preview-image-generation"]:
        body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": img}}, {"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
        try:
            res = json.loads(http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  {"Content-Type": "application/json", "x-goog-api-key": key},
                                  json.dumps(body).encode()))
            parts = res["candidates"][0]["content"]["parts"]
            pic = next((p for p in parts if "inlineData" in p or "inline_data" in p), None)
            if pic:
                d = pic.get("inlineData") or pic.get("inline_data")
                Path(path).write_bytes(base64.b64decode(d["data"]))
                out[model] = "ok"
                return out
            out[model] = "no image: " + json.dumps(parts)[:200]
        except urllib.error.HTTPError as e:
            out[model] = f"HTTP {e.code}: {e.read()[:300]!r}"
        except Exception as e:  # noqa: BLE001
            out[model] = str(e)[:300]
        log("  gemini", model, out[model][:160])
    return out


def stage_a(out):
    for name, desc in CHARS.items():
        for k in range(3):
            p = out / f"{name}_{k}.jpg"
            prompt = (f"full body character reference, front view, standing straight, whole body from head to shoes "
                      f"visible, {desc}, plain pure white background, no shadow, centered, {STYLE}")
            REPORT[f"{name}_{k}"] = poll(prompt, p, 900 + k * 37, w=768, h=1152)
            log(name, k, REPORT[f"{name}_{k}"])


def stage_b(out, base_url):
    src = out / "mina_0.jpg"
    url = base_url + "mina_0.jpg"
    tests = {
        "kontext_wave": "the same girl, exactly the same face, hair, hair clip and yellow dress, now waving her hand "
                        "and smiling, full body, plain white background",
        "kontext_park": "the same girl, exactly the same face, hair and yellow dress, standing in a sunny green park "
                        "pointing up at a tree, wide shot",
    }
    for name, prompt in tests.items():
        REPORT[name] = poll(prompt, out / f"{name}.jpg", 77, model="kontext", image=url)
        log(name, REPORT[name])
    REPORT["gemini_wave"] = gemini_edit(src, "Keep this exact same girl (same face, hair, hair clip, yellow dress, "
                                        "shoes). Show her waving her hand and smiling, full body, plain white "
                                        "background.", out / "gemini_wave.png")
    try:
        from rembg import remove
        from PIL import Image
        Image.open(src).convert("RGB").save(out / "_tmp.png")
        cut = remove(Image.open(out / "_tmp.png"))
        cut.save(out / "mina_0_cut.png")
        REPORT["rembg"] = "ok"
    except Exception as e:  # noqa: BLE001
        REPORT["rembg"] = str(e)[:300]


if __name__ == "__main__":
    stage, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rp = out / "report.json"
    if rp.exists():
        REPORT.update(json.loads(rp.read_text()))
    if stage == "a":
        stage_a(out)
    else:
        stage_b(out, sys.argv[3])
    rp.write_text(json.dumps(REPORT, indent=1, ensure_ascii=False))
