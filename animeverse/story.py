"""Render a short, original anime story Reel (1080x1920, 30fps, ~45-70s, music + text blips).

Every run invents two characters (name, hair, eyes, outfit, accessory) and a story
from a built-in bank of genres and plot beats, then animates it visual-novel
style: drawn characters that blink, talk and react, a narrated setting, a
looming villain, effects and synthesized music. No AI service or API key needed,
and nothing copyrighted is used.

Usage: python story.py [--seed N] [--out clip.mp4]
Prints the post caption/tags as JSON (same shape post_reel.py expects).
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS, SR = 1080, 1920, 30, 44100
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
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


def mix(c1, c2, k):
    return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))


# ---------------------------------------------------------------- story bank
# A line is (speaker, text, expression, effect). Speakers: N narrator, A hero, B partner, V villain.
GENRES = {
    "fantasy": {
        "places": [("the Crystal Forest", "forest"), ("the floating city of Aerith", "sky"),
                   ("the ruins of Castle Vael", "ruins")],
        "items": [("a glowing dragon egg", "Dragon Egg"), ("a cracked moon-stone", "Moon-Stone"),
                  ("a sword that hums at night", "Humming Sword"), ("a map drawn in starlight", "Starlight Map")],
        "powers": ["fire", "lightning", "starlight", "shadow"],
        "villains": ["the Ash King", "Lady Morrow", "the Hollow Knight"],
        "outfits": ["armor", "kimono", "hoodie"],
        "titles": ["{A} and the {ItemTitle}", "The Heir of {PlaceTitle}", "{A}: The {Power} Awakens"],
        "beats": [
            [[("N", "In {place}, legends say {item} chooses its own master."),
              ("A", "Then why did it land on MY doorstep?!", "surprised")],
             [("N", "Nobody in {place} had seen real magic for a hundred years."),
              ("A", "Until this morning... when I found {item}.", "serious")],
             [("A", "Another boring day of chores in {place}...", "sad"),
              ("N", "It was the last boring day of {A}'s life.")]],
            [[("B", "Hand it over. You have no idea what you're holding.", "angry"),
              ("A", "And you do? Who even are you?", "angry")],
             [("B", "Finally! I've been searching for the one who woke it.", "happy"),
              ("A", "Woke it...? It's ALIVE?!", "surprised")],
             [("B", "Relax. I'm not your enemy. Not yet, anyway.", "smug"),
              ("A", "That's... not comforting at all.", "sad")]],
            [[("N", "Then the sky turned black.", None, "shock"),
              ("V", "That treasure is mine. Give it back, little thief.", None, "dark")],
             [("N", "The ground split open, and {V} rose from the dark.", None, "shock"),
              ("V", "Ahh... the key, delivered right to my door.", None, "dark")]],
            [[("B", "Run! We can't beat {V} like this!", "surprised"),
              ("A", "No. I'm done running.", "serious", "aura")],
             [("A", "My hands... they're burning with {power}!", "surprised", "aura"),
              ("B", "It's choosing you, {A}. Don't fight it!", "serious")]],
            [[("V", "Didn't {B} tell you? {B} works for ME.", None, "dark"),
              ("B", "...I did. But that was before I met you, {A}.", "sad")],
             [("B", "Wait... that mark on your hand. You're the lost heir!", "surprised"),
              ("A", "The lost WHAT?!", "surprised")],
             [("V", "Fool. It was never a weapon. It was a prison... and you opened it.", None, "dark"),
              ("A", "Then I'll close it again. With you inside!", "angry")]],
            [[("A", "Everything I have... take it! {POWER} STRIKE!", "angry", "flash"),
              ("N", "Light swallowed the whole sky.", None, "flash")],
             [("B", "Together, {A}! On three!", "serious", "aura"),
              ("A", "THREE!", "angry", "flash")]],
            [[("N", "{V} was gone. But {item} had started to crack...", None, "dark"),
              ("A", "Hey, {B}... was it supposed to do that?", "surprised")],
             [("B", "We won... right?", "happy"),
              ("N", "Far away, a second pair of red eyes opened.", None, "dark")]],
        ],
    },
    "school": {
        "places": [("the school rooftop", "rooftop"), ("Class 2-B after school", "classroom"),
                   ("the cherry blossom path", "sakura")],
        "items": [("a love letter with no name", "Nameless Letter"), ("a lost diary", "Lost Diary"),
                  ("a flyer for a club that doesn't exist", "Club That Doesn't Exist"),
                  ("a broken music box", "Broken Music Box")],
        "powers": ["courage", "honesty", "friendship"],
        "villains": [],
        "outfits": ["sailor", "blazer", "hoodie"],
        "titles": ["{A} and the {ItemTitle}", "{A}, {B} and the {ItemTitle}", "The {ItemTitle} Mystery"],
        "beats": [
            [[("N", "It started with {item}, left on {A}'s desk."),
              ("A", "Who would leave this... for ME?", "surprised")],
             [("A", "Okay. Deep breath. Today I finally say it.", "serious"),
              ("N", "{A} had been practicing for three weeks.")]],
            [[("B", "Oh! Is that... where did you get that?!", "surprised", "sparkle"),
              ("A", "You recognize it? Don't tell me it's yours.", "smug")],
             [("B", "You're late again, {A}. Of course you are.", "smug"),
              ("A", "I was busy! Doing... important things.", "sad")]],
            [[("N", "Then the bell rang, and everyone else vanished.", None, "shock"),
              ("A", "Wait. Where did the whole class go?", "surprised")],
             [("N", "The wind tore {item} out of {A}'s hands.", None, "shock"),
              ("B", "It's going over the fence! GRAB IT!", "surprised", "speed")]],
            [[("B", "If anyone reads that, my life is over!", "sad"),
              ("A", "Then I won't let anyone read it. Promise.", "serious")],
             [("A", "Why are you blushing like that?", "smug"),
              ("B", "I'm NOT blushing! It's the sunset!", "angry", "sparkle")]],
            [[("B", "...Fine. I wrote it. For you, {A}.", "sad", "sparkle"),
              ("A", "For... me?", "surprised")],
             [("A", "Wait. This handwriting... it's mine?!", "surprised", "shock"),
              ("B", "You don't remember writing it? Seriously?", "surprised")]],
            [[("A", "{B}! There's something I need to tell you too!", "serious", "sparkle"),
              ("N", "The cherry blossoms stopped falling, just for a second.", None, "sparkle")],
             [("B", "Then say it already! Before I lose my nerve!", "angry", "sparkle"),
              ("A", "I... I'll be honest with you. Always.", "happy", "sparkle")]],
            [[("B", "So... same time tomorrow?", "happy"),
              ("N", "Neither of them noticed the second letter in the locker.")],
             [("A", "Best. Day. EVER.", "happy", "sparkle"),
              ("N", "Somewhere, someone else was reading the diary.", None, "dark")]],
        ],
    },
    "scifi": {
        "places": [("Neo-Tokyo, 2099", "neon"), ("Orbital Station Kaguya", "space"),
                   ("the neon underground", "neon")],
        "items": [("a stolen AI chip", "Stolen Chip"), ("a memory drive with no owner", "Memory Drive"),
                  ("an android arm that still moves", "Android Arm")],
        "powers": ["overclock", "plasma", "hacking"],
        "villains": ["Unit ZERO", "the Director", "OMEGA"],
        "outfits": ["tech", "hoodie", "armor"],
        "titles": ["{A}: System Override", "Ghost of {PlaceTitle}", "The {ItemTitle}"],
        "beats": [
            [[("N", "In {place}, everyone is tracked. Everyone except {A}."),
              ("A", "One last job. Then I'm out for good.", "serious")],
             [("N", "Three seconds after {A} touched {item}, every alarm went off.", None, "shock"),
              ("A", "Oh, that's not good.", "surprised")]],
            [[("B", "Don't move. Drop the chip, runner.", "angry"),
              ("A", "Love the confidence. Hate the aim.", "smug")],
             [("B", "Systems online. Hello, {A}. I've been waiting.", "neutral"),
              ("A", "You're... an android?", "surprised")]],
            [[("V", "Unauthorized access detected. Deleting {A}.", None, "dark"),
              ("N", "Every screen in {place} turned red.", None, "shock")],
             [("V", "You took something of mine. I'm taking it back.", None, "dark"),
              ("B", "That's {V}. We need to go. NOW.", "surprised", "speed")]],
            [[("A", "Can you hack the door or not?!", "angry", "speed"),
              ("B", "Ninety percent done. Ninety-one...", "serious")],
             [("B", "My power cell is failing, {A}. Leave me.", "sad"),
              ("A", "Not happening. We leave together.", "serious", "aura")]],
            [[("B", "Wait. My memories... they're YOURS, {A}.", "surprised", "shock"),
              ("A", "That's impossible. Isn't it?", "sad")],
             [("V", "Who do you think built {B}? I did.", None, "dark"),
              ("B", "Then I'll be the bug in your system.", "angry")]],
            [[("A", "Full {power}! Everything we've got!", "angry", "flash"),
              ("N", "The whole city went dark for one second.", None, "flash")],
             [("B", "Uploading the virus... NOW!", "serious", "aura"),
              ("V", "No... NO! This isn't possible!", None, "flash")]],
            [[("N", "{V} went offline. For now.", None, "dark"),
              ("A", "So, partner... how do you feel about being a runner?", "happy")],
             [("B", "Mission complete.", "happy"),
              ("N", "Somewhere deep in the network, {V} rebooted.", None, "dark")]],
        ],
    },
    "yokai": {
        "places": [("the old shrine at midnight", "shrine"), ("a foggy mountain village", "village")],
        "items": [("a white fox mask", "Fox Mask"), ("a paper charm that won't burn", "Unburnable Charm"),
                  ("a bell that rings by itself", "Ringing Bell")],
        "powers": ["spirit fire", "moonlight", "the old words"],
        "villains": ["the Nine-Tailed Shadow", "the Mist Oni", "the Hungry Ghost"],
        "outfits": ["kimono", "blazer", "hoodie"],
        "titles": ["The {ItemTitle} of {PlaceTitle}", "{A} and the Spirit Fox", "Midnight at the Shrine"],
        "beats": [
            [[("N", "Grandma always said: never visit {place} after dark."),
              ("A", "So, of course, here I am.", "smug")],
             [("N", "{A} found {item} in the attic. It was warm.", None),
              ("A", "Why does it feel like it's watching me?", "surprised")]],
            [[("B", "You can see me? Nobody has seen me in 300 years.", "surprised"),
              ("A", "You have FOX EARS. How could I miss that?", "surprised")],
             [("B", "Little human. You're wearing my face.", "smug"),
              ("A", "Wait, this mask is YOURS?", "surprised")]],
            [[("N", "The lanterns went out, one by one.", None, "shock"),
              ("V", "A living soul... how delicious.", None, "dark")],
             [("V", "The seal is broken. Thank you, child.", None, "dark"),
              ("B", "{V}... it's free?!", "surprised", "shock")]],
            [[("B", "Hold my hand. Whatever you do, don't let go.", "serious"),
              ("A", "Your hand is freezing!", "surprised")],
             [("A", "There has to be a way to seal it again!", "angry"),
              ("B", "There is. But it costs a memory.", "sad")]],
            [[("B", "I'm the one who was sealed first, {A}. With {V}.", "sad"),
              ("A", "Then I'm not leaving without you.", "serious", "aura")],
             [("V", "Your grandmother made a promise to me, child.", None, "dark"),
              ("A", "Then I'm the one who breaks it!", "angry", "aura")]],
            [[("A", "By {power}... I seal you!", "angry", "flash"),
              ("N", "Every bell in the village rang at once.", None, "flash")],
             [("B", "Now, {A}! Say the old words with me!", "serious", "aura"),
              ("N", "Blue fire filled the night.", None, "flash")]],
            [[("N", "Morning came. {B} was gone. Only the mask remained.", None, "dark"),
              ("A", "...Same time tonight, fox?", "happy")],
             [("B", "Thank you, {A}. I'll be watching over you.", "happy", "sparkle"),
              ("N", "But one bell kept ringing.", None, "dark")]],
        ],
    },
}

FIRST_NAMES = ["Haru", "Yuki", "Ren", "Aoi", "Kai", "Mio", "Sora", "Hina", "Riku", "Nao", "Akane", "Kenta",
               "Rin", "Takumi", "Emi", "Daichi", "Saki", "Haruto", "Kaede", "Yuto", "Mei", "Shun", "Nana", "Toma"]
HAIR = [(30, 30, 40), (90, 55, 35), (240, 205, 110), (220, 225, 240), (250, 150, 190), (70, 120, 230),
        (200, 50, 60), (140, 80, 200), (60, 180, 170), (255, 140, 60)]
EYES = [(60, 140, 240), (230, 70, 80), (90, 200, 120), (170, 90, 230), (240, 170, 50), (60, 200, 220)]
SKIN = [(255, 228, 210), (250, 214, 188), (230, 190, 160), (200, 150, 115), (160, 110, 80)]
STYLES = ["short", "spiky", "long", "twintails", "ponytail", "bob"]
OUTFIT_COLORS = [(40, 50, 90), (180, 40, 60), (40, 110, 80), (230, 230, 235), (60, 60, 70), (120, 70, 160)]
ACCENTS = [(230, 60, 70), (250, 200, 60), (80, 200, 255), (255, 120, 200), (120, 230, 140)]


def make_character(rng, name, genre, avoid=None):
    while True:
        c = dict(name=name, hair=rng.choice(HAIR), eyes=rng.choice(EYES), skin=rng.choice(SKIN),
                 style=rng.choice(STYLES), outfit=rng.choice(GENRES[genre]["outfits"]),
                 cloth=rng.choice(OUTFIT_COLORS), accent=rng.choice(ACCENTS),
                 extra=rng.choice([None, None, "clip", "headband", "glasses", "scar"]))
        if not avoid or (c["hair"] != avoid["hair"] and c["style"] != avoid["style"]):
            return c


# Recurring cast drawn as AI art (art/chars/*.png, cut out by art/key.py): (name, file, name-tag/aura color).
# Genres with a cast use it; the drawn characters are only a fallback when no art is available.
ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art", "chars")
CAST = {
    "fantasy": [("Kael", "kael", (130, 80, 210)), ("Seris", "seris", (80, 140, 220)), ("Riven", "riven", (220, 100, 40))],
    "school": [("Haruto", "haruto", (150, 95, 55)), ("Aoi", "aoi", (120, 70, 180)), ("Mina", "mina", (235, 135, 80))],
    "scifi": [("Nova", "nova", (30, 160, 220)), ("Rook", "rook", (210, 50, 60))],
}


def available_cast():
    return {g: c for g, c in CAST.items()
            if all(os.path.exists(os.path.join(ART_DIR, f + ".png")) for _, f, _ in c)}


def write_story(rng):
    cast = available_cast()
    genre = rng.choice(sorted(cast) if cast else list(GENRES))
    g = GENRES[genre]
    if genre in cast:
        (a_name, a_file, a_col), (b_name, b_file, b_col) = rng.sample(cast[genre], 2)
        A = dict(name=a_name, sprite=os.path.join(ART_DIR, a_file + ".png"), hair=a_col, accent=a_col)
        B = dict(name=b_name, sprite=os.path.join(ART_DIR, b_file + ".png"), hair=b_col, accent=b_col)
    else:
        a_name, b_name = rng.sample(FIRST_NAMES, 2)
        A = make_character(rng, a_name, genre)
        B = make_character(rng, b_name, genre, avoid=A)
    if genre == "yokai" and "sprite" not in B:
        B["extra"] = "foxears"
        B["hair"] = rng.choice([(235, 235, 245), (250, 170, 80), (220, 225, 240)])
    place, bg = rng.choice(g["places"])
    item, item_title = rng.choice(g["items"])
    power = rng.choice(g["powers"])
    villain = rng.choice(g["villains"]) if g["villains"] else None
    slots = dict(A=a_name, B=b_name, V=villain or "", place=place, item=item, ItemTitle=item_title,
                 power=power, POWER=power.upper(), Power=power.title(),
                 PlaceTitle=place.replace("the ", "").title().replace(" Of ", " of ").replace(" At ", " at "))
    lines = []
    for beat, options in enumerate(g["beats"]):
        for ln in rng.choice(options):
            spk, text = ln[0], ln[1]
            expr = ln[2] if len(ln) > 2 and ln[2] else "neutral"
            fx = ln[3] if len(ln) > 3 else None
            lines.append(dict(speaker=spk, text=text.format(**slots), expr=expr, fx=fx, beat=beat))
    title = rng.choice(g["titles"]).format(**slots)
    return dict(genre=genre, title=title, A=A, B=B, villain=villain, place=place, bg=bg, lines=lines,
                item=item)


# ---------------------------------------------------------------- characters
EXPR = {  # brow inner/outer y offsets (fraction of R), eye mode, mouth
    "neutral": (0, 0, "open", "line"),
    "happy": (-0.05, -0.03, "closed", "smile"),
    "sad": (-0.1, 0.05, "open", "frown"),
    "angry": (0.1, -0.06, "lid", "shout"),
    "surprised": (-0.12, -0.12, "small", "o"),
    "smug": (0.03, -0.08, "lid", "smirk"),
    "serious": (0.06, -0.02, "lid", "line"),
}


def draw_character(d, c, cx, cy, R, expr, t, talking, dim, flip):
    shade = (lambda col: mix(col, (25, 20, 45), 0.45)) if dim else (lambda col: col)
    hair, dark_hair = shade(c["hair"]), shade(mix(c["hair"], (0, 0, 0), 0.35))
    skin, skin_sh = shade(c["skin"]), shade(mix(c["skin"], (150, 80, 90), 0.25))
    cloth, accent = shade(c["cloth"]), shade(c["accent"])
    white = shade((250, 250, 255))
    line = shade((40, 25, 35))
    st = c["style"]
    fl = -1 if flip else 1

    # back hair
    if st == "long":
        pts = [(cx - R * 1.12, cy - R * 0.4)]
        for k in range(9):
            x = cx - R * 1.25 + k * R * 2.5 / 8
            pts.append((x, cy + R * 2.3 + (R * 0.18 if k % 2 else 0)))
        pts.append((cx + R * 1.12, cy - R * 0.4))
        d.polygon(pts, fill=dark_hair)
    elif st == "twintails":
        for s in (-1, 1):
            sway = math.sin(t * 2 + s) * R * 0.05
            d.ellipse((cx + s * R * 1.25 - R * 0.42 + sway, cy - R * 0.7, cx + s * R * 1.25 + R * 0.42 + sway,
                       cy + R * 2.0), fill=hair)
            d.ellipse((cx + s * R * 0.95 - R * 0.15, cy - R * 0.85, cx + s * R * 0.95 + R * 0.15, cy - R * 0.55),
                      fill=accent)
    elif st == "ponytail":
        sway = math.sin(t * 2) * R * 0.08
        d.polygon([(cx - fl * R * 0.6, cy - R * 0.9), (cx - fl * R * 1.6 + sway, cy + R * 0.2),
                   (cx - fl * R * 1.3 + sway, cy + R * 1.6), (cx - fl * R * 0.9, cy + R * 0.2)], fill=hair)
    elif st == "bob":
        d.rounded_rectangle((cx - R * 1.15, cy - R * 0.9, cx + R * 1.15, cy + R * 0.95), int(R * 0.5), fill=dark_hair)
    d.ellipse((cx - R * 1.1, cy - R * 1.18, cx + R * 1.1, cy + R * 0.6), fill=hair)

    # body
    d.rectangle((cx - R * 0.22, cy + R * 0.7, cx + R * 0.22, cy + R * 1.3), fill=skin_sh)
    body = [(cx - R * 0.35, cy + R * 1.15), (cx - R * 1.3, cy + R * 1.5), (cx - R * 1.55, cy + R * 4.5),
            (cx + R * 1.55, cy + R * 4.5), (cx + R * 1.3, cy + R * 1.5), (cx + R * 0.35, cy + R * 1.15)]
    o = c["outfit"]
    if o == "hoodie":
        d.ellipse((cx - R * 0.95, cy + R * 0.95, cx + R * 0.95, cy + R * 1.6), fill=shade(mix(c["cloth"], (0, 0, 0), 0.3)))
    d.polygon(body, fill=cloth)
    if o == "sailor":
        d.polygon([(cx - R * 1.2, cy + R * 1.47), (cx, cy + R * 2.3), (cx + R * 1.2, cy + R * 1.47),
                   (cx + R * 0.35, cy + R * 1.15), (cx - R * 0.35, cy + R * 1.15)], fill=white)
        d.polygon([(cx - R * 1.1, cy + R * 1.55), (cx, cy + R * 2.15), (cx + R * 1.1, cy + R * 1.55)],
                  outline=shade(c["cloth"]), width=max(2, int(R * 0.04)))
        d.polygon([(cx, cy + R * 2.0), (cx - R * 0.4, cy + R * 2.25), (cx - R * 0.3, cy + R * 2.6),
                   (cx, cy + R * 2.2), (cx + R * 0.3, cy + R * 2.6), (cx + R * 0.4, cy + R * 2.25)], fill=accent)
    elif o == "blazer":
        d.polygon([(cx - R * 0.35, cy + R * 1.15), (cx, cy + R * 2.4), (cx + R * 0.35, cy + R * 1.15)], fill=white)
        d.polygon([(cx - R * 0.08, cy + R * 1.35), (cx + R * 0.08, cy + R * 1.35), (cx + R * 0.13, cy + R * 2.3),
                   (cx, cy + R * 2.45), (cx - R * 0.13, cy + R * 2.3)], fill=accent)
        for s in (-1, 1):
            d.line((cx + s * R * 0.35, cy + R * 1.15, cx + s * R * 0.05, cy + R * 2.6), fill=line,
                   width=max(2, int(R * 0.03)))
    elif o == "hoodie":
        for s in (-1, 1):
            d.line((cx + s * R * 0.25, cy + R * 1.3, cx + s * R * 0.3, cy + R * 2.2), fill=white,
                   width=max(2, int(R * 0.04)))
    elif o == "armor":
        for s in (-1, 1):
            d.ellipse((cx + s * R * 1.15 - R * 0.42, cy + R * 1.25, cx + s * R * 1.15 + R * 0.42, cy + R * 1.9),
                      fill=shade((170, 175, 190)), outline=accent, width=max(2, int(R * 0.05)))
        d.polygon([(cx - R * 0.6, cy + R * 1.5), (cx + R * 0.6, cy + R * 1.5), (cx, cy + R * 2.4)],
                  fill=shade((150, 155, 175)))
        d.ellipse((cx - R * 0.15, cy + R * 1.65, cx + R * 0.15, cy + R * 1.95), fill=accent)
    elif o == "kimono":
        for s in (-1, 1):
            d.line((cx + s * R * 0.4, cy + R * 1.15, cx - s * R * 0.3, cy + R * 2.6), fill=white,
                   width=max(3, int(R * 0.12)))
        d.rectangle((cx - R * 1.38, cy + R * 2.7, cx + R * 1.38, cy + R * 3.1), fill=accent)
    elif o == "tech":
        for s in (-1, 1):
            d.line((cx + s * R * 0.4, cy + R * 1.2, cx + s * R * 1.05, cy + R * 1.55, cx + s * R * 1.15, cy + R * 3),
                   fill=accent, width=max(2, int(R * 0.05)))
        d.rectangle((cx - R * 0.35, cy + R * 1.15, cx + R * 0.35, cy + R * 1.4), fill=shade((40, 40, 50)))

    # face
    face = []
    for k in range(41):
        a = k / 40 * math.tau
        x, y = math.sin(a), -math.cos(a)
        if y > 0:
            x *= 1 - 0.38 * y ** 1.5
            y *= 1.08
        face.append((cx + x * R * 0.88, cy + y * R))
    d.polygon(face, fill=skin)
    d.ellipse((cx - R * 0.6, cy + R * 0.25, cx - R * 0.3, cy + R * 0.42), fill=shade((255, 160, 170)) + (0,))

    brow_in, brow_out, eye_mode, mouth = EXPR.get(expr, EXPR["neutral"])
    blink = (t * 1.0 + c["name"].__len__() * 0.37) % 3.7 < 0.12
    ey = cy + R * 0.12
    for s in (-1, 1):
        ex = cx + s * R * 0.38
        ew, eh = R * 0.2, R * 0.24
        if blink or eye_mode == "closed":
            d.arc((ex - ew, ey - eh * 0.6, ex + ew, ey + eh * 0.9), 200, 340, fill=line, width=max(3, int(R * 0.05)))
        else:
            d.ellipse((ex - ew, ey - eh, ex + ew, ey + eh), fill=white)
            iw = ew * (0.55 if eye_mode == "small" else 0.85)
            ih = eh * (0.6 if eye_mode == "small" else 0.88)
            iris = shade(c["eyes"])
            d.ellipse((ex - iw, ey - ih + eh * 0.1, ex + iw, ey + ih + eh * 0.1), fill=iris)
            d.ellipse((ex - iw * 0.5, ey - ih * 0.4 + eh * 0.1, ex + iw * 0.5, ey + ih * 0.5 + eh * 0.1),
                      fill=shade(mix(c["eyes"], (0, 0, 0), 0.6)))
            d.ellipse((ex - iw * 0.55, ey - ih * 0.7, ex - iw * 0.05, ey - ih * 0.15), fill=white)
            d.ellipse((ex + iw * 0.2, ey + ih * 0.3, ex + iw * 0.45, ey + ih * 0.55), fill=white)
            if eye_mode == "lid":
                d.rectangle((ex - ew * 1.1, ey - eh * 1.1, ex + ew * 1.1, ey - eh * 0.35), fill=skin)
            d.line((ex - ew * 1.1, ey - eh * (0.35 if eye_mode == "lid" else 0.95) + s * 0,
                    ex + ew * 1.1, ey - eh * (0.35 if eye_mode == "lid" else 0.95) - (eh * 0.15 if eye_mode != "lid" else 0)),
                   fill=line, width=max(3, int(R * 0.06)))
        bx_in, bx_out = ex - s * ew * 0.9, ex + s * ew * 1.1
        by = ey - eh * 1.6
        d.line((bx_in, by + brow_in * R, bx_out, by + brow_out * R), fill=dark_hair, width=max(3, int(R * 0.055)))
        if expr in ("happy", "smug") or (expr == "neutral" and c.get("blush")):
            d.ellipse((ex - R * 0.15, ey + R * 0.2, ex + R * 0.15, ey + R * 0.32), fill=shade((255, 150, 160)))
    if c["extra"] == "glasses":
        for s in (-1, 1):
            ex = cx + s * R * 0.38
            d.rounded_rectangle((ex - R * 0.27, ey - R * 0.22, ex + R * 0.27, ey + R * 0.25), int(R * 0.08),
                                outline=line, width=max(2, int(R * 0.035)))
        d.line((cx - R * 0.11, ey, cx + R * 0.11, ey), fill=line, width=max(2, int(R * 0.03)))
    if c["extra"] == "scar":
        d.line((cx + fl * R * 0.5, ey + R * 0.25, cx + fl * R * 0.3, ey + R * 0.45), fill=skin_sh, width=max(2, int(R * 0.04)))
    d.line((cx + fl * R * 0.03, cy + R * 0.42, cx + fl * R * 0.07, cy + R * 0.47), fill=skin_sh, width=max(2, int(R * 0.03)))

    my = cy + R * 0.66
    mw = R * 0.16
    open_ = talking and int(t * 9) % 2 == 0
    if mouth == "shout" or (open_ and mouth not in ("o",)):
        h = R * (0.16 if mouth == "shout" else 0.1)
        d.polygon([(cx - mw, my - h * 0.3), (cx + mw, my - h * 0.3), (cx + mw * 0.6, my + h), (cx - mw * 0.6, my + h)],
                  fill=shade((140, 40, 50)))
    elif mouth == "o":
        d.ellipse((cx - mw * 0.5, my - R * 0.06, cx + mw * 0.5, my + R * 0.1), fill=shade((140, 40, 50)))
    elif mouth == "smile":
        d.chord((cx - mw, my - R * 0.1, cx + mw, my + R * 0.12), 0, 180, fill=shade((140, 40, 50)))
    elif mouth == "frown":
        d.arc((cx - mw * 0.8, my, cx + mw * 0.8, my + R * 0.16), 200, 340, fill=line, width=max(2, int(R * 0.035)))
    elif mouth == "smirk":
        d.line((cx - mw * 0.6, my, cx + mw * 0.3 * fl, my, cx + mw * 0.8 * fl, my - R * 0.06), fill=line,
               width=max(2, int(R * 0.035)))
    else:
        d.line((cx - mw * 0.5, my, cx + mw * 0.5, my), fill=line, width=max(2, int(R * 0.035)))

    # front hair: cap over the top of the head with a zigzag of bangs across the forehead
    pts = []
    for k in range(0, 21):
        a = math.pi + k / 20 * math.pi
        pts.append((cx + math.cos(a) * R * 1.08, cy - R * 0.15 + math.sin(a) * R * 1.05))
    n = 7
    for k in range(n, -1, -1):
        x = cx - R * 1.0 + k * R * 2.0 / n
        if k in (0, n):
            pts.append((x, cy + R * (0.55 if st in ("long", "bob", "twintails") else 0.15)))
        elif k % 2:
            pts.append((x + R * 0.08 * fl, cy - R * (0.12 + 0.08 * ((k * 7) % 3))))
        else:
            pts.append((x, cy - R * 0.55))
    d.polygon(pts, fill=hair)
    if st == "spiky":
        for k in range(7):
            a = math.radians(-160 + k * 23)
            bx, by = cx + math.cos(a) * R * 0.95, cy - R * 0.15 + math.sin(a) * R * 0.95
            tx, ty = cx + math.cos(a) * R * 1.55, cy - R * 0.15 + math.sin(a) * R * 1.55
            px, py = -math.sin(a) * R * 0.22, math.cos(a) * R * 0.22
            d.polygon([(bx - px, by - py), (bx + px, by + py), (tx, ty)], fill=hair)
    d.arc((cx - R * 0.8, cy - R * 1.05, cx + R * 0.8, cy + R * 0.2), 210, 300, fill=shade(mix(c["hair"], (255, 255, 255), 0.45)),
          width=max(3, int(R * 0.07)))
    if c["extra"] == "clip":
        x0, x1 = sorted((cx + fl * R * 0.55, cx + fl * R * 0.8))
        d.rectangle((x0, cy - R * 0.55, x1, cy - R * 0.47), fill=accent)
    elif c["extra"] == "headband":
        d.arc((cx - R * 1.05, cy - R * 1.2, cx + R * 1.05, cy + R * 0.6), 195, 345, fill=accent, width=max(4, int(R * 0.1)))
    elif c["extra"] == "foxears":
        for s in (-1, 1):
            bx = cx + s * R * 0.6
            d.polygon([(bx - R * 0.3, cy - R * 0.9), (bx + s * R * 0.15, cy - R * 1.75), (bx + R * 0.3, cy - R * 0.95)], fill=hair)
            d.polygon([(bx - R * 0.15, cy - R * 0.95), (bx + s * R * 0.12, cy - R * 1.5), (bx + R * 0.15, cy - R * 0.98)],
                      fill=shade((255, 170, 190)))


def draw_villain(d, cx, cy, R, t, alpha):
    if alpha <= 0:
        return
    for k in range(5, 0, -1):
        r = R * (1.2 + k * 0.18 + 0.05 * math.sin(t * 3 + k))
        d.ellipse((cx - r * 1.3, cy - r, cx + r * 1.3, cy + r * 1.6), fill=(140, 40, 200, int(alpha * 22)))
    body = (10, 5, 20, int(alpha * 235))
    d.polygon([(cx - R * 0.4, cy + R * 0.7), (cx - R * 2.2, cy + R * 1.6), (cx - R * 2.6, cy + R * 3.5),
               (cx + R * 2.6, cy + R * 3.5), (cx + R * 2.2, cy + R * 1.6), (cx + R * 0.4, cy + R * 0.7)], fill=body)
    d.ellipse((cx - R, cy - R * 1.1, cx + R, cy + R), fill=body)
    for s in (-1, 1):
        d.polygon([(cx + s * R * 0.55, cy - R * 0.85), (cx + s * R * 1.1, cy - R * 1.9), (cx + s * R * 0.85, cy - R * 0.6)],
                  fill=body)
        glow = 0.75 + 0.25 * math.sin(t * 5)
        d.polygon([(cx + s * R * 0.12, cy), (cx + s * R * 0.62, cy - R * 0.14), (cx + s * R * 0.55, cy + R * 0.08)],
                  fill=(255, 40, 60, int(alpha * 255 * glow)))


# ---------------------------------------------------------------- backgrounds
BW, BH = W + 120, H + 80


def gradient(top, bottom):
    t = np.linspace(0, 1, BH)[:, None, None]
    arr = (np.array(top) * (1 - t) + np.array(bottom) * t).astype(np.uint8)
    return Image.fromarray(np.repeat(arr, BW, axis=1), "RGB")


def make_bg(kind, rng):
    if kind == "forest":
        img = gradient((10, 40, 50), (20, 90, 70))
        d = ImageDraw.Draw(img, "RGBA")
        for layer, col in enumerate([(15, 60, 55), (10, 45, 40), (5, 28, 25)]):
            for _ in range(9):
                x = rng.uniform(0, BW)
                w = rng.uniform(60, 140) * (1 + layer * 0.3)
                d.rectangle((x - w * 0.12, 300, x + w * 0.12, BH), fill=col)
                for k in range(4):
                    y = 250 + k * 260 + layer * 60
                    d.polygon([(x - w * (1.2 - k * 0.1), y + 260), (x, y), (x + w * (1.2 - k * 0.1), y + 260)], fill=col)
        for _ in range(12):
            x, y = rng.uniform(0, BW), rng.uniform(900, 1500)
            d.ellipse((x - 40, y - 25, x + 40, y + 25), fill=(120, 255, 230, 40))
    elif kind == "sky":
        img = gradient((80, 150, 240), (250, 190, 210))
        d = ImageDraw.Draw(img, "RGBA")
        for _ in range(10):
            x, y = rng.uniform(0, BW), rng.uniform(100, 1300)
            for k in range(5):
                r = rng.uniform(50, 110)
                d.ellipse((x + k * 60 - r, y - r * 0.6, x + k * 60 + r, y + r * 0.6), fill=(255, 255, 255, 150))
        for _ in range(4):
            x, y = rng.uniform(100, BW - 100), rng.uniform(500, 1200)
            w = rng.uniform(120, 220)
            d.polygon([(x - w, y), (x + w, y), (x + w * 0.3, y + w * 0.9), (x - w * 0.3, y + w * 0.9)], fill=(110, 80, 90))
            d.rectangle((x - w, y - 20, x + w, y), fill=(90, 160, 90))
            for k in range(3):
                bx = x - w * 0.6 + k * w * 0.6
                d.rectangle((bx - 18, y - 120, bx + 18, y - 20), fill=(240, 240, 255))
                d.polygon([(bx - 26, y - 120), (bx, y - 170), (bx + 26, y - 120)], fill=(80, 110, 200))
    elif kind == "ruins":
        img = gradient((50, 25, 70), (230, 120, 90))
        d = ImageDraw.Draw(img, "RGBA")
        d.ellipse((BW * 0.6 - 140, 380, BW * 0.6 + 140, 660), fill=(255, 210, 160, 200))
        for _ in range(8):
            x = rng.uniform(0, BW)
            h = rng.uniform(300, 900)
            d.rectangle((x - 40, BH - 500 - h, x + 40, BH), fill=(40, 20, 45))
            d.polygon([(x - 60, BH - 500 - h), (x + 60, BH - 500 - h), (x + 30, BH - 540 - h)], fill=(40, 20, 45))
        d.rectangle((0, BH - 500, BW, BH), fill=(30, 15, 35))
    elif kind == "rooftop":
        img = gradient((250, 140, 90), (120, 60, 120))
        d = ImageDraw.Draw(img, "RGBA")
        d.ellipse((BW / 2 - 200, 500, BW / 2 + 200, 900), fill=(255, 220, 150, 230))
        x = 0
        while x < BW:
            w, h = rng.uniform(60, 160), rng.uniform(150, 600)
            d.rectangle((x, 1150 - h, x + w, 1150), fill=(70, 40, 80))
            x += w + 5
        d.rectangle((0, 1150, BW, BH), fill=(110, 110, 120))
        for x in range(0, BW, 60):
            d.line((x, 980, x, 1150), fill=(60, 70, 80), width=6)
        d.line((0, 990, BW, 990), fill=(60, 70, 80), width=10)
    elif kind == "classroom":
        img = gradient((240, 230, 200), (220, 200, 170))
        d = ImageDraw.Draw(img, "RGBA")
        for k in range(3):
            x = 80 + k * 360
            d.rectangle((x, 250, x + 300, 850), fill=(140, 200, 250))
            d.rectangle((x, 250, x + 300, 850), outline=(150, 120, 90), width=14)
            d.line((x + 150, 250, x + 150, 850), fill=(150, 120, 90), width=10)
            d.ellipse((x + 40, 600, x + 260, 760), fill=(255, 200, 220, 160))
        d.rectangle((0, 1150, BW, BH), fill=(170, 120, 80))
        for k in range(4):
            x = 60 + k * 300
            d.rectangle((x, 1050, x + 220, 1090), fill=(190, 150, 100))
            d.rectangle((x + 20, 1090, x + 35, 1250), fill=(90, 90, 100))
            d.rectangle((x + 185, 1090, x + 200, 1250), fill=(90, 90, 100))
    elif kind == "sakura":
        img = gradient((255, 200, 220), (200, 230, 255))
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle((0, 1200, BW, BH), fill=(170, 200, 140))
        d.polygon([(BW / 2 - 60, 1200), (BW / 2 + 60, 1200), (BW / 2 + 400, BH), (BW / 2 - 400, BH)], fill=(220, 200, 170))
        for _ in range(7):
            x, y = rng.uniform(0, BW), rng.uniform(500, 1000)
            d.rectangle((x - 22, y, x + 22, 1250), fill=(110, 70, 70))
            for _ in range(10):
                r = rng.uniform(70, 140)
                ox, oy = rng.uniform(-200, 200), rng.uniform(-260, 40)
                d.ellipse((x + ox - r, y + oy - r, x + ox + r, y + oy + r), fill=(255, 175, 205, 210))
    elif kind == "neon":
        img = gradient((10, 5, 40), (60, 20, 90))
        d = ImageDraw.Draw(img, "RGBA")
        x = 0
        while x < BW:
            w, h = rng.uniform(100, 220), rng.uniform(500, 1500)
            d.rectangle((x, BH - h, x + w, BH), fill=(20, 15, 40))
            for wy in range(int(BH - h + 30), BH, 50):
                for wx in range(int(x + 15), int(x + w - 15), 35):
                    if rng.random() < 0.35:
                        d.rectangle((wx, wy, wx + 14, wy + 22), fill=rng.choice([(255, 220, 120), (120, 220, 255)]))
            if rng.random() < 0.6:
                c = rng.choice([(255, 60, 180), (60, 230, 255), (180, 255, 80)])
                d.rectangle((x + 20, BH - h + 80, x + 50, BH - h + 380), fill=c + (220,))
            x += w + 10
    elif kind == "space":
        img = gradient((5, 5, 20), (20, 10, 50))
        d = ImageDraw.Draw(img, "RGBA")
        for _ in range(300):
            x, y = rng.uniform(0, BW), rng.uniform(0, BH)
            r = rng.choice([1, 1, 2, 3])
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randint(80, 255)))
        d.ellipse((BW * 0.65 - 330, 300, BW * 0.65 + 330, 960), fill=(200, 90, 60))
        d.ellipse((BW * 0.65 - 330, 300, BW * 0.65 + 330, 960), outline=(255, 170, 120), width=8)
        d.rectangle((0, 0, BW, 110), fill=(60, 65, 80))
        d.rectangle((0, 1250, BW, BH), fill=(60, 65, 80))
        d.rectangle((0, 0, 60, BH), fill=(60, 65, 80))
        d.rectangle((BW - 60, 0, BW, BH), fill=(60, 65, 80))
        for y in (1300, 1400, 1500):
            d.line((0, y, BW, y), fill=(90, 230, 255, 120), width=4)
    elif kind == "shrine":
        img = gradient((10, 15, 50), (40, 30, 90))
        d = ImageDraw.Draw(img, "RGBA")
        for _ in range(150):
            x, y = rng.uniform(0, BW), rng.uniform(0, 900)
            d.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=(255, 255, 255, rng.randint(80, 255)))
        d.ellipse((BW * 0.25 - 110, 250, BW * 0.25 + 110, 470), fill=(250, 245, 220))
        red = (200, 40, 40)
        d.rectangle((BW / 2 - 330, 650, BW / 2 - 280, 1250), fill=red)
        d.rectangle((BW / 2 + 280, 650, BW / 2 + 330, 1250), fill=red)
        d.polygon([(BW / 2 - 450, 600), (BW / 2 + 450, 600), (BW / 2 + 400, 660), (BW / 2 - 400, 660)], fill=red)
        d.rectangle((BW / 2 - 380, 720, BW / 2 + 380, 760), fill=red)
        d.rectangle((0, 1250, BW, BH), fill=(30, 30, 45))
        for x in (BW * 0.15, BW * 0.85):
            d.rectangle((x - 30, 1050, x + 30, 1150), fill=(250, 190, 90))
            d.ellipse((x - 90, 1010, x + 90, 1190), fill=(255, 190, 90, 50))
    else:  # village
        img = gradient((120, 140, 140), (60, 80, 80))
        d = ImageDraw.Draw(img, "RGBA")
        pts = [(0, 900)] + [(x, 900 - rng.uniform(100, 400)) for x in range(0, BW + 150, 150)] + [(BW, 900)]
        d.polygon(pts + [(BW, BH), (0, BH)], fill=(70, 90, 90))
        for _ in range(6):
            x, y = rng.uniform(0, BW), rng.uniform(950, 1150)
            d.rectangle((x - 90, y, x + 90, y + 140), fill=(50, 45, 50))
            d.polygon([(x - 130, y), (x, y - 100), (x + 130, y)], fill=(40, 35, 45))
            d.rectangle((x - 20, y + 50, x + 20, y + 100), fill=(250, 200, 120))
        d.rectangle((0, 1250, BW, BH), fill=(45, 60, 55))
    return img


PARTICLES = {"forest": "fireflies", "sky": "clouds", "ruins": "embers", "rooftop": "petals", "classroom": "dust",
             "sakura": "petals", "neon": "rain", "space": "twinkle", "shrine": "fireflies", "village": "fog"}


def particles(d, kind, t, rng_seed):
    rng = random.Random(rng_seed)
    if kind == "petals":
        for _ in range(40):
            x0, y0, sp = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(80, 180)
            y = (y0 + sp * t) % (H + 40) - 20
            x = x0 + math.sin(t * 1.5 + y0) * 40
            r = rng.uniform(8, 16)
            d.ellipse((x - r, y - r * 0.55, x + r, y + r * 0.55), fill=(255, 180, 210, 220))
    elif kind == "fireflies":
        for _ in range(30):
            x0, y0 = rng.uniform(0, W), rng.uniform(300, 1400)
            x = x0 + math.sin(t * 0.7 + x0) * 50
            y = y0 + math.cos(t * 0.5 + y0) * 40
            a = int(150 + 100 * math.sin(t * 3 + x0))
            d.ellipse((x - 12, y - 12, x + 12, y + 12), fill=(200, 255, 150, a // 4))
            d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(230, 255, 180, a))
    elif kind == "embers":
        for _ in range(35):
            x0, sp = rng.uniform(0, W), rng.uniform(60, 160)
            y = H - ((rng.uniform(0, H) + sp * t) % H)
            x = x0 + math.sin(t + x0) * 30
            d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(255, 150, 60, 200))
    elif kind == "rain":
        for _ in range(90):
            x0, y0 = rng.uniform(0, W + 200), rng.uniform(0, H)
            y = (y0 + 1600 * t) % H
            x = x0 - y * 0.15
            d.line((x, y, x - 8, y + 50), fill=(160, 200, 255, 110), width=2)
    elif kind == "twinkle":
        for _ in range(40):
            x, y = rng.uniform(0, W), rng.uniform(0, 1200)
            a = int(255 * max(0, math.sin(t * rng.uniform(1, 4) + x)))
            d.line((x - 8, y, x + 8, y), fill=(255, 255, 255, a), width=2)
            d.line((x, y - 8, x, y + 8), fill=(255, 255, 255, a), width=2)
    elif kind == "fog":
        for k in range(5):
            y = 800 + k * 150
            x = (t * (20 + k * 8) + k * 300) % (W + 600) - 600
            d.ellipse((x, y, x + 900, y + 160), fill=(220, 230, 230, 45))
    elif kind == "clouds":
        for k in range(3):
            x = (t * (25 + k * 10) + k * 400) % (W + 500) - 500
            y = 300 + k * 350
            d.ellipse((x, y, x + 420, y + 120), fill=(255, 255, 255, 90))
    elif kind == "dust":
        for _ in range(25):
            x0, y0 = rng.uniform(0, W), rng.uniform(200, 1200)
            x, y = x0 + math.sin(t * 0.4 + y0) * 30, y0 + math.cos(t * 0.3 + x0) * 30
            d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(255, 250, 220, 120))


# ---------------------------------------------------------------- timeline + rendering
TITLE_DUR, END_DUR, CPS = 3.2, 4.5, 42


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


def build_timeline(story):
    t = TITLE_DUR
    for ln in story["lines"]:
        ln["t0"] = t
        ln["dur"] = len(ln["text"]) / CPS + (2.2 if ln["speaker"] == "N" else 1.8)
        t += ln["dur"]
    return t + END_DUR


class Renderer:
    def __init__(self, story, seed):
        self.s = story
        self.seed = seed
        self.bg = make_bg(story["bg"], random.Random(seed))
        self.sprites = {k: self.load_sprite(story[k], k == "B") for k in ("A", "B") if "sprite" in story[k]}
        if self.sprites:
            # soft focus on the scenery so the detailed character art stands out
            self.bg = self.bg.filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.8))
        self.part = PARTICLES[story["bg"]]
        self.dlg_font = font(46)
        self.total = build_timeline(story)
        self.v_first = next((ln["t0"] for ln in story["lines"] if ln["speaker"] == "V"), None)

    def draw_smoky_villain(self, img, d, cy, t, alpha):
        """A blurred shadow figure with sharp glowing eyes, to sit with the painted character art."""
        if alpha <= 0:
            return
        if not hasattr(self, "villain_layer"):
            layer = Image.new("RGBA", (W, 1300))
            draw_villain(ImageDraw.Draw(layer, "RGBA"), W / 2, 420, 190, 0.0, 1.0)
            self.villain_layer = layer.filter(ImageFilter.GaussianBlur(9))
        a = self.villain_layer.getchannel("A").point(lambda v: int(v * alpha))
        img.paste(self.villain_layer, (0, int(cy - 420)), a)
        glow = 0.7 + 0.3 * math.sin(t * 5)
        for s_ in (-1, 1):
            ex, ey = W / 2 + s_ * 190 * 0.35, cy - 190 * 0.03
            for r, al in ((38, 50), (22, 110)):
                d.ellipse((ex - r * 1.6, ey - r * 0.6, ex + r * 1.6, ey + r * 0.6), fill=(255, 30, 50, int(al * alpha * glow)))
            d.polygon([(ex - s_ * 55, ey + 8), (ex + s_ * 45, ey - 14), (ex + s_ * 40, ey + 6)],
                      fill=(255, 90, 100, int(255 * alpha * glow)))

    @staticmethod
    def load_sprite(c, mirror):
        img = Image.open(c["sprite"]).convert("RGBA")
        hgt = 1180
        img = img.resize((int(img.width * hgt / img.height), hgt), Image.LANCZOS)
        if mirror:
            img = ImageOps.mirror(img)
        r, g, b, a = img.split()
        dim = Image.merge("RGBA", [ch.point(lambda v: int(v * 0.45)) for ch in (r, g, b)] + [a])
        big = img.resize((int(img.width * 1.05), int(img.height * 1.05)), Image.LANCZOS)
        glow_a = a.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(28)).point(lambda v: int(v * 0.85))
        glow = Image.new("RGBA", big.size, c["accent"] + (0,))
        glow.putalpha(glow_a.resize(big.size))
        return dict(normal=img, dim=dim, big=big, glow=glow)

    def draw_sprites(self, img, ln, t):
        """Paste the AI character art: the speaker steps forward and lights up, the other dims."""
        enter = ease((t - TITLE_DUR * 0.6) / (TITLE_DUR * 0.4 + 0.4))
        order = ["A", "B"]
        if ln and ln["speaker"] == "A":
            order = ["B", "A"]
        for key in order:
            sp = self.sprites[key]
            speaking = ln is not None and ln["speaker"] == key
            dim = ln is not None and ln["speaker"] not in (key, "N")
            pic = sp["big"] if speaking else sp["dim"] if dim else sp["normal"]
            cx = (330 if key == "A" else 750) + (1 - enter) * (-700 if key == "A" else 700)
            if speaking:
                cx += 40 if key == "A" else -40
            y = H - 40 - pic.height + math.sin(t * 2.0 + (0 if key == "A" else 1.7)) * 5
            if speaking and t - ln["t0"] < len(ln["text"]) / CPS:
                y -= abs(math.sin((t - ln["t0"]) * 9)) * 7
            if ln and ln["fx"] in ("shock", "flash") and t - ln["t0"] < 0.4:
                r = random.Random(int(t * FPS) + (7 if key == "B" else 0))
                cx += r.uniform(-12, 12)
            x = int(cx - pic.width / 2)
            if speaking and ln["fx"] == "aura":
                gl = sp["glow"]
                flick = 0.75 + 0.25 * math.sin(t * 12)
                img.paste(gl, (x, int(y)), gl.getchannel("A").point(lambda v: int(v * flick)))
            img.paste(pic, (x, int(y)), pic)
            if speaking and ln["fx"] == "sparkle":
                d = ImageDraw.Draw(img, "RGBA")
                for k in range(6):
                    a = t * 1.5 + k * 1.05
                    sx, sy = cx + math.cos(a) * 260, 900 + math.sin(a * 1.3) * 200
                    sz = 16 + 8 * math.sin(t * 6 + k)
                    d.polygon([(sx, sy - sz), (sx + sz * 0.3, sy), (sx, sy + sz), (sx - sz * 0.3, sy)], fill=(255, 255, 255, 230))
                    d.polygon([(sx - sz, sy), (sx, sy + sz * 0.3), (sx + sz, sy), (sx, sy - sz * 0.3)], fill=(255, 255, 255, 230))

    def line_at(self, t):
        cur = None
        for ln in self.s["lines"]:
            if ln["t0"] <= t:
                cur = ln
        return cur

    def frame(self, t):
        s = self.s
        pan = t / self.total
        ox = int(60 + 50 * math.sin(pan * math.pi))
        oy = int(80 * pan)
        ln = self.line_at(t) if TITLE_DUR <= t < self.total - END_DUR else None
        shake = (0, 0)
        if ln and ln["fx"] in ("shock", "flash") and t - ln["t0"] < 0.45:
            r = random.Random(int(t * FPS))
            amp = 18 * (1 - (t - ln["t0"]) / 0.45)
            shake = (int(r.uniform(-amp, amp)), int(r.uniform(-amp, amp)))
        img = self.bg.crop((ox + shake[0] + 20, oy + shake[1], ox + shake[0] + 20 + W, oy + shake[1] + H))
        img = img.copy()
        d = ImageDraw.Draw(img, "RGBA")
        particles(d, self.part, t, self.seed)
        if ln and ln["fx"] == "dark":
            d.rectangle((0, 0, W, H), fill=(60, 0, 30, 90))

        # villain looms once introduced, until the final beat
        if self.v_first is not None and t >= self.v_first:
            last_beat = ln["beat"] if ln else 6
            alpha = min(1, (t - self.v_first) / 0.8) * (0.35 if last_beat >= 6 else 1.0)
            if ln and ln["speaker"] != "V":
                alpha *= 0.7
            if self.sprites:
                self.draw_smoky_villain(img, d, 560 + math.sin(t * 1.2) * 15, t, alpha)
            else:
                draw_villain(d, W / 2, 560 + math.sin(t * 1.2) * 15, 170, t, alpha)

        # characters
        if self.sprites and t >= TITLE_DUR * 0.6:
            self.draw_sprites(img, ln, t)
            d = ImageDraw.Draw(img, "RGBA")
        elif t >= TITLE_DUR * 0.6:
            for key, cx, flip in (("A", 290, False), ("B", 790, True)):
                c = s[key]
                speaking = ln is not None and ln["speaker"] == key
                expr = ln["expr"] if speaking else ("neutral" if not ln or ln["speaker"] == "N" else
                                                    self.reaction(key, ln))
                talking = speaking and t - ln["t0"] < len(ln["text"]) / CPS
                bob = math.sin(t * 2.2 + (0 if key == "A" else 1.4)) * 6
                lift = -18 if speaking else 0
                R = 150 if speaking else 140
                if speaking and ln["fx"] == "aura":
                    g = s[key]["accent"]
                    for k in range(6, 0, -1):
                        r = R * (1.3 + k * 0.12 + 0.05 * math.sin(t * 8 + k))
                        d.ellipse((cx - r, 1130 - r, cx + r, 1130 + r * 1.3), fill=g + (25,))
                dim = ln is not None and ln["speaker"] not in (key, "N")
                draw_character(d, c, cx, 1130 + bob + lift, R, expr, t, talking, dim, flip)
                if speaking and ln["fx"] == "sparkle":
                    for k in range(6):
                        a = t * 1.5 + k * 1.05
                        x, y = cx + math.cos(a) * R * 1.5, 1050 + math.sin(a * 1.3) * R
                        sz = 14 + 8 * math.sin(t * 6 + k)
                        d.polygon([(x, y - sz), (x + sz * 0.3, y), (x, y + sz), (x - sz * 0.3, y)],
                                  fill=(255, 255, 255, 230))
                        d.polygon([(x - sz, y), (x, y + sz * 0.3), (x + sz, y), (x, y - sz * 0.3)],
                                  fill=(255, 255, 255, 230))

        if ln and ln["fx"] == "speed":
            r = random.Random(int(t * FPS))
            for _ in range(30):
                y = r.uniform(0, H)
                x = r.uniform(-300, W)
                d.line((x, y, x + r.uniform(200, 500), y), fill=(255, 255, 255, 120), width=3)

        # dialogue / narration
        if ln:
            self.text_box(d, ln, t)
        # header
        hf = font(34)
        d.text((40, 60), s["title"], font=hf, fill=(255, 255, 255, 230), stroke_width=3, stroke_fill=(0, 0, 0, 200))
        tf = font(26)
        tag = "AnimeVerse Hub Original"
        d.text((W - 40 - d.textlength(tag, font=tf), 110), tag, font=tf, fill=(255, 220, 120, 230),
               stroke_width=2, stroke_fill=(0, 0, 0, 200))

        if ln and ln["fx"] == "flash" and t - ln["t0"] < 0.5:
            d.rectangle((0, 0, W, H), fill=(255, 255, 255, int(230 * (1 - (t - ln["t0"]) / 0.5))))
        if ln and ln["fx"] == "shock" and t - ln["t0"] < 0.25:
            d.rectangle((0, 0, W, H), fill=(255, 255, 255, int(120 * (1 - (t - ln["t0"]) / 0.25))))
        if t < TITLE_DUR:
            self.title_card(d, t)
        if t >= self.total - END_DUR:
            self.end_card(d, t - (self.total - END_DUR))
        for edge in (TITLE_DUR, self.total - END_DUR):
            if abs(t - edge) < 0.3:
                d.rectangle((0, 0, W, H), fill=(0, 0, 0, int(255 * (1 - abs(t - edge) / 0.3))))
        return img

    def reaction(self, key, ln):
        return {"shock": "surprised", "flash": "serious", "dark": "serious"}.get(ln["fx"], "neutral")

    def text_box(self, d, ln, t):
        shown = ln["text"][: int((t - ln["t0"]) * CPS) + 1]
        spk = ln["speaker"]
        if spk == "N":
            f = font(44)
            lines = wrap(d, ln["text"], f, W - 200)
            hgt = len(lines) * 58 + 60
            y0 = 240
            d.rounded_rectangle((60, y0, W - 60, y0 + hgt), 24, fill=(0, 0, 0, 170))
            y = y0 + 30
            count = 0
            for line in lines:
                part = shown[count: count + len(line)]
                count += len(line) + 1
                lw = d.textlength(line, font=f)
                d.text(((W - lw) / 2, y), part, font=f, fill=(255, 245, 220, 255))
                y += 58
            return
        f = self.dlg_font
        box = (40, 1420, W - 40, 1790)
        name = self.s["villain"].title() if spk == "V" and self.s["villain"] else self.s[spk]["name"] if spk != "V" else "???"
        col = (200, 40, 70) if spk == "V" else self.s[spk]["hair"]
        if sum(col) > 600:
            col = mix(col, (60, 60, 90), 0.5)
        d.rounded_rectangle(box, 30, fill=(255, 255, 255, 255), outline=col + (255,), width=6)
        nf = font(40)
        nw = d.textlength(name, font=nf)
        nx = 80 if spk == "A" else (W - 80 - nw - 40 if spk == "B" else (W - nw) / 2 - 20)
        d.rounded_rectangle((nx, 1380, nx + nw + 40, 1450), 20, fill=col + (255,))
        d.text((nx + 20, 1389), name, font=nf, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        lines = wrap(d, ln["text"], f, box[2] - box[0] - 80)
        y = 1480
        count = 0
        for line in lines:
            part = shown[count: count + len(line)]
            count += len(line) + 1
            d.text((80, y), part, font=f, fill=(30, 25, 40))
            y += 60
        if t - ln["t0"] > len(ln["text"]) / CPS:
            if int(t * 3) % 2:
                d.polygon([(W - 100, 1740), (W - 70, 1740), (W - 85, 1760)], fill=(30, 25, 40))

    def title_card(self, d, t):
        a = min(1, t * 3) * min(1, (TITLE_DUR - t) * 3)
        d.rectangle((0, 0, W, H), fill=(10, 5, 25, int(200 * a)))
        g = {"fantasy": "FANTASY", "school": "SCHOOL STORY", "scifi": "SCI-FI", "yokai": "SPIRIT MYSTERY"}[self.s["genre"]]
        f = font(40)
        gw = d.textlength(g, font=f)
        d.text(((W - gw) / 2, 700), g, font=f, fill=(255, 210, 90, int(255 * a)))
        f = font(76)
        y = 790
        for line in wrap(d, self.s["title"], f, W - 140):
            lw = d.textlength(line, font=f)
            d.text(((W - lw) / 2 - (1 - ease(t * 2)) * 200, y), line, font=f, fill=(255, 255, 255, int(255 * a)),
                   stroke_width=5, stroke_fill=(120, 40, 200, int(255 * a)))
            y += 95
        f = font(36)
        sub = "An AnimeVerse Hub Original"
        sw = d.textlength(sub, font=f)
        d.text(((W - sw) / 2, y + 30), sub, font=f, fill=(255, 255, 255, int(220 * a)))

    def end_card(self, d, el):
        a = min(1, el * 2.5)
        d.rectangle((0, 0, W, H), fill=(10, 5, 25, int(210 * a)))
        rows = [("THE END...?", 110, (255, 90, 120)), ("What happens next?", 56, (255, 255, 255)),
                ("Tell us in the comments!", 50, (255, 210, 90)), ("", 30, (0, 0, 0)),
                ("Follow AnimeVerse Hub", 52, (255, 255, 255)), ("for a new story every 4 hours", 40, (200, 200, 255))]
        y = 650
        for text, size, col in rows:
            f = font(size)
            tw = d.textlength(text, font=f)
            d.text(((W - tw) / 2, y), text, font=f, fill=col + (int(255 * a),), stroke_width=max(2, size // 20),
                   stroke_fill=(0, 0, 0, int(255 * a)))
            y += size * 1.45


# ---------------------------------------------------------------- audio
MOODS = {0: "calm", 1: "calm", 2: "tense", 3: "tense", 4: "tense", 5: "epic", 6: "calm"}


def soundtrack(story, total, path, rng):
    n = int(SR * total)
    out = np.zeros(n)
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    key = {"fantasy": 50, "school": 55, "scifi": 45, "yokai": 52}[story["genre"]]
    major = story["genre"] == "school"
    progs = {"calm": [0, 5, 7, 3] if not major else [0, 7, 9, 5], "tense": [0, 1, 0, 6], "epic": [0, 8, 3, 10]}
    bpm = {"calm": 84, "tense": 110, "epic": 140}

    def mood_at(t):
        ln = None
        for x in story["lines"]:
            if x["t0"] <= t:
                ln = x
        return MOODS[ln["beat"]] if ln else "calm"

    t = 0.0
    step = 0
    while t < total:
        mood = mood_at(t)
        beat = 60 / bpm[mood]
        prog = progs[mood]
        root = key + prog[(step // 8) % 4]
        s = int(t * SR)
        ln_ = int(beat / 2 * SR)
        e = min(n, s + ln_)
        tt = np.arange(e - s) / SR
        third = 4 if major and mood == "calm" else 3
        arp = [0, third, 7, 12, 7, third, 12, 15][step % 8]
        lead = np.sin(2 * np.pi * hz(root + 12 + arp) * tt) * np.exp(-tt * (5 if mood == "calm" else 8))
        out[s:e] += lead * 0.08
        if step % 2 == 0:
            pad_len = min(n, s + int(beat * SR)) - s
            pt = np.arange(pad_len) / SR
            for iv in (0, third, 7):
                out[s:s + pad_len] += np.sin(2 * np.pi * hz(root + iv) * pt) * 0.03
            if mood != "calm":
                kt = np.arange(min(int(0.15 * SR), n - s)) / SR
                out[s:s + len(kt)] += np.sin(2 * np.pi * (50 + 90 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 15) * 0.3
        if mood == "epic" and step % 4 == 2:
            sl = min(int(0.12 * SR), n - s)
            out[s:s + sl] += rng.standard_normal(sl) * np.exp(-np.arange(sl) / SR * 25) * 0.12
        t += beat / 2
        step += 1
    # text blips, pitched per speaker, and hits for effects
    pitch = {"A": 640, "B": 820, "V": 180, "N": 420}
    for ln in story["lines"]:
        chars = len(ln["text"])
        for k in range(0, chars, 3):
            if ln["text"][k] == " ":
                continue
            s = int((ln["t0"] + k / CPS) * SR)
            bl = min(int(0.035 * SR), n - s)
            if bl <= 0:
                continue
            bt = np.arange(bl) / SR
            out[s:s + bl] += np.sin(2 * np.pi * pitch[ln["speaker"]] * bt) * np.exp(-bt * 60) * 0.06
        if ln["fx"] in ("shock", "flash"):
            s = int(ln["t0"] * SR)
            bl = min(int(1.0 * SR), n - s)
            bt = np.arange(bl) / SR
            boom = (np.convolve(rng.standard_normal(bl), np.ones(20) / 20, "same") * 2
                    + np.sin(2 * np.pi * (45 + 100 * np.exp(-bt * 10)) * bt)) * np.exp(-bt * 4)
            out[s:s + bl] += boom * (0.6 if ln["fx"] == "flash" else 0.4)
    fade = np.minimum(1, np.minimum(np.arange(n) / SR / 1.0, (total - np.arange(n) / SR) / 1.5))
    out *= np.maximum(fade, 0)
    out /= max(1e-6, np.percentile(np.abs(out), 99.8))
    pcm = (np.tanh(out * 0.8) * 0.95 * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- main
def make_post(story):
    a, b = story["A"]["name"], story["B"]["name"]
    q = {"fantasy": f"Should {a} trust {b}?", "school": f"Team {a} or Team {b}?",
         "scifi": f"Would you trust {b} with your life?", "yokai": "Would YOU visit that shrine at night?"}
    caption = (f"🎬 {story['title']}: an AnimeVerse Hub original story. "
               f"{q[story['genre']]} What happens next? 👇")
    tags = ["#anime", "#animestory", "#originalcharacter", "#animeshorts",
            {"fantasy": "#fantasyanime", "school": "#schoolanime", "scifi": "#cyberpunk", "yokai": "#yokai"}[story["genre"]]]
    return {"caption": caption, "tags": tags, "title": story["title"], "genre": story["genre"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="clip.mp4")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else time.time_ns() % 2**31
    story = write_story(random.Random(seed))
    r = Renderer(story, seed)
    total = r.total
    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.wav")
        soundtrack(story, total, audio, np.random.default_rng(seed))
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", args.out],
            stdin=subprocess.PIPE)
        for k in range(int(total * FPS)):
            ff.stdin.write(r.frame(k / FPS).convert("RGB").tobytes())
        ff.stdin.close()
        if ff.wait() != 0:
            sys.exit("ffmpeg failed")
    post = make_post(story)
    post["seed"] = seed
    post["seconds"] = round(total, 1)
    print(json.dumps(post))


if __name__ == "__main__":
    main()
