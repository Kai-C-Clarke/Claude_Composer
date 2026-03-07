"""
The Composer — Flask Backend
Lyria 2 (Vertex AI) edition

Pipeline:
  User prompt
  → Confucius (DeepSeek) → JSON interpretation
  → build_lyria_prompt() → Lyria 2 (Vertex AI) → 48kHz WAV
  → SoX reverb → lame MP3
  → base64 JSON response → HTML5 audio player

Env vars required:
  DEEPSEEK_API_KEY           — DeepSeek API key (Confucius)
  GOOGLE_SERVICE_ACCOUNT_JSON — Full JSON string of GCP service account key
  GOOGLE_CLOUD_PROJECT       — GCP project ID  e.g. "composer-ai-12345"
  GOOGLE_CLOUD_LOCATION      — Vertex AI region  e.g. "us-central1"
"""

import os
import json
import base64
import tempfile
import subprocess
import requests as req
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, jsonify
from flask_cors import CORS

import google.auth.transport.requests
from google.oauth2 import service_account


# ──────────────────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)


# ──────────────────────────────────────────────────────────
# CONFUCIUS  (DeepSeek)
# ──────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL     = "https://api.deepseek.com/v1/chat/completions"

CONFUCIUS_SYSTEM = """You are Confucius, Master of interpretation. A student brings you a feeling or intention.
You must translate it into a musical commission for one of seven classical composers.

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "composer":        "Vivaldi|Bach|Mozart|Beethoven|Chopin|Tchaikovsky|Debussy",
  "key":             "D minor" (or any appropriate key),
  "tempo":           120 (integer BPM),
  "mood":            "one word: energetic|dramatic|melancholic|peaceful|joyful|mysterious|triumphant|romantic|contemplative|playful",
  "programme_note":  "Two sentences. What feeling this music will evoke and why this composer was chosen."
}

Composer selection guide (based on musical energy):
- HIGH energy/tempo  → Vivaldi (sequences, fire), Beethoven (drama, power)
- MEDIUM energy      → Bach (intellect, counterpoint), Mozart (elegance, wit)
- LOW energy/tempo   → Chopin (intimate nocturne), Tchaikovsky (sweeping romance), Debussy (impressionist mist)

Do not select the same composer twice in a row. Vary your choices."""


def call_confucius(user_prompt: str) -> dict:
    payload = {
        "model": "deepseek-chat",
        "temperature": 0.5,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": CONFUCIUS_SYSTEM},
            {"role": "user",   "content": user_prompt}
        ]
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json"
    }
    r = req.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


# ──────────────────────────────────────────────────────────
# LYRIA PROMPT BUILDER
# ──────────────────────────────────────────────────────────

LYRIA_STYLE_PROMPTS = {
    # Vivaldi: bright, darting, relentless forward motion
    "Vivaldi":     (
        "Bright solo violin darting through rapid repeated figures over plucked strings and harpsichord, "
        "crisp and energetic, sudden shifts between loud and soft, sparkling and propulsive, "
        "baroque chamber ensemble, {key}, {tempo} BPM"
    ),

    # Bach: orderly voices in conversation, inevitably interlocking
    "Bach":        (
        "Harpsichord with several independent melodic lines weaving around each other in strict order, "
        "a theme introduced then answered, walking bass below, ornamented and precise, "
        "baroque keyboard, {key}, {tempo} BPM"
    ),

    # Mozart: singing and elegant, light and transparent
    "Mozart":      (
        "Piano with a clear singing melody, light string accompaniment, woodwind echoes, "
        "balanced and elegant phrases, graceful and transparent, classical chamber style, "
        "{key}, {tempo} BPM"
    ),

    # Beethoven: stormy, forceful, dramatic silences and outbursts
    "Beethoven":   (
        "Full orchestra with driving strings, sudden dramatic silences followed by powerful brass and timpani, "
        "forceful and stormy, heroic and determined, building to overwhelming climaxes, "
        "{key}, {tempo} BPM"
    ),

    # Chopin: intimate solo piano, freely breathing melody, rich harmony
    "Chopin":      (
        "Solo piano with a freely breathing singing melody in the right hand, "
        "rich flowing accompaniment in the left hand spreading warmly, "
        "intimate and expressive, romantic and personal, {key}, {tempo} BPM"
    ),

    # Tchaikovsky: sweeping string melody rising with yearning intensity
    "Tchaikovsky": (
        "Strings playing a broad sweeping melody that rises with deep feeling, "
        "rich cello counter-melody beneath, warm and yearning, building to an emotional peak "
        "with full orchestra, deeply expressive, {key}, {tempo} BPM"
    ),

    # Debussy: hazy, shimmering, dissolving harmonies, like mist or water
    "Debussy":     (
        "Solo piano with a delicate floating melody over soft rippling accompaniment, "
        "harmonies that blur and dissolve without resolving, hazy and shimmering, "
        "like light on water or mist in the morning, gentle and atmospheric, "
        "{key}, {tempo} BPM"
    ),
}

