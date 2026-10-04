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


def balance_value():
    token = os.environ.get("POLLINATIONS_TOKEN", "").strip()
    try:
        req = urllib.request.Request("https://gen.pollinations.ai/account/balance",
                                     headers={"Authorization": f"Bearer {token}", "User-Agent": "tk-bot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return float(json.loads(r.read()).get("balance", 0))
    except Exception:  # noqa: BLE001
        return None


HORDE_MODELS = ["AlbedoBase XL (SDXL)", "Juggernaut XL", "Dreamshaper", "stable_diffusion"]
HORDE_NEG = "people, person, child, character, animal, text, letters, watermark, logo, blurry, deformed, dark"


def horde(prompt, path, seed, deadline):
    """Free community GPUs (AI Horde) for backgrounds, so the small Pollinations budget is kept for poses."""
    key = os.environ.get("HORDE_API_KEY", "").strip() or "0000000000"
    hdr = {"apikey": key, "Client-Agent": "tarihin-karanligi:1.0:github", "Content-Type": "application/json",
           "User-Agent": "tarihin-karanligi-bot/1.0"}
    body = {"prompt": prompt[:850] + " ### " + HORDE_NEG,
            "params": {"width": 1024, "height": 576, "steps": 28, "cfg_scale": 6.5, "n": 1,
                       "sampler_name": "k_euler_a", "karras": True, "seed": str(seed)},
            "models": HORDE_MODELS, "nsfw": False, "censor_nsfw": True, "r2": True,
            "slow_workers": True, "trusted_workers": False}
    base = "https://aihorde.net/api/v2/generate/"

    def call(url, data=None, method=None, timeout=40):
        req = urllib.request.Request(url, headers=hdr, data=data, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    jid = None
    for attempt in range(6):
        try:
            jid = json.loads(call(base + "async", json.dumps(body).encode()))["id"]
            break
        except Exception as e:  # noqa: BLE001
            log("  horde submit", attempt + 1, str(e)[:120])
            time.sleep(20 + 10 * attempt)
    if not jid:
        return "horde submit failed"
    while time.time() < deadline:
        time.sleep(10)
        try:
            chk = json.loads(call(base + "check/" + jid, timeout=30))
        except Exception:  # noqa: BLE001
            continue
        if chk.get("faulted") or not chk.get("is_possible", True):
            return "horde impossible"
        if chk.get("done"):
            try:
                g = (json.loads(call(base + "status/" + jid, timeout=60)).get("generations") or [{}])[0]
                if g.get("censored"):
                    return "horde censored"
                img = g.get("img", "")
                if img.startswith("http"):
                    with urllib.request.urlopen(urllib.request.Request(img, headers={"User-Agent": "tk-bot/1.0"}),
                                                timeout=60) as r:
                        data = r.read()
                else:
                    import base64
                    data = base64.b64decode(img)
                from PIL import Image
                import io
                Image.open(io.BytesIO(data)).convert("RGB").save(path, "JPEG", quality=94)
                log("  horde ok", g.get("model"))
                return "ok"
            except Exception as e:  # noqa: BLE001
                return "horde fetch " + str(e)[:100]
    try:
        call(base + "status/" + jid, method="DELETE", timeout=20)
    except Exception:  # noqa: BLE001
        pass
    return "horde timeout"


RESERVE = 0.06   # pollen left for the Tarihin Karanligi daily images


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
        bal = balance_value()
        if bal is not None and bal < RESERVE:
            run["budget_hit"] = f"reserve ({bal}) " + time.strftime("%H:%M UTC", time.gmtime())
            break
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
    catalog = json.loads(cat.read_text(encoding="utf-8")) if cat.exists() else {}
    bgs.update({k: v["en"] for k, v in catalog.items()})
    # backgrounds made by AI Horde look more photographic; upgrade them to flux when the pollen budget allows
    flux_done = set(REPORT.get("flux_bgs") or []) | set(BGS)
    upgrade = [k for k in bgs if k not in flux_done and (lib / "bg" / f"{k}_1.jpg").exists()]
    upgrade.sort(key=lambda k: not catalog.get(k, {}).get("flux_only"))
    for name in upgrade:
        bal = balance_value()
        if bal is None or bal < RESERVE:
            break
        p = lib / "bg" / f"{name}_1.jpg"
        tmp = lib / "bg" / f"_{name}.jpg"
        res = poll(f"{bgs[name]}, {BG_STYLE}", tmp, 307, w=1344, h=768)
        log("flux upgrade", name, res)
        if res != "ok":
            break
        tmp.replace(p)
        REPORT["flux_bgs"] = sorted(set(REPORT.get("flux_bgs") or []) | {name})
        run["made"].append("flux:" + name)
    todo = [(n, d) for n, d in bgs.items() if not (lib / "bg" / f"{n}_1.jpg").exists()]
    if todo:
        from concurrent.futures import ThreadPoolExecutor
        deadline = time.time() + 25 * 60

        def one(item):
            name, desc = item
            p = lib / "bg" / f"{name}_1.jpg"
            res = horde(f"{desc}, {BG_STYLE}", p, 307, deadline)
            log(p.name, res)
            return p.name, res
        with ThreadPoolExecutor(3) as ex:
            for name, res in ex.map(one, todo):
                if res == "ok":
                    run["made"].append(name)
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
