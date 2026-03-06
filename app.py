import os, re, subprocess, tempfile, base64, json, requests, random
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app)

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-44c5721e2b254942b2c208e052a3fc57')
SOUNDFONT = os.environ.get('SOUNDFONT', '/usr/share/sounds/sf2/FluidR3_GM.sf2')

CONFUCIUS_SYSTEM = """You are Confucius, the Master Voice of The Composer.
You interpret a user's feeling or mood and select the right composer and musical parameters.

Match ENERGY LEVEL first, then character:

HIGH ENERGY (fire, dancing, celebration, triumph, storms, battle, joy, excitement, flags, wind, waves):
- Vivaldi: driving sequences, rapid notes, bright, unstoppable forward motion
- Beethoven: dramatic power, motivic force, sudden silences, heroic struggle

MEDIUM ENERGY (walking, flowing, conversation, curiosity, elegance, narrative):
- Bach: contrapuntal, walking bass, intellectual, ordered
- Mozart: singing melody, Alberti bass, elegant, balanced, graceful

LOW ENERGY (melancholy, longing, dreams, night, twilight, memory, grief, love, solitude):
- Chopin: nocturne, bel canto, chromatic, ornamental, intimate
- Tchaikovsky: sweeping lyrical, passionate, emotional, romantic yearning
- Debussy: impressionist, floating, atmospheric, colour without narrative

EXAMPLES:
"fire, dancers, chanting" -> Vivaldi, minor, fast (120-132)
"flag flying, storm, waves" -> Vivaldi, minor, fast (126-132)
"village celebration" -> Vivaldi, major, fast (116-132)
"triumphant homecoming" -> Beethoven, major, strong (96-112)
"lonely autumn evening" -> Chopin, minor, slow (60-72)
"gentle morning light" -> Debussy, major, slow (60-76)
"deep grief" -> Chopin or Tchaikovsky, minor, slow (54-66)
"intellectual puzzle" -> Bach, minor, moderate (84-96)

Output ONLY a JSON object, no markdown:
{
  "composer": "Vivaldi",
  "key": "Dm",
  "tempo": 126,
  "mood": "fierce and exhilarating, like flames rising",
  "programme_note": "Two or three sentences in Confucius voice — poetic, oblique, wise."
}

Keys: minor (Cm, Dm, Gm, Am, Em) for dark/fierce/sad; major (C, D, F, G, Bb) for bright/joyful
Tempo: 54-72 slow, 76-96 moderate, 100-116 lively, 120-144 fast"""