MOOD_MAP = {
    "energetic":     "energetic, driving, vital, spirited",
    "dramatic":      "dramatic, intense, powerful, fierce",
    "melancholic":   "melancholic, wistful, tender, sorrowful",
    "peaceful":      "peaceful, serene, calm, tranquil",
    "joyful":        "joyful, bright, celebratory, cheerful",
    "mysterious":    "mysterious, shadowy, intriguing, veiled",
    "triumphant":    "triumphant, heroic, majestic, glorious",
    "romantic":      "romantic, expressive, passionate, yearning",
    "contemplative": "contemplative, reflective, introspective, meditative",
    "playful":       "playful, light, sprightly, witty",
}


LYRIA_NEGATIVE_PROMPTS = {
    "Vivaldi":     "vocals, singing, piano, drums, electronic, synthesizer, electric guitar, pop, modern, brass",
    "Bach":        "vocals, singing, drums, electronic, synthesizer, electric guitar, pop, modern, orchestra, brass",
    "Mozart":      "vocals, singing, drums, electronic, synthesizer, electric guitar, pop, modern, heavy brass",
    "Beethoven":   "vocals, singing, electronic, synthesizer, electric guitar, pop, modern, jazz",
    "Chopin":      "vocals, singing, drums, electronic, synthesizer, electric guitar, pop, modern, orchestra, violin, trumpet",
    "Tchaikovsky": "vocals, singing, drums, electronic, synthesizer, electric guitar, pop, modern, jazz, piano",
    "Debussy":     "vocals, singing, drums, electronic, synthesizer, electric guitar, pop, modern, trumpet, trombone, violin, orchestra",
}


def build_lyria_prompt(c: dict) -> tuple:
    composer = c.get("composer", "Mozart")
    key      = c.get("key", "C major")
    tempo    = c.get("tempo", 120)
    mood     = c.get("mood", "expressive").lower()

    style    = LYRIA_STYLE_PROMPTS.get(composer, LYRIA_STYLE_PROMPTS["Mozart"])
    style    = style.format(key=key, tempo=tempo)
    mood_str = MOOD_MAP.get(mood, mood)

    prompt = f"{style}, {mood_str}, instrumental"

    negative = LYRIA_NEGATIVE_PROMPTS.get(composer, "vocals, singing, drums, electronic, synthesizer, electric guitar, pop, modern")

    return prompt, negative


# ──────────────────────────────────────────────────────────
# LYRIA API
# ──────────────────────────────────────────────────────────

def _get_access_token() -> str:
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set")
    sa_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _lyria_single(prompt: str, negative: str) -> bytes:
    """Single Lyria API call — returns raw WAV bytes."""
    project  = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var not set")

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/lyria-002:predict"
    )

    payload = {
        "instances": [{"prompt": prompt, "negative_prompt": negative}],
        "parameters": {}
    }

    last_error = None
    for attempt in range(3):
        if attempt > 0:
            import time
            time.sleep(4 * attempt)

        token = _get_access_token()
        r = req.post(url, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }, json=payload, timeout=120)

        if r.status_code == 200:
            resp = r.json()
            pred = resp["predictions"][0]
            audio_b64 = (
                pred.get("audioContent")
                or pred.get("bytesBase64Encoded")
                or pred.get("audio", {}).get("content")
            )
            if not audio_b64:
                raise RuntimeError(f"Unexpected Lyria response keys: {list(pred.keys())}")
            return base64.b64decode(audio_b64)

        last_error = f"Lyria API {r.status_code}: {r.text[:400]}"
        if r.status_code != 503:
            break

    raise RuntimeError(last_error)


