"""Cut AI character art out of its chroma-green background: art/raw/*.png -> art/chars/*.png (RGBA)."""
import glob
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))


def key(src, dst):
    im = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    # how much greener than the other channels a pixel is
    spill = g - np.maximum(r, b)
    # the green differs between images, so measure it from the corners
    corners = np.concatenate([spill[:20, :20].ravel(), spill[:20, -20:].ravel()])
    bg = float(np.median(corners))
    alpha = np.clip((bg * 0.8 - spill) / (bg * 0.55), 0, 1)
    a = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    # remove green fringe on the edges
    im[..., 1] = np.minimum(g, np.maximum(r, b) + 10)
    out = Image.fromarray(im.astype(np.uint8)).convert("RGBA")
    out.putalpha(a)
    bbox = out.getbbox()
    out.crop(bbox).save(dst)


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "chars"), exist_ok=True)
    for src in sorted(glob.glob(os.path.join(HERE, "raw", "*.png"))):
        dst = os.path.join(HERE, "chars", os.path.basename(src))
        key(src, dst)
        print(dst, file=sys.stderr)
