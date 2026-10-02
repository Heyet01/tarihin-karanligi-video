"""Daily job: get today's script from Make, render, prepare the Pages site and notify payload."""
import datetime
import json
import os
import re
import shutil
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


def get_job():
    if os.environ.get("JOB_FILE"):
        return json.loads(Path(os.environ["JOB_FILE"]).read_text(encoding="utf-8"))
    url, token = os.environ["MAKE_WEBHOOK_URL"], os.environ["MAKE_TOKEN"]
    body = json.dumps({"action": "script", "token": token}).encode()
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=280) as r:
                job = clean_json(r.read().decode("utf-8"))
            if isinstance(job.get("scenes"), list) and len(job["scenes"]) >= 3:
                n_words = sum(len(str(s.get("text", "")).split()) for s in job["scenes"])
                limit = 40 if len(job["scenes"]) <= 5 else 72   # 5 scenes ~18-20 s, longer test videos up to ~40 s
                if n_words > limit and attempt == 0:   # too long: ask once more
                    log(f"script too long ({n_words} words), asking again")
                    continue
                return job
            last = f"bad job: {str(job)[:300]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        log(f"script attempt {attempt + 1} failed: {last}")
        time.sleep(40)
    raise RuntimeError(f"could not get script: {last}")


def main():
    job = get_job()
    log("job:", json.dumps({k: v for k, v in job.items() if k != "scenes"}, ensure_ascii=False)[:400])
    run = os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
    folder = datetime.datetime.utcnow().strftime("%Y-%m-%d") + "-" + run
    site = OUT / "site"
    dest = site / folder
    dest.mkdir(parents=True, exist_ok=True)
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
        "description": (str(job.get("description", "")).replace("<", "").replace(">", "")[:4700]
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
    }
    # ASCII-safe snippet so Make can set the Turkish language on YouTube after upload
    meta["yt_snippet"] = json.dumps({"title": meta["title"], "description": meta["description"],
                                     "categoryId": "27", "defaultLanguage": "tr",
                                     "defaultAudioLanguage": "tr"})
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (site / ".nojekyll").write_text("")
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
