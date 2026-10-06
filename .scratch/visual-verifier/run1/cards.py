import numpy as np, json
from collections import deque
from PIL import Image

def components(mask, min_area):
    H,W = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out=[]; ys,xs = np.nonzero(mask)
    for y0,x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0,x0]: continue
        q=deque([(y0,x0)]); seen[y0,x0]=True; pts=[]
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

def overlap(c1,c2):
    ix = max(0, min(c1['x1'],c2['x1'])-max(c1['x0'],c2['x0']))
    iy = max(0, min(c1['y1'],c2['y1'])-max(c1['y0'],c2['y0']))
    return ix*iy

a = np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)
R,G,B = a[...,0],a[...,1],a[...,2]
strong = (R>=160)&(G>=100)&(B<=110)&(R>G+30)&(G>B+40)
weak   = (R>=100)&(R<=175)&(G>=60)&(B<=95)&(R>G+25)&(G>B+15)
gold = strong|weak
print('strong',strong.sum(),'weak',weak.sum())
comps = components(gold, 80)
# 卡片大小的盒子：宽 120-360, 高 60-200
cards=[]
for c in comps:
    w=c['x1']-c['x0']+1; h=c['y1']-c['y0']+1
    if 110<=w<=400 and 55<=h<=230:
        # 估计边框强度：盒子边缘行的 strong 占比
        y0,y1,x0,x1=c['y0'],c['y1'],c['x0'],c['x1']
        edge = np.concatenate([strong[y0:y1+1,x0:x0+3].ravel(), strong[y0:y1+1,x1-2:x1+1].ravel(), strong[y0:y0+3,x0:x1+1].ravel(), strong[y1-2:y1+1,x0:x1+1].ravel()])
        gld  = np.concatenate([gold[y0:y1+1,x0:x0+3].ravel(), gold[y0:y1+1,x1-2:x1+1].ravel(), gold[y0:y0+3,x0:x1+1].ravel(), gold[y1-2:y1+1,x0:x1+1].ravel()])
        cards.append({**c,'w':w,'h':h,'edge_strong':round(float(edge.mean()),3),'edge_gold':round(float(gld.mean()),3)})
cards.sort(key=lambda c:(c['y0'],c['x0']))
print(f'候选卡片盒: {len(cards)}')
ocr = json.load(open(r'D:\AIProj\bloodkill\.scratch\visual-verifier\run1\r-board-desktop.json',encoding='utf-8'))
for c in cards:
    inside=[o['text'] for o in ocr if o['cx']>=c['x0']-15 and o['cx']<=c['x1']+15 and o['cy']>=c['y0']-10 and o['cy']<=c['y1']+10]
    print(f"  card x[{c['x0']:4}-{c['x1']:4}] y[{c['y0']:3}-{c['y1']:3}] {c['w']}x{c['h']} strong_edge={c['edge_strong']} gold_edge={c['edge_gold']} text={'|'.join(inside)[:60]}")
# 两两重叠检测
ov=[(i,j) for i in range(len(cards)) for j in range(i+1,len(cards)) if overlap(cards[i],cards[j])>0]
print('卡片盒重叠对:', ov if ov else '无')
# 越界检测
W,Hh=1440,900
oob=[c for c in cards if c['x0']<0 or c['x1']>=W or c['y0']<0 or c['y1']>=Hh]
print('越界卡片:', [(c['x0'],c['x1'],c['y0'],c['y1']) for c in oob] if oob else '无')
# 横向溢出整体检测：最右侧非背景像素
bg = (R<50)&(G<30)&(B<40)
col_any = ~bg.any(axis=0)
rightmost = int(np.nonzero(col_any)[0].max()) if col_any.any() else -1
print('最右非背景列:', rightmost, '(宽度1440)')
