"""Audio capture, sound styles, the built-in Windows voice and streaming text-to-speech."""
from .core import *
from .system import *

class Recorder:
    def __init__(s):
        s.stream = None; s.chunks = []; s.level = 0.0; s.spoke = False; s.last_voice = 0; s.t0 = 0

    def start(s):
        s.chunks = []; s.spoke = False; s.level = 0.0; s.t0 = s.last_voice = time.time()

        def cb(data, frames, t, status):
            s.chunks.append(data.copy())
            rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2))) / 32768
            s.level = min(1.0, rms * 8)
            if rms > 0.015: s.spoke = True; s.last_voice = time.time()
        s.stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=cb)
        s.stream.start()

    def stop(s):
        if s.stream: s.stream.stop(); s.stream.close(); s.stream = None
        s.level = 0.0
        if not s.chunks or not s.spoke: return None
        pcm = np.concatenate(s.chunks); buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm.tobytes())
        return buf.getvalue()


# ---------- voice: styles, personalities, built-in voice (no key) ----------
VOICE_STYLES = {   # rate = pitch/speed factor (resampling), fx = character effect, sapi = speaking-speed offset of the built-in voice
    "natural":    dict(label="Natural",         desc="Your system's normal voice",            rate=1.0,  fx=None,          sapi=0),
    "chipmunk":   dict(label="Chipmunk",        desc="Tiny, fast and squeaky",                rate=1.55, fx=None,          sapi=1),
    "giant":      dict(label="Deep giant",      desc="Slow, rumbling and enormous",           rate=0.72, fx=None,          sapi=-1),
    "robot":      dict(label="Robot",           desc="Buzzy metallic android",                rate=1.0,  fx="robot",       sapi=0),
    "alien":      dict(label="Alien",           desc="Warbly visitor from another galaxy",    rate=1.2,  fx="alien",       sapi=0),
    "grandpa":    dict(label="Wobbly grandpa",  desc="Slow, shaky and very wise",             rate=0.88, fx="wobble",      sapi=-2),
    "squirrel":   dict(label="Hyper squirrel",  desc="Way too much coffee",                   rate=1.35, fx="wobble_fast", sapi=3),
    "haunted":    dict(label="Haunted hallway", desc="Deep and echoing",                      rate=0.85, fx="echo",        sapi=-1),
    "megaphone":  dict(label="Megaphone",       desc="Loud, crunchy and official",            rate=1.0,  fx="megaphone",   sapi=0),
    "underwater": dict(label="Underwater",      desc="Blub blub, muffled and wavy",           rate=0.95, fx="underwater",  sapi=0),
}
PERSONAS = {      # wording only: never changes accuracy or what the assistant reports about its actions
    "default": ("Friendly (default)", ""),
    "pirate":  ("Pirate", "Speak like a cheerful pirate (arr, matey), lightly."),
    "butler":  ("Posh butler", "Speak like a refined, slightly dry British butler."),
    "coach":   ("Hype coach", "Speak like an upbeat sports coach cheering the user on."),
    "wizard":  ("Grumpy wizard", "Speak like a grumpy but kind old wizard."),
    "zen":     ("Calm zen guide", "Speak slowly and calmly like a gentle meditation guide."),
    "robot":   ("Deadpan robot", "Speak like a deadpan, literal-minded robot, with dry humour."),
    "noir":    ("Noir detective", "Speak like a hard-boiled noir detective narrating the case."),
}