STYLE_MAPS = {
    "Bach": """STYLE — BACH:
V:1 melody: sequences (repeat pattern a step up/down), motor eighth notes, stepwise with 3rd/4th leaps
V:2 bass: walking bass — stepwise, as melodic as right hand, contrary motion, eighth notes throughout
Harmony: modulate to dominant or relative, seventh chords by step, suspensions (4-3, 7-6)
Rhythm: continuous eighth notes in bass, strict time, terraced dynamics
AVOID: Alberti bass, waltz patterns, chromaticism, sentimentality""",

    "Mozart": """STYLE — MOZART:
V:1 melody: singing, graceful, 4-bar question/answer, peak at bar 3, one ornament per phrase
V:2 bass: Alberti bass — low note then chord: C,2 G,2 E,2 G,2 — light throughout
Harmony: diatonic I-IV-V-vi, clear cadences, modulate to dominant for B section
Rhythm: quarters and eighths, at least one dotted rhythm per phrase
AVOID: chromaticism, sforzandi, anything effortful""",

    "Beethoven": """STYLE — BEETHOVEN:
V:1 melody: short motivic cell (2-4 notes), transposed up/down, dramatic leaps, rests as drama
V:2 bass: heavy block chords on strong beats, octave bass notes for power, sforzando accents
Harmony: subito pp after ff, diminished sevenths, unexpected key changes
Rhythm: dotted rhythms, at least one bar of silence (z8), accents on weak beats
AVOID: long lyrical lines, gentle motion, ornamental decoration""",

    "Chopin": """STYLE — CHOPIN:
V:1 melody: long arching bel canto lines, chromatic passing notes, trill (!trill!), grace notes, dotted rhythms
V:2 bass: NOCTURNE BASS — deep bass note (2 units) then mid-register chord (6 units) per bar
  Correct example: C,,2 (EGc)6 | G,,2 (DGb)6 | F,,2 (FAc)6 | G,,2 (GBd)6 |
  NEVER use Alberti bass or walking bass for Chopin
Harmony: chromatic inner voices, Neapolitan chord, delayed resolution
Rhythm: expressively varied — mix 3+1+2+2, 4+2+2 patterns; never metronomic
AVOID: Alberti bass, walking bass, mechanical motion, block chords in melody""",

    "Debussy": """STYLE — DEBUSSY:
V:1 melody: pentatonic or whole-tone scale, long held notes (4-8 units), silence (z), no strong arrival
V:2 bass: parallel chord blocks sliding by step, sustained pedal notes (4-8 units)
Harmony: parallel ninth chords, NO dominant-tonic resolution, colour not function
Rhythm: long values dominate, no strong beat-1 accent
AVOID: diatonic runs, rhythmic drive, clear cadences, Alberti bass""",

    "Tchaikovsky": """STYLE — TCHAIKOVSKY:
V:1 melody: sweeping arching lines, soar then sigh downward (e2 d2 c2), climax at bar 5-6
V:2 bass: sustained half-note chords — two chords per bar, inner voice movement between them
  Correct example: (DFA)4 (EGB)4 | (CEG)4 (DFA)4 | — warm, rich, sustained
Harmony: diminished seventh, augmented sixth, sequence a step lower for yearning
Rhythm: lyrical and unhurried, long values at phrase peaks
AVOID: short motivic cells, mechanical regularity, harsh dissonance""",

    "Vivaldi": """STYLE — VIVALDI:
V:1 melody: sequences — same pattern repeated a step up/down (D E F A | E F G B | F G A c)
  Use rapid eighth notes throughout. Use dotted rhythms for energy.
  ARPEGGIATE chords by writing notes SEQUENTIALLY, never as brackets:
  WRONG: (DFA)4  ← block chord, forbidden ✗
  CORRECT: D2 F2 A2 d2  ← broken arpeggio, ascending ✓
  CORRECT: d2 A2 F2 D2  ← broken arpeggio, descending ✓
  Never hold a note longer than 2 units in fast passages.

V:2 bass: DRIVING ALTERNATING BASS — alternate between root note and chord, every 2 units:
  Correct example bar in Dm: D,2 (DFA)2 D,2 (DFA)2 |
  Correct example bar in Am: A,,2 (ACE)2 A,,2 (ACE)2 |
  Correct example bar in F:  F,,2 (FAC)2 F,,2 (FAC)2 |
  The bass root is 2 units, the chord is 2 units, alternating. Total per bar = 8. Always.

Harmony: chord changes every bar or half-bar, clear I-V-i-IV, circle of fifths sequences
Rhythm: relentless eighth-note pulse in both voices, NO held notes, NO hesitation
AVOID: bracket chords (DFA) in melody, held notes over 2 units, lyrical passages, chromaticism"""
}

RELATIVES = {
    "Cm":"Eb","Gm":"Bb","Dm":"F","Am":"C","Em":"G","Bm":"D",
    "Fm":"Ab","Bbm":"Db","C":"Am","G":"Em","D":"Bm","A":"F#m",
    "F":"Dm","Bb":"Gm","Eb":"Cm","Ab":"Fm","E":"C#m","B":"G#m"
}

# Scale notes for each key — used to scrub bum notes from MIDI
KEY_SCALES = {
    "Dm": [2,5,7,9,0,2,4],    # D E F G A Bb C  (D natural minor)
    "Cm": [0,2,3,5,7,8,10],   # C D Eb F G Ab Bb
    "Gm": [7,9,10,0,2,3,5],   # G A Bb C D Eb F
    "Am": [9,11,0,2,4,5,7],   # A B C D E F G
    "Em": [4,6,7,9,11,0,2],   # E F# G A B C D
    "Bm": [11,1,2,4,6,7,9],   # B C# D E F# G A
    "C":  [0,2,4,5,7,9,11],   # C D E F G A B
    "G":  [7,9,11,0,2,4,6],   # G A B C D E F#
    "D":  [2,4,6,7,9,11,1],   # D E F# G A B C#
    "F":  [5,7,9,10,0,2,4],   # F G A Bb C D E
    "Bb": [10,0,2,3,5,7,9],   # Bb C D Eb F G A
    "Eb": [3,5,7,8,10,0,2],   # Eb F G Ab Bb C D
    "Ab": [8,10,0,1,3,5,7],   # Ab Bb C Db Eb F G
}


