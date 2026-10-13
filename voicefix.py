"""Voice fallback: if Microsoft edge-tts is blocked (HTTP 403), narrate with the free offline Piper voice.

Used by the workflow: python -c "import render, voicefix; voicefix.install(render); ..."
"""
import asyncio
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VOICES = [os.environ.get("PIPER_VOICE") or "tr/tr_TR/dfki/medium/tr_TR-dfki-medium",
          "tr/tr_TR/fahrettin/medium/tr_TR-fahrettin-medium"]
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
# Piper is now the main voice (the user prefers it); set USE_EDGE=1 to try edge-tts first.
STATE = {"edge_dead": os.environ.get("USE_EDGE") != "1", "model": None}


# ---- Turkish text fixes (wrong words / badly written numbers) ----
import json
import re

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS_W = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def tr_number(n):
    """1237 -> bin iki yüz otuz yedi"""
    if n == 0:
        return "sıfır"
    parts = []
    if n >= 1000000:
        parts.append(tr_number(n // 1000000) + " milyon")
        n %= 1000000
    if n >= 1000:
        k = n // 1000
        parts.append("bin" if k == 1 else tr_number(k) + " bin")
        n %= 1000
    if n >= 100:
        h = n // 100
        parts.append("yüz" if h == 1 else _ONES[h] + " yüz")
        n %= 100
    if n >= 10:
        parts.append(_TENS_W[n // 10])
        n %= 10
    if n:
        parts.append(_ONES[n])
    return " ".join(parts)


_ONE_RE = "|".join(w for w in _ONES[2:])
_TEN_RE = "|".join(_TENS_W[1:])


def fix_bin(text):
    # "bin iki otuz yedi" -> "bin iki yüz otuz yedi" (a hundreds digit written without "yüz")
    return re.sub(rf"\b(bin|Bin)\s+({_ONE_RE})\s+(?=({_TEN_RE}|{_ONE_RE})\b)", r"\1 \2 yüz ", str(text))


def fix_numbers(text):
    s = fix_bin(text)
    # plain digits -> words (years etc.); a suffix after the apostrophe is attached: 1453'te -> ...elli üçte
    s = re.sub(r"\b(\d{1,7})(?![\d.,])(?:['’](\w+))?",
               lambda m: tr_number(int(m.group(1))) + (m.group(2) or ""), s)
    return re.sub(r"\s{2,}", " ", s).strip()


def proofread(texts, log):
    """Ask Gemini to correct spelling / grammar / invented words without changing meaning or length."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or not texts:
        return texts
    prompt = ("Aşağıdaki JSON listesindeki Türkçe cümleler bir tarih videosunda seslendirilecek. Her cümleyi "
              "Türkçe yazım ve dil bilgisi açısından düzelt: uydurma veya yanlış türetilmiş kelimeleri doğru, "
              "yaygın Türkçe kelimelerle değiştir (örn. şüphelilukla -> şüpheyle), yanlış ekleri düzelt, "
              "sayıları ve yılları doğru şekilde yazıyla yaz (örn. 1237 -> bin iki yüz otuz yedi). Anlamı, "
              "bilgiyi ve cümle sayısını DEĞİŞTİRME; kelime sayısını en fazla 2 değiştir; doğru olan cümleye "
              "dokunma. Sadece aynı uzunlukta bir JSON string listesi döndür.\n\n" + json.dumps(texts, ensure_ascii=False))
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}}).encode()
    for model in ("gemini-flash-latest", "gemini-flash-lite-latest"):
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=90) as resp:
                out = json.loads(resp.read())
            fixed = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
            if not (isinstance(fixed, list) and len(fixed) == len(texts)
                    and all(isinstance(t, str) and t.strip() for t in fixed)):
                raise ValueError("bad shape")
            res = []
            for a, b in zip(texts, fixed):
                ok = abs(len(a.split()) - len(b.split())) <= 3
                res.append(b.strip() if ok else a)
                if ok and b.strip() != a:
                    log("  dil duzeltme:", a, "->", b.strip())
            return res
        except Exception as e:  # noqa: BLE001
            log("  proofread failed:", model, str(e)[:160])
            time.sleep(3)
    return texts


def install(r):
    log = r.log

    def model():
        if STATE["model"] is not None:
            return STATE["model"]
        STATE["model"] = ""
        try:
            import piper  # noqa: F401
        except Exception:  # noqa: BLE001
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "piper-tts"], check=False)
        cache = Path.home() / ".cache" / "piper"
        cache.mkdir(parents=True, exist_ok=True)
        for v in VOICES:
            name = v.split("/")[-1]
            try:
                for suf in (".onnx", ".onnx.json"):
                    p = cache / (name + suf)
                    if not p.exists() or p.stat().st_size < 100:
                        with urllib.request.urlopen(BASE + v + suf, timeout=180) as resp:
                            p.write_bytes(resp.read())
                STATE["model"] = str(cache / (name + ".onnx"))
                log("  piper voice:", name)
                break
            except Exception as e:  # noqa: BLE001
                log("  piper voice download failed:", name, e)
        return STATE["model"]

    def synth_voice(text, workdir, idx, offline):
        if offline:
            return orig(text, workdir, idx, offline)
        mp3, wav = workdir / f"v{idx}.mp3", workdir / f"v{idx}.wav"
        text = r.speakable(text)
        for attempt in range(0 if STATE["edge_dead"] else 3):
            try:
                words = asyncio.run(r._tts(text, str(mp3), os.environ.get("TTS_RATE", "+2%"),
                                           os.environ.get("TTS_PITCH", "-3Hz")))
                audio = r.decode_wav(str(mp3), str(wav))
                if len(audio) > r.SR * 0.5:
                    return audio, words
            except Exception as e:  # noqa: BLE001
                log(f"  tts attempt {attempt + 1} failed: {str(e)[:160]}")
                time.sleep(4 * (attempt + 1))
        if not STATE["edge_dead"]:
            log("  edge-tts unavailable, switching to the free offline Piper voice")
        STATE["edge_dead"] = True
        raw = workdir / f"v{idx}_piper.wav"
        for attempt in range(2):
            try:
                m = model()
                if not m:
                    raise RuntimeError("no piper voice")
                subprocess.run([sys.executable, "-m", "piper", "-m", m, "-f", str(raw),
                                "--length-scale", os.environ.get("PIPER_SPEED", "0.92")],
                               input=text.encode("utf-8"), check=True, timeout=300)
                audio = r.decode_wav(str(raw), str(wav))
                if len(audio) > r.SR * 0.3:
                    return audio, []   # no word timings: render spreads the words evenly
            except Exception as e:  # noqa: BLE001
                log(f"  piper attempt {attempt + 1} failed: {str(e)[:160]}")
                time.sleep(3)
        raise RuntimeError("TTS failed")

    orig = r.synth_voice
    r.synth_voice = synth_voice

    orig_speakable = r.speakable
    r.speakable = lambda t: fix_numbers(orig_speakable(fix_bin(t)))

    orig_render = r.render

    def render(job, *a, **kw):
        try:
            scenes = [sc for sc in job.get("scenes", []) if isinstance(sc, dict) and sc.get("text")]
            fixed = proofread([fix_bin(sc["text"]) for sc in scenes], log)
            for sc, t in zip(scenes, fixed):
                sc["text"] = t
        except Exception as e:  # noqa: BLE001
            log("  text fix skipped:", e)
        return orig_render(job, *a, **kw)

    r.render = render
