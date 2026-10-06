# -*- coding: utf-8 -*-
# 像素级墨迹分析：对 help-*.png / rules-q-*.png 量化"？"墨迹中心相对圆环中心的偏移。
import json, glob, os, re
from PIL import Image

OUT = r"D:/AIProj/bloodkill/.scratch/ui-help-legend/shots/issue-01"

def is_gold(px):
    r, g, b = px[0], px[1], px[2]
    return r > 170 and g > 120 and b < 170 and r > g > b

def analyze(fp, btn_css):
    im = Image.open(fp).convert("RGB")
    W, H = im.size
    px = im.load()
    scale = W / (btn_css + 16.0)  # clip = 元素 + 8px 边距 * 2
    pts = [(x, y) for y in range(H) for x in range(W) if is_gold(px[x, y])]
    if not pts:
        return {"file": os.path.basename(fp), "error": "no gold pixels"}
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    ringL, ringR, ringT, ringB = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (ringL + ringR) / 2.0, (ringT + ringB) / 2.0
    rOuter = (ringR - ringL) / 2.0
    stroke = 1.5 * scale  # svg 描边 1（36px 档 ≈1.5px）×截屏 scale
    rInner = rOuter - stroke - 2
    ink = [(x, y) for (x, y) in pts if ((x - cx) ** 2 + (y - cy) ** 2) < rInner * rInner]
    if not ink:
        return {"file": os.path.basename(fp), "error": "no ink inside ring"}
    ix = [p[0] for p in ink]; iy = [p[1] for p in ink]
    icx, icy = sum(ix) / len(ix), sum(iy) / len(iy)
    ibox = (min(ix), min(ix), max(ix)) 
    res = {
        "file": os.path.basename(fp),
        "img": [W, H], "scale": round(scale, 2),
        "ring_bbox": [ringL, ringT, ringR, ringB],
        "ring_center_css": [round((cx - 8 * scale) / scale, 2), round((cy - 8 * scale) / scale, 2)],
        "ink_bbox_px": [min(ix), min(iy), max(ix), max(iy)],
        "ink_center_css_offset": [round((icx - cx) / scale, 2), round((icy - cy) / scale, 2)],
        "ink_bbox_left_css":  round((min(ix) - cx) / scale, 2),
        "ink_bbox_right_css": round((max(ix) - cx) / scale, 2),
        "ink_bbox_top_css":   round((min(iy) - cy) / scale, 2),
        "ink_bbox_bot_css":   round((max(iy) - cy) / scale, 2),
        "ink_px_count": len(ink),
    }
    return res

results = []
for fp in sorted(glob.glob(os.path.join(OUT, "help-*-v4.png"))):
    w = int(re.search(r"help-(\d+)-v4", fp).group(1))
    btn = {1024: 36, 768: 36, 640: 32, 480: 28, 360: 28, 320: 28}[w]
    results.append(analyze(fp, btn))
for fp in sorted(glob.glob(os.path.join(OUT, "rules-q-*-v4.png"))):
    results.append(analyze(fp, 26))
print(json.dumps(results, indent=1, ensure_ascii=False))
