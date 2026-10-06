import numpy as np
from PIL import Image
a = np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)
R,G,B = a[...,0],a[...,1],a[...,2]
warm = (R>90)&(R>G)&(G>B)
ys,xs = np.nonzero(warm)
q = (a[ys,xs]//16*16)
colors,counts = np.unique(q,axis=0,return_counts=True)
idx = np.argsort(-counts)[:20]
print('warm(R>90,R>G>B) px:', warm.sum())
for i in idx:
    print('  ', tuple(int(v) for v in colors[i]), counts[i])
# 沿椭圆边缘采样：椭圆 center(720,377) axes(1009,490)
import math
cx,cy,ax,ay=720,377,1009/2,490/2
print('--- 椭圆环采样（半径系数 0.97-1.03）---')
seen={}
for t in range(0,360,3):
    best=None
    for f in [0.9,0.95,0.97,1.0,1.03,1.06,1.1]:
        x=int(cx+ax*f*math.cos(math.radians(t))); y=int(cy+ay*f*math.sin(math.radians(t)))
        if 0<=x<1440 and 0<=y<900:
            c=tuple(a[y,x])
            if c not in seen: seen[c]=[]
            seen[c].append((t,f))
top=sorted(seen.items(), key=lambda kv:-len(kv[1]))[:12]
for c,lst in top:
    print('  ', c, len(lst))