def build_brief(composer, key, tempo, mood):
    style = STYLE_MAPS.get(composer, STYLE_MAPS["Chopin"])
    key_b = RELATIVES.get(key, "F")
    return f"""Compose a ternary form piece (ABA') with coda in the style of {composer}.
Mood: {mood}

Section A: 8 bars, K:{key}, Q:1/4={tempo}
Section B: 8 bars, K:{key_b}, contrasting character
Section A': 8 bars, K:{key}, return embellished
Coda: 4 bars, dissolving descent

{style}

══ FORMAT — FOLLOW EXACTLY OR THE MUSIC WILL NOT PLAY ══

Use this exact structure:
X:1
T:Title
M:4/4
L:1/8
Q:1/4={tempo}
K:{key}
V:1 clef=treble name="Melody"
%%MIDI channel 1
%%MIDI program 0
[ALL 28 bars of Voice 1 here]
V:2 clef=bass name="Bass"
%%MIDI channel 2
%%MIDI program 0
[ALL 28 bars of Voice 2 here]

ABSOLUTE RULES:
1. Voice 1 ALL 28 bars first. Then Voice 2 ALL 28 bars. NEVER interleave.
2. Voice 1: ONE note at a time. Never (G4 c4). Write: G2 c2 A2 F2
3. Every bar = exactly 8 units. eighth=1, quarter=2, dotted-quarter=3, half=4
   WARNING: note/ = half length. Use whole note names only: D2 not D/
   WRONG: D3 E/ F2 G2 = 7.5 units  CORRECT: D3 E F2 G2 = 8 units
4. Voice 2 must have exactly 28 bars. Never empty.
5. Mix note lengths in melody — never all quarter notes.
6. Dynamics in Voice 1 only, in double quotes: "ff" at start for Vivaldi

Output ONLY ABC notation. No explanation. No markdown. Start with X:1"""


def call_deepseek(messages, system=None, temperature=0.7, max_tokens=3500):
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages
    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                 "Content-Type": "application/json"},
        json=payload, timeout=90
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def postprocess_midi(mid_path, out_path, key="Dm", composer="Vivaldi"):
    """
    Apply per-channel velocity shaping, timing humanisation,
    and chromatic note scrubbing to snap out-of-key notes to scale.
    """
    try:
        import mido

        # Scale pitch classes allowed for this key
        allowed_pcs = set(KEY_SCALES.get(key, KEY_SCALES["Dm"]))
        # For minor keys allow raised 7th (harmonic minor) too
        minor_keys = {"Dm","Cm","Gm","Am","Em","Bm","Fm","Bbm"}
        if key in minor_keys:
            root = KEY_SCALES[key][0]
            raised_7 = (root - 2) % 12
            allowed_pcs.add(raised_7)

        mid = mido.MidiFile(mid_path)
        out = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat, type=mid.type)

        tpb = mid.ticks_per_beat  # ticks per quarter note
        # For timing humanisation: jitter in ticks
        # At 132bpm, one eighth = tpb/2 ticks. Jitter ±5% of eighth = small but audible
        eighth_ticks = tpb // 2

        for track_idx, track in enumerate(mid.tracks):
            new_track = mido.MidiTrack()
            out.tracks.append(new_track)
            note_idx = 0

            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    ch = msg.channel
                    pitch = msg.note
                    pc = pitch % 12

                    # ── Pitch correction: snap out-of-key notes ──
                    if pc not in allowed_pcs:
                        # Try semitone down first, then up
                        if (pc - 1) % 12 in allowed_pcs:
                            pitch = pitch - 1
                        elif (pc + 1) % 12 in allowed_pcs:
                            pitch = pitch + 1
                        pitch = max(21, min(108, pitch))

                    # ── Velocity shaping ──
                    if ch == 0:  # melody
                        # Phrase shape: accent beat 1 of each bar, swell mid-phrase
                        phrase_pos = (note_idx % 16) / 16.0
                        shape = 1.0 - abs(phrase_pos - 0.45) * 0.5
                        # Beat accent: every 4 notes ≈ one bar at eighth pulse
                        beat_accent = 12 if (note_idx % 4 == 0) else 0
                        base_vel = int(72 + shape * 18) + beat_accent
                        vel = max(55, min(105, base_vel + random.randint(-8, 8)))
                        # Timing: slight push on beat 1, slight lag mid-bar
                        if note_idx % 4 == 0:
                            time_jitter = random.randint(-5, 3)   # slightly early on beat
                        else:
                            time_jitter = random.randint(-10, 12) # more expressive elsewhere
                    else:  # bass
                        # Bass: steady, slightly quieter, accent on root notes
                        is_root = (note_idx % 2 == 0)  # alternating root/chord pattern
                        base_vel = 58 if is_root else 48
                        vel = max(38, min(68, base_vel + random.randint(-5, 5)))
                        time_jitter = random.randint(-4, 4)  # minimal bass jitter

                    note_idx += 1
                    new_time = max(0, msg.time + time_jitter)
                    new_track.append(msg.copy(note=pitch, velocity=vel, time=new_time))

                elif msg.type == 'note_off':
                    new_track.append(msg)
                else:
                    new_track.append(msg)

        out.save(out_path)
        return True
    except Exception as e:
        return False


