"""Render a random, original ~7 minute anime fight video (1280x720, 24fps, music + sound effects).

Each video picks a style (stick figure, power battle or sword duel), two fighters
and a random best-of-three fight choreography. Everything is drawn and
synthesized from scratch, so there is no copyrighted footage or audio.

Usage: python fight.py [--style stick|power|sword|mix] [--seed N] [--duration 420] [--out fight.mp4]
Prints the post title/description as JSON.
"""
import argparse
import bisect
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
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, SR = 1280, 720, 24, 44100
ARENA = 650
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
NAMES = ["KAZE", "RAIJIN", "AKIRA", "HOTARU", "KUROGANE", "YAMI", "SORA", "RYU", "ZEN", "KAGE",
         "TORA", "HIKARI", "OBORO", "JIN", "REN", "MAKOTO", "SHIRO", "ENJI", "TSUKI", "GORO"]
STYLE_TITLES = {"stick": "Stick Fight", "power": "Power Battle", "sword": "Sword Duel"}

_fonts = {}


def font(size):
    size = max(8, int(size))
    if size not in _fonts:
        path = next((p for p in FONT_PATHS if os.path.exists(p)), None)
        _fonts[size] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    return _fonts[size]


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


# ---------------------------------------------------------------- skeleton
# Pose angles in degrees: 0 points straight down, 90 points toward the opponent, 180 up.
# (torso lean, front shoulder, front elbow, back shoulder, back elbow,
#  front hip, front knee, back hip, back knee)
T_LEN, U_LEN, F_LEN, TH_LEN, SH_LEN, HEAD_R, SWORD = 62, 32, 30, 40, 40, 14, 74
POSES = {
    "guard": (8, 50, 100, 25, 110, 22, 18, -22, 12),
    "guard2": (12, 58, 95, 30, 105, 26, 26, -18, 20),
    "punch": (18, 92, 0, 15, 115, 30, 10, -32, 5),
    "cross": (22, 30, 110, 92, 0, 32, 15, -30, 5),
    "kick": (-18, 45, 90, -25, 60, 95, 0, -8, 8),
    "highkick": (-35, 60, 80, -40, 50, 135, 0, -5, 5),
    "uppercut": (0, 165, 15, 10, 110, 25, 5, -20, 0),
    "block": (-6, 80, 95, 70, 100, 25, 35, -25, 30),
    "hit": (-28, 125, 50, -35, 30, -5, 25, 25, 30),
    "fly": (-65, 150, 30, 170, 20, 55, 45, 30, 70),
    "down": (-90, -100, 10, -80, 10, 92, 5, 85, 15),
    "crouch": (20, 40, 120, 40, 120, 70, 110, -5, 95),
    "kneel": (25, 20, 30, -10, 30, 80, 100, -20, 120),
    "charge": (5, 35, 20, -35, 20, 45, 50, -45, 50),
    "blast": (15, 90, 0, 86, 5, 42, 30, -42, 10),
    "jump": (10, 130, 40, 150, 40, 75, 115, 40, 120),
    "dash": (42, -50, 30, -65, 30, 65, 65, -55, 45),
    "windup": (-10, 175, 40, 20, 100, 20, 10, -25, 10),
    "slash": (28, 60, 0, 10, 90, 50, 40, -40, 10),
    "thrust": (30, 90, 0, -20, 60, 60, 50, -45, 5),
    "victory": (0, 175, 0, 25, 80, 10, 0, -10, 0),
    "airkick": (-25, 60, 70, 120, 60, 100, 0, 20, 110),
    "getup": (30, 20, 60, 30, 60, 90, 120, -10, 110),
}


def vec(a, d):
    r = math.radians(a)
    return d * math.sin(r), math.cos(r)


def skeleton(pose, x, h, d):
    """World-space joint positions; the lowest body point rests at height h above the ground."""
    lean, fsh, felb, bsh, belb, fhip, fkn, bhip, bkn = pose
    tx, ty = vec(lean, d)
    p = {"hip": (0.0, 0.0)}
    p["chest"] = (T_LEN * tx, -T_LEN * ty)
    p["head"] = (p["chest"][0] + (HEAD_R + 5) * tx, p["chest"][1] - (HEAD_R + 5) * ty)
    for side, sh, elb in (("f", fsh, felb), ("b", bsh, belb)):
        ex, ey = vec(sh, d)
        el = (p["chest"][0] + U_LEN * ex, p["chest"][1] + U_LEN * ey)
        hx, hy = vec(sh + elb, d)
        p[side + "el"] = el
        p[side + "ha"] = (el[0] + F_LEN * hx, el[1] + F_LEN * hy)
        p[side + "dir"] = (hx, hy)
    for side, hp, kn in (("f", fhip, fkn), ("b", bhip, bkn)):
        kx, ky = vec(hp, d)
        k = (TH_LEN * kx, TH_LEN * ky)
        fx, fy = vec(hp - kn, d)
        p[side + "kn"] = k
        p[side + "ft"] = (k[0] + SH_LEN * fx, k[1] + SH_LEN * fy)
    low = max(v[1] + (HEAD_R if k == "head" else 0) for k, v in p.items() if not k.endswith("dir"))
    oy = -h - low
    out = {k: (x + v[0], oy + v[1]) if not k.endswith("dir") else v for k, v in p.items()}
    hx, hy = out["fdir"]
    out["tip"] = (out["fha"][0] + SWORD * hx, out["fha"][1] + SWORD * hy)
    return out


class Track:
    """Keyframed pose/position timeline for one fighter."""

    def __init__(self, x):
        self.keys = [(0.0, POSES["guard"], x, 0.0)]
        self.times = [0.0]

    def add(self, t, pose, x, h):
        i = bisect.bisect_right(self.times, t)
        self.times.insert(i, t)
        self.keys.insert(i, (t, pose, x, h))

    def at(self, t):
        i = bisect.bisect_right(self.times, t)
        if i == 0:
            return self.keys[0][1:]
        if i >= len(self.keys):
            return self.keys[-1][1:]
        t0, p0, x0, h0 = self.keys[i - 1]
        t1, p1, x1, h1 = self.keys[i]
        u = ease((t - t0) / (t1 - t0)) if t1 > t0 else 1.0
        pose = tuple(a + (b - a) * u for a, b in zip(p0, p1))
        return pose, x0 + (x1 - x0) * u, h0 + (h1 - h0) * u


