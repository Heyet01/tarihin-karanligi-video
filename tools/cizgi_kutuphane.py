"""Builds (and keeps growing) the fixed character pose library and scene backgrounds for 'Mina ile Efe'.

Every pose is an edit of ONE approved master image (Pollinations 'kontext'), so face, hair, clothes and
colours stay identical; the background is then removed (rembg) to get a transparent sprite.
The library is resumable: files that already exist are kept, missing ones are made in priority order.
kontext runs on a small daily free budget, so the run stops asking for poses at the first 402 and the
next scheduled run continues.  Backgrounds and props use flux.
usage: python tools/cizgi_kutuphane.py LIB_DIR MASTER_BASE_URL
"""
import json
import os
import sys
import time
import urllib.error
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
    "kite": "holding up a small red diamond-shaped kite with both hands, happy",
    "ladder": "carrying a long wooden ladder on his shoulder, friendly smile",
    "give": "holding out a small red diamond-shaped kite in one hand, kind smile",
}
# most useful first; the free kontext budget is small, so one seed per pose
PRIORITY = ["efe_wave", "efe_sad", "efe_surprised", "efe_point", "efe_laugh", "dede_wave", "dede_point",
            "dede_talk", "mina_surprised", "mina_laugh", "mina_think", "mina_sad", "efe_think", "efe_kite",
            "dede_laugh", "dede_surprised", "dede_ladder", "dede_give", "efe_talk"]
BGS = {
    "park_wide": "a sunny green city park in a Turkish town with yellow tulips, a stone path, benches and a huge "
                 "old plane tree on the right, blue sky with soft clouds",
    "park_tree": "a huge old plane tree in a sunny park, thick trunk and wide branches, a small red diamond kite "
                 "stuck high in the branches, green lawn in front",
    "park_path": "a sunny park path lined with yellow and red tulips and green bushes, a wooden bench, trees",
    "park_sunset": "a green park hill at sunset, orange and pink sky, soft golden light, a few trees",
    "kite_sky": "a small red diamond-shaped kite with a long ribbon tail flying high in a bright blue sky with "
                "fluffy white clouds above the green treetops of a park",
}
BG_STYLE = ("empty scene, no people, no characters, high quality 3D animated family movie background, soft warm "
            "cinematic lighting, vibrant pastel colours, wide 16:9 shot, ground visible in the lower third, no text")
REPORT = {"runs": []}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def poll(prompt, path, seed, model="flux", image=None, w=1024, h=1024):
    """Returns 'ok', 'budget' (402) or an error string."""
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    q = {"width": w, "height": h, "model": model, "nologo": "true", "seed": seed, "enhance": "false",
         "private": "true", "referrer": "tarihinkaranligi"}
    if image:
        q["image"] = image
    url = "https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt[:1500]) + "?" + urllib.parse.urlencode(q)
    err = "?"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tarihin-karanligi-bot/1.0",
                                                      **({"Authorization": f"Bearer {token}"} if token else {})})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) > 10000:
                path.write_bytes(data)
                return "ok"
            err = f"small {len(data)}"
        except urllib.error.HTTPError as e:
            if e.code == 402:
                return "budget"
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = str(e)[:120]
        log("  retry", attempt + 1, err)
        time.sleep(10 * (attempt + 1))
    return err


def balance():
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    out = {}
    for u in ("https://gen.pollinations.ai/account/balance", "https://enter.pollinations.ai/api/account/balance"):
        try:
            req = urllib.request.Request(u, headers={"Authorization": f"Bearer {token}", "User-Agent": "tk-bot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out[u] = r.read()[:200].decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            out[u] = f"HTTP {e.code} {e.read()[:120]!r}"
        except Exception as e:  # noqa: BLE001
            out[u] = str(e)[:120]
    return out


def main():
    lib, base = Path(sys.argv[1]), sys.argv[2]
    for d in ("raw", "bg", "png"):
        (lib / d).mkdir(parents=True, exist_ok=True)
    rp = lib / "report.json"
    if rp.exists():
        try:
            REPORT.update(json.loads(rp.read_text()))
        except ValueError:
            pass
    run = {"start": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "made": [], "budget_hit": None,
           "balance": balance()}
    # the approved masters are the 'happy' pose of efe and dede
    for ch in ("efe", "dede"):
        p = lib / "raw" / f"{ch}_happy_1.jpg"
        if not p.exists():
            try:
                with urllib.request.urlopen(base + MASTERS[ch], timeout=60) as r:
                    p.write_bytes(r.read())
                run["made"].append(p.name)
            except Exception as e:  # noqa: BLE001
                log("master", ch, e)
    for job in PRIORITY:
        ch, pose = job.split("_", 1)
        p = lib / "raw" / f"{job}_1.jpg"
        if p.exists():
            continue
        res = poll(KEEP.format(pose=POSES[pose]), p, 111, model="kontext", image=base + MASTERS[ch])
        log(p.name, res)
        if res == "budget":
            run["budget_hit"] = time.strftime("%H:%M UTC", time.gmtime())
            break
        if res == "ok":
            run["made"].append(p.name)
        time.sleep(4)
    bgs = dict(BGS)
    cat = Path(__file__).resolve().parent.parent / "cizgi" / "sahneler.json"
    if cat.exists():
        bgs.update({k: v["en"] for k, v in json.loads(cat.read_text(encoding="utf-8")).items()})
    for name, desc in bgs.items():
        p = lib / "bg" / f"{name}_1.jpg"
        if p.exists():
            continue
        res = poll(f"{desc}, {BG_STYLE}", p, 307, w=1344, h=768)
        log(p.name, res)
        if res == "ok":
            run["made"].append(p.name)
    try:
        from PIL import Image
        from rembg import new_session, remove
        sess = None
        for p in sorted((lib / "raw").glob("*.jpg")):
            q = lib / "png" / (p.stem + ".png")
            if q.exists():
                continue
            sess = sess or new_session("isnet-general-use")
            cut = remove(Image.open(p).convert("RGB"), session=sess)
            bb = cut.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
            if bb:
                cut = cut.crop(bb)
            cut.save(q)
            run["made"].append(q.name)
    except Exception as e:  # noqa: BLE001
        run["rembg"] = str(e)[:300]
    run["end"] = time.strftime("%H:%M UTC", time.gmtime())
    REPORT["runs"] = (REPORT.get("runs") or [])[-30:] + [run]
    REPORT["missing"] = [j for j in PRIORITY if not (lib / "raw" / f"{j}_1.jpg").exists()]
    rp.write_text(json.dumps(REPORT, indent=1))
    log("made", len(run["made"]), "missing", len(REPORT["missing"]))


if __name__ == "__main__":
    main()
