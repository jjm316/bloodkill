import numpy as np, json
from PIL import Image

def lum(c):
    r,g,b = [c[...,i].astype(float)/255 for i in range(3)]
    def f(u): return np.where(u<=0.03928, u/12.92, ((u+0.055)/1.055)**2.4)
    return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)

def components(mask, min_area=40):
    # simple BFS labeling
    H,W = mask.shape
    lab = np.zeros((H,W), dtype=int)
    out=[]; cur=0
    from collections import deque
    ys,xs = np.nonzero(mask)
    coords = set(zip(ys.tolist(), xs.tolist()))
    seen = np.zeros_like(mask)
    for y0,x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0,x0]: continue
        cur+=1; q=deque([(y0,x0)]); seen[y0,x0]=True; pts=[]
        while q:
            y,x=q.popleft(); pts.append((y,x))
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                ny,nx=y+dy,x+dx
                if 0<=ny<H and 0<=nx<W and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True; q.append((ny,nx))
        if len(pts)>=min_area:
            py=[p[0] for p in pts]; px=[p[1] for p in pts]
            out.append({'y0':min(py),'y1':max(py),'x0':min(px),'x1':max(px),'area':len(pts)})
    return out

def analyze(path, name):
    a = np.asarray(Image.open(path).convert('RGB')).astype(int)
    H,W = a.shape[:2]
    R,G,B = a[...,0],a[...,1],a[...,2]
    gold = (R>140)&(G>90)&(B>40)&(R>G+25)&(G>B+25)&(B<140)
    crimson = (R>35)&(R<110)&(G<45)&(B<60)&(R>G+20)&(R>B+15)
    print(f'== {name} {W}x{H} gold_px={gold.sum()} ({gold.sum()/(W*H)*100:.2f}%) crimson_px={crimson.sum()} ({crimson.sum()/(W*H)*100:.2f}%)')
    # largest crimson component -> table ellipse
    comps = components(crimson, 3000)
    comps.sort(key=lambda c:-c['area'])
    if comps:
        t = comps[0]
        cx,cy=(t['x0']+t['x1'])/2,(t['y0']+t['y1'])/2
        print(f'  table-crimson-bbox x[{t["x0"]}-{t["x1"]}] y[{t["y0"]}-{t["y1"]}] center=({cx:.0f},{cy:.0f}) axes=({(t["x1"]-t["x0"])},{(t["y1"]-t["y0"])})')
    # gold components -> rings/cards/borders
    gcomps = components(gold, 150)
    gcomps.sort(key=lambda c: (c['y0'], c['x0']))
    big = [c for c in gcomps if (c['x1']-c['x0'])>50 or (c['y1']-c['y0'])>50]
    print(f'  gold-components(>=150px): {len(gcomps)}, of which sizable: {len(big)}')
    for c in big[:24]:
        w,h=c['x1']-c['x0']+1, c['y1']-c['y0']+1
        print(f'    gold-box x[{c["x0"]}-{c["x1"]}] y[{c["y0"]}-{c["y1"]}] {w}x{h} area={c["area"]}')
    return a, gold, crimson

a,gold,crimson = analyze(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png','board-desktop-1440')
np.save(r'D:\AIProj\bloodkill\.scratch\visual-verifier\run1\gold-desktop.npy', gold)
np.save(r'D:\AIProj\bloodkill\.scratch\visual-verifier\run1\crimson-desktop.npy', crimson)
