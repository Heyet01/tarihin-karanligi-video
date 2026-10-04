"""Builds the fixed character pose library (and scene backgrounds) for the 'Mina ile Efe' series.

Every pose is an edit of ONE approved master image (Pollinations 'kontext'), so face, hair, clothes and
colours stay identical; the background is then removed (rembg) to get a transparent sprite.
usage: python tools/cizgi_kutuphane.py OUT_DIR MASTER_BASE_URL
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

KEEP = ("Keep the exact same character: same face, same eyes, same hair and hairstyle, same hair clip, same "
        "clothes, same shoes and same colours. Change only the pose and expression: {pose}. Full body from head "
        "to shoes, the character alone, plain pure white background, no other people, no text.")
MASTERS = {"mina": "mina_1.jpg", "efe": "efe_0.jpg", "dede": "dede_0.jpg"}
POSES = {
    "happy": "standing, smiling happily with mouth closed, arms relaxed",
    "talk": "standing, smiling and talking with the mouth open",
    "wave": "waving one hand hello, big smile",
    "point": "pointing up into the sky with one arm, excited face",
    "surprised": "surprised, both hands on the cheeks, mouth open in an O shape",
    "sad": "sad face, looking down, shoulders slumped",
    "think": "thinking, one finger on the chin, eyes looking up",
    "laugh": "laughing joyfully with eyes closed and both arms raised",
}
EXTRA = {   # episode specific poses for the pilot
    "efe": {"kite": "holding up a small red diamond-shaped kite with both hands, happy"},
    "dede": {"ladder": "carrying a long wooden ladder on his shoulder, friendly smile",
             "give": "holding out a small red diamond-shaped kite in one hand, kind smile"},
}
BGS = {
    "park_wide": "a sunny green city park in a Turkish town with yellow tulips, a stone path, benches and a huge "
                 "old plane tree on the right, blue sky with soft clouds",
    "park_tree": "a huge old plane tree in a sunny park, thick trunk and wide branches, a small red diamond kite "
                 "stuck high in the branches, green lawn in front",
    "park_path": "a sunny park path lined with yellow and red tulips and green bushes, a wooden bench, trees",
    "park_sunset": "a green park hill at sunset, orange and pink sky, soft golden light, a few trees",
}
BG_STYLE = ("empty scene, no people, no characters, high quality 3D animated family movie background, soft warm "
            "cinematic lighting, vibrant pastel colours, wide 16:9 shot, ground visible in the lower third, no text")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def poll(prompt, path, seed, model="flux", image=None, w=1024, h=1024):
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    q = {"width": w, "height": h, "model": model, "nologo": "true", "seed": seed, "enhance": "false",
         "private": "true", "referrer": "tarihinkaranligi"}
    if image:
        q["image"] = image
    url = "https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt[:1500]) + "?" + urllib.parse.urlencode(q)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tarihin-karanligi-bot/1.0",
                                                      **({"Authorization": f"Bearer {token}"} if token else {})})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) > 10000:
                path.write_bytes(data)
                return True
        except Exception as e:  # noqa: BLE001
            log("  retry", attempt + 1, str(e)[:150])
        time.sleep(8 * (attempt + 1))
    return False


def main():
    out, base = Path(sys.argv[1]), sys.argv[2]
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "bg").mkdir(parents=True, exist_ok=True)
    rep = {}
    jobs = []
    for ch, master in MASTERS.items():
        poses = dict(POSES)
        if ch == "dede":
            poses = {k: poses[k] for k in ("happy", "talk", "wave", "point", "laugh", "surprised")}
        poses.update(EXTRA.get(ch, {}))
        for pose, desc in poses.items():
            for s in (1, 2):
                jobs.append((ch, pose, s, KEEP.format(pose=desc), base + master))
    for ch, pose, s, prompt, img in jobs:
        p = out / "raw" / f"{ch}_{pose}_{s}.jpg"
        ok = poll(prompt, p, 100 + s * 11, model="kontext", image=img)
        rep[p.name] = ok
        log(p.name, ok)
    for name, desc in BGS.items():
        for s in (1, 2):
            p = out / "bg" / f"{name}_{s}.jpg"
            ok = poll(f"{desc}, {BG_STYLE}", p, 300 + s * 7, w=1344, h=768)
            rep[p.name] = ok
            log(p.name, ok)
    # transparent sprites
    try:
        from rembg import new_session, remove
        from PIL import Image
        sess = new_session("isnet-general-use")
        (out / "png").mkdir(exist_ok=True)
        for p in sorted((out / "raw").glob("*.jpg")):
            im = Image.open(p).convert("RGB")
            cut = remove(im, session=sess, alpha_matting=False)
            bb = cut.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
            if bb:
                cut = cut.crop(bb)
            cut.save(out / "png" / (p.stem + ".png"))
        rep["rembg"] = "ok"
    except Exception as e:  # noqa: BLE001
        rep["rembg"] = str(e)[:300]
    (out / "report.json").write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
