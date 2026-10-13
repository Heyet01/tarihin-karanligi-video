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