def lyria_generate(prompt: str, negative: str) -> tuple:
    """
    Fire two Lyria calls in parallel, return (wav1_bytes, wav2_bytes).
    Same prompt = same key/style — safe to splice together.
    Total wait = one generation, not two.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_lyria_single, prompt, negative)
        f2 = pool.submit(_lyria_single, prompt, negative)
        wav1 = f1.result()
        wav2 = f2.result()
    return wav1, wav2


# ──────────────────────────────────────────────────────────
# AUDIO POST-PROCESSING
# ──────────────────────────────────────────────────────────

def find_loop_point(wav_path: str, tempo: int) -> float:
    """
    Scan bar boundaries in the WAV and return the one with the lowest
    RMS energy — most likely a phrase breath / cadence point.
    Looks only in bars 8..24 so we get a musically useful segment length.
    Returns loop point in seconds.
    """
    import wave as wavemod
    import struct
    import math

    bar_secs   = (60.0 / max(tempo, 40)) * 4   # one 4/4 bar
    window     = 0.08                            # RMS window around each boundary (seconds)

    with wavemod.open(wav_path, 'rb') as wf:
        rate      = wf.getframerate()
        channels  = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames  = wf.getnframes()
        raw       = wf.readframes(n_frames)

    # Unpack to signed integers
    fmt      = {1: 'b', 2: 'h', 4: 'i'}.get(sampwidth, 'h')
    samples  = struct.unpack(f'<{len(raw)//sampwidth}{fmt}', raw)
    # Mono-mix if stereo
    if channels > 1:
        samples = [sum(samples[i:i+channels])//channels
                   for i in range(0, len(samples), channels)]

    total_secs = len(samples) / rate
    win_frames = int(window * rate)

    best_pos   = bar_secs * 16   # fallback: 16 bars
    best_rms   = float('inf')

    bar = 8
    while bar <= 24:
        pos_secs = bar * bar_secs
        if pos_secs + window >= total_secs:
            break
        centre = int(pos_secs * rate)
        lo     = max(0, centre - win_frames // 2)
        hi     = min(len(samples), lo + win_frames)
        chunk  = samples[lo:hi]
        if chunk:
            rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
            if rms < best_rms:
                best_rms = rms
                best_pos = pos_secs
        bar += 1

    return best_pos


def wav_to_mp3(wav_bytes: bytes, wav_bytes2: bytes = None, tempo: int = 120) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        wav_in1  = os.path.join(tmp, "in1.wav")
        wav_in2  = os.path.join(tmp, "in2.wav")
        wav_seg1 = os.path.join(tmp, "seg1.wav")
        wav_seg2 = os.path.join(tmp, "seg2.wav")
        wav_join = os.path.join(tmp, "join.wav")
        wav_verb = os.path.join(tmp, "verb.wav")
        mp3_out  = os.path.join(tmp, "out.mp3")

        cf_secs  = 0.25
        fade_out = 3.0

        with open(wav_in1, "wb") as f:
            f.write(wav_bytes)

        # ── 1. Find RMS phrase-end in clip 1 ─────────────────
        end1 = find_loop_point(wav_in1, tempo)
        subprocess.run(
            ["sox", wav_in1, wav_seg1, "trim", "0", str(end1)],
            capture_output=True, timeout=30
        )
        seg1 = wav_seg1 if os.path.exists(wav_seg1) else wav_in1

        # ── 2. Find RMS phrase-start in clip 2 ───────────────
        if wav_bytes2:
            with open(wav_in2, "wb") as f:
                f.write(wav_bytes2)
            # Trim FROM the quietest point so clip 2 begins at a breath
            start2 = find_loop_point(wav_in2, tempo)
            subprocess.run(
                ["sox", wav_in2, wav_seg2, "trim", str(start2)],
                capture_output=True, timeout=30
            )
            seg2 = wav_seg2 if os.path.exists(wav_seg2) else wav_in2
        else:
            seg2 = None

        # ── 3. Splice the two segments ────────────────────────
        if seg2:
            splice_cmd = [
                "sox", seg1, seg2, wav_join,
                "splice", "-q", f"{end1},{cf_secs}"
            ]
            result = subprocess.run(splice_cmd, capture_output=True, timeout=60)
            joined = wav_join if result.returncode == 0 else seg1
        else:
            joined = seg1

        # ── 4. Pad silence at start + reverb + fade out ──────
        sox_verb = subprocess.run(
            ["sox", joined, wav_verb,
             "pad", "1.5", "0",
             "reverb", "28", "55", "85", "100", "0.1",
             "fade", "t", "0", "0", str(fade_out)],
            capture_output=True, timeout=60
        )
        src = wav_verb if sox_verb.returncode == 0 else joined

        # ── 5. Encode to MP3 ──────────────────────────────────
        lame = subprocess.run(
            ["lame", "-b", "192", "-q", "2", src, mp3_out],
            capture_output=True, timeout=60
        )
        if lame.returncode != 0:
            raise RuntimeError(f"lame: {lame.stderr.decode()}")

        with open(mp3_out, "rb") as f:
            return f.read()


# ──────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "engine": "lyria-002"})


@app.route("/compose", methods=["POST"])
def compose():
    data = request.get_json(force=True)
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided"}), 400

    try:
        # Step 1: Confucius interprets
        confucius = call_confucius(user_prompt)

        # Step 2: Build Lyria prompt
        lyria_prompt, lyria_negative = build_lyria_prompt(confucius)

        # Step 3: Generate music
        wav1, wav2 = lyria_generate(lyria_prompt, lyria_negative)

        # Step 4: Post-process — splice two generations, reverb, fade, encode
        mp3_bytes = wav_to_mp3(wav1, wav_bytes2=wav2, tempo=confucius.get("tempo", 120))
        mp3_b64   = base64.b64encode(mp3_bytes).decode()

        return jsonify({
            "success":        True,
            "mp3":            mp3_b64,
            "composer":       confucius.get("composer"),
            "key":            confucius.get("key"),
            "tempo":          confucius.get("tempo"),
            "mood":           confucius.get("mood"),
            "programme_note": confucius.get("programme_note", ""),
            "lyria_prompt":   lyria_prompt,   # shown in UI for transparency
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
