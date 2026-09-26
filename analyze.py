"""Weekly niche outlier analysis for Tarihin Karanligi.

Searches recent Turkish history/mystery Shorts through the Make YouTube proxy,
scores each video against its channel's average (outlier score), asks Gemini
(via Make) what the winners have in common, emails the report and saves the
lessons to insights.txt so the daily script writer can learn from them.
"""
import datetime
import html
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = os.environ["MAKE_WEBHOOK_URL"]
TOKEN = os.environ["MAKE_TOKEN"]
QUERIES = [
    "tarih gizem",
    "osmanlı tarihi bilinmeyenler",
    "tarihin karanlık yüzü",
    "çözülemeyen gizemler",
    "antik uygarlık gizemi",
    "ilginç tarih bilgileri shorts",
]
DAYS = 21


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def call(payload, timeout=150):
    data = json.dumps(dict(payload, token=TOKEN)).encode("utf-8")
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"call failed ({attempt + 1}): {e}")
            time.sleep(15)
    raise RuntimeError(f"Make call failed: {last}")


def yt(path, params):
    txt = call({"action": "yt", "path": path + "?" + urllib.parse.urlencode(params)})
    return json.loads(txt)


def seconds(iso):
    # PT1M5S -> 65
    total, num = 0, ""
    for ch in iso.replace("PT", ""):
        if ch.isdigit():
            num += ch
        else:
            total += int(num or 0) * {"H": 3600, "M": 60, "S": 1}.get(ch, 0)
            num = ""
    return total


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    after = (now - datetime.timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in QUERIES:
        res = yt("/v3/search", {"part": "snippet", "type": "video", "q": q, "regionCode": "TR",
                                "relevanceLanguage": "tr", "publishedAfter": after, "videoDuration": "short",
                                "order": "viewCount", "maxResults": 25})
        found = [it["id"]["videoId"] for it in res.get("items", []) if it.get("id", {}).get("videoId")]
        log(f"'{q}': {len(found)} videos")
        ids += [i for i in found if i not in ids]
    videos = []
    for part in chunks(ids, 50):
        res = yt("/v3/videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(part)})
        videos += res.get("items", [])
    ch_ids = sorted({v["snippet"]["channelId"] for v in videos})
    channels = {}
    for part in chunks(ch_ids, 50):
        res = yt("/v3/channels", {"part": "statistics", "id": ",".join(part)})
        for c in res.get("items", []):
            channels[c["id"]] = c.get("statistics", {})

    rows = []
    for v in videos:
        st, sn = v.get("statistics", {}), v["snippet"]
        views = int(st.get("viewCount", 0))
        dur = seconds(v.get("contentDetails", {}).get("duration", "PT0S"))
        cs = channels.get(sn["channelId"], {})
        ch_views, ch_count = int(cs.get("viewCount", 0)), max(1, int(cs.get("videoCount", 1)))
        subs = int(cs.get("subscriberCount", 0)) if not cs.get("hiddenSubscriberCount") else 0
        avg = max(1.0, ch_views / ch_count)
        if views < 5000 or dur == 0 or dur > 180:
            continue
        pub = datetime.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        age = max(1.0, (now - pub).total_seconds() / 86400)
        rows.append({"id": v["id"], "title": sn["title"], "channel": sn["channelTitle"], "views": views,
                     "subs": subs, "score": round(views / avg, 1), "per_day": int(views / age),
                     "likes": int(st.get("likeCount", 0)), "comments": int(st.get("commentCount", 0)),
                     "dur": dur})
    rows.sort(key=lambda r: (r["score"], r["views"]), reverse=True)
    top = rows[:20]
    log(f"{len(videos)} videos, {len(rows)} after filter")
    if not top:
        raise RuntimeError("no videos found")

    lines = [f"{r['views']} izlenme | {r['score']}x kanal ortalaması | {r['title']} | {r['channel']}" for r in top]
    table = "".join(
        f"<tr><td>{i + 1}</td><td><a href='https://youtube.com/shorts/{r['id']}'>{html.escape(r['title'])}</a></td>"
        f"<td>{html.escape(r['channel'])}</td><td>{r['views']:,}</td><td>{r['score']}x</td>"
        f"<td>{r['per_day']:,}/gün</td><td>{r['subs']:,}</td></tr>"
        for i, r in enumerate(top))
    table = ("<table border='1' cellpadding='5' style='border-collapse:collapse'><tr><th>#</th><th>Video</th>"
             "<th>Kanal</th><th>İzlenme</th><th>Patlama</th><th>Hız</th><th>Abone</th></tr>" + table + "</table>")
    analysis = call({"action": "report", "titles": "\n".join(lines), "table": table,
                     "stats": f"{len(videos)} video tarandı, {len(rows)} tanesi filtreden geçti, son {DAYS} gün"})
    analysis = analysis.strip()
    stamp = now.strftime("%Y-%m-%d")
    body = [f"Son analiz: {stamp}", "Nişte en çok patlayan Shorts başlıkları:"]
    body += [f"- {r['title']} ({r['score']}x)" for r in top[:10]]
    body += ["", "Çıkarılan dersler:", analysis[:2500]]
    Path("insights.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    log("insights.txt written")


if __name__ == "__main__":
    main()
