"""Rebuild a TikTok 'full story' video: part 1 without its cliffhanger line + part 2 without its recap hook.

Scene timings are recovered by re-synthesising the narration with the same TTS settings render.py uses
(the clip lengths decide where each scene starts), then checked against the real video durations.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")
import render  # noqa: E402

SITE = "https://heyet01.github.io/tarihin-karanligi-video/"
OUT = Path("out")
WORK = OUT / "fixwork"


def fetch(url, dst):
    with urllib.request.urlopen(url, timeout=180) as r:
        Path(dst).write_bytes(r.read())
    return dst


def durs_for(texts, tag):
    d = []
    for i, t in enumerate(texts):
        a, _ = render.synth_voice(t, WORK, f"{tag}{i}", False)
        d.append(len(a) / render.SR + 0.25)
    d[-1] += 1.0
    return d


def probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    tt = json.loads(Path("tiktok_state.json").read_text(encoding="utf-8"))
    folder = tt["video_url"].rstrip("/").split("/")[-2]
    meta = json.loads(fetch(SITE + folder + "/meta.json", WORK / "meta.json").read_text(encoding="utf-8"))
    p2_texts = [s.strip() for s in re.findall(r"[^.!?]+[.!?]+", meta["script"]) if s.strip()]
    p1_texts = json.loads(os.environ["P1_SCENES"])
    p1_total = float(os.environ["P1_DURATION"])

    d1 = durs_for(p1_texts, "a")
    d2 = durs_for(p2_texts, "b")
    print("part1 scenes", len(d1), "sum", round(sum(d1), 2), "expected", p1_total)
    print("part2 scenes", len(d2), "sum", round(sum(d2), 2), "expected", meta["duration"])
    if abs(sum(d1) - p1_total) > 0.35 or abs(sum(d2) - float(meta["duration"])) > 0.35:
        sys.exit("timings do not match the videos, refusing to cut blindly")
    cut1 = sum(d1[:-1])          # start of the 'Devamı akşam' scene
    skip2 = d2[0]                # end of the recap hook
    print("cut part1 at", round(cut1, 3), "skip part2 first", round(skip2, 3))

    full = fetch(SITE + folder + "/video_full.mp4", WORK / "full.mp4")
    p2 = fetch(SITE + folder + "/video_ig.mp4", WORK / "p2.mp4")
    print("full", probe_dur(full), "p2", probe_dur(p2))
    flt = (f"[0:v]trim=0:{cut1:.3f},setpts=PTS-STARTPTS,fps=24,scale=720:1280,setsar=1[v0];"
           f"[0:a]atrim=0:{cut1:.3f},afade=t=out:st={cut1 - 0.2:.3f}:d=0.2,asetpts=PTS-STARTPTS,aresample=48000[a0];"
           f"[1:v]trim=start={skip2:.3f},setpts=PTS-STARTPTS,fps=24,scale=720:1280,setsar=1[v1];"
           f"[1:a]atrim=start={skip2:.3f},afade=t=in:st=0:d=0.15,asetpts=PTS-STARTPTS,aresample=48000[a1];"
           "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
    out = OUT / "tiktok_fix.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(full), "-i", str(p2), "-filter_complex", flt,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-maxrate", "3500k", "-bufsize", "7000k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-ac", "2", "-movflags", "+faststart", str(out)], check=True)
    print("fixed video", round(probe_dur(out), 2), "s,", round(out.stat().st_size / 1e6, 2), "MB")
    for s in (0.5, cut1 - 1.0, cut1 + 0.6, cut1 + 3):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s:.2f}", "-i", str(out), "-frames:v", "1",
                        "-vf", "scale=360:-2", "-q:v", "5", str(OUT / f"fix_{s:.1f}.jpg")], check=False)


if __name__ == "__main__":
    main()
