"""BGM 素材生成器：按曲目标签合成真实可用的背景音乐

config/bgm/ 下的 mp3 此前是 Git LFS 指针文件（132 字节），BGM 功能从未生效。
本脚本用 numpy 按每首曲目的文字描述（曲风/情绪/速度）合成对应的音乐，
确保"实际音乐与描述匹配"：钢琴曲就是钢琴音色分解和弦、科技电子就是
合成器琶音+四踩鼓、古风古筝就是五声音阶拨弦……

用法：python scripts/make_bgm.py [--duration 90] [--outdir config/bgm]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100


# ---------- 音色/组件 ----------

def env_ad(n: int, a: float, d: float, s_level: float = 0.0) -> np.ndarray:
    """Attack-Decay( sustain=0 ) 包络"""
    t = np.arange(n) / SR
    na = max(1, int(a * SR))
    e = np.zeros(n)
    ramp = np.linspace(0, 1, na)
    e[:na] = ramp
    rest = n - na
    if rest > 0:
        e[na:] = np.linspace(1, s_level, rest) ** 1.5 if s_level > 0 else np.exp(-np.arange(rest) / (d * SR))
    return e


def piano_note(freq: float, dur: float, vol: float = 0.5) -> np.ndarray:
    """软钢琴：基频+泛音，指数衰减"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = (np.sin(2 * np.pi * freq * t) * 1.0
         + np.sin(2 * np.pi * freq * 2 * t) * 0.35
         + np.sin(2 * np.pi * freq * 3 * t) * 0.15
         + np.sin(2 * np.pi * freq * 4.01 * t) * 0.06)
    return w * np.exp(-t / (dur * 0.45)) * vol


def pluck_note(freq: float, dur: float, vol: float = 0.5, bright: float = 1.0) -> np.ndarray:
    """拨弦（吉他/尤克里里/古筝）：快速衰减+高频泛音"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = (np.sin(2 * np.pi * freq * t) * 1.0
         + np.sin(2 * np.pi * freq * 2 * t) * 0.5 * bright
         + np.sin(2 * np.pi * freq * 3.02 * t) * 0.3 * bright)
    return w * np.exp(-t / (dur * 0.18)) * vol


def synth_note(freq: float, dur: float, vol: float = 0.35, saw: float = 0.6) -> np.ndarray:
    """合成器（科技电子）：锯齿+方波近似"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    saw_w = 2 * ((freq * t) % 1.0) - 1
    sq = np.sign(np.sin(2 * np.pi * freq * t))
    w = saw_w * saw + sq * (1 - saw) * 0.4
    return w * env_ad(n, 0.01, dur * 0.3) * vol


