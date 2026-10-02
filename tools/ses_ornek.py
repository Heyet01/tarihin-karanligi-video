import asyncio, json, os, subprocess, edge_tts
job = json.load(open("tools/ornek_job.json", encoding="utf-8"))
lines = [s["text"] for s in job["scenes"]]
V = [("1_simdiki_ahmet", "tr-TR-AhmetNeural", "+14%"),
     ("2_andrew", "en-US-AndrewMultilingualNeural", "+8%"),
     ("3_brian", "en-US-BrianMultilingualNeural", "+8%"),
     ("4_florian", "de-DE-FlorianMultilingualNeural", "+8%"),
     ("5_remy", "fr-FR-RemyMultilingualNeural", "+8%"),
     ("6_emel_kadin", "tr-TR-EmelNeural", "+10%")]
os.makedirs("ses", exist_ok=True)
rep = {}
async def one(text, voice, rate, mp3):
    n = 0
    com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                n += 1
    return n
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", "0.25", "/tmp/gap.wav"], check=True)
for name, voice, rate in V:
    try:
        parts, nb = [], 0
        for i, t in enumerate(lines):
            mp3 = f"/tmp/{name}_{i}.mp3"
            nb += asyncio.run(one(t, voice, rate, mp3))
            wav = f"/tmp/{name}_{i}.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", "24000", wav], check=True)
            parts += [wav, "/tmp/gap.wav"]
        with open("/tmp/list.txt", "w") as f:
            f.write("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "/tmp/list.txt",
                        "-c:a", "libmp3lame", "-b:a", "96k", f"ses/{name}.mp3"], check=True)
        rep[name] = {"voice": voice, "rate": rate, "word_boundaries": nb, "words": sum(len(t.split()) for t in lines)}
    except Exception as e:
        rep[name] = {"voice": voice, "error": str(e)}
    print(name, rep[name], flush=True)
json.dump(rep, open("ses/rapor.json", "w"), indent=1)
