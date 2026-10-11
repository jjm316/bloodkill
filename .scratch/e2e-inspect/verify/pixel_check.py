from PIL import Image
import os, math

V = "D:/AIProj/bloodkill/.scratch/e2e-inspect/verify"
SH = "D:/AIProj/bloodkill/.scratch/e2e-inspect/shots"

def lum(hex_or_rgb):
    if isinstance(hex_or_rgb, str):
        h = hex_or_rgb.lstrip('#'); rgb = tuple(int(h[i:i+2],16) for i in (0,2,4))
    else: rgb = hex_or_rgb
    def f(c):
        c = c/255
        return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
    r,g,b = (f(c) for c in rgb)
    return 0.2126*r + 0.7152*g + 0.0722*b

def ratio(fg, bg):
    l1, l2 = lum(fg), lum(bg)
    if l1 < l2: l1, l2 = l2, l1
    return (l1+0.05)/(l2+0.05)

print("== contrast (white text on badge bg) ==")
for name, bg in [("rose #8e2723", "#8e2723"), ("beast #33608f", "#33608f"), ("order #8a5fc0", "#8a5fc0"), ("eye-icon #1f1219 on white", None)]:
    if bg:
        print(f"white on {name}: {ratio('#ffffff', bg):.2f}:1")
print(f"eye icon #1f1219 on #ffffff: {ratio('#1f1219', '#ffffff'):.2f}:1")

def region_colors(img, x, y, w, h):
    px = img.load()
    cnt = {}
    for dy in range(int(h)):
        for dx in range(int(w)):
            p = px[int(x)+dx, int(y)+dy]
            # quantize to 8-steps to bucket similar colors
            q = tuple((c//16)*16 for c in p[:3])
            cnt[q] = cnt.get(q, 0) + 1
    total = int(w*h)
    top = sorted(cnt.items(), key=lambda kv: -kv[1])[:5]
    return total, top

for f in ["board-cdp-1440x950.png", "board-cdp-390x844.png", "legend-inspect-note-1440.png", "board-1440x950.png"]:
    p = os.path.join(V, f)
    im = Image.open(p)
    print(f, im.size)

# badge crops on desktop CDP shot (coords from geom-1440.json)
im = Image.open(os.path.join(V, "board-cdp-1440x950.png")).convert("RGB")
crops = [("amei", 564, 158, 30, 33), ("mimi", 951, 158, 30, 33)]
for name, x, y, w, h in crops:
    box = im.crop((x, y, x+w, y+h))
    box.resize((w*8, h*8), Image.NEAREST).save(os.path.join(V, f"crop-{name}-badge-8x.png"))
    total, top = region_colors(im, x+2, y+2, 20, 20)
    print(f"crop {name}: dominant colors (quantized) {top}")
    # count white-ish pixels (text + eye) in badge body incl. eye area
    px = im.load()
    white = dark = 0
    for dy in range(33):
        for dx in range(30):
            r,g,b = px[x+dx, y+dy]
            if r>230 and g>230 and b>230: white += 1
            if r<50 and g<50 and b<60: dark += 1
    print(f"crop {name}: white-ish px={white}, dark px={dark} (of 990)")

# mobile crops
im3 = Image.open(os.path.join(V, "board-cdp-390x844.png")).convert("RGB")
for name, x, y, w, h in [("amei-m", 143, 112, 30, 33), ("mimi-m", 143, 390, 30, 33)]:
    box = im3.crop((x, y, x+w, y+h))
    box.resize((w*8, h*8), Image.NEAREST).save(os.path.join(V, f"crop-{name}-badge-8x.png"))
    total, top = region_colors(im3, x+2, y+2, 20, 20)
    print(f"crop {name}: dominant {top}")

# legend note crop with margin (x=380.5,y=685,w=627,h=76)
iml = Image.open(os.path.join(V, "legend-inspect-note-1440.png")).convert("RGB")
iml.crop((340, 640, 1050, 790)).resize((1420, 300)).save(os.path.join(V, "crop-legend-inspect-2x.png"))
print("legend crop saved")

# structural diff vs reference board
ref = Image.open(os.path.join(SH, "board-after-1440.png")).convert("RGB")
mine = Image.open(os.path.join(V, "board-1440x950.png")).convert("RGB")
print("ref", ref.size, "mine", mine.size)
if ref.size == mine.size:
    from PIL import ImageChops
    diff = ImageChops.difference(ref, mine)
    bbox = diff.getbbox()
    hist = diff.convert("L").histogram()
    changed = sum(hist[16:])
    print(f"diff bbox={bbox}, pixels changed>16: {changed} ({100*changed/(ref.size[0]*ref.size[1]):.2f}%)")
