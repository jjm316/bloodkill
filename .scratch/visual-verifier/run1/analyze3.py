import numpy as np
from PIL import Image

SHOTS = r"D:/AIProj/bloodkill/.scratch/ui-true-color/shots"

# Border sampling: vertical profile at x=360 (top border area) and x=46 (left border), y=200
for f in ["self-seat-rose.png", "self-seat-beast.png", "self-seat-secret-order.png"]:
    im = Image.open(f"{SHOTS}/{f}").convert("RGB")
    a = np.asarray(im).astype(int)
    print(f"=== {f}")
    # top border profile: scan y 25..60 at x=360 for goldish pixels
    hits = []
    for y in range(25, 60):
        r, g, b = a[y, 360]
        if r > 90 and g > 60 and b < 110 and r > b + 40:
            hits.append((y, (r, g, b)))
    print("  top border goldish @x=360:", hits[:8])
    # left border profile: scan x 25..60 at y=200
    hits = []
    for x in range(25, 60):
        r, g, b = a[200, x]
        if r > 90 and g > 60 and b < 110 and r > b + 40:
            hits.append((x, (r, g, b)))
    print("  left border goldish @y=200:", hits[:8])
    # bottom border: scan y 320..360 at x=360
    hits = []
    for y in range(320, 360):
        r, g, b = a[y, 360]
        if r > 90 and g > 60 and b < 110 and r > b + 40:
            hits.append((y, (r, g, b)))
    print("  bottom border goldish @x=360:", hits[:8])

# 1440 board self card border check + 老K border
im = Image.open(f"{SHOTS}/board-rose-1440.png").convert("RGB")
a = np.asarray(im).astype(int)
print("=== board-rose-1440 self card border: scan y 515..645 @x=725 (vertical through card)")
hits = [(y, tuple(a[y,725])) for y in range(515, 645) if a[y,725][0]>150 and a[y,725][1]>110 and a[y,725][2]<120]
print("  goldish:", hits[:6], "...", hits[-3:] if len(hits)>6 else "")
print("=== 老K card border @x=370 scan y 455..545")
hits = [(y, tuple(a[y,370])) for y in range(455, 545) if a[y,370][0]>150 and a[y,370][1]>110 and a[y,370][2]<120]
print("  goldish:", hits[:6], "...", hits[-3:] if len(hits)>6 else "")

# 老K badge in 1440: dark-ring rose dot — sample around (470,477)
print("=== 老K badge region sample (x 455..485, y 462..492) distinct colors")
from collections import Counter
c = Counter()
for y in range(462, 493):
    for x in range(455, 486):
        c[tuple(a[y,x])] += 1
for col, n in c.most_common(8):
    print("   ", col, n)
