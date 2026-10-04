"""Daily 'Mina ile Efe' episode: Gemini script -> Turkish + English renders -> YouTube uploads.

Turkish episode goes to the 'Mina ile Efe' channel (MINA_REFRESH_TOKEN), the English dub to BoomBooKidsTV
(BOOMBOO_REFRESH_TOKEN).  Both use the same OAuth client (YT_CLIENT_ID / YT_CLIENT_SECRET).
usage: python tools/cizgi_gunluk.py LIB_DIR OUT_DIR HISTORY_JSON
env: GEMINI_KEY, CIZGI_DRY=1 (render only), CIZGI_LANGS=tr,en, CIZGI_EPISODE=<json file to reuse>
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cizgi_bolum import Lib, log, render  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHARS = ("mina", "efe", "dede")
SLOTS = ("left", "midleft", "center", "midright", "right")
TOPICS = [
    "paylaşmak", "dişlerini fırçalamak", "ellerini yıkamak", "renkleri öğrenmek", "1'den 10'a saymak",
    "sebze ve meyve yemek", "teşekkür etmek ve lütfen demek", "özür dilemek", "oyuncakları toplamak",
    "trafik ışıkları ve karşıdan karşıya geçmek", "hayvanları sevmek ve korumak", "çöpü çöp kutusuna atmak",
    "suyu boşa harcamamak", "mevsimler", "şekiller (daire, kare, üçgen)", "duygular: üzülmek ve sevinmek",
    "sabırlı olmak ve sıra beklemek", "kaybolursan ne yaparsın (güvenilir bir büyüğe söyle)", "erken uyumak",
    "kendi kıyafetini giymek", "yeni bir arkadaş edinmek", "yardımlaşma", "kardeş sevgisi", "dürüst olmak",
    "korkularla baş etmek (karanlıktan korkmak)", "doktora gitmek", "bitki yetiştirmek", "geri dönüşüm",
    "güneşten korunmak ve su içmek", "kitap okumayı sevmek", "zıt kavramlar (büyük-küçük, sıcak-soğuk)",
    "hafta günleri", "büyüklere saygı", "kar yağınca giyinmek", "piknik ve doğayı temiz bırakmak",
    "hayvan sesleri", "deniz kenarında güvenlik", "kızınca sakinleşmek", "kazanmak ve kaybetmek (oyunda)",
    "yeni şeyler denemek (yeni yemek)", "sağlıklı kahvaltı", "toplu taşımada kurallar", "kütüphanede sessiz olmak",
    "doğum günü sürprizi hazırlamak", "pazar alışverişi ve sayma", "çiftlik hayvanları", "böcekleri tanımak",
    "yağmur ve gökkuşağı", "elmanın yolculuğu (ağaçtan sofraya)", "ekmeğin yapılışı (fırın)",
]
SYSTEM = """Sen okul öncesi çocuklar (3-7 yaş) için Türkçe çizgi dizi senaristisin. Dizinin adı "Mina ile Efe".
Karakterler: Mina (6 yaşında, meraklı, yardımsever, akıllı abla), Efe (4 yaşında, neşeli, biraz sakar ve çok soru soran
küçük kardeş), Hasan Dede (mahallenin ve parkın bilge, sevecen yaşlı bahçıvanı; çocukların akıl danıştığı büyük) ve
anlatıcı. Başka konuşan karakter YOK (anne, öğretmen, hayvan vb. sadece anlatıcının cümlelerinde geçebilir).
Kurallar:
- Her bölüm TEK bir basit değer ya da beceri öğretir; mesaj doğal hikâyenin içinde verilir, vaaz gibi değil.
- Cümleler kısa ve sade (en fazla 14 kelime), sıcak, neşeli ve güvenli. Şiddet, korku, tehlikeli taklit edilebilir
  davranış (ağaca tırmanma, ateş, ilaç vb.), marka, gerçek kişi, din ve siyaset YOK. Tehlike varsa çocuklar bir büyüğe sorar.
- Bölüm akışı: selamlama -> günlük hayattan küçük bir sorun -> merak, denemeler, komik küçük aksilikler -> Hasan Dede
  ya da çocukların kendi fikriyle çözüm -> öğrenilen ders -> izleyiciye soru -> vedalaşma ("Hoşça kalın arkadaşlar!").
- Ara sıra izleyiciyle konuş: "Sizce ne yapmalı?", "Hadi birlikte sayalım!" gibi; tekrarlar ve sayışmalar çocuklar için iyidir.
- Mina ve Efe en çok konuşan karakterlerdir; anlatıcı satırların en fazla %20'si olsun.
- Her satırın "en" alanına Amerikalı çocuklar için doğal İngilizce çevirisini yaz (Hasan Dede = "Grandpa Hasan",
  Türkçe isimler Mina ve Efe aynen kalır).
