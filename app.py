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
    # Vivaldi: relentless violin sequences, terraced dynamics, bright continuo snap
    "Vivaldi":     (
        "Solo violin over harpsichord and pizzicato strings, rapid ascending and descending "
        "sequence patterns repeating at different pitches, crisp detached bowing, snapping "
        "continuo bass on every beat, sudden loud-soft contrasts, bright and propulsive, "
        "{key}, {tempo} BPM, no brass, no drums"
    ),

    # Bach: interlocking independent voices, walking bass, ordered inevitability
    "Bach":        (
        "Harpsichord with four independent polyphonic voices weaving around each other, "
        "a subject introduced alone then answered by a second voice, steady walking bass, "
        "ornamental trills on cadences, voices entering one by one, ordered and inevitable, "
        "{key}, {tempo} BPM, no strings, no drums"
    ),

    # Mozart: singing melody over Alberti bass, woodwind dialogue, clean cadences
    "Mozart":      (
        "Piano with singing right-hand melody over steady Alberti bass left hand, "
        "oboe and flute echoing the theme in answer, clear four-bar phrases with question "
        "and response, graceful turn ornaments, bright clean cadences, light and transparent, "
        "{key}, {tempo} BPM"
    ),

    # Beethoven: short rhythmic motif hammered and developed, volcanic contrasts
    "Beethoven":   (
        "Full orchestra with a short insistent rhythmic motif hammered by strings, "
        "sudden silence then fortissimo brass and timpani explosion, theme torn apart "
        "and rebuilt in new keys, relentless driving development, heroic horn calls, "
        "volcanic sudden soft-to-loud surges, {key}, {tempo} BPM"
    ),

    # Chopin: bel canto right hand singing freely, left hand arpeggios as cushion
    "Chopin":      (
        "Solo piano, right hand singing an expressive long-breathed melody with subtle "
        "rhythmic freedom, left hand flowing broken-chord arpeggios spreading warmly "
        "across the keyboard, chromatic inner harmonies that ache and resolve, "
        "intimate and confessional, {key}, {tempo} BPM, no orchestra, no other instruments"
    ),

    # Tchaikovsky: soaring string theme, yearning sequence, climax with brass surge
    "Tchaikovsky": (
        "Strings playing a broad soaring melody that rises and falls with yearning, "
        "sequence pushing higher each repetition toward an emotional peak, cellos carrying "
        "a rich counter-melody below, sudden warm brass chord at the climax, "
        "deeply felt and expressive, {key}, {tempo} BPM, no piano, no drums"
    ),

    # Debussy: cascading piano arpeggios, whole-tone chords dissolving, like light on water
    "Debussy":     (
        "Solo piano, left hand cascading broken arpeggios rising and falling like waves, "
        "right hand pentatonic melody floating delicately above, parallel ninth chords "
        "dissolving into silence, whole-tone scale passages blurring the harmony, "
        "soft sustain pedal throughout, like light shimmering on still water, "
        "{key}, {tempo} BPM, no orchestra, no drums, no violin"
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


def lyria_generate(prompt: str, negative: str) -> bytes:
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

    token = _get_access_token()
    r = req.post(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }, json=payload, timeout=120)

    if r.status_code != 200:
        raise RuntimeError(f"Lyria API {r.status_code}: {r.text[:400]}")

    audio_b64 = r.json()["predictions"][0]["audioContent"]
    return base64.b64decode(audio_b64)


# ──────────────────────────────────────────────────────────
# AUDIO POST-PROCESSING
# ──────────────────────────────────────────────────────────

def wav_to_mp3(wav_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        wav_in   = os.path.join(tmp, "in.wav")
        wav_verb = os.path.join(tmp, "verb.wav")
        mp3_out  = os.path.join(tmp, "out.mp3")

        with open(wav_in, "wb") as f:
            f.write(wav_bytes)

        # SoX reverb
        sox = subprocess.run(
            ["sox", wav_in, wav_verb, "reverb", "28", "55", "85", "100", "0.1"],
            capture_output=True, timeout=60
        )
        src = wav_verb if sox.returncode == 0 else wav_in

        # lame encode
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
        wav_bytes = lyria_generate(lyria_prompt, lyria_negative)

        # Step 4: Post-process to MP3
        mp3_bytes = wav_to_mp3(wav_bytes)
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