# ---------------------------------------------------------------- choreography
class Fight:
    def __init__(self, rng, style, names, duration):
        self.rng, self.style, self.names, self.duration = rng, style, names, duration
        self.tr = [Track(-180), Track(180)]
        self.fx, self.sfx, self.hits, self.rounds = [], [], [], []
        self.t = 0.0
        self.moves = {"stick": ["punch", "cross", "kick", "highkick", "punch"],
                      "power": ["punch", "cross", "kick", "highkick"],
                      "sword": ["slash", "thrust", "slash", "kick"]}[style]

    # helpers
    def pos(self, i):
        return self.tr[i].keys[-1][2]

    def facing(self, i):
        return 1 if self.pos(1 - i) >= self.pos(i) else -1

    def key(self, i, dt, pose, x=None, h=0.0):
        x = self.pos(i) if x is None else max(-ARENA, min(ARENA, x))
        self.tr[i].add(self.t + dt, POSES[pose], x, h)

    def cut(self, i, x, pose="guard"):
        """Jump instantly to a new position (used at round starts, hidden by a fade)."""
        last = self.tr[i].keys[-1]
        self.tr[i].add(self.t, last[1], last[2], last[3])
        self.tr[i].add(self.t + 0.01, POSES[pose], x, 0.0)

    def effect(self, kind, dt, dur, **kw):
        self.fx.append(dict(kind=kind, t0=self.t + dt, dur=dur, **kw))

    def sound(self, kind, dt=0.0, **kw):
        self.sfx.append(dict(kind=kind, t=self.t + dt, **kw))

    def hit(self, target, dt, dmg):
        self.hits.append([self.t + dt, target, dmg])

    def hold(self, dt):
        for i in (0, 1):
            self.key(i, dt, "guard")

    # beats
    def idle(self, dur):
        n = max(1, int(dur / 0.45))
        for k in range(n):
            for i in (0, 1):
                x = self.pos(i) - self.facing(i) * self.rng.uniform(-18, 22)
                self.key(i, (k + 1) * dur / n, "guard2" if k % 2 == 0 else "guard", x)
        if abs(self.pos(0) - self.pos(1)) < 90:
            self.key(0, dur, "guard", self.pos(0) - self.facing(0) * 40)
        self.t += dur

    def close_in(self, a):
        b = 1 - a
        d = self.facing(a)
        if abs(self.pos(b) - self.pos(a)) < 150:
            return
        start, target = self.pos(a), self.pos(b) - d * 105
        self.key(a, 0.08, "dash")
        self.key(a, 0.36, "dash", target)
        self.key(a, 0.48, "guard", target)
        self.key(b, 0.48, "guard")
        self.effect("speed", 0.05, 0.4)
        self.effect("dust", 0.05, 0.5, x=start)
        self.sound("whoosh", 0.05)
        self.t += 0.5

    def combo(self, a, n):
        b = 1 - a
        self.close_in(a)
        sword = self.style == "sword"
        for _ in range(n):
            d = self.facing(a)
            move = self.rng.choice(self.moves)
            wind = 0.1
            if move == "slash":
                self.key(a, 0.1, "windup")
                wind = 0.2
            self.key(a, wind, move)
            xb = self.pos(b)
            iy = {"kick": -80, "highkick": -150}.get(move, -115)
            ix = xb - d * 18
            if self.rng.random() < 0.42:
                self.key(b, max(0.02, wind - 0.05), "block")
                self.key(b, wind + 0.14, "block", xb + d * 14)
                self.effect("spark" if sword and move != "kick" else "impact", wind, 0.3, x=ix, y=iy, size=0.6)
                self.sound("clank" if sword and move != "kick" else "block", wind)
                self.hit(b, wind, self.rng.uniform(0.5, 1.5))
            else:
                self.key(b, wind + 0.03, "hit", xb + d * 26)
                self.key(b, wind + 0.24, "guard", xb + d * 32)
                self.effect("impact", wind, 0.3, x=ix, y=iy, size=1.0)
                if sword and move != "kick":
                    self.effect("arc", wind - 0.05, 0.25, x=ix, y=iy, d=d, big=False)
                self.effect("shake", wind, 0.15, amp=6)
                self.sound("slash" if sword and move != "kick" else "hit", wind)
                self.hit(b, wind, self.rng.uniform(3, 7))
            self.key(a, wind + 0.1, move, self.pos(a) + d * 18)
            self.key(a, wind + 0.24, "guard")
            self.t += wind + 0.26

    def knockback(self, a, ko=False):
        b = 1 - a
        self.close_in(a)
        d = self.facing(a)
        if self.style == "sword":
            move, prep = "slash", "windup"
        else:
            move = self.rng.choice(["uppercut", "highkick"])
            prep = "crouch" if move == "uppercut" else "guard2"
        xb = self.pos(b)
        land = max(-ARENA, min(ARENA, xb + d * self.rng.uniform(260, 380)))
        self.key(a, 0.15, prep)
        self.key(a, 0.3, move)
        self.key(a, 0.65, move)
        self.key(a, 0.9, "guard")
        self.key(b, 0.28, "guard")
        self.key(b, 0.33, "hit", xb + d * 20)
        self.key(b, 0.55, "fly", (xb + land) / 2, 120)
        self.key(b, 0.82, "fly", land - d * 20, 25)
        self.key(b, 0.9, "down", land)
        self.effect("impact", 0.3, 0.4, x=xb - d * 15, y=-125, size=1.8)
        if self.style == "sword":
            self.effect("arc", 0.25, 0.3, x=xb - d * 15, y=-120, d=d, big=True)
        self.effect("flash", 0.3, 0.25, alpha=110)
        self.effect("shake", 0.3, 0.4, amp=14)
        self.effect("shockwave", 0.9, 0.5, x=land)
        self.effect("dust", 0.9, 0.7, x=land)
        self.sound("big", 0.3)
        self.sound("land", 0.9)
        self.hit(b, 0.3, self.rng.uniform(10, 15))
        if ko:
            self.t += 1.0
            return
        self.key(b, 1.6, "down")
        self.key(b, 1.95, "getup")
        self.key(b, 2.25, "guard")
        self.key(a, 2.25, "guard")
        self.t += 2.3

    def aerial(self, a):
        b = 1 - a
        d = self.facing(a)
        mid = (self.pos(a) + self.pos(b)) / 2
        H0 = 170
        for i, x in ((a, mid - d * 55), (b, mid + d * 55)):
            self.key(i, 0.15, "crouch")
            self.key(i, 0.45, "jump", x, H0)
            self.effect("dust", 0.15, 0.6, x=self.pos(i))
        self.sound("whoosh", 0.15)
        t = 0.6
        for k in range(3):
            att, dfn = (a, b) if k % 2 == 0 else (b, a)
            move = self.rng.choice(["airkick", "punch", "slash" if self.style == "sword" else "cross"])
            self.key(att, t, move, h=H0 + 8)
            self.key(dfn, t, "block", h=H0 - 5)
            self.key(att, t + 0.2, "jump", h=H0)
            self.key(dfn, t + 0.2, "jump", h=H0)
            self.effect("spark" if self.style == "sword" else "impact", t, 0.3, x=mid, y=-H0 - 110, size=0.8)
            self.sound("clank" if self.style == "sword" else "block", t)
            t += 0.3
        land = max(-ARENA, min(ARENA, mid + d * 140))
        self.key(a, t + 0.05, "airkick", mid - d * 20, H0 + 20)
        self.key(b, t + 0.08, "hit", mid + d * 30, H0)
        self.key(b, t + 0.35, "fly", land, 20)
        self.key(b, t + 0.4, "down", land)
        self.key(a, t + 0.45, "jump", mid - d * 30, 80)
        self.key(a, t + 0.65, "crouch", mid - d * 30)
        self.key(a, t + 0.9, "guard")
        self.effect("impact", t + 0.05, 0.35, x=mid + d * 15, y=-H0 - 110, size=1.5)
        self.effect("shake", t + 0.4, 0.45, amp=16)
        self.effect("shockwave", t + 0.4, 0.6, x=land)
        self.effect("dust", t + 0.4, 0.8, x=land)
        self.sound("hit", t + 0.05)
        self.sound("land", t + 0.4)
        self.hit(b, t + 0.05, self.rng.uniform(9, 13))
        self.key(b, t + 1.3, "down")
        self.key(b, t + 1.6, "getup")
        self.key(b, t + 1.9, "guard")
        self.t += t + 1.95

    def charge(self, a):
        b = 1 - a
        self.key(a, 0.25, "charge")
        self.key(a, 1.8, "charge")
        self.key(b, 0.9, "guard2")
        self.key(b, 1.8, "guard")
        self.effect("aura", 0.2, 1.7, who=a)
        self.effect("shake", 0.4, 1.4, amp=3)
        self.sound("charge", 0.2, dur=1.6)
        self.t += 1.85

    def blast(self, a, ko=False):
        b = 1 - a
        d = self.facing(a)
        xa, xb = self.pos(a), self.pos(b)
        if abs(xb - xa) < 220:
            self.key(a, 0.25, "dash", xb - d * 280)
            self.t += 0.3
            xa = self.pos(a)
        self.key(a, 0.15, "blast")
        self.key(a, 0.9, "blast")
        self.key(a, 1.1, "guard")
        self.sound("blast", 0.15)
        option = "hit" if ko else self.rng.choices(["hit", "block", "dodge"], [45, 30, 25])[0]
        if option == "dodge":
            far = xb + d * 700
            self.effect("projectile", 0.15, 0.85, x0=xa + d * 60, x1=far, y=-125, who=a)
            self.key(b, 0.4, "crouch")
            self.key(b, 0.55, "jump", h=150)
            self.key(b, 0.85, "jump", h=60)
            self.key(b, 0.98, "guard")
            self.effect("explosion", 1.0, 0.8, x=far, y=-60, size=0.8)
            self.sound("boom", 1.0, vol=0.4)
            self.t += 1.3
            return
        self.effect("projectile", 0.15, 0.5, x0=xa + d * 60, x1=xb - d * 10, y=-125, who=a)
        self.sound("boom", 0.65)
        if option == "block":
            self.key(b, 0.4, "block")
            self.key(b, 0.65, "block")
            self.key(b, 0.95, "block", xb + d * 70)
            self.key(b, 1.2, "guard")
            self.effect("explosion", 0.65, 0.6, x=xb - d * 25, y=-115, size=0.8)
            self.effect("shake", 0.65, 0.3, amp=8)
            self.hit(b, 0.65, self.rng.uniform(2, 4))
            self.t += 1.25
            return
        land = max(-ARENA, min(ARENA, xb + d * 300))
        self.key(b, 0.62, "guard")
        self.key(b, 0.68, "hit")
        self.key(b, 0.9, "fly", (xb + land) / 2, 110)
        self.key(b, 1.15, "fly", land, 20)
        self.key(b, 1.22, "down", land)
        self.effect("explosion", 0.65, 0.9, x=xb, y=-115, size=1.4)
        self.effect("flash", 0.65, 0.3, alpha=140)
        self.effect("shake", 0.65, 0.5, amp=15)
        self.effect("dust", 1.22, 0.7, x=land)
        self.sound("land", 1.22)
        self.hit(b, 0.65, self.rng.uniform(11, 15))
        if ko:
            self.t += 1.4
            return
        self.key(b, 1.9, "down")
        self.key(b, 2.2, "getup")
        self.key(b, 2.5, "guard")
        self.t += 2.55

    def beam_clash(self, winner, ko=False):
        a, b = winner, 1 - winner
        mid = max(-300, min(300, (self.pos(0) + self.pos(1)) / 2))
        da = self.facing(a)
        self.key(a, 0.4, "dash", mid - da * 260)
        self.key(b, 0.4, "dash", mid + da * 260)
        for i in (a, b):
            self.key(i, 0.7, "charge")
            self.key(i, 1.0, "blast")
            self.key(i, 4.8, "blast")
        self.effect("aura", 0.4, 0.7, who=a)
        self.effect("aura", 0.4, 0.7, who=b)
        self.effect("beam", 1.0, 3.8, a=a, b=b, mid=mid, d=da)
        self.effect("shake", 1.0, 3.8, amp=4)
        self.sound("beam", 1.0, dur=3.8)
        xb = mid + da * 260
        land = max(-ARENA, min(ARENA, xb + da * 200))
        self.key(b, 4.85, "hit")
        self.key(b, 5.1, "fly", (xb + land) / 2, 100)
        self.key(b, 5.35, "down", land)
        self.key(a, 5.3, "guard")
        self.effect("explosion", 4.8, 1.1, x=xb, y=-110, size=2.0)
        self.effect("flash", 4.8, 0.4, alpha=200)
        self.effect("shake", 4.8, 0.6, amp=20)
        self.sound("boom", 4.8, vol=1.2)
        self.hit(b, 4.8, self.rng.uniform(15, 20))
        if ko:
            self.t += 5.5
            return
        self.key(b, 6.0, "down")
        self.key(b, 6.3, "getup")
        self.key(b, 6.6, "guard")
        self.t += 6.65

    def sword_clash(self, a):
        b = 1 - a
        mid = max(-300, min(300, (self.pos(0) + self.pos(1)) / 2))
        d = self.facing(a)
        self.key(a, 0.3, "dash", mid - d * 45)
        self.key(b, 0.3, "dash", mid + d * 45)
        self.sound("whoosh", 0.05)
        self.effect("speed", 0.05, 0.3)
        t = 0.35
        for k in range(self.rng.randint(3, 5)):
            for i, p in ((a, "slash" if k % 2 == 0 else "windup"), (b, "windup" if k % 2 == 0 else "slash")):
                self.key(i, t, p)
            self.effect("spark", t, 0.35, x=mid, y=-120 + self.rng.uniform(-25, 25), size=1.2)
            self.effect("flash", t, 0.12, alpha=60)
            self.sound("clank", t)
            t += 0.32
        self.key(a, t + 0.2, "dash", mid - d * 230)
        self.key(b, t + 0.2, "dash", mid + d * 230)
        self.key(a, t + 0.4, "guard")
        self.key(b, t + 0.4, "guard")
        self.t += t + 0.45

    def dash_through(self, a, ko=False):
        b = 1 - a
        d = self.facing(a)
        xa, xb = self.pos(a), self.pos(b)
        if abs(xb + d * 200) > ARENA:
            shift = -d * 250
            self.key(a, 0.3, "dash", xa + shift)
            self.key(b, 0.3, "guard", xb + shift)
            self.t += 0.35
            xa, xb = xa + shift, xb + shift
        dest = xb + d * 200
        self.key(a, 0.3, "windup")
        self.key(a, 0.7, "windup")
        self.key(a, 0.78, "thrust", dest)
        self.key(a, 0.85, "slash", dest + d * 10)
        self.key(a, 1.7, "slash")
        self.key(b, 0.7, "guard")
        self.key(b, 1.3, "guard")
        self.effect("arc", 0.72, 0.6, x0=xa, x1=dest, y=-115, d=d, big=True, line=True)
        self.effect("flash", 0.74, 0.2, alpha=150)
        self.effect("speed", 0.7, 0.3)
        self.sound("slash", 0.72)
        self.key(b, 1.35, "hit")
        self.effect("impact", 1.35, 0.4, x=xb, y=-120, size=1.6)
        self.effect("shake", 1.35, 0.3, amp=10)
        self.sound("big", 1.35)
        self.hit(b, 1.35, self.rng.uniform(12, 16))
        if ko:
            self.key(b, 1.7, "kneel")
            self.key(b, 2.6, "kneel")
            self.key(b, 3.0, "down")
            self.effect("dust", 3.0, 0.7, x=xb)
            self.sound("land", 3.0)
            self.t += 3.0
            return
        self.key(b, 1.7, "kneel")
        self.key(b, 2.1, "guard")
        self.key(a, 2.1, "guard")
        self.t += 2.15

    # structure
    def text(self, dt, dur, text, size=110, color=(255, 255, 255), y=0.42, sub=None):
        self.effect("text", dt, dur, text=text, size=size, color=color, y=y, sub=sub)

    def finisher(self, winner):
        if self.style == "power":
            if self.rng.random() < 0.5:
                self.beam_clash(winner, ko=True)
            else:
                self.charge(winner)
                self.blast(winner, ko=True)
        elif self.style == "sword":
            self.dash_through(winner, ko=True)
        else:
            self.combo(winner, 2)
            self.knockback(winner, ko=True)

    def play_round(self, n, winner, t_end, final):
        loser = 1 - winner
        start = self.t
        self.effect("fade", 0, 0.6)
        self.cut(0, -180)
        self.cut(1, 180)
        self.t += 0.01
        self.text(0.3, 1.6, "FINAL ROUND" if final else f"ROUND {n}")
        self.text(2.0, 1.0, "FIGHT!", size=150, color=(255, 210, 60))
        self.sound("gong", 2.0)
        self.idle(3.0)
        beats = {"stick": [("combo", 5), ("knock", 2), ("aerial", 2), ("idle", 2)],
                 "power": [("combo", 4), ("knock", 2), ("aerial", 2), ("blast", 2), ("charge", 1),
                           ("beam", 1), ("idle", 2)],
                 "sword": [("combo", 4), ("clash", 3), ("dash", 2), ("aerial", 1), ("knock", 1), ("idle", 2)]}
        kinds, weights = zip(*beats[self.style])
        while self.t < t_end - 9:
            a = winner if self.rng.random() < 0.6 else loser
            kind = self.rng.choices(kinds, weights)[0]
            if kind == "combo":
                self.combo(a, self.rng.randint(2, 5))
            elif kind == "knock":
                self.knockback(a)
            elif kind == "aerial":
                self.aerial(a)
            elif kind == "blast":
                self.blast(a)
            elif kind == "charge":
                self.charge(a)
                self.blast(a)
            elif kind == "beam":
                self.beam_clash(a)
            elif kind == "clash":
                self.sword_clash(a)
            elif kind == "dash":
                self.dash_through(a)
            else:
                self.idle(self.rng.uniform(0.8, 1.8))
            if self.rng.random() < 0.35:
                self.idle(self.rng.uniform(0.5, 1.2))
        self.finisher(winner)
        self.text(0.0, 2.2, "K.O.!", size=170, color=(255, 70, 70))
        self.effect("flash", 0.0, 0.4, alpha=170)
        self.sound("boom", 0.0, vol=0.8)
        self.key(winner, 0.9, "victory")
        self.key(winner, 3.5, "victory")
        self.key(loser, 3.5, "down")
        self.t += 3.6
        self.rounds.append((start, self.t, winner))

    def build(self):
        self.text(0.2, 2.2, "AnimeVerse Hub", size=90, sub="presents")
        self.effect("vs", 2.5, 3.0)
        self.sound("gong", 2.5)
        self.idle(5.6)
        winner = self.rng.randint(0, 1)
        order = [winner, 1 - winner]
        self.rng.shuffle(order)
        order.append(winner)
        per_round = (self.duration - 5.6 - 9) / 3
        for n, w in enumerate(order, 1):
            self.play_round(n, w, 5.6 + per_round * n, n == 3)
        self.winner = winner
        self.effect("outro", 0.3, max(8.0, self.duration - self.t))
        self.key(winner, max(8.0, self.duration - self.t), "victory")
        self.key(1 - winner, max(8.0, self.duration - self.t), "down")
        self.t = max(self.t + 8.0, self.duration)
        self._scale_damage()

    def _scale_damage(self):
        """Make each round's loser hit exactly 0 HP at the K.O. and the winner end with some left."""
        for start, end, winner in self.rounds:
            rh = [h for h in self.hits if start <= h[0] <= end]
            for target, total in ((1 - winner, 100.0), (winner, self.rng.uniform(35, 75))):
                hs = [h for h in rh if h[1] == target]
                s = sum(h[2] for h in hs)
                for h in hs:
                    h[2] = h[2] * total / s if s else 0

    def health(self, i, t):
        for start, end, _ in self.rounds:
            if start <= t <= end + 0.01:
                return max(0.0, 100 - sum(h[2] for h in self.hits if h[1] == i and start <= h[0] <= t))
        return 100.0


