import numpy as np
from collections import deque
from PIL import Image

def components(mask, min_area):
    H,W = mask.shape
    seen=np.zeros_like(mask,dtype=bool); out=[]
    ys,xs=np.nonzero(mask)
    for y0,x0 in zip(ys.tolist(),xs.tolist()):
        if seen[y0,x0]: continue
        q=deque([(y0,x0)]); seen[y0,x0]=True; pts=[]
        while q:
            y,x=q.popleft(); pts.append((y,x))
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1),(2,0),(-2,0),(0,2),(0,-2)):
                ny,nx=y+dy,x+dx
                if 0<=ny<H and 0<=nx<W and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True; q.append((ny,nx))
        if len(pts)>=min_area:
            py=[p[0] for p in pts]; px=[p[1] for p in pts]
            out.append({'y0':min(py),'y1':max(py),'x0':min(px),'x1':max(px),'area':len(pts)})
    return out

a=np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)
R,G,B=a[...,0],a[...,1],a[...,2]
strong=(R>=150)&(G>=95)&(B<=115)&(R>G+30)&(G>B+35)
print('strong gold px:',strong.sum())
comps=components(strong,15)
comps.sort(key=lambda c:(c['y0'],c['x0']))
print('clusters(>=15px):',len(comps))
for c in comps:
    w=c['x1']-c['x0']+1;h=c['y1']-c['y0']+1
    print(f"  x[{c['x0']:4}-{c['x1']:4}] y[{c['y0']:3}-{c['y1']:3}] {w}x{h} area={c['area']}")

# 阿紫卡左/右边缘纵向扫描找金色
print('--- 阿紫卡左边缘 x=610 纵向 y490-660 金色像素 ---')
for x in range(604,620):
    col=np.nonzero(strong[490:660,x])[0]
    if len(col): print(f'  x={x}: y={[int(v)+490 for v in col]}')
print('--- 阿紫卡右边缘 x=826-836 ---')
for x in range(822,840):
    col=np.nonzero(strong[490:660,x])[0]
    if len(col): print(f'  x={x}: y={[int(v)+490 for v in col]}')