Sadece JSON döndür."""
USER = """Bugünün konusu: @TOPIC@
Daha önce yapılan bölümler (tekrar etme): @PAST@

Kullanabileceğin mekânlar (bg alanına SADECE bu adlardan birini yaz):
@BGS@

Karakter pozları (pose alanında SADECE bunlar):
@POSES@

Uzunluk: 30-36 sahne, toplam 290-330 satır (yaklaşık 14-15 dakika). Her sahnede 6-12 satır. Bu uzunluk ÇOK ÖNEMLİ.
Bir sahnede en fazla 3 karakter durur; yerleri: left, midleft, center, midright, right (farklı olmalı).
Konuşan karakter o sahnede bulunmalı (anlatıcı hariç). Duygu değişince "pose" ile pozu değiştir
(ör. üzülünce sad, şaşırınca surprised, gülünce laugh, gösterirken point, düşünürken think, selamlarken wave).
Aynı mekânda arka arkaya en fazla 3 sahne olsun; bölüm 4-7 farklı mekân kullansın.

JSON şeması:
{"title_tr": "2-4 kelimelik bölüm adı", "title_en": "...", "cover_tr": "kapak yazısı: EN FAZLA 3 kelime ve 20 harf, merak uyandıran",
 "cover_en": "...", "cover_bg": "mekân adı", "cover_poses": {"mina": "poz", "efe": "poz"},
 "description_tr": "2-3 cümle, ebeveynler için bölüm özeti ve öğrettiği değer", "description_en": "...",
 "tags_tr": ["10 arama etiketi"], "tags_en": ["10 search tags"],
 "scenes": [{"bg": "mekân", "chars": {"mina": "left", "efe": "midleft"}, "start_pose": {"mina": "happy", "efe": "happy"},
   "lines": [{"who": "anlatici|mina|efe|dede", "text": "Türkçe cümle", "en": "English line", "pose": {"efe": "wave"}}]}]}"""


def gemini(prompt, system):
    key = os.environ.get("GEMINI_KEY", "").strip()
    body = json.dumps({"system_instruction": {"parts": [{"text": system}]},
                       "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.9, "maxOutputTokens": 65536,
                                            "responseMimeType": "application/json"}}).encode()
    last = None
    models = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-flash-lite-latest"] * 4   # 503 'overloaded' is common
    for attempt, model in enumerate(models):
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=900) as r:
                out = json.loads(r.read())
            txt = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"] if not p.get("thought"))
            txt = re.sub(r"^```(json)?|```$", "", txt.strip()).strip()
            ep = json.loads(txt)
            n = sum(len(s.get("lines", [])) for s in ep.get("scenes", []))
            log("gemini", model, "scenes", len(ep.get("scenes", [])), "lines", n)
            if n < 90:
                raise ValueError(f"too short: {n} lines")
            return ep
        except Exception as e:  # noqa: BLE001
            last = e
            log("gemini", model, "failed:", str(e)[:300])
            time.sleep(20 + 15 * attempt)
    raise RuntimeError(f"gemini failed: {last}")


def clean(text):
    text = re.sub(r"\([^)]*\)|\*[^*]*\*|\[[^\]]*\]", " ", str(text or ""))
    text = re.sub(r"[^\w\s.,!?;:'\"’…\-çğıöşüÇĞİÖŞÜâîû]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


TR_HINT = set("ve bir bu ben sen biz çok ama da de mı mi mu mü ne neden nasıl hadi evet hayır şimdi abla dede için gibi".split())
EN_HINT = set("the and is are you i my we to a it this that what do let's yes no now sister grandpa with for".split())


def lang_score(text):
    w = re.findall(r"[\wçğıöşüÇĞİÖŞÜ']+", text.lower())
    tr = sum(x in TR_HINT for x in w) + 2 * len(re.findall("[çğıöşü]", text.lower()))
    en = sum(x in EN_HINT for x in w)
    return tr - en


def fix_languages(ep):
    """Gemini sometimes swaps the Turkish and English text of a line; put them back."""
    n = 0
    for sc in ep.get("scenes", []):
        for ln in sc.get("lines", []):
            t, e = str(ln.get("text") or ""), str(ln.get("en") or "")
            if t and e and lang_score(t) < 0 < lang_score(e):
                ln["text"], ln["en"] = e, t
                n += 1
    if n:
        log("fixed swapped languages:", n)
    return ep


def available(lib):
    poses = {c: sorted({p.stem[len(c) + 1:].rsplit("_", 1)[0] for p in (lib / "png").glob(f"{c}_*.png")}) for c in CHARS}
    for c in CHARS:
        poses[c] = [p for p in poses[c] if p != "master"] or ["happy"]
    cat = json.loads((ROOT / "cizgi" / "sahneler.json").read_text(encoding="utf-8"))
    rp = lib / "report.json"
    flux = set(json.loads(rp.read_text()).get("flux_bgs") or []) if rp.exists() else set()
    bgs = {k: v for k, v in cat.items() if ((lib / "bg" / f"{k}_1.jpg").exists() or (lib / "bg" / f"{k}_2.jpg").exists())
           and (not v.get("flux_only") or k in flux)}
    return poses, bgs


def normalize(ep, poses, bgs):
    """Make the script safe for the renderer: known places/characters/poses only, no overlaps."""
    default_bg = "park_wide" if "park_wide" in bgs else next(iter(bgs))
    scenes = []
    for sc in ep.get("scenes", []):
        bg = sc.get("bg") if sc.get("bg") in bgs else default_bg
        empty = bool(bgs[bg].get("empty"))
        chars = {}
        for c, slot in (sc.get("chars") or {}).items():
            c = str(c).lower()
            if c in CHARS and not empty and len(chars) < 3:
                chars[c] = slot if slot in SLOTS and slot not in chars.values() else None
        lines = []
        for ln in sc.get("lines", []):
            who = str(ln.get("who", "anlatici")).lower()
            who = who if who in CHARS + ("anlatici",) else "anlatici"
            text = clean(ln.get("text"))
            if not text:
                continue
            if who in CHARS and who not in chars:
                if empty or len(chars) >= 3:
                    who = "anlatici"
                else:
                    chars[who] = None
            pose = {c: p for c, p in (ln.get("pose") or {}).items() if c in chars and p in poses.get(c, [])}
            lines.append({"who": who, "text": text, "en": clean(ln.get("en")), "pose": pose})
        if not lines:
            continue
        free = [s for s in SLOTS if s not in chars.values()]
        order = ["left", "right", "midleft", "midright", "center"]
        for c in chars:
            if chars[c] is None:
                pick = next(s for s in order if s in free)
                free.remove(pick)
                chars[c] = pick
        start = {c: p for c, p in (sc.get("start_pose") or {}).items() if c in chars and p in poses.get(c, [])}
        z0 = 1.0 + 0.04 * (len(scenes) % 2)
        scenes.append({"bg": bg, "chars": chars, "start_pose": start, "lines": lines,
                       "cam": [z0, 2.04 - z0, 0.02 * (1 if len(scenes) % 3 == 0 else -1)]})
    ep["scenes"] = scenes
    cp = ep.get("cover_poses") or {}
    ep["cover_poses"] = {c: (cp.get(c) if cp.get(c) in poses[c] else poses[c][0] if "happy" not in poses[c] else "happy")
                         for c in ("mina", "efe")}
    if ep.get("cover_bg") not in bgs or bgs[ep.get("cover_bg")].get("empty"):
        ep["cover_bg"] = scenes[0]["bg"] if scenes else default_bg
    return ep


def cover_text(ep, lang):
    txt = str(ep.get("cover_" + lang) or "").strip()
    title = str(ep.get("title_" + lang) or "").strip()
    if not txt or len(txt) > 24 or len(txt.split()) > 4:
        txt = title if len(title) <= 24 else " ".join(title.split()[:3])
    return txt


def for_lang(ep, lang):
    tr = lang == "tr"
    scenes = []
    for sc in ep["scenes"]:
        lines = [dict(l, text=l["text"] if tr else l["en"]) for l in sc["lines"] if tr or l.get("en")]
        if lines:
            scenes.append(dict(sc, lines=lines))
    return {"lang": lang, "series": "Mina ile Efe" if tr else "Mina & Efe",
            "title": ep["title_tr"] if tr else ep["title_en"],
            "cover_text": cover_text(ep, lang),
            "cover_chars": ep["cover_poses"], "cover_bg": ep["cover_bg"],
            "end_big": "Mina ile Efe" if tr else "Mina & Efe",
            "end_small": "Yeni bölümde görüşmek üzere!" if tr else "See you in the next episode!",
            "music_seed": int(time.time()) % 1000, "scenes": scenes}


# ------------------------------------------------------------------ YouTube
def access_token(refresh):
    body = json.dumps({"client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
                       "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["access_token"]


def api(tok, url, body=None, method="GET"):
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/" + url,
                                 data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def upload(tok, path, meta):
    size = Path(path).stat().st_size
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers["Location"]
    for attempt in range(3):
        try:
            with open(path, "rb") as fh:
                req = urllib.request.Request(loc, data=fh, method="PUT",
                                             headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
                with urllib.request.urlopen(req, timeout=1800) as r:
                    return json.loads(r.read())["id"]
        except urllib.error.HTTPError as e:
            log("upload error", e.code, e.read()[:300])
            raise
        except Exception as e:  # noqa: BLE001
            log("upload retry", attempt, e)
            time.sleep(20)
    raise RuntimeError("upload failed")


def set_thumb(tok, vid, path):
    req = urllib.request.Request(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                                 data=Path(path).read_bytes(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status


def add_caption(tok, vid, srt, lang):
    boundary = "cizgi" + str(int(time.time()))
    meta = json.dumps({"snippet": {"videoId": vid, "language": lang, "name": "", "isDraft": False}})
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + Path(srt).read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://www.googleapis.com/upload/youtube/v3/captions?uploadType=multipart&part=snippet",
                                 data=body, method="POST",
                                 headers={"Authorization": f"Bearer {tok}",
                                          "Content-Type": f"multipart/related; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("id")


def playlist(tok, name, about, lang, vid):
    items = api(tok, "playlists?part=snippet&mine=true&maxResults=50").get("items", [])
    pid = next((i["id"] for i in items if i["snippet"]["title"] == name), None)
    if not pid:
        pid = api(tok, "playlists?part=snippet,status", {"snippet": {"title": name, "description": about,
                                                                     "defaultLanguage": lang},
                                                         "status": {"privacyStatus": "public"}}, "POST")["id"]
    api(tok, "playlistItems?part=snippet", {"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video",
                                                                                          "videoId": vid}}}, "POST")
    return pid


CHANNELS = {
    "tr": {"token": "MINA_REFRESH_TOKEN", "hour_utc": 14, "expect": "minaileefe",
           "playlist": ("Mina ile Efe - Tüm Bölümler", "Mina ile Efe çizgi dizisinin bütün bölümleri. Okul öncesi çocuklar için eğitici, neşeli hikâyeler."),
           "suffix": "| Mina ile Efe | Çocuklar İçin Eğitici Çizgi Film",
           "foot": "\n\nMina ile Efe, 3-7 yaş arası çocuklar için her gün yeni bölümle yayınlanan eğitici bir çizgi dizidir. "
                   "Mina, kardeşi Efe ve bilge Hasan Dede ile paylaşmayı, yardımlaşmayı ve dünyayı keşfetmeyi öğreniyoruz.\n\n"
                   "Yeni bölümleri kaçırmamak için kanala abone olun!\n\n#minaileefe #çizgifilm #çocukçizgifilm #eğiticiçizgifilm #masal",
           "base_tags": ["Mina ile Efe", "çizgi film", "çocuk çizgi filmi", "eğitici çizgi film", "türkçe çizgi film",
                         "okul öncesi", "çocuklar için", "masal"]},
    "en": {"token": "BOOMBOO_REFRESH_TOKEN", "hour_utc": 20, "expect": "boomboo",
           "playlist": ("Mina & Efe - Full Episodes", "All episodes of Mina & Efe, a gentle cartoon series for preschoolers about kindness, sharing and discovering the world."),
           "suffix": "| Mina & Efe | Cartoons for Kids",
           "foot": "\n\nMina & Efe is a gentle animated series for kids aged 3-7. Join Mina, her little brother Efe and "
                   "kind Grandpa Hasan as they learn about sharing, helping and the world around them. A new episode every day!\n\n"
                   "Subscribe for new episodes!\n\n#cartoonsforkids #kidscartoon #preschool #kidsstories",
           "base_tags": ["Mina and Efe", "cartoons for kids", "kids cartoon", "preschool learning", "kids stories",
                         "animated series", "toddler learning", "BoomBoo Kids"]},
}


def publish(lang, ep, out):
    ch = CHANNELS[lang]
    refresh = os.environ.get(ch["token"], "").strip()
    if not refresh:
        log("no token for", lang, "- skipping upload")
        return None
    tok = access_token(refresh)
    me = api(tok, "channels?part=snippet&mine=true").get("items", [{}])
    name = (me[0].get("snippet", {}).get("title", "") if me else "")
    log(lang, "channel:", name)
    if ch["expect"] not in name.replace("İ", "i").lower().replace("\u0307", "").replace(" ", ""):
        raise RuntimeError(f"token belongs to the wrong channel: {name}")
    title = f"{ep['title_' + lang]} {ch['suffix']}"[:100]
    desc = (str(ep.get("description_" + lang, "")) + ch["foot"]).replace("<", "").replace(">", "")[:4900]
    tags = [str(t)[:40] for t in (ep.get("tags_" + lang) or [])][:12] + ch["base_tags"]
    now = datetime.now(timezone.utc)
    target = now.replace(hour=ch["hour_utc"], minute=0, second=0, microsecond=0)
    status = {"selfDeclaredMadeForKids": True, "embeddable": True, "containsSyntheticMedia": False}
    if target - now > timedelta(minutes=20):
        status.update(privacyStatus="private", publishAt=target.strftime("%Y-%m-%dT%H:%M:%SZ"))
    else:
        status.update(privacyStatus="public")
    meta = {"snippet": {"title": title, "description": desc, "tags": tags, "categoryId": "1",
                        "defaultLanguage": lang, "defaultAudioLanguage": lang}, "status": status}
    vid = upload(tok, out / "bolum.mp4", meta)
    log(lang, "uploaded", vid, status)
    for name, fn in (("thumb", lambda: set_thumb(tok, vid, out / "kapak.jpg")),
                     ("caption", lambda: add_caption(tok, vid, out / f"altyazi_{lang}.srt", lang)),
                     ("playlist", lambda: playlist(tok, *ch["playlist"], lang, vid))):
        try:
            log(lang, name, fn())
        except urllib.error.HTTPError as e:
            log(lang, name, "failed", e.code, e.read()[:300])
        except Exception as e:  # noqa: BLE001
            log(lang, name, "failed", e)
    return vid


def main():
    lib, out, hist_p = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    dry = os.environ.get("CIZGI_DRY", "0") == "1"
    langs = [x for x in (os.environ.get("CIZGI_LANGS") or "tr,en").split(",") if x in ("tr", "en")]
    history = json.loads(hist_p.read_text()) if hist_p.exists() else []
    today = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
    if not dry and any(h.get("date") == today and h.get("tr_id") for h in history):
        log("today's episode already published")
        return
    poses, bgs = available(lib)
    log("poses", poses, "bgs", list(bgs))
    if os.environ.get("CIZGI_EPISODE"):
        ep = json.loads(Path(os.environ["CIZGI_EPISODE"]).read_text(encoding="utf-8"))
    else:
        done = [h.get("topic") for h in history]
        topic = next((t for t in TOPICS if t not in done), TOPICS[len(history) % len(TOPICS)])
        past = ", ".join(h.get("title_tr", "") for h in history[-30:]) or "yok"
        prompt = (USER.replace("@TOPIC@", topic).replace("@PAST@", past)
                  .replace("@BGS@", "\n".join(f"- {k}: {v['tr']}" for k, v in bgs.items()))
                  .replace("@POSES@", "\n".join(f"- {c}: {', '.join(p)}" for c, p in poses.items())))
        ep = gemini(prompt, SYSTEM)
        ep["topic"] = topic
    ep = normalize(fix_languages(ep), poses, bgs)
    (out / "bolum.json").write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
    rec = {"date": today, "topic": ep.get("topic"), "title_tr": ep.get("title_tr"), "title_en": ep.get("title_en"),
           "scenes": len(ep["scenes"]), "lines": sum(len(s["lines"]) for s in ep["scenes"])}
    log("episode", json.dumps(rec, ensure_ascii=False))
    choice = json.loads((lib / "choice.json").read_text()) if (lib / "choice.json").exists() else {}
    for lang in langs:
        o = out / lang
        o.mkdir(exist_ok=True)
        render(for_lang(ep, lang), Lib(lib, choice), o)
        rec[lang + "_duration"] = json.loads((o / "info.json").read_text())["duration"]
        if not dry:
            try:
                rec[lang + "_id"] = publish(lang, ep, o)
            except urllib.error.HTTPError as e:
                rec[lang + "_error"] = f"{e.code} {e.read()[:300]!r}"
                log(lang, "publish failed", rec[lang + "_error"])
            except Exception as e:  # noqa: BLE001
                rec[lang + "_error"] = str(e)[:300]
                log(lang, "publish failed", e)
        for f in (o / "work").glob("*"):
            f.unlink()
    if not dry:
        history.append(rec)
        hist_p.write_text(json.dumps(history[-400:], ensure_ascii=False, indent=1))
    (out / "summary.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    log("done", json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()