# ---------------------------------------------------------------- rendering
PALETTES = {
    "stick": dict(body=[(25, 25, 25), (190, 30, 30)], glow=None, sky=((246, 243, 233), (236, 230, 214)),
                  ground=(70, 60, 50), hud=(30, 30, 30)),
    "power": dict(body=[(255, 196, 70), (90, 190, 255)], glow=[(255, 140, 20), (40, 120, 255)],
                  sky=((22, 12, 48), (120, 40, 110)), ground=(48, 36, 52), hud=(255, 255, 255)),
    "sword": dict(body=[(14, 10, 18), (14, 10, 18)], glow=None, sky=((250, 150, 70), (120, 30, 70)),
                  ground=(30, 14, 24), hud=(255, 255, 255)),
}


class Renderer:
    def __init__(self, fight, rng):
        self.f, self.rng = fight, rng
        self.style = fight.style
        self.pal = PALETTES[self.style]
        self.cam = None
        self.facing = [1, -1]
        self.sky = self._sky()
        self.far = self._far_layer()

    def _sky(self):
        top, bot = self.pal["sky"]
        t = np.linspace(0, 1, H)[:, None, None]
        arr = (np.array(top) * (1 - t) + np.array(bot) * t).astype(np.uint8)
        img = Image.fromarray(np.repeat(arr, W, axis=1), "RGB")
        d = ImageDraw.Draw(img, "RGBA")
        rng = random.Random(1)
        if self.style == "stick":
            for y in range(40, H, 34):
                d.line((0, y, W, y), fill=(120, 150, 200, 40), width=1)
            d.line((90, 0, 90, H), fill=(220, 90, 90, 60), width=2)
        elif self.style == "power":
            for _ in range(160):
                x, y = rng.uniform(0, W), rng.uniform(0, H * 0.6)
                r = rng.choice([1, 1, 2])
                d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randint(80, 255)))
            d.ellipse((W * 0.75 - 60, 70, W * 0.75 + 60, 190), fill=(255, 230, 240, 230))
        else:
            d.ellipse((W * 0.5 - 150, H * 0.3 - 150, W * 0.5 + 150, H * 0.3 + 150), fill=(255, 220, 150, 200))
            for _ in range(6):
                y = rng.uniform(80, 300)
                x = rng.uniform(-100, W)
                d.rounded_rectangle((x, y, x + rng.uniform(200, 500), y + 10), 5,
                                    fill=(255, 200, 160, 90))
        return img

    def _far_layer(self):
        """A wide strip of distant scenery that scrolls slower than the fighters (parallax)."""
        fw, fh = W * 3, 260
        img = Image.new("RGBA", (fw, fh))
        d = ImageDraw.Draw(img)
        rng = random.Random(2)
        if self.style == "stick":
            for x in range(0, fw, 260):
                hgt = rng.uniform(60, 140)
                d.line((x, fh, x + 70, fh - hgt, x + 140, fh), fill=(60, 60, 60, 90), width=3)
        elif self.style == "power":
            pts = [(0, fh)]
            for x in range(0, fw + 80, 80):
                pts.append((x, fh - rng.uniform(60, 220)))
            pts.append((fw, fh))
            d.polygon(pts, fill=(40, 20, 60, 255))
            pts = [(0, fh)] + [(x, fh - rng.uniform(20, 110)) for x in range(0, fw + 60, 60)] + [(fw, fh)]
            d.polygon(pts, fill=(60, 30, 75, 255))
        else:
            pts = [(0, fh)] + [(x, fh - rng.uniform(40, 120)) for x in range(0, fw + 120, 120)] + [(fw, fh)]
            d.polygon(pts, fill=(90, 30, 60, 255))
            for x in range(150, fw, 520):
                base = fh - 40
                for lvl in range(3):
                    w2 = 70 - lvl * 18
                    y = base - lvl * 38
                    d.polygon([(x - w2, y), (x + w2, y), (x + w2 * 0.6, y - 18), (x - w2 * 0.6, y - 18)],
                              fill=(40, 12, 30, 255))
                    d.rectangle((x - w2 * 0.45, y, x + w2 * 0.45, y + 20), fill=(40, 12, 30, 255))
            for _ in range(12):
                x = rng.uniform(0, fw)
                d.rectangle((x - 4, fh - 150, x + 4, fh), fill=(30, 10, 25, 255))
                d.ellipse((x - 50, fh - 190, x + 50, fh - 120), fill=(30, 10, 25, 255))
        return img

    # camera
    def update_camera(self, states, t):
        (pa, xa, ha), (pb, xb, hb) = states
        dist = abs(xa - xb)
        tz = max(0.85, min(1.9, W * 0.55 / (dist + 260)))
        tx = (xa + xb) / 2
        ty = -(ha + hb) / 2 * 0.6 - 90
        if self.cam is None:
            self.cam = [tx, ty, tz]
        k = 0.12
        self.cam[0] += (tx - self.cam[0]) * k
        self.cam[1] += (ty - self.cam[1]) * k
        self.cam[2] += (tz - self.cam[2]) * k
        amp = sum(e["amp"] * (1 - (t - e["t0"]) / e["dur"]) for e in self.active(t, "shake"))
        self.shake = (self.rng.uniform(-amp, amp), self.rng.uniform(-amp, amp))

    def S(self, x, y):
        cx, cy, z = self.cam
        return ((x - cx) * z + W / 2 + self.shake[0], (y - cy) * z + H * 0.6 + self.shake[1])

    def active(self, t, kind=None):
        return [e for e in self.f.fx if e["t0"] <= t < e["t0"] + e["dur"] and (kind is None or e["kind"] == kind)]

    # drawing
    def background(self):
        img = self.sky.copy()
        cx, cy, z = self.cam
        gx, gy = self.S(cx, 0)
        off = int((cx * 0.25) % W)
        top = int(gy - self.far.height * min(z, 1.3) * 0.9)
        far = self.far if z == 1 else self.far.resize((self.far.width, int(self.far.height * min(z, 1.3) * 0.9)))
        img.paste(far, (-W - off + int(self.shake[0] * 0.3), top), far)
        d = ImageDraw.Draw(img, "RGBA")
        gy = min(gy, H)
        d.rectangle((0, gy, W, H), fill=self.pal["ground"])
        if self.style == "stick":
            d.rectangle((0, gy, W, H), fill=(246, 243, 233))
            d.line((0, gy, W, gy), fill=(30, 30, 30), width=max(3, int(5 * z)))
        else:
            d.line((0, gy, W, gy), fill=(255, 255, 255, 50), width=2)
        x0 = int((cx - W / z) // 120) * 120
        for wx in range(x0, int(cx + W / z) + 120, 120):
            sx, sy = self.S(wx, 0)
            col = (40, 40, 40, 90) if self.style == "stick" else (255, 255, 255, 25)
            d.line((sx, sy + 10 * z, sx - 30 * z, sy + 40 * z), fill=col, width=2)
        return img, d

    def draw_fighter(self, d, i, pose, x, h, t):
        dd = self.facing[i]
        p = skeleton(pose, x, h, dd)
        z = self.cam[2]
        sp = {k: self.S(*v) for k, v in p.items() if not k.endswith("dir")}
        chains = [("hip", "chest"), ("chest", "bel", "bha"), ("hip", "bkn", "bft"),
                  ("hip", "fkn", "fft"), ("chest", "fel", "fha")]
        col = self.pal["body"][i]
        hx, hy = sp["head"]
        hr = HEAD_R * z
        layers = []
        if self.style == "power":
            g = self.pal["glow"][i]
            layers = [(g + (60,), 18 * z), (col + (255,), 8 * z), ((255, 255, 240, 255), 3 * z)]
        elif self.style == "sword":
            layers = [(col + (255,), 10 * z)]
        else:
            layers = [(col + (255,), 7 * z)]
        if self.style == "sword":
            band = (200, 30, 40) if i == 0 else (235, 235, 235)
            wave_ = math.sin(t * 9 + i) * 6 * z
            d.line((hx, hy - hr * 0.3, hx - dd * 30 * z, hy - hr * 0.2 + wave_,
                    hx - dd * 50 * z, hy + wave_ * 1.5), fill=band, width=max(2, int(4 * z)))
        for fill, w in layers:
            w = max(1, int(w))
            for ch in chains:
                d.line([sp[k] for k in ch], fill=fill, width=w, joint="curve")
                for k in (ch[0], ch[-1]):
                    d.ellipse((sp[k][0] - w / 2, sp[k][1] - w / 2, sp[k][0] + w / 2, sp[k][1] + w / 2), fill=fill)
            r = hr + (w - 3 * z) / 2 if self.style == "power" else hr
            d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=fill)
        if self.style == "power":
            g = self.pal["glow"][i]
            for k in range(4):
                a = math.radians(-60 + k * 35 + math.sin(t * 6 + k) * 4) * dd
                bx, by = hx - dd * hr * 0.3, hy - hr * 0.6
                tipx, tipy = bx - math.sin(a) * hr * 2.1, by - math.cos(a) * hr * 2.1
                d.polygon([(bx - 6 * z, by), (bx + 6 * z, by), (tipx, tipy)], fill=col)
        if self.style == "sword":
            fx, fy = sp["fha"]
            tx, ty = sp["tip"]
            d.line((fx, fy, tx, ty), fill=(225, 225, 240), width=max(2, int(3 * z)))
            hxv, hyv = p["fdir"]
            d.line((fx - hyv * 7 * z, fy + hxv * 7 * z, fx + hyv * 7 * z, fy - hxv * 7 * z),
                   fill=(60, 50, 40), width=max(2, int(4 * z)))
        return p

    def draw_fx(self, d, e, t, front, sk):
        u = (t - e["t0"]) / e["dur"]
        z = self.cam[2]
        k = e["kind"]
        rng = random.Random(int(e["t0"] * 1000))
        if not front:
            if k == "shockwave":
                x, y = self.S(e["x"], 0)
                r = (30 + 260 * u) * z
                d.ellipse((x - r, y - r * 0.2, x + r, y + r * 0.2), outline=(255, 255, 255, int(220 * (1 - u))),
                          width=max(2, int(6 * z * (1 - u))))
            elif k == "dust":
                for j in range(8):
                    a = rng.uniform(-1, 1)
                    x, y = self.S(e["x"] + a * 90 * u, -abs(a) * 30 * u - 10)
                    r = (12 + 25 * u) * z
                    c = (120, 110, 100) if self.style == "stick" else (200, 180, 170)
                    d.ellipse((x - r, y - r, x + r, y + r), fill=c + (int(110 * (1 - u)),))
            elif k == "aura":
                i = e["who"]
                p = sk[i]
                cx, cy = self.S(*p["chest"])
                g = self.pal["glow"][i] if self.pal["glow"] else (255, 220, 80)
                grow = min(1, u * 3)
                for j in range(14):
                    a = j / 14 * math.tau + t * 3
                    flick = 0.7 + 0.3 * math.sin(t * 30 + j * 2.3)
                    rx = 55 * z * grow * flick
                    ry = 110 * z * grow * flick
                    ex, ey = cx + math.cos(a) * rx, cy + 20 * z + math.sin(a) * ry * 0.6 - abs(math.cos(a)) * 20 * z
                    d.polygon([(cx, cy + 90 * z), (ex - 12 * z, ey), (ex, ey - 55 * z * flick), (ex + 12 * z, ey)],
                              fill=g + (70,))
                for j in range(10):
                    px = cx + rng.uniform(-60, 60) * z
                    py = cy + 80 * z - ((t * 260 + j * 37) % 200) * z
                    d.line((px, py, px, py - 14 * z), fill=(255, 255, 255, 160), width=2)
            return
        if k == "impact":
            x, y = self.S(e["x"], e["y"])
            s = e["size"] * z * (0.6 + u)
            pts = []
            for j in range(16):
                r = (60 if j % 2 == 0 else 22) * s * (0.8 + 0.4 * rng.random())
                a = j / 16 * math.tau
                pts.append((x + math.cos(a) * r, y + math.sin(a) * r))
            alpha = int(255 * (1 - u))
            fill = (255, 230, 80, alpha) if self.style != "sword" else (255, 255, 255, alpha)
            d.polygon(pts, fill=fill, outline=(30, 30, 30, alpha) if self.style == "stick" else None)
            r = 18 * s
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, alpha))
        elif k == "spark":
            x, y = self.S(e["x"], e["y"])
            for j in range(14):
                a = rng.uniform(0, math.tau)
                sp = rng.uniform(60, 200) * e["size"] * z
                r0, r1 = sp * u, sp * u + 20 * z
                d.line((x + math.cos(a) * r0, y + math.sin(a) * r0 + 80 * u * u * z,
                        x + math.cos(a) * r1, y + math.sin(a) * r1 + 80 * u * u * z),
                       fill=(255, 220, 120, int(255 * (1 - u))), width=max(1, int(3 * z)))
            r = 25 * z * (1 - u)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 230, int(230 * (1 - u))))
        elif k == "arc":
            alpha = int(255 * (1 - u))
            if e.get("line"):
                x0, y0 = self.S(e["x0"], e["y"])
                x1, y1 = self.S(e["x1"], e["y"])
                for w, a in ((14, 80), (6, 200), (2, 255)):
                    d.line((x0, y0 - 6 * z, x1, y1 + 6 * z), fill=(255, 255, 255, int(a * (1 - u))),
                           width=max(1, int(w * z)))
            else:
                x, y = self.S(e["x"], e["y"])
                r = (95 if e["big"] else 65) * z
                start = -70 if e["d"] > 0 else 110
                d.arc((x - r, y - r, x + r, y + r), start, start + 140,
                      fill=(255, 255, 255, alpha), width=max(2, int(8 * z * (1 - u))))
        elif k == "projectile":
            g = self.pal["glow"][e["who"]] if self.pal["glow"] else (120, 200, 255)
            for j in range(7):
                uu = max(0.0, u - j * 0.035)
                x, y = self.S(e["x0"] + (e["x1"] - e["x0"]) * uu, e["y"])
                r = (26 - j * 3) * z
                d.ellipse((x - r, y - r, x + r, y + r), fill=g + (int(200 - j * 25),))
            x, y = self.S(e["x0"] + (e["x1"] - e["x0"]) * u, e["y"])
            r = 12 * z
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 255))
        elif k == "explosion":
            x, y = self.S(e["x"], e["y"])
            s = e["size"] * z
            for r0, c in ((160, (255, 80, 30)), (110, (255, 170, 40)), (60, (255, 250, 210))):
                r = r0 * s * min(1, u * 3) * (1 + 0.2 * u)
                d.ellipse((x - r, y - r, x + r, y + r), fill=c + (int(230 * (1 - u)),))
            r = 220 * s * u
            d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, int(200 * (1 - u))),
                      width=max(2, int(8 * s)))
        elif k == "beam":
            a, b = e["a"], e["b"]
            ha, hb = sk[a]["fha"], sk[b]["fha"]
            if u < 0.8:
                cxw = e["mid"] + math.sin(u * 16) * 70 * min(1, u * 4)
            else:
                cx0 = e["mid"] + math.sin(0.8 * 16) * 70
                cxw = cx0 + (hb[0] - cx0) * ease((u - 0.8) / 0.2)
            cyw = (ha[1] + hb[1]) / 2
            for (sx, sy), who in ((ha, a), (hb, b)):
                if who == b and u >= 0.8:
                    continue
                g = self.pal["glow"][who]
                p0 = self.S(sx, sy)
                p1 = self.S(cxw, cyw)
                for w, c in ((46, g + (90,)), (26, g + (220,)), (10, (255, 255, 255, 255))):
                    d.line((p0, p1), fill=c, width=max(1, int(w * z * (0.9 + 0.1 * math.sin(t * 40)))))
            x, y = self.S(cxw, cyw)
            r = (55 + 12 * math.sin(t * 25)) * z
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 230))
            r *= 1.5
            d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 240, 180, 160), width=max(2, int(6 * z)))

    def screen_fx(self, img, d, t):
        for e in self.active(t):
            u = (t - e["t0"]) / e["dur"]
            k = e["kind"]
            rng = random.Random(int(t * FPS))
            if k == "speed":
                c = (40, 40, 40) if self.style == "stick" else (255, 255, 255)
                for _ in range(26):
                    y = rng.uniform(0, H)
                    x = rng.uniform(-200, W)
                    d.line((x, y, x + rng.uniform(150, 400), y), fill=c + (int(120 * (1 - u)),), width=2)
            elif k == "flash":
                d.rectangle((0, 0, W, H), fill=(255, 255, 255, int(e["alpha"] * (1 - u))))
            elif k == "fade":
                d.rectangle((0, 0, W, H), fill=(0, 0, 0, int(255 * (1 - u))))
            elif k == "text":
                self.big_text(d, e, u)
            elif k == "vs":
                self.vs_card(d, u)
            elif k == "outro":
                self.outro(d, u, t - e["t0"])

    def big_text(self, d, e, u):
        a = min(1, u * 8) * min(1, (1 - u) * 6)
        size = e["size"] * (1.4 - 0.4 * ease(u * 6))
        f = font(size)
        tw = d.textlength(e["text"], font=f)
        x, y = (W - tw) / 2, H * e["y"] - size / 2
        d.text((x, y), e["text"], font=f, fill=e["color"] + (int(255 * a),),
               stroke_width=max(2, int(size / 18)), stroke_fill=(0, 0, 0, int(255 * a)))
        if e.get("sub"):
            f2 = font(40)
            sw = d.textlength(e["sub"], font=f2)
            d.text(((W - sw) / 2, y + size * 1.15), e["sub"], font=f2, fill=(255, 255, 255, int(255 * a)),
                   stroke_width=3, stroke_fill=(0, 0, 0, int(255 * a)))

    def vs_card(self, d, u):
        a = min(1, u * 6) * min(1, (1 - u) * 5)
        slide = (1 - ease(u * 4)) * 400
        d.polygon([(0, H * 0.3), (W * 0.55, H * 0.3), (W * 0.45, H * 0.7), (0, H * 0.7)],
                  fill=self.pal["body"][0][:3] + (int(200 * a),) if self.style == "power" else (200, 40, 40, int(200 * a)))
        d.polygon([(W * 0.55, H * 0.3), (W, H * 0.3), (W, H * 0.7), (W * 0.45, H * 0.7)],
                  fill=self.pal["body"][1][:3] + (int(200 * a),) if self.style == "power" else (30, 30, 60, int(200 * a)))
        f = font(84)
        n0, n1 = self.f.names
        d.text((W * 0.06 - slide, H * 0.5), n0, font=f, fill=(255, 255, 255, int(255 * a)),
               stroke_width=4, stroke_fill=(0, 0, 0, int(255 * a)))
        w1 = d.textlength(n1, font=f)
        d.text((W * 0.94 - w1 + slide, H * 0.5), n1, font=f, fill=(255, 255, 255, int(255 * a)),
               stroke_width=4, stroke_fill=(0, 0, 0, int(255 * a)))
        f2 = font(130)
        vw = d.textlength("VS", font=f2)
        d.text(((W - vw) / 2, H * 0.22), "VS", font=f2, fill=(255, 220, 60, int(255 * a)),
               stroke_width=6, stroke_fill=(0, 0, 0, int(255 * a)))
        f3 = font(36)
        sub = STYLE_TITLES[self.style].upper()
        sw = d.textlength(sub, font=f3)
        d.text(((W - sw) / 2, H * 0.74), sub, font=f3, fill=(255, 255, 255, int(255 * a)),
               stroke_width=3, stroke_fill=(0, 0, 0, int(255 * a)))

    def outro(self, d, u, el):
        a = min(1, el * 2)
        d.rectangle((0, 0, W, H), fill=(0, 0, 0, int(120 * a)))
        lines = [(f"{self.f.names[self.f.winner]} WINS!", 110, (255, 215, 60)),
                 ("Follow AnimeVerse Hub for more fights", 44, (255, 255, 255)),
                 ("Who should fight next? Comment below!", 40, (255, 160, 220))]
        y = H * 0.22
        for text, size, col in lines:
            f = font(size)
            tw = d.textlength(text, font=f)
            d.text(((W - tw) / 2, y), text, font=f, fill=col + (int(255 * a),),
                   stroke_width=max(2, size // 18), stroke_fill=(0, 0, 0, int(255 * a)))
            y += size * 1.5

    def hud(self, d, t):
        bw, bh, top = 470, 24, 28
        for i in (0, 1):
            hp = self.f.health(i, t) / 100
            x0 = 40 if i == 0 else W - 40 - bw
            d.rectangle((x0 - 3, top - 3, x0 + bw + 3, top + bh + 3), fill=(0, 0, 0, 200))
            d.rectangle((x0, top, x0 + bw, top + bh), fill=(150, 20, 20, 255))
            fw = bw * hp
            if i == 0:
                d.rectangle((x0 + bw - fw, top, x0 + bw, top + bh), fill=(255, 210, 50, 255))
            else:
                d.rectangle((x0, top, x0 + fw, top + bh), fill=(255, 210, 50, 255))
            f = font(28)
            name = self.f.names[i]
            nx = x0 if i == 0 else x0 + bw - d.textlength(name, font=f)
            d.text((nx, top + bh + 6), name, font=f, fill=(255, 255, 255, 255), stroke_width=3,
                   stroke_fill=(0, 0, 0, 255))
            wins = sum(1 for s, e, w in self.f.rounds if w == i and e <= t)
            for k in range(2):
                cx = (x0 + bw + 22) if i == 0 else (x0 - 22)
                cy = top + 4 + k * 18 if False else top + bh / 2
                cx += (k * 20) * (1 if i == 0 else -1)
                d.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=(255, 210, 50, 255) if k < wins else (0, 0, 0, 160),
                          outline=(255, 255, 255, 255))
        f = font(22)
        tag = "AnimeVerse Hub"
        d.text((W - d.textlength(tag, font=f) - 20, H - 38), tag, font=f, fill=(255, 255, 255, 200),
               stroke_width=2, stroke_fill=(0, 0, 0, 200))

    def frame(self, t):
        states = [self.f.tr[i].at(t) for i in (0, 1)]
        for i in (0, 1):
            dx = states[1 - i][1] - states[i][1]
            if abs(dx) > 1:
                self.facing[i] = 1 if dx > 0 else -1
        self.update_camera(states, t)
        img, d = self.background()
        sk = [skeleton(states[i][0], states[i][1], states[i][2], self.facing[i]) for i in (0, 1)]
        live = self.active(t)
        for e in live:
            self.draw_fx(d, e, t, False, sk)
        # the fighter who is down or getting hit is drawn behind
        order = sorted((0, 1), key=lambda i: states[i][0][0] > -20)
        for i in order:
            self.draw_fighter(d, i, *states[i], t)
        for e in live:
            self.draw_fx(d, e, t, True, sk)
        self.hud(d, t)
        self.screen_fx(img, d, t)
        return img


# ---------------------------------------------------------------- audio
def lowpass(x, k):
    return np.convolve(x, np.ones(k) / k, mode="same") if k > 1 else x


def sfx_wave(kind, rng, dur=None):
    def env(n, decay):
        return np.exp(-np.arange(n) / SR * decay)

    if kind in ("hit", "big", "land", "block"):
        n = int(SR * (0.35 if kind == "big" else 0.18))
        t = np.arange(n) / SR
        f0 = {"hit": 120, "big": 80, "land": 60, "block": 300}[kind]
        tone = np.sin(2 * np.pi * (f0 + 150 * np.exp(-t * 40)) * t) * env(n, 18)
        noise = lowpass(rng.standard_normal(n), 3 if kind == "block" else 8) * env(n, 40)
        return (tone * 0.9 + noise * 0.6) * (1.3 if kind == "big" else 0.9)
    if kind == "clank":
        n = int(SR * 0.45)
        t = np.arange(n) / SR
        s = sum(np.sin(2 * np.pi * f * t) / (j + 1) for j, f in enumerate((1250, 1870, 2650, 3400)))
        return s * env(n, 9) * 0.45 + rng.standard_normal(n) * env(n, 60) * 0.3
    if kind in ("whoosh", "slash"):
        n = int(SR * (0.3 if kind == "whoosh" else 0.22))
        e = np.sin(np.linspace(0, np.pi, n)) ** 2
        return lowpass(rng.standard_normal(n), 6 if kind == "whoosh" else 2) * e * (0.7 if kind == "whoosh" else 0.6)
    if kind == "boom":
        n = int(SR * 1.3)
        t = np.arange(n) / SR
        return (lowpass(rng.standard_normal(n), 25) * 2.5 + np.sin(2 * np.pi * (50 + 120 * np.exp(-t * 8)) * t)) \
            * env(n, 3.5) * 0.9
    if kind == "blast":
        n = int(SR * 0.6)
        t = np.arange(n) / SR
        return np.sin(2 * np.pi * (900 * np.exp(-t * 4) + 150) * t) * env(n, 5) * 0.35 \
            + lowpass(rng.standard_normal(n), 4) * env(n, 6) * 0.4
    if kind in ("charge", "beam"):
        n = int(SR * dur)
        t = np.arange(n) / SR
        rise = np.linspace(0, 1, n)
        f = 90 + (220 * rise if kind == "charge" else 40 * np.sin(t * 3))
        ph = 2 * np.pi * np.cumsum(f) / SR
        buzz = np.tanh(np.sin(ph) * 3) * 0.3 + lowpass(rng.standard_normal(n), 5) * 0.35
        trem = 0.7 + 0.3 * np.sin(t * 2 * np.pi * (8 + 10 * rise))
        fade = np.minimum(1, np.minimum(t / 0.1, (dur - t) / 0.15))
        return buzz * trem * fade * (0.5 + 0.5 * rise)
    if kind == "gong":
        n = int(SR * 1.6)
        t = np.arange(n) / SR
        s = sum(np.sin(2 * np.pi * f * t) / (j + 1) for j, f in enumerate((180, 272, 410, 590)))
        return s * env(n, 2.5) * 0.4
    return np.zeros(1)


def soundtrack(fight, path, rng):
    n = int(SR * fight.t) + SR
    out = np.zeros(n)
    t_all = np.arange(n) / SR
    # battle music: 150 bpm minor progression, drums, bass and arpeggio
    bpm, beat = 150, 60 / 150
    progs = [[57, 53, 55, 52], [50, 46, 48, 45], [52, 48, 50, 47], [45, 41, 43, 48]]
    prog = rng.choice(progs)
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    nb = int(fight.t / beat) + 1
    kick_n = int(0.18 * SR)
    kt = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * (50 + 110 * np.exp(-kt * 35)) * kt) * np.exp(-kt * 14)
    snare_n = int(0.16 * SR)
    snare = rng.standard_normal(snare_n) * np.exp(-np.arange(snare_n) / SR * 22)
    hat_n = int(0.05 * SR)
    hat = np.diff(rng.standard_normal(hat_n + 1)) * np.exp(-np.arange(hat_n) / SR * 80) * 0.5
    for b in range(nb):
        s = int(b * beat * SR)
        root = prog[(b // 8) % len(prog)]
        intro = b * beat < 5.6

        def put(sig, at, g):
            e = min(n, at + len(sig))
            if at < n:
                out[at:e] += sig[: e - at] * g

        if not intro:
            put(kick, s, 0.55)
            if b % 2 == 1:
                put(snare, s, 0.22)
        for h in range(2):
            put(hat, s + int(h * beat / 2 * SR), 0.18)
        for h in range(2):
            ln = int(beat / 2 * SR)
            tt = np.arange(ln) / SR
            bass = np.tanh(np.sin(2 * np.pi * hz(root - 12) * tt) * 2) * np.exp(-tt * 6)
            put(bass, s + int(h * beat / 2 * SR), 0.16)
        for h in range(4):
            ln = int(beat / 4 * SR)
            tt = np.arange(ln) / SR
            note = root + 12 + [0, 3, 7, 12, 10, 7, 3, 7][(b * 4 + h) % 8]
            lead = (np.sin(2 * np.pi * hz(note) * tt) + 0.3 * np.sin(4 * np.pi * hz(note) * tt)) * np.exp(-tt * 9)
            put(lead, s + int(h * beat / 4 * SR), 0.07)
    music_fade = np.minimum(1, np.minimum(t_all / 1.5, np.maximum(0, (fight.t - t_all) / 3)))
    out *= music_fade
    for s in fight.sfx:
        sig = sfx_wave(s["kind"], rng, s.get("dur"))
        at = int(s["t"] * SR)
        e = min(n, at + len(sig))
        if at < n:
            out[at:e] += sig[: e - at] * s.get("vol", 1.0)
    out = out[: int(SR * fight.t)]
    out /= max(1e-6, np.percentile(np.abs(out), 99.7))
    out = np.tanh(out * 0.8) * 0.95
    pcm = (out * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- main
def make_post(fight):
    a, b = fight.names
    w = fight.names[fight.winner]
    style = STYLE_TITLES[fight.style]
    title = f"{a} vs {b} | Epic Anime {style} | AnimeVerse Hub"
    desc = (f"⚔️ {a} vs {b}. 7 minutes, 3 rounds, one winner. 🔥\n\n"
            f"Did {w} deserve the win? Who should fight next? Drop it in the comments 👇\n"
            f"Follow AnimeVerse Hub for a new fight every few hours!\n\n"
            "#anime #animefight #animation #fightscene #AnimeVerseHub")
    return {"title": title, "description": desc, "style": fight.style, "names": [a, b], "winner": w}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="mix", choices=["mix", "stick", "power", "sword"])
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--duration", type=float, default=420)
    ap.add_argument("--out", default="fight.mp4")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else time.time_ns() % 2**31
    rng = random.Random(seed)
    style = args.style if args.style != "mix" else rng.choice(["stick", "power", "sword"])
    names = rng.sample(NAMES, 2)
    fight = Fight(rng, style, names, args.duration)
    fight.build()
    renderer = Renderer(fight, random.Random(seed + 1))
    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.wav")
        soundtrack(fight, audio, np.random.default_rng(seed))
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", args.out],
            stdin=subprocess.PIPE)
        frames = int(fight.t * FPS)
        for k in range(frames):
            ff.stdin.write(renderer.frame(k / FPS).tobytes())
            if k % (FPS * 30) == 0:
                print(f"rendered {k / FPS:.0f}s / {fight.t:.0f}s", file=sys.stderr)
        ff.stdin.close()
        if ff.wait() != 0:
            sys.exit("ffmpeg failed")
    post = make_post(fight)
    post["seed"] = seed
    print(json.dumps(post))


if __name__ == "__main__":
    main()