def clean_abc(abc_text):
    lines = []
    for line in abc_text.split('\n'):
        if line.strip().startswith('```'): continue
        if '%%MIDI pedal' in line: continue
        lines.append(line)
    return '\n'.join(lines)


def abc_to_mp3(abc_text, key="Dm", composer="Vivaldi"):
    with tempfile.TemporaryDirectory() as d:
        abc_f     = os.path.join(d, 'piece.abc')
        mid_f     = os.path.join(d, 'piece.mid')
        mid_pp_f  = os.path.join(d, 'piece_pp.mid')
        wav_f     = os.path.join(d, 'piece.wav')
        wav_rev_f = os.path.join(d, 'piece_reverb.wav')
        mp3_f     = os.path.join(d, 'piece.mp3')

        with open(abc_f, 'w') as f:
            f.write(clean_abc(abc_text))

        r = subprocess.run(['abc2midi', abc_f, '-o', mid_f],
                           capture_output=True, text=True, timeout=30)
        if not os.path.exists(mid_f):
            raise RuntimeError(f"abc2midi: {r.stderr[:400]}")

        # Post-process MIDI: pitch correction + velocity + humanisation
        if postprocess_midi(mid_f, mid_pp_f, key=key, composer=composer) \
                and os.path.exists(mid_pp_f):
            render_mid = mid_pp_f
        else:
            render_mid = mid_f

        r = subprocess.run(['fluidsynth', '-ni', '-F', wav_f, '-r', '44100',
                            SOUNDFONT, render_mid],
                           capture_output=True, text=True, timeout=60)
        if not os.path.exists(wav_f):
            raise RuntimeError(f"fluidsynth: {r.stderr[:400]}")

        # Reverb
        subprocess.run(['sox', wav_f, wav_rev_f,
                        'reverb', '28', '55', '85', '100', '0.1'],
                       capture_output=True, timeout=30)
        render_wav = wav_rev_f if os.path.exists(wav_rev_f) else wav_f

        # MP3
        r = subprocess.run(['lame', '-b', '192', '-q', '2', render_wav, mp3_f],
                           capture_output=True, text=True, timeout=30)
        if not os.path.exists(mp3_f):
            raise RuntimeError(f"lame: {r.stderr[:300]}")

        with open(mp3_f, 'rb') as f:
            return base64.b64encode(f.read()).decode()


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/compose', methods=['POST'])
def compose():
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400
    raw = ''
    try:
        raw = call_deepseek([{"role": "user", "content": prompt}],
                            system=CONFUCIUS_SYSTEM, temperature=0.5)
        json_text = re.sub(r'```json|```', '', raw).strip()
        interp = json.loads(json_text)

        composer = interp.get('composer', 'Chopin')
        key      = interp.get('key', 'Cm')
        tempo    = interp.get('tempo', 66)
        mood     = interp.get('mood', 'reflective')
        note     = interp.get('programme_note', '')

        brief = build_brief(composer, key, tempo, mood)
        abc = call_deepseek([{"role": "user", "content": brief}],
                            temperature=0.6, max_tokens=3500)
        abc = re.sub(r'```abc|```', '', abc).strip()

        mp3 = abc_to_mp3(abc, key=key, composer=composer)

        return jsonify({'abc': abc, 'mp3': mp3, 'composer': composer,
                        'key': key, 'tempo': tempo, 'mood': mood,
                        'programme_note': note})

    except json.JSONDecodeError:
        return jsonify({'error': 'Confucius could not parse the mood', 'raw': raw}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
