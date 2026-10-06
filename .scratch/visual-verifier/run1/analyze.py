import numpy as np
from PIL import Image

SHOTS = r"D:/AIProj/bloodkill/.scratch/ui-true-color/shots"
TARGETS = {
    "rose":   (142, 39, 35),
    "beast":  (51, 96, 143),
    "violet": (138, 95, 192),
    "gold":   (245, 197, 24),
}
TOL = 14

def lum(c):
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def ratio(a, b):
    la, lb = lum(a), lum(b)
    if la < lb: la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)

def scan(path, region=None):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    if region:
        x0, y0, x1, y1 = region
        a = a[y0:y1, x0:x1]
        ox, oy = x0, y0
    else:
        ox = oy = 0
    out = {}
    for name, (tr, tg, tb) in TARGETS.items():
        m = (np.abs(a[:, :, 0] - tr) <= TOL) & (np.abs(a[:, :, 1] - tg) <= TOL) & (np.abs(a[:, :, 2] - tb) <= TOL)
        cnt = int(m.sum())
        if cnt:
            ys, xs = np.nonzero(m)
            out[name] = (cnt, int(xs.min() + ox), int(ys.min() + oy), int(xs.max() + ox), int(ys.max() + oy))
        else:
            out[name] = (0, None, None, None, None)
    return im.size, out

def card_bg(path, box):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    x0, y0, x1, y1 = box
    patch = a[y0:y1, x0:x1].reshape(-1, 3)
    med = np.median(patch, axis=0).astype(int)
    return tuple(med)

CARD = (31, 18, 25)  # #1f1219
print("=== WCAG contrast vs card bg #1f1219 (31,18,25) ===")
for name, c in TARGETS.items():
    print(f"  {name:7s} {c}  ->  {ratio(c, CARD):.2f}:1")

print()
print("=== closeup scans (badge + chip presence) ===")
for f in ["self-seat-rose.png", "self-seat-beast.png", "self-seat-secret-order.png"]:
    size, res = scan(f"{SHOTS}/{f}")
    print(f"{f}  size={size}")
    for k, v in res.items():
        cnt, x0, y0, x1, y1 = v
        if cnt:
            print(f"   {k:7s} n={cnt:6d} bbox=({x0},{y0})-({x1},{y1})")
        else:
            print(f"   {k:7s} n=0")

print()
print("=== measured card bg in closeups (patch 560..660 x 250..320) ===")
for f in ["self-seat-rose.png", "self-seat-beast.png", "self-seat-secret-order.png"]:
    bg = card_bg(f"{SHOTS}/{f}", (560, 250, 660, 320))
    print(f"{f}: bg={bg}")
    for name, c in TARGETS.items():
        pass

print()
print("=== 390 narrow board scan ===")
size, res = scan(f"{SHOTS}/board-secret-order-390.png")
print(f"board-secret-order-390.png size={size} (viewport width=390)")
for k, v in res.items():
    cnt, x0, y0, x1, y1 = v
    print(f"   {k:7s} n={cnt:6d} bbox=({x0},{y0})-({x1},{y1})")

print()
print("=== legend-note-secret-order.png dots (2x) ===")
size, res = scan(f"{SHOTS}/legend-note-secret-order.png")
print(f"size={size}")
for k, v in res.items():
    cnt, x0, y0, x1, y1 = v
    print(f"   {k:7s} n={cnt:6d} bbox=({x0},{y0})-({x1},{y1})")
