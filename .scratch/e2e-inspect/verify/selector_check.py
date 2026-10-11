from PIL import Image
import os
V="D:/AIProj/bloodkill/.scratch/e2e-inspect/verify"
im=Image.open("D:/AIProj/bloodkill/.scratch/e2e-inspect/shots/selector-1440.png").convert("RGB")
print("selector-1440.png", im.size)
px=im.load()
W,H=im.size
# find rows containing non-background content: background is dark theme (#12141a-ish)
def row_activity(y, x0=0, x1=None):
    x1 = x1 or W
    c=0
    for x in range(x0, x1, 2):
        r,g,b=px[x,y]
        if abs(r-18)>28 or abs(g-20)>28 or abs(b-26)>28: c+=1
    return c
bands=[]
in_band=False
for y in range(0, H, 2):
    a=row_activity(y)
    if a>3 and not in_band: start=y; in_band=True
    elif a<=3 and in_band: bands.append((start,y)); in_band=False
if in_band: bands.append((start,H))
bands=[b for b in bands if b[1]-b[0]>=6]
print("content bands (y ranges):", bands)
# For each band, get x-extent
for (y0,y1) in bands:
    xs=[x for x in range(0,W,2) for y in range(y0,y1,4) if (lambda p: abs(p[0]-18)>30 or abs(p[1]-20)>30 or abs(p[2]-26)>30)(px[x,y])]
    if xs: print(f"band y{y0}-{y1}: x {min(xs)}-{max(xs)} width {max(xs)-min(xs)}")
# crop and zoom the central panel area (approx middle 700px)
im.crop((370, 0, 1070, H)).resize((1400, H*2)).save(os.path.join(V,"crop-selector-2x.png"))
print("selector crop saved")