class VoiceFX:
    """Per-sentence audio post-processing (int16 mono PCM in/out): pitch/speed by resampling, then a character effect."""
    def __init__(s, style, in_rate, out_rate=24000):
        st = VOICE_STYLES.get(style) or VOICE_STYLES["natural"]
        s.fx = st["fx"]; s.step = (in_rate / out_rate) * st["rate"]; s.sr = out_rate     # input samples consumed per output sample
        s.prev = None; s.frac = 0.0; s.n = 0; s.hist = np.zeros(48, dtype=np.float32); s.echo = np.zeros(int(out_rate * 0.22), dtype=np.float32)

    def _vib(s, y, hz, depth):
        H = s.hist.size; buf = np.concatenate((s.hist, y)); t = (s.n + np.arange(y.size)) / s.sr
        out = np.interp(np.arange(y.size) + H - depth * (1 + np.sin(2 * np.pi * hz * t)), np.arange(buf.size), buf)
        s.hist = buf[-H:]; return out

    def _effect(s, y):
        t = (s.n + np.arange(y.size)) / s.sr; f = s.fx
        if f == "robot": y = 0.2 * y + 1.1 * y * np.sin(2 * np.pi * 55 * t)
        elif f == "alien": y = s._vib(y, 6.0, 10) * (0.55 + 0.45 * np.sin(2 * np.pi * 95 * t)) * 1.3
        elif f == "wobble": y = s._vib(y, 5.5, 9)
        elif f == "wobble_fast": y = s._vib(y, 9.0, 5)
        elif f == "echo":
            d = s.echo.size; out = np.empty_like(y); i = 0
            while i < y.size:          # blocks no longer than the delay: feedback always comes from finished output
                m = min(d, y.size - i); out[i:i + m] = y[i:i + m] + 0.45 * s.echo[:m]; s.echo = np.concatenate((s.echo[m:], out[i:i + m])); i += m
            y = out * 0.85
        elif f == "megaphone": y = np.tanh(3.0 * (y - np.convolve(y, np.ones(24) / 24, "same"))) * 0.8
        elif f == "underwater": y = s._vib(np.convolve(y, np.ones(14) / 14, "same"), 2.2, 18) * 1.6
        s.n += y.size; return y

    def process(s, pcm):
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if x.size == 0: return b""
        if s.prev is not None: x = np.concatenate((s.prev, x))
        idx = np.arange(s.frac, len(x) - 1, s.step)
        if idx.size: y = np.interp(idx, np.arange(len(x)), x).astype(np.float32); s.frac = idx[-1] + s.step - (len(x) - 1)
        else: y = x[:0]; s.frac -= len(x) - 1
        s.prev = x[-1:]
        if y.size and s.fx: y = s._effect(y.astype(np.float32)).astype(np.float32)
        return (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()


def _b64(x): return base64.b64encode(str(x).encode("utf-8")).decode("ascii")


class SapiEngine:
    """Windows' own text-to-speech (System.Speech) via one long-lived PowerShell helper: no API key, works offline, fast after warm-up."""
    SCRIPT = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
function D($x){ [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($x)) }
[Console]::Out.WriteLine('READY'); [Console]::Out.Flush()
while(($l=[Console]::In.ReadLine()) -ne $null){
  try{
    if($l -eq 'LIST'){ [Console]::Out.WriteLine('VOICES '+(($s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -join '|')); [Console]::Out.Flush(); continue }
    $p=$l.Split('|'); $s.Rate=[int]$p[0]
    if($p[1] -ne ''){ try{ $s.SelectVoice((D $p[1])) }catch{} }
    $s.SetOutputToWaveFile((D $p[2])); $s.Speak((D $p[3])); $s.SetOutputToNull()
    [Console]::Out.WriteLine('OK')
  }catch{ [Console]::Out.WriteLine('ERR '+$_.Exception.Message) }
  [Console]::Out.Flush()
}"""

    def __init__(s): s.p = None; s.lock = threading.Lock(); s._voices = None

    def available(s): return sys.platform == "win32"

    def _start(s):
        enc = base64.b64encode(s.SCRIPT.encode("utf-16-le")).decode()
        s.p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        if b"READY" not in s.p.stdout.readline(): raise RuntimeError("the Windows speech helper did not start")

    def _talk(s, line):
        if s.p is None or s.p.poll() is not None: s._start()
        wd = threading.Timer(25, lambda: s.p and s.p.kill()); wd.start()       # a hung helper must never freeze speech forever
        try:
            s.p.stdin.write((line + "\n").encode("ascii")); s.p.stdin.flush()
            return s.p.stdout.readline().decode("utf-8", "replace").strip()
        finally: wd.cancel()

    def warm(s):
        try:
            with s.lock:
                if s.p is None: s._start()
        except Exception: pass

    def voices(s):
        if s._voices is None:
            try:
                with s.lock: r = s._talk("LIST")
                s._voices = [v for v in r[7:].split("|") if v] if r.startswith("VOICES") else []
            except Exception: s._voices = []
        return s._voices

    def synth(s, text, rate=0, voice=""):
        """-> (mono int16 PCM bytes, sample rate)."""
        fd, path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        try:
            voice = voice if voice and "|" not in voice else ""
            with s.lock: r = s._talk(f"{max(-10, min(10, int(rate)))}|{_b64(voice) if voice else ''}|{_b64(path)}|{_b64(text[:700])}")
            if not r.startswith("OK"): raise RuntimeError(r[4:] or "the Windows voice returned nothing")
            with wave.open(path, "rb") as w:
                ch, sw, fr, raw = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())
            if sw != 2: raise RuntimeError("unsupported voice format")
            a = np.frombuffer(raw, dtype="<i2")
            if ch > 1: a = a.reshape(-1, ch).mean(axis=1).astype("<i2")
            return a.tobytes(), fr
        finally:
            try: os.remove(path)
            except OSError: pass


LOCAL_STT = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$e = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$e.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$e.SetInputToWaveFile($env:AIO_WAV)
$o=@(); while($true){ $r=$e.Recognize([TimeSpan]::FromSeconds(10)); if($r -eq $null){break}; $o+=$r.Text }
[Console]::OutputEncoding=[Text.Encoding]::UTF8; Write-Output ($o -join ' ')"""


def local_transcribe(wav):
    """Offline speech-to-text with Windows' built-in recognizer: used when the model can't take audio and no Whisper key is set."""
    if sys.platform != "win32": raise RuntimeError("built-in speech recognition needs Windows")
    fd, path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
    try:
        open(path, "wb").write(wav)
        enc = base64.b64encode(LOCAL_STT.encode("utf-16-le")).decode()
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc], capture_output=True, timeout=40,
                           env={**os.environ, "AIO_WAV": path}, creationflags=NO_WINDOW)
        if r.returncode: raise RuntimeError("Windows speech recognition isn't set up (Settings > Time & language > Speech)")
        return r.stdout.decode("utf-8", "replace").strip()
    finally:
        try: os.remove(path)
        except OSError: pass


