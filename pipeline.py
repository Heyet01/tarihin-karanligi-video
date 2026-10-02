"""Daily job: get today's script from Make, render, prepare the Pages site and notify payload."""
import datetime
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from render import log, render

OUT = Path("out")


def clean_json(txt):
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?", "", txt).strip()
    txt = re.sub(r"```$", "", txt).strip()
    return json.loads(txt)


SITE_URL = "https://heyet01.github.io/tarihin-karanligi-video/"
FORBIDDEN = re.compile(r"\w*yıl(?:dır|\s+önce|\s+sonra)\b", re.IGNORECASE)
CLIFF = "Devamı akşam! Kaçırmamak için takip et."


def tr_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3)


def load_pool():
    pool = []
    for line in Path("topics.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "|" in line:
            cat, topic = [x.strip() for x in line.split("|", 1)]
            pool.append((cat, topic))
    return pool


def load_state():
    """State lives on the Pages site (state.json) so nothing has to be committed."""
    try:
        with urllib.request.urlopen(SITE_URL + "state.json?t=" + str(int(time.time())), timeout=20) as r:
            st = json.loads(r.read().decode("utf-8"))
            if isinstance(st, dict):
                return st
    except Exception as e:  # noqa: BLE001
        log("state.json not found on site, using seed:", e)
    p = Path("state_seed.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def plan(state, now):
    """Decide topic and part (1 = noon cliffhanger, 2 = evening continuation, 0 = single video)."""
    if os.environ.get("TOPIC"):
        return {"category": os.environ.get("CATEGORY", ""), "topic": os.environ["TOPIC"],
                "part": int(os.environ.get("PART", "0"))}
    ser = state.get("series") or {}
    if ser.get("part") == 1 and ser.get("topic"):
        try:
            age_h = (now - datetime.datetime.fromisoformat(ser["at"])).total_seconds() / 3600
        except Exception:  # noqa: BLE001
            age_h = 99
        if age_h < 30:
            return {"category": ser.get("category", ""), "topic": ser["topic"], "part": 2,
                    "prev_title": ser.get("title", ""), "prev_script": ser.get("script", ""),
                    "look": ser.get("look"), "prev_folder": ser.get("folder"), "prev_cut": ser.get("cut")}
    pool = load_pool()
    used = set(state.get("used", []))
    fresh = [p for p in pool if p[1] not in used] or pool
    last_cat = state.get("last_category")
    other = [p for p in fresh if p[0] != last_cat] or fresh
    # balanced rotation: prefer the category used least recently
    recent_cats = state.get("recent_categories", [])
    def staleness(cat):
        return recent_cats[::-1].index(cat) if cat in recent_cats else 99
    best = max(staleness(c) for c, _ in other)
    choices = [p for p in other if staleness(p[0]) == best]
    cat = random.choice(sorted({c for c, _ in choices}))
    topic = random.choice([t for c, t in choices if c == cat])
    part = 1 if now.hour < 15 else 0
    return {"category": cat, "topic": topic, "part": part}


def brief_for(pl, state):
    recent = " | ".join(state.get("recent_titles", [])[-12:][::-1]) or "yok"
    lines = [f"BUGÜNÜN KONUSU (SADECE bunu anlat, başka konu seçme): {pl['topic']}  [{pl['category']}]",
             f"Kanalın son video başlıkları (açılış ve başlık kalıplarını tekrarlama): {recent}"]
    if pl["part"] == 1:
        lines.append(
            "BÖLÜM KURALI: Bu 1. BÖLÜM (öğle videosu). TAM 5 sahne, toplam 26-31 kelime. "
            "title sonu ' (1. Bölüm)' ve 1 emoji olsun, toplam en fazla 55 karakter. "
            "Hikayeyi en merak edilen anda kes; twist'i ve sonucu AÇIKLAMA. "
            f"5. sahne tam olarak şu cümle olsun: {CLIFF}")
    elif pl["part"] == 2:
        lines.append(
            "BÖLÜM KURALI: Bu 2. BÖLÜM (akşam videosu), öğlen yayınlanan 1. bölümün devamı. "
            f"1. bölümün başlığı: {pl.get('prev_title', '')}. 1. bölümün metni: {pl.get('prev_script', '')} "
            "TAM 7 sahne, toplam 45-60 kelime. title aynı konuyu anlatsın, sonu ' (2. Bölüm)' ve 1 emoji olsun. "
            "1. sahne öğlen kalan merakı hatırlatan kısa bir hook olsun (1. bölümün cümlelerini tekrarlama), "
            "sonra yeni detaylar, twist ve sonuç gelsin; son sahne A mı, B mi sorusu olsun.")
    else:
        lines.append(
            "BÖLÜM KURALI: Bu tek parça video. TAM 7 sahne, toplam 45-60 kelime. title'da 'Bölüm' yazma. "
            "Son sahne A mı, B mi sorusu olsun.")
    return "\n\n".join(lines)


def fix_title(title, part):
    title = re.sub(r"\s*\(\s*\d\.\s*Bölüm\s*\)", "", title).strip()
    if part not in (1, 2):
        return title
    m = re.match(r"^(.*?)(\s*[^\w\s\)\!\?\.\,'’\"]+)?$", title)
    base, emo = (m.group(1), m.group(2) or "") if m else (title, "")
    base = base.strip()[:56]
    return f"{base} ({part}. Bölüm){(' ' + emo.strip()) if emo.strip() else ''}"


def problems(job, pl):
    errs = []
    scenes = job.get("scenes") or []
    want = 5 if pl["part"] == 1 else 7
    if abs(len(scenes) - want) > 1:
        errs.append(f"{len(scenes)} sahne (beklenen {want})")
    text = " ".join(str(s.get("text", "")) for s in scenes) + " " + str(job.get("title", ""))
    if FORBIDDEN.search(text):
        errs.append("hesaplanmış süre ifadesi: " + FORBIDDEN.search(text).group(0))
    if pl["part"] != 1 and "Devamı akşam" in text:
        errs.append("yanlış yerde 'Devamı akşam'")
    return errs


def get_job():
    if os.environ.get("JOB_FILE"):
        job = json.loads(Path(os.environ["JOB_FILE"]).read_text(encoding="utf-8"))
        return job, {"category": "", "topic": job.get("title", ""), "part": 0}, {}
    url, token = os.environ["MAKE_WEBHOOK_URL"], os.environ["MAKE_TOKEN"]
    state = load_state()
    pl = plan(state, tr_now())
    log("plan:", json.dumps(pl, ensure_ascii=False)[:300])
    body = json.dumps({"action": "script", "token": token, "topic": pl["topic"], "category": pl["category"],
                       "part": str(pl["part"]), "brief": brief_for(pl, state)}).encode()
    last, best = None, None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=280) as r:
                job = clean_json(r.read().decode("utf-8"))
            if isinstance(job.get("scenes"), list) and len(job["scenes"]) >= 3:
                n_words = sum(len(str(s.get("text", "")).split()) for s in job["scenes"])
                limit = 40 if len(job["scenes"]) <= 5 else 72   # 5 scenes ~18-20 s, longer videos up to ~40 s
                errs = problems(job, pl)
                if n_words > limit:
                    errs.append(f"{n_words} kelime")
                best = best or job
                if errs and attempt < 2:
                    last = "; ".join(errs)
                    log(f"script rejected ({last}), asking again")
                    continue
                return finalize(job if not errs else best, pl), pl, state
            last = f"bad job: {str(job)[:300]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        log(f"script attempt {attempt + 1} failed: {last}")
        time.sleep(40)
    if best:
        return finalize(best, pl), pl, state
    raise RuntimeError(f"could not get script: {last}")


def finalize(job, pl):
    job["title"] = fix_title(str(job.get("title") or job.get("cover_text") or "Tarihin Karanlığı"), pl["part"])
    if pl["part"] == 1 and job.get("scenes"):
        job["scenes"][-1]["text"] = CLIFF
    return job


def save_state(state, pl, job, script, site, folder="", info=None):
    now = tr_now()
    st = {k: state.get(k, []) for k in ("used", "recent_titles", "recent_categories")}
    if pl["part"] != 2 and pl["topic"]:
        st["used"] = (st["used"] + [pl["topic"]])[-200:]
        st["recent_categories"] = (st["recent_categories"] + [pl["category"]])[-6:]
    st["recent_titles"] = (st["recent_titles"] + [job["title"]])[-20:]
    st["last_category"] = pl["category"]
    info = info or {}
    st["series"] = ({"part": 1, "topic": pl["topic"], "category": pl["category"], "title": job["title"],
                     "script": script, "at": now.isoformat(timespec="minutes"), "folder": folder,
                     "cut": info.get("last_start"), "look": info.get("look")} if pl["part"] == 1 else {})
    st["updated"] = now.isoformat(timespec="minutes")
    (site / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def make_full(pl, part2_mp4, out_mp4, work):
    """Part 1 (without its 'Devamı akşam' line) + part 2 = one ~1 minute story for TikTok."""
    if not pl.get("prev_folder"):
        return False
    work.mkdir(parents=True, exist_ok=True)
    p1 = work / "part1.mp4"
    try:
        with urllib.request.urlopen(SITE_URL + pl["prev_folder"] + "/video_ig.mp4", timeout=120) as r:
            p1.write_bytes(r.read())
        cut = pl.get("prev_cut")
        trim = f"trim=0:{cut}," if cut else ""
        atrim = f"atrim=0:{cut},afade=t=out:st={max(0.0, float(cut) - 0.25)}:d=0.25," if cut else ""
        flt = (f"[0:v]{trim}setpts=PTS-STARTPTS,fps=24,scale=720:1280,setsar=1[v0];"
               f"[0:a]{atrim}asetpts=PTS-STARTPTS,aresample=48000[a0];"
               "[1:v]setpts=PTS-STARTPTS,fps=24,scale=720:1280,setsar=1[v1];"
               "[1:a]asetpts=PTS-STARTPTS,aresample=48000[a1];"
               "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p1), "-i", str(part2_mp4),
                        "-filter_complex", flt, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(out_mp4)],
                       check=True, timeout=600)
        log("full story video:", round(out_mp4.stat().st_size / 1e6, 2), "MB")
        return True
    except Exception as e:  # noqa: BLE001
        log("full story video failed:", e)
        return False


def tiktok_caption(title, description):
    desc = re.sub(r"\n*(?:⏪|⏰|🔔)[^\n]*", "", description).replace("#shorts", "#keşfet")
    return f"{title}\n\n{desc.strip()}\n\n🔔 Takip et, her gün yeni bir tarih sırrı!"


def main():
    job, pl, state = get_job()
    log("job:", json.dumps({k: v for k, v in job.items() if k != "scenes"}, ensure_ascii=False)[:400])
    run = os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
    folder = datetime.datetime.utcnow().strftime("%Y-%m-%d") + "-" + run
    site = OUT / "site"
    dest = site / folder
    dest.mkdir(parents=True, exist_ok=True)
    if pl.get("look") and not job.get("look"):
        job["look"] = pl["look"]
    info = render(job, OUT / "work", dest / "video_ig.mp4", dest / "video_yt.mp4")
    shutil.rmtree(OUT / "work", ignore_errors=True)
    log("render:", json.dumps(info))

    repo = os.environ.get("GITHUB_REPOSITORY", "Heyet01/tarihin-karanligi-video")
    owner, name = repo.split("/")
    base = f"https://{owner.lower()}.github.io/{name}/{folder}/"
    script = " ".join(s.get("text", "") for s in job["scenes"])
    meta = {
        "action": "publish",
        "folder": folder,
        "title": str(job.get("title") or job.get("cover_text") or "Tarihin Karanlığı")[:95].replace("<", "").replace(">", ""),
        "description": (str(job.get("description", "")).replace("<", "").replace(">", "")[:4600]
                        + {1: "\n\n⏰ 2. bölüm bu akşam kanalda!", 2: "\n\n⏪ 1. bölüm kanalda, önce onu izle!"}.get(pl["part"], "")
                        + "\n\n🔔 Her gün 2 yeni tarih sırrı: abone ol, devamını kaçırma!"),
        "fact_check": job.get("fact_check", ""),
        "cover_text": job.get("cover_text", ""),
        "script": script,
        "duration": info["duration"],
        "images_ok": info["images_ok"],
        "scenes": info["scenes"],
        "yt_mb": info["yt_mb"],
        "video_ig_url": base + "video_ig.mp4",
        "video_yt_url": base + "video_yt.mp4",
        "cover_url": base + "cover.jpg",
        "topic": pl.get("topic", ""),
        "part": pl.get("part", 0),
    }
    # ASCII-safe snippet so Make can set the Turkish language on YouTube after upload
    meta["yt_snippet"] = json.dumps({"title": meta["title"], "description": meta["description"],
                                     "categoryId": "27", "defaultLanguage": "tr",
                                     "defaultAudioLanguage": "tr"})
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (site / ".nojekyll").write_text("")
    if pl.get("topic") and not os.environ.get("JOB_FILE"):
        save_state(state, pl, job, script, site, folder, info)
    if pl.get("part") in (0, 2) and not os.environ.get("JOB_FILE"):
        full = pl["part"] == 2 and make_full(pl, dest / "video_ig.mp4", dest / "video_full.mp4", OUT / "full_work")
        shutil.rmtree(OUT / "full_work", ignore_errors=True)
        tt_title = fix_title(pl.get("prev_title", ""), 0) if full else meta["title"]
        tiktok = {"date": tr_now().strftime("%Y-%m-%d"), "part": pl["part"], "full": bool(full),
                  "title": tt_title[:90], "caption": tiktok_caption(tt_title, meta["description"]),
                  "video_url": base + ("video_full.mp4" if full else "video_ig.mp4"), "posted": False}
        (OUT / "tiktok.json").write_text(json.dumps(tiktok, ensure_ascii=False, indent=1), encoding="utf-8")
    (site / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>Tarihin Karanlığı</title>'
        f'<p>Son video: <a href="{folder}/video_ig.mp4">{folder}</a></p>', encoding="utf-8")
    (OUT / "notify.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    log("done", base)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        OUT.mkdir(exist_ok=True)
        (OUT / "error.txt").write_text(str(e)[:500], encoding="utf-8")
        raise
    sys.exit(0)
