"""Render an original, copyright-free animated Reel (1080x1920, 30fps, with music).

Every clip is drawn from scratch (procedural backgrounds, particles, text and a
synthesized music loop), so nothing is taken from real anime footage.

Usage: python make_clip.py [--index N] [--out clip.mp4]
Without --index, the post is picked by the current 4-hour slot so each run
gets the next post in content.json.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SECONDS = 1080, 1920, 30, 12
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
BRAND = "AnimeVerse Hub"


def font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def gradient(top, bottom):
    t = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(top) * (1 - t) + np.array(bottom) * t).astype(np.uint8)
    return Image.fromarray(np.repeat(arr, W, axis=1), "RGB")


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def draw_text_block(img, post, t):
    """Kicker pill, title and lines, each sliding in with a stagger."""
    d = ImageDraw.Draw(img, "RGBA")
    y = 560

    a = ease_out(t / 0.5)
    f = font(52)
    tw = d.textlength(post["kicker"], font=f)
    x = (W - tw) / 2
    d.rounded_rectangle((x - 36, y - 14 - (1 - a) * 80, x + tw + 36, y + 66 - (1 - a) * 80),
                        radius=40, fill=(236, 72, 153, int(230 * a)))
    d.text((x, y - (1 - a) * 80), post["kicker"], font=f, fill=(255, 255, 255, int(255 * a)))
    y += 150

    for i, (text, size) in enumerate([(post["title"], 92)] + [(l, 66) for l in post["lines"]]):
        a = ease_out((t - 0.4 - i * 0.35) / 0.6)
        if a <= 0:
            break
        f = font(size)
        for line in wrap(d, text, f, W - 140):
            lw = d.textlength(line, font=f)
            x = (W - lw) / 2 + (1 - a) * 300
            d.text((x + 5, y + 5), line, font=f, fill=(0, 0, 0, int(160 * a)))
            d.text((x, y), line, font=f, fill=(255, 255, 255, int(255 * a)),
                   stroke_width=3 if i == 0 else 0, stroke_fill=(120, 40, 200, int(255 * a)))
            y += int(size * 1.25)
        y += 30

    # Brand footer + call to action
    f = font(44)
    d.text(((W - d.textlength(BRAND, font=f)) / 2, H - 260), BRAND, font=f, fill=(255, 255, 255, 220))
    if t > SECONDS - 4:
        a = ease_out((t - (SECONDS - 4)) / 0.5)
        cta = "Comment below + Follow for more"
        f = font(48)
        lw = d.textlength(cta, font=f)
        d.rounded_rectangle(((W - lw) / 2 - 30, H - 420, (W + lw) / 2 + 30, H - 340), radius=40,
                            fill=(124, 58, 237, int(240 * a)))
        d.text(((W - lw) / 2, H - 408), cta, font=f, fill=(255, 255, 255, int(255 * a)))


def wrap(d, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    return lines + [cur]


class Sakura:
    """Night sky, glowing moon, falling cherry-blossom petals."""

    def __init__(self, rng):
        self.bg = gradient((20, 12, 60), (190, 60, 140))
        d = ImageDraw.Draw(self.bg)
        for _ in range(140):
            x, y = rng.uniform(0, W), rng.uniform(0, H * 0.6)
            r = rng.choice([1, 1, 2, 3])
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255))
        glow = Image.new("RGBA", (W, H))
        gd = ImageDraw.Draw(glow)
        for r, a in [(300, 30), (240, 50), (190, 255)]:
            gd.ellipse((W * 0.7 - r, 330 - r, W * 0.7 + r, 330 + r), fill=(255, 235, 245, a))
        self.bg.paste(glow.filter(ImageFilter.GaussianBlur(12)), (0, 0), glow.filter(ImageFilter.GaussianBlur(12)))
        self.petals = [dict(x=rng.uniform(0, W), y=rng.uniform(-H, H), s=rng.uniform(14, 34),
                            vy=rng.uniform(90, 220), sway=rng.uniform(30, 90), ph=rng.uniform(0, 6.28),
                            spin=rng.uniform(-3, 3)) for _ in range(90)]

    def frame(self, t):
        img = self.bg.copy()
        d = ImageDraw.Draw(img, "RGBA")
        for p in self.petals:
            y = (p["y"] + p["vy"] * t) % (H + 100) - 50
            x = p["x"] + math.sin(t * 1.5 + p["ph"]) * p["sway"]
            s = p["s"] * (0.6 + 0.4 * abs(math.sin(t * p["spin"] + p["ph"])))
            d.ellipse((x - s, y - p["s"] * 0.55, x + s, y + p["s"] * 0.55), fill=(255, 183, 213, 220))
        return img


class PowerUp:
    """Rotating manga speed lines, pulsing aura and a rising power meter."""

    def __init__(self, rng):
        self.rng = rng
        self.angles = [rng.uniform(0, 2 * math.pi) for _ in range(160)]

    def frame(self, t):
        pulse = 0.5 + 0.5 * math.sin(t * 6)
        img = gradient((40 + int(40 * pulse), 0, 70), (230, 90, 20))
        d = ImageDraw.Draw(img, "RGBA")
        cx, cy = W / 2, H * 0.42
        for a in self.angles:
            a += t * 0.4
            r0 = 260 + 40 * math.sin(a * 7 + t * 9)
            d.line((cx + math.cos(a) * r0, cy + math.sin(a) * r0,
                    cx + math.cos(a) * 1600, cy + math.sin(a) * 1600), fill=(255, 255, 255, 70), width=4)
        aura = Image.new("RGBA", (W, H))
        ad = ImageDraw.Draw(aura)
        r = 200 + 40 * pulse
        ad.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 220, 80, 170))
        img.paste(aura.filter(ImageFilter.GaussianBlur(40)), (0, 0), aura.filter(ImageFilter.GaussianBlur(40)))
        # power meter
        level = int(9001 * ease_out(t / (SECONDS * 0.8)))
        f = font(56)
        label = f"POWER LEVEL: {level:,}"
        d.text(((W - d.textlength(label, font=f)) / 2, 300), label, font=f, fill=(255, 255, 255),
               stroke_width=4, stroke_fill=(0, 0, 0))
        if t < SECONDS * 0.85:  # screen shake while charging
            dx, dy = self.rng.randint(-8, 8), self.rng.randint(-8, 8)
            img = img.transform(img.size, Image.AFFINE, (1, 0, dx, 0, 1, dy))
        return img


class Warp:
    """Hyperspace starfield streaking out from the center."""

    def __init__(self, rng):
        self.bg = gradient((5, 5, 25), (60, 20, 110))
        self.stars = [dict(a=rng.uniform(0, 2 * math.pi), z=rng.uniform(0.05, 1),
                           c=rng.choice([(255, 255, 255), (180, 200, 255), (255, 170, 230)])) for _ in range(260)]

    def frame(self, t):
        img = self.bg.copy()
        d = ImageDraw.Draw(img, "RGBA")
        cx, cy = W / 2, H * 0.45
        speed = 0.25 + 0.5 * ease_out(t / 3)
        for s in self.stars:
            z = (s["z"] + t * speed) % 1.0
            r1, r2 = 1400 * z ** 2, 1400 * max(z - 0.06 * speed, 0) ** 2
            d.line((cx + math.cos(s["a"]) * r2, cy + math.sin(s["a"]) * r2,
                    cx + math.cos(s["a"]) * r1, cy + math.sin(s["a"]) * r1),
                   fill=s["c"] + (int(255 * z),), width=max(1, int(6 * z)))
        return img


STYLES = {"sakura": Sakura, "powerup": PowerUp, "warp": Warp}


def music(path, style, rng):
    """Synthesize an original lo-fi chord + arpeggio loop."""
    sr = 44100
    n = sr * SECONDS
    t = np.arange(n) / sr
    roots = {"sakura": [57, 53, 48, 55], "powerup": [52, 48, 50, 47], "warp": [50, 46, 53, 48]}[style]
    bpm = 140 if style == "powerup" else 90
    beat = 60 / bpm
    out = np.zeros(n)
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    bar = beat * 4
    for b in range(int(SECONDS / bar) + 1):
        root = roots[b % len(roots)]
        s, e = int(b * bar * sr), min(int((b + 1) * bar * sr), n)
        seg = t[s:e] - b * bar
        for iv in (0, 3 if style != "sakura" else 4, 7, 12):  # pad chord
            out[s:e] += 0.05 * np.sin(2 * np.pi * hz(root + iv) * seg) * np.exp(-seg * 0.4)
        for k in range(8):  # arpeggio eighths
            ns, ne = s + int(k * beat / 2 * sr), min(s + int((k + 1) * beat / 2 * sr), e)
            if ns >= ne:
                continue
            nt = t[ns:ne] - t[ns]
            note = root + 12 + rng.choice([0, 3, 7, 10, 12])
            out[ns:ne] += 0.09 * np.sin(2 * np.pi * hz(note) * nt) * np.exp(-nt * 6)
        for k in range(4):  # soft kick
            ks = s + int(k * beat * sr)
            ke = min(ks + int(0.15 * sr), n)
            if ks >= ke:
                continue
            kt = t[ks:ke] - t[ks]
            out[ks:ke] += 0.25 * np.sin(2 * np.pi * (60 + 80 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 20)
    fade = np.minimum(1, np.minimum(t / 0.5, (SECONDS - t) / 1.0))
    pcm = (np.clip(out * fade, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def load_posts():
    with open(os.path.join(HERE, "content.json")) as f:
        return json.load(f)


def pick(posts, index=None):
    if index is None:
        index = int(time.time() // (4 * 3600))
    return posts[index % len(posts)]


def render(post, out):
    rng = random.Random(post["title"])
    scene = STYLES[post["style"]](rng)
    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "music.wav")
        music(audio, post["style"], rng)
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio,
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out],
            stdin=subprocess.PIPE)
        for i in range(FPS * SECONDS):
            t = i / FPS
            img = scene.frame(t)
            draw_text_block(img, post, t)
            ff.stdin.write(img.convert("RGB").tobytes())
        ff.stdin.close()
        if ff.wait() != 0:
            sys.exit("ffmpeg failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int)
    ap.add_argument("--out", default="clip.mp4")
    args = ap.parse_args()
    post = pick(load_posts(), args.index)
    render(post, args.out)
    print(json.dumps(post))


if __name__ == "__main__":
    main()
