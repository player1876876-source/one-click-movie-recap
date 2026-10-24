import os, uuid, json, re, subprocess, asyncio, shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from openai import OpenAI
import edge_tts

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
WORK = ROOT / "work"
for folder in (UPLOADS, OUTPUTS, WORK):
    folder.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError((p.stderr or "FFmpeg failed")[-1800:])
    return p.stdout

def duration_of(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(out.strip())

def srt_time(seconds):
    seconds = max(0, float(seconds))
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def ass_time(seconds):
    cs = int(max(0, float(seconds)) * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def write_subtitles(segments, folder):
    srt_path = folder / "burmese_subtitles.srt"
    ass_path = folder / "burmese_subtitles.ass"
    with srt_path.open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n{seg['my']}\n\n")
    # ASS styling: white Myanmar text with black outline, lower center.
    with ass_path.open("w", encoding="utf-8-sig") as f:
        f.write("""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans Myanmar,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,3,1,2,70,70,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""")
        for seg in segments:
            txt = seg["my"].replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")
            f.write(f"Dialogue: 0,{ass_time(seg['start'])},{ass_time(seg['end'])},Default,,0,0,0,,{txt}\n")
    return srt_path, ass_path

def atempo_chain(factor):
    # ffmpeg atempo accepts 0.5..2 per filter; chain if needed
    factor = max(0.5, min(2.0, factor))
    return f"atempo={factor:.4f}"

async def make_voice(text, output):
    # Microsoft Edge online TTS voice. Internet connection is required.
    communicate = edge_tts.Communicate(text, "my-MM-NilarNeural", rate="+0%")
    await communicate.save(str(output))

def process_video(src, jobdir, options):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY မရှိသေးပါ။ README ထဲက API Key အဆင့်ကို အရင်လုပ်ပါ။")
    client = OpenAI(api_key=api_key)
    audio = jobdir / "audio.mp3"
    # Compress audio to make it easier to upload to transcription service.
    run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "48k", str(audio)])
    if audio.stat().st_size > 24 * 1024 * 1024:
        raise RuntimeError("အသံဖိုင်က 24MB ကျော်နေပါတယ်။ ပိုတိုတဲ့ Video နဲ့ အရင်စမ်းပါ (၁-၃ မိနစ်ခန့်).")

    with audio.open("rb") as af:
        transcript = client.audio.transcriptions.create(
            model="whisper-1", file=af, response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
    raw = getattr(transcript, "segments", None) or []
    if not raw:
        raise RuntimeError("စကားပြောစာသား မရပါ။ အသံပါတဲ့ Video နဲ့ ပြန်စမ်းပါ။")

    source_lines = []
    for s in raw:
        start = float(s["start"] if isinstance(s, dict) else s.start)
        end = float(s["end"] if isinstance(s, dict) else s.end)
        txt = (s["text"] if isinstance(s, dict) else s.text).strip()
        if txt and end > start:
            source_lines.append({"start": start, "end": end, "en": txt})
    if not source_lines:
        raise RuntimeError("အသံစာသား မရပါ။")

    # Translate each segment into natural, concise spoken Burmese.
    translated = []
    batch_size = 20
    for i in range(0, len(source_lines), batch_size):
        batch = source_lines[i:i+batch_size]
        payload = [{"id": j, "text": x["en"]} for j, x in enumerate(batch)]
        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":"Translate movie narration into natural, conversational spoken Burmese. Use Myanmar script only. Keep each line concise enough for dubbing. Preserve meaning; do not add plot facts. Return only a JSON array of strings in the same order."},
                {"role":"user","content":json.dumps(payload, ensure_ascii=False)}
            ],
            temperature=0.3
        )
        content = result.choices[0].message.content or ""
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.I|re.M).strip()
        try:
            arr = json.loads(content)
        except Exception:
            raise RuntimeError("ဘာသာပြန် AI က JSON မမှန်တဲ့အဖြေ ပြန်ပေးပါတယ်။ နောက်တစ်ကြိမ် ပြန်စမ်းပါ။")
        if not isinstance(arr, list) or len(arr) != len(batch):
            raise RuntimeError("ဘာသာပြန်စာကြောင်းအရေအတွက် မကိုက်ပါ။")
        translated.extend(str(x).strip() for x in arr)

    segments = []
    for item, my_text in zip(source_lines, translated):
        segments.append({"start": item["start"], "end": item["end"], "en": item["en"], "my": my_text or item["en"]})
    _, ass_path = write_subtitles(segments, jobdir)

    # Generate each Burmese voice segment, fit it to its subtitle window, and build a timed narration track.
    voice_parts = []
    cursor = 0.0
    for i, seg in enumerate(segments):
        start, end = seg["start"], seg["end"]
        if start > cursor + 0.03:
            silence = jobdir / f"silence_{i}.wav"
            gap = start - cursor
            run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t",f"{gap:.3f}","-c:a","pcm_s16le",str(silence)])
            voice_parts.append(silence)
        raw_voice = jobdir / f"voice_{i}.mp3"
        wav_voice = jobdir / f"voicefit_{i}.wav"
        asyncio.run(make_voice(seg["my"], raw_voice))
        rawdur = duration_of(raw_voice)
        target = max(0.25, end - start)
        factor = rawdur / target
        # Avoid extreme distortion; keep output duration close to subtitle duration.
        factor = max(0.5, min(2.0, factor))
        run(["ffmpeg","-y","-i",str(raw_voice),"-filter:a",f"{atempo_chain(factor)},apad,atrim=duration={target:.3f}",
             "-ar","24000","-ac","1","-c:a","pcm_s16le",str(wav_voice)])
        voice_parts.append(wav_voice)
        cursor = max(cursor, end)

    narration = jobdir / "narration.wav"
    concat_file = jobdir / "concat.txt"
    with concat_file.open("w", encoding="utf-8") as f:
        for p in voice_parts:
            f.write("file '" + str(p.resolve()).replace("'", "'\\''") + "'\n")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat_file),"-c:a","pcm_s16le",str(narration)])

    out = OUTPUTS / f"recap_{jobdir.name}.mp4"
    # Vertical layout: blurred full-frame background + centered original video.
    # Subtitle file is burned into the exported video.
    vf = ("[0:v]split=2[bg][fg];"
          "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=20:2[blur];"
          "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
          "[blur][front]overlay=(W-w)/2:(H-h)/2,")
    if options.get("zoom", True):
        vf += "scale=1080:1920,"
    ass_escaped = str(ass_path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    vf += f"ass='{ass_escaped}'[v]"
    # -shortest prevents audio extending beyond video; export can be long.
    run(["ffmpeg","-y","-i",str(src),"-i",str(narration),"-filter_complex",vf,
         "-map","[v]","-map","1:a:0","-c:v","libx264","-preset","veryfast","-crf","24",
         "-c:a","aac","-b:a","128k","-shortest","-movflags","+faststart",str(out)])
    return out

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/api/process")
def api_process():
    if "video" not in request.files:
        return jsonify(error="Video ဖိုင်ကို ရွေးပါ။"), 400
    file = request.files["video"]
    if not file.filename:
        return jsonify(error="Video ဖိုင်ကို ရွေးပါ။"), 400
    ext = Path(secure_filename(file.filename)).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error="MP4, MOV, MKV, WEBM, AVI ဖိုင်သာ လက်ခံပါတယ်။"), 400
    jobid = uuid.uuid4().hex[:10]
    jobdir = WORK / jobid
    jobdir.mkdir(parents=True, exist_ok=True)
    src = UPLOADS / f"{jobid}{ext}"
    file.save(src)
    options = {"zoom": request.form.get("zoom") == "on"}
    try:
        out = process_video(src, jobdir, options)
        return jsonify(message="ပြီးပါပြီ။", download=f"/download/{out.name}")
    except Exception as e:
        app.logger.exception("Recap processing failed")
        return jsonify(error=str(e)[:1200]), 500
    finally:
        # Keep job files for debugging and subtitles; remove uploaded source to save space.
        try:
            src.unlink(missing_ok=True)
        except Exception:
            pass

@app.get("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUTS, filename, as_attachment=True)

@app.get("/api/health")
def health():
    return jsonify(status="ok", ffmpeg=shutil.which("ffmpeg") is not None)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
