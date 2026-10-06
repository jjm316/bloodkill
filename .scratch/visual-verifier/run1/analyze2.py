import numpy as np
from PIL import Image
from collections import deque

SHOTS = r"D:/AIProj/bloodkill/.scratch/ui-true-color/shots"
OUT = r"D:/AIProj/bloodkill/.scratch/visual-verifier/run1"
TARGETS = {
    "rose":   (142, 39, 35),
    "beast":  (51, 96, 143),
    "violet": (138, 95, 192),
    "gold":   (245, 197, 24),
}
TOL = 14

def mask_of(a, name):
    tr, tg, tb = TARGETS[name]
    return (np.abs(a[:,:,0]-tr)<=TOL) & (np.abs(a[:,:,1]-tg)<=TOL) & (np.abs(a[:,:,2]-tb)<=TOL)

def clusters(m, min_px=8):
    h, w = m.shape
    seen = np.zeros_like(m, dtype=bool)
    out = []
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]: continue
        q = deque([(y0, x0)]); seen[y0, x0] = True
        pts = []
        while q:
            y, x = q.popleft(); pts.append((y, x))
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    ny, nx = y+dy, x+dx
                    if 0<=ny<h and 0<=nx<w and m[ny,nx] and not seen[ny,nx]:
                        seen[ny,nx]=True; q.append((ny,nx))
        if len(pts) >= min_px:
            ys2 = [p[0] for p in pts]; xs2 = [p[1] for p in pts]
            out.append((len(pts), min(xs2), min(ys2), max(xs2), max(ys2)))
    out.sort(key=lambda c: (-c[0]))
    return out

def report(path, region=None, colors=None, min_px=8, label=""):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    ox, oy = 0, 0
    if region:
        x0,y0,x1,y1 = region
        a = a[y0:y1, x0:x1]; ox, oy = x0, y0
    print(f"--- {label or path} region={region} size={im.size}")
    for name in (colors or TARGETS):
        cs = clusters(mask_of(a, name), min_px)
        top = cs[:6]
        if not top: print(f"   {name:7s}: no clusters >= {min_px}px")
        for n,x0,y0,x1,y1 in top:
            print(f"   {name:7s} n={n:5d} bbox=({x0+ox},{y0+oy})-({x1+ox},{y1+oy}) size={x1-x0+1}x{y1-y0+1} center=({(x0+x1)//2+ox},{(y0+y1)//2+oy})")

def crop(path, box, scale, outname):
    im = Image.open(path).convert("RGB").crop(box)
    im = im.resize((im.width*scale, im.height*scale), Image.NEAREST)
    im.save(f"{OUT}/{outname}")
    print(f"saved {OUT}/{outname} ({im.width}x{im.height})")

# 1. legend dots (bottom region only, exclude previous note dots at top)
report(f"{SHOTS}/legend-note-secret-order.png", region=(20,100,200,160), label="legend dots row")
crop(f"{SHOTS}/legend-note-secret-order.png", (25,105,175,160), 6, "zoom-legend-dots.png")

# 2. closeup badge + stray pixel hunt
for f, c in [("self-seat-rose.png","rose"), ("self-seat-beast.png","beast"), ("self-seat-secret-order.png","violet")]:
    report(f"{SHOTS}/{f}", colors=[c,"gold"], min_px=8, label=f)
    crop(f"{SHOTS}/{f}", (600,0,696,80), 6, f"zoom-badge-{c}.png")

crop(f"{SHOTS}/self-seat-rose.png", (160,0,440,140), 3, "zoom-rose-topleft.png")

# 3. 390 board: violet stray + chip/badge clusters
report(f"{SHOTS}/board-secret-order-390.png", colors=["violet","gold","beast"], min_px=6, label="390 board")
crop(f"{SHOTS}/board-secret-order-390.png", (170,110,390,280), 3, "zoom-390-selfcard.png")
crop(f"{SHOTS}/board-secret-order-390.png", (355,110,390,290), 8, "zoom-390-rightedge.png")

# 4. board-rose-1440: self card vs 老K card
crop(f"{SHOTS}/board-rose-1440.png", (600,505,840,645), 3, "zoom-1440-selfcard.png")
crop(f"{SHOTS}/board-rose-1440.png", (250,455,500,550), 3, "zoom-1440-laok.png")

# 5. legend label 线索印记 check
crop(f"{SHOTS}/legend-rose-1440.png", (395,690,700,770), 3, "zoom-legend-label.png")