# ---------- streaming text-to-speech ----------
class Speaker:
    """Two threads: one fetches/synthesizes audio for sentence N+1 while the other is still playing sentence N.
    Works out of the box with the built-in Windows voice; ElevenLabs / OpenAI-compatible voices are optional upgrades."""
    SR = 24000

    def __init__(s, cfg):
        s.cfg = cfg; s.gen = 0; s.tq = queue.Queue(); s.aq = queue.Queue(); s.stream = None; s.err_cb = None; s.sapi = SapiEngine(); s._warned = set(); s.last_write = 0.0
        threading.Thread(target=s._fetch, daemon=True).start()
        threading.Thread(target=s._play, daemon=True).start()
        if s.provider() == "system": threading.Thread(target=s.sapi.warm, daemon=True).start()

    def provider(s):
        c = s.cfg; p = c.get("tts_provider", "system")
        if p == "off" or c.get("muted"): return "off"
        if p in ("elevenlabs", "openai") and c.get("tts_key"): return p
        return "system" if s.sapi.available() else "off"             # no key (or no cloud) -> the built-in voice, never silence

    def enabled(s): return s.provider() != "off"

    def speaking(s):
        """True while speech is queued or audio chunks are still being played (drives the orb's voice animation)."""
        return time.time() - s.last_write < 0.35 or not s.aq.empty() or not s.tq.empty()

    def say(s, text):
        text = clean_for_speech(text)
        if text and s.enabled(): s.tq.put((s.gen, text))

    def stop(s):
        s.gen += 1
        for q in (s.tq, s.aq):
            try:
                while True: q.get_nowait()
            except queue.Empty: pass
        st, s.stream = s.stream, None
        if st is not None:
            try: st.abort()
            except Exception: pass

    def _err(s, msg, once=None):
        if once:
            if once in s._warned: return
            s._warned.add(once)
        if s.err_cb: s.err_cb(msg)

    def _request(s, text, prov):
        c = s.cfg
        if prov == "elevenlabs":
            return SESSION.post(f"https://api.elevenlabs.io/v1/text-to-speech/{c['tts_voice']}/stream",
                                params={"output_format": "pcm_24000"}, headers={"xi-api-key": c["tts_key"]},
                                json={"text": text, "model_id": c["tts_model"]}, stream=True, timeout=(5, 30))
        return SESSION.post(c["tts_url"], headers={"Authorization": "Bearer " + c["tts_key"]}, stream=True, timeout=(5, 30),
                            json={"model": c["tts_model"], "voice": c["tts_voice"], "input": text, "response_format": "pcm"})

    def _put(s, gen, fx, pcm):
        out = fx.process(pcm)
        for i in range(0, len(out), 4800):
            if gen != s.gen: return False
            s.aq.put((gen, out[i:i + 4800]))
        return True

    def _fetch_system(s, gen, text):
        c = s.cfg; st = c.get("voice_style", "natural")
        rate = (VOICE_STYLES.get(st) or VOICE_STYLES["natural"])["sapi"] + int(c.get("voice_rate", 0))
        pcm, sr = s.sapi.synth(text, rate, str(c.get("voice_name", "")))
        if gen == s.gen: s._put(gen, VoiceFX(st, sr, s.SR), pcm)

    def _fetch_cloud(s, gen, text, prov):
        r = s._request(text, prov)
        if r.status_code != 200:
            s._err(f"Online voice error {r.status_code} (check the TTS key / voice id): using the built-in voice instead", once="cloud")
            if s.sapi.available(): s._fetch_system(gen, text)
            return
        fx = VoiceFX(s.cfg.get("voice_style", "natural"), s.SR); rem = b""
        for ch in r.iter_content(4800):
            if gen != s.gen: r.close(); return
            data = rem + ch; n = len(data) // 2 * 2; rem = data[n:]
            if n and not s._put(gen, fx, data[:n]): r.close(); return

    def _fetch(s):
        while True:
            gen, text = s.tq.get()
            if gen != s.gen: continue
            try:
                prov = s.provider()
                if prov == "system": s._fetch_system(gen, text)
                elif prov != "off": s._fetch_cloud(gen, text, prov)
            except Exception as ex:
                s._err(f"Voice error: {str(ex)[:100]}", once="err:" + str(ex)[:40])

    def _play(s):
        while True:
            gen, chunk = s.aq.get()
            if gen != s.gen: continue
            try:
                if s.stream is None:
                    st = sd.RawOutputStream(samplerate=s.SR, channels=1, dtype="int16", latency="low"); st.start(); s.stream = st
                s.stream.write(chunk); s.last_write = time.time()
            except Exception:
                s.stream = None


# ---------- animated orb ----------

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