def pad_note(freq: float, dur: float, vol: float = 0.25) -> np.ndarray:
    """弦乐/铺底长音：微失谐叠加+慢包络"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = sum(np.sin(2 * np.pi * (freq * (1 + d)) * t) for d in (-0.003, 0, 0.003))
    e = np.minimum(1, t / (dur * 0.3)) * np.minimum(1, (dur - t) / (dur * 0.35))
    return w / 3 * np.clip(e, 0, 1) * vol


def kick(n_beat: float = 0.25) -> np.ndarray:
    n = int(n_beat * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 18) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 10) * 0.8


def hat(n_beat: float = 0.08, vol: float = 0.15) -> np.ndarray:
    n = int(n_beat * SR)
    noise = np.random.default_rng(7).uniform(-1, 1, n)
    return noise * np.exp(-np.arange(n) / (0.012 * SR)) * vol


def timpani(freq: float = 73.0, dur: float = 1.2, vol: float = 0.6) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 1.5 * t)
    return w * np.exp(-t / 0.35) * vol


NOTE_FREQ = {}
_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
for _o in range(1, 7):
    for _i, _nm in enumerate(_NAMES):
        NOTE_FREQ[f"{_nm}{_o}"] = 440.0 * 2 ** ((_o - 4) + (_i - 9) / 12)


def chord_freqs(root: str, typ: str = "maj", inv: int = 0) -> list[float]:
    intervals = {"maj": [0, 4, 7], "min": [0, 3, 7], "maj7": [0, 4, 7, 11],
                 "min7": [0, 3, 7, 10], "dom7": [0, 4, 7, 10], "sus": [0, 5, 7]}
    base = NOTE_FREQ[root]
    freqs = [base * 2 ** (iv / 12) for iv in intervals[typ]]
    for _ in range(inv):
        freqs.append(freqs.pop(0) * 2)
    return freqs


def mix(buf: np.ndarray, sound: np.ndarray, at: float) -> None:
    i = int(at * SR)
    j = min(len(buf), i + len(sound))
    if i < len(buf):
        buf[i:j] += sound[: j - i]


def normalize(x: np.ndarray, peak: float = 0.85) -> np.ndarray:
    m = np.abs(x).max()
    return x / m * peak if m > 0 else x


# ---------- 曲目定义（与 default.yaml bgm_library 一一对应） ----------

def build_track(key: str, duration: float) -> np.ndarray:
    N = int(duration * SR)
    buf = np.zeros(N)
    rng = np.random.default_rng(42)

    def arpeggio(pattern_notes, bpm, note_fn, vol, gap_beats=1/2, dur=None):
        beat = 60 / bpm
        tstep = beat * gap_beats
        t = 0.0
        seq = 0
        while t < duration - 1:
            f = pattern_notes[seq % len(pattern_notes)]
            mix(buf, note_fn(f, dur or tstep * 2.2, vol), t)
            t += tstep
            seq += 1

    if key == "soft_piano":
        prog = [("C3", "maj"), ("A2", "min"), ("F2", "maj"), ("G2", "maj")]
        notes = []
        for r, ty in prog:
            notes += chord_freqs(r, ty) * 2
        arpeggio(notes, 72, piano_note, 0.32, gap_beats=1, dur=1.8)

    elif key == "upbeat_corporate":
        prog = [("C3", "maj"), ("G2", "maj"), ("A2", "min"), ("F2", "maj")]
        for i, (r, ty) in enumerate(prog * 8):
            t0 = i * 2 * (60 / 120)
            for f in chord_freqs(r, ty):
                mix(buf, synth_note(f, 1.9, 0.12, saw=0.2), t0)
            beat = 60 / 120
            for b in range(2):
                mix(buf, kick(), t0 + b * beat)
                mix(buf, hat(), t0 + b * beat + beat / 2)
        arpeggio([NOTE_FREQ[n] for n in ["C4", "E4", "G4", "C5", "G4", "E4"]], 120,
                 synth_note, 0.10, gap_beats=1 / 2, dur=0.3)

    elif key == "tech_electronic":
        prog = [("A2", "min"), ("F2", "min"), ("C3", "maj"), ("G2", "maj")]
        beat = 60 / 128
        arp = [NOTE_FREQ[n] for n in ["A3", "C4", "E4", "A4", "E4", "C4"]]
        t = 0.0
        i = 0
        while t < duration:
            root, ty = prog[(i // 32) % 4]
            f = arp[i % 6]
            mix(buf, synth_note(f * 2, 0.22, 0.12, saw=0.85), t)
            mix(buf, kick(), t)
            if i % 2 == 1:
                mix(buf, hat(0.06, 0.12), t + beat / 2)
            if i % 32 == 0:
                for cf in chord_freqs(root, ty):
                    mix(buf, synth_note(cf, beat * 30, 0.06, saw=0.5), t)
            t += beat / 2
            i += 1

    elif key == "warm_acoustic":
        prog = [("G2", "maj"), ("D3", "maj"), ("E3", "min"), ("C3", "maj")]
        beat = 60 / 92
        for i, (r, ty) in enumerate(prog * 9):
            t0 = i * 4 * beat
            fs = chord_freqs(r, ty)
            for k in range(8):
                mix(buf, pluck_note(fs[k % len(fs)] * 2, 0.9, 0.22, bright=0.7), t0 + k * beat / 2)
            mix(buf, piano_note(fs[0] / 2, beat * 4, 0.18), t0)

    elif key == "chinese_guzheng":
        pent = ["C4", "D4", "E4", "G4", "A4", "C5", "A4", "G4"]
        beat = 60 / 88
        for i in range(int(duration / (beat / 2))):
            t = i * beat / 2
            f = NOTE_FREQ[pent[i % 8]]
            vol = 0.3 if i % 8 in (0, 4) else 0.2
            mix(buf, pluck_note(f, 1.1, vol, bright=1.3), t)
        for i, root in enumerate(["C3", "A2", "F2", "G2"]):
            t0 = i * 4 * beat
            for f in chord_freqs(root, "sus" if root != "C3" else "maj"):
                mix(buf, pluck_note(f / 2 * 2, 1.6, 0.14, bright=0.6), t0)

    elif key == "news_serious":
        prog = [("D2", "min"), ("B1", "maj"), ("G2", "maj"), ("A2", "min")]
        beat = 60 / 96
        for i, (r, ty) in enumerate(prog * 10):
            t0 = i * 4 * beat
            for f in chord_freqs(r, ty):
                mix(buf, pad_note(f, beat * 4.2, 0.16), t0)
            mix(buf, piano_note(chord_freqs(r, ty)[0], beat, 0.3), t0)
            mix(buf, piano_note(chord_freqs(r, ty)[2], beat, 0.22), t0 + beat * 2)
            mix(buf, kick(0.2), t0)
            mix(buf, kick(0.2), t0 + beat * 2)

    elif key == "lofi_chill":
        prog = [("F2", "maj7"), ("E2", "min7"), ("D2", "min7"), ("G2", "dom7")]
        beat = 60 / 75
        for i, (r, ty) in enumerate(prog * 8):
            t0 = i * 4 * beat
            for f in chord_freqs(r, ty):
                mix(buf, piano_note(f * 2, 2.2, 0.14), t0 + rng.uniform(0, 0.03))
            mix(buf, kick(0.3), t0)
            mix(buf, kick(0.3), t0 + beat * 2.5)
            mix(buf, hat(0.1, 0.08), t0 + beat)
            mix(buf, hat(0.1, 0.08), t0 + beat * 3)
        noise = rng.uniform(-1, 1, N) * 0.012
        buf += noise * (0.5 + 0.5 * np.sin(np.arange(N) / SR * 0.5))

    elif key == "cinematic_epic":
        prog = [("C2", "min"), ("A1", "maj"), ("F2", "maj"), ("G2", "maj")]
        beat = 60 / 80
        for i, (r, ty) in enumerate(prog * 7):
            t0 = i * 4 * beat
            grow = 0.10 + 0.05 * (i / 28)
            for f in chord_freqs(r, ty):
                mix(buf, pad_note(f, beat * 4.4, grow), t0)
                mix(buf, pad_note(f * 2, beat * 4.4, grow * 0.5), t0)
            mix(buf, timpani(65.4, 1.4, 0.5 + 0.02 * i), t0)
            mix(buf, timpani(65.4, 1.4, 0.4), t0 + beat * 3)
            for b in range(4):
                mix(buf, timpani(97.9, 0.5, 0.3), t0 + beat * 3 + b * beat / 2)

    elif key == "happy_ukulele":
        prog = [("C3", "maj"), ("G3", "maj"), ("A3", "min"), ("F3", "maj")]
        beat = 60 / 138
        for i, (r, ty) in enumerate(prog * 12):
            t0 = i * 4 * beat
            fs = chord_freqs(r, ty)
            for k in range(8):
                mix(buf, pluck_note(fs[k % len(fs)], 0.5, 0.24, bright=1.1), t0 + k * beat / 2)

    elif key == "emotional_strings":
        prog = [("C2", "maj"), ("G2", "maj"), ("A2", "min"), ("F2", "maj")]
        beat = 60 / 66
        for i, (r, ty) in enumerate(prog * 5):
            t0 = i * 4 * beat
            for f in chord_freqs(r, ty):
                mix(buf, pad_note(f, beat * 4.6, 0.18), t0)
            melody = [NOTE_FREQ[n] for n in ["G4", "E4", "C5", "D4"]]
            mix(buf, pad_note(melody[i % 4] * 2, beat * 3.5, 0.12), t0 + beat * 0.5)

    elif key == "jazz_cafe":
        prog = [("D2", "maj7"), ("G2", "dom7"), ("C3", "maj7"), ("A2", "min7")]
        beat = 60 / 100
        for i, (r, ty) in enumerate(prog * 7):
            t0 = i * 4 * beat
            for k, f in enumerate(chord_freqs(r, ty)):
                mix(buf, piano_note(f * 2, 1.0, 0.16), t0 + (k % 2) * beat * 0.75)
            for b in range(8):
                mix(buf, hat(0.12, 0.09), t0 + b * beat / 2 + beat / 4)
            mix(buf, kick(0.25), t0 + beat)
            mix(buf, kick(0.25), t0 + beat * 3)

    elif key == "ambient_pad":
        prog = [("C2", "maj"), ("F2", "maj"), ("A2", "min"), ("G2", "maj")]
        beat = 60 / 60
        for i, (r, ty) in enumerate(prog * 4):
            t0 = i * 4 * beat
            for f in chord_freqs(r, ty):
                mix(buf, pad_note(f, beat * 5.5, 0.15), t0)
                mix(buf, pad_note(f * 2.0, beat * 5.0, 0.07), t0 + beat)

    elif key == "corporate_uplifting":
        prog = [("C3", "maj"), ("F2", "maj"), ("G2", "maj"), ("C3", "maj")]
        beat = 60 / 112
        arp = [1, 2, 3, 2]
        for i, (r, ty) in enumerate(prog * 8):
            t0 = i * 4 * beat
            fs = chord_freqs(r, ty)
            for b in range(8):
                f = fs[arp[b % 4] - 1] * 2
                mix(buf, synth_note(f, 0.35, 0.10, saw=0.3), t0 + b * beat / 2)
            mix(buf, kick(), t0)
            mix(buf, kick(), t0 + beat * 2)
            mix(buf, hat(0.07, 0.10), t0 + beat)
            mix(buf, hat(0.07, 0.10), t0 + beat * 3)
            mix(buf, pad_note(fs[0], beat * 4, 0.10), t0)

    elif key == "sad_piano":
        prog = [("A2", "min"), ("F2", "maj"), ("C3", "maj"), ("G2", "maj")]
        beat = 60 / 60
        melody_map = {
            0: ["A4", "C5", "E5", "C5"], 1: ["F4", "A4", "C5", "A4"],
            2: ["E4", "G4", "C5", "G4"], 3: ["D4", "G4", "B4", "G4"],
        }
        for i, (r, ty) in enumerate(prog * 5):
            t0 = i * 4 * beat
            mix(buf, piano_note(chord_freqs(r, ty)[0], beat * 4, 0.16), t0)
            for k, nm in enumerate(melody_map[i % 4]):
                mix(buf, piano_note(NOTE_FREQ[nm], beat * 1.6, 0.26), t0 + k * beat)

    else:
        # 未定义曲目：中性钢琴分解兜底
        arpeggio([NOTE_FREQ[n] for n in ["C3", "E3", "G3", "C4", "G3", "E3"]], 80,
                 piano_note, 0.25, gap_beats=1, dur=1.5)

    return normalize(buf)


TRACKS = [
    "soft_piano", "upbeat_corporate", "tech_electronic", "warm_acoustic",
    "chinese_guzheng", "news_serious", "lofi_chill", "cinematic_epic",
    "happy_ukulele", "emotional_strings", "jazz_cafe", "ambient_pad",
    "corporate_uplifting", "sad_piano",
]


def main():
    import imageio_ffmpeg

    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=90)
    ap.add_argument("--outdir", default="config/bgm")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    tmp_wav = outdir / "_tmp_bgm.wav"
    for key in TRACKS:
        out_mp3 = outdir / f"{key}.mp3"
        buf = build_track(key, args.duration)
        sf.write(str(tmp_wav), buf.astype(np.float32), SR)
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp_wav),
             "-b:a", "128k", str(out_mp3)],
            capture_output=True, text=True,
        )
        size = out_mp3.stat().st_size if out_mp3.exists() else 0
        print(f"{key}: {size // 1024}KB {'OK' if r.returncode == 0 and size > 10000 else 'FAIL ' + r.stderr[-100:]}")
    tmp_wav.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
