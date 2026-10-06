import numpy as np, json
from PIL import Image
from collections import Counter

def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(int)
mob = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-mobile-390.png')
base = load(r'D:\AIProj\bloodkill\.scratch\ui-review\07-mobile-board.png')
wai = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\waiting-desktop-1440.png')
lob = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\lobby-desktop-1440.png')
desk= load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png')
mock= load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-board-desktop.png')

# ---- 移动端卡片检测：找比页面底稍亮的卡片矩形 (bg>18)
def card_rows(img, label, x0=0,x1=None):
    H,W=img.shape[:2]; x1=x1 or W
    # 卡片背景 ~ (40,25,35) 页面 ~ (14,8,12)
    R,G,B=img[...,0],img[...,1],img[...,2]
    cardbg=(R>26)&(R<70)&(G>14)&(G<45)&(B>18)&(B<60)&(R>=B-6)
    rows=cardbg[:,x0:x1].sum(axis=1)
    segs=[]; inseg=False
    for y,v in enumerate(rows):
        if v>30 and not inseg: start=y; inseg=True
        elif v<=30 and inseg:
            if y-start>25: segs.append((start,y))
            inseg=False
    print(f'--- {label} 卡片横带(y范围): {segs[:12]}')
    for (ys,ye) in segs[:8]:
        cols=np.nonzero(cardbg[ys:ye,x0:x1].sum(axis=0)>=(ye-ys)*0.5)[0]+x0
        if len(cols):
            # 分组连续列 -> 列块
            groups=[]; s=cols[0]; p=cols[0]
            for c in cols[1:]:
                if c-p>8: groups.append((s,p)); s=c
                p=c
            groups.append((s,p))
            print(f'    y[{ys}-{ye}] 列块: {[(int(a)+x0,int(b)+x0) for a,b in groups if b-a>25]}')
    return segs

print('===== 移动端 390x844 =====')
card_rows(mob,'新主题移动端')
card_rows(base,'基线移动端')

# 右缘截断检查：等待文本行 y 430-450
R,G,B=mob[...,0],mob[...,1],mob[...,2]
lit=(R+G+B)>250
print('等待行 y428-452 每列亮像素数(370-390):', [int(lit[428:452,x].sum()) for x in range(370,390)])
print('等待行下方 y455-470 亮像素总数(x0-390):', int(lit[455:470,:].sum()))
# 第二行文本检测（剩N秒）
rows=lit[430:480,:].sum(axis=1)
nz=[(i+430,int(v)) for i,v in enumerate(rows) if v>5]
print('y430-480 亮像素行:', nz[:15])

# ---- 等待房 团子(你) 行高亮
print('===== 等待房行底色对比 =====')
def strip(img,y0,y1,x0,x1,label):
    reg=img[y0:y1,x0:x1].reshape(-1,3)
    print(f'  {label}: 均色{tuple(round(float(v)) for v in reg.mean(axis=0))}')
for (y0,y1,lab) in [(126,140,'阿玫行(房主)'),(222,236,'大猫行'),(262,278,'团子(你)行')]:
    strip(wai,y0,y1,118,232,lab)
# 团子行金边检查
R,G,B=wai[...,0],wai[...,1],wai[...,2]
gold=(R>120)&(G>80)&(B<110)&(R>G+25)&(G>B+25)
print('团子(你)行区域金像素:', int(gold[258:282,112:240].sum()), ' 大猫行区域金像素:', int(gold[218:240,112:240].sum()))
print('团子行左边框 x108-118 y260-278 金:', int(gold[260:278,108:118].sum()))

# ---- 大厅按钮金边 & 标题衬线
print('===== 大厅 =====')
R,G,B=lob[...,0],lob[...,1],lob[...,2]
goldl=(R>110)&(G>70)&(B<110)&(R>G+20)&(G>B+20)
# 创建房间按钮 OCR (688-754, ~215-232)
print('创建房间按钮周边金像素 y206-244 x676-766:', int(goldl[206:244,676:766].sum()))
print('加入房间按钮周边金像素 y328-366 x676-766:', int(goldl[328:366,676:766].sum()))
# 标题笔画衬线分析：水平细笔画 vs 垂直
t=lob[72:102,520:670]
T=t.mean(axis=2)
dark=T<120
# 水平行程长度（细水平笔画=>衬线/宋体特征）
def runs_2d(mask,axis):
    out=[]
    m=mask if axis==0 else mask.T
    for row in m:
        c=0
        for v in row:
            if v: c+=1
            elif c: out.append(c); c=0
        if c: out.append(c)
    return out
hr=runs_2d(dark,1); vr=runs_2d(dark,0)
hr=[x for x in hr if x>0]; vr=[x for x in vr if x>0]
print(f'标题暗笔画 水平行程: n={len(hr)} 均值={np.mean(hr):.2f} | 垂直行程: n={len(vr)} 均值={np.mean(vr):.2f} | H/V 比={np.mean(hr)/max(np.mean(vr),0.01):.2f}')
# 正文对照（姓名标签 524-563,130-145）
b=lob[128:150,520:570]; Bm=b.mean(axis=2); darkb=Bm<120
hrb=runs_2d(darkb,1); vrb=runs_2d(darkb,0)
hrb=[x for x in hrb if x>0]; vrb=[x for x in vrb if x>0]
if hrb and vrb:
    print(f'正文暗笔画 水平行程: 均值={np.mean(hrb):.2f} | 垂直行程: 均值={np.mean(vrb):.2f} | H/V 比={np.mean(hrb)/max(np.mean(vrb),0.01):.2f}')

# ---- 参考稿金边卡位置（老K vs 大猫 语义核对）
R,G,B=mock[...,0],mock[...,1],mock[...,2]
gm=(R>=150)&(G>=95)&(B<=115)&(R>G+30)&(G>B+35)
ys,xs=np.nonzero(gm)
# 老K mock (342,502), 大猫 mock (955,492)
print('===== 参考稿金像素分布 =====')
for (x0,x1,y0,y1,lab) in [(250,440,470,560,'老K卡区'),(880,1140,460,570,'大猫卡区'),(500,950,340,420,'横幅区'),(590,860,500,650,'阿紫卡区')]:
    print(f'  {lab}: {int(gm[y0:y1,x0:x1].sum())}')

# ---- 桌面桌渐变 (1.1 深绯红渐变)
R,G,B=desk[...,0],desk[...,1],desk[...,2]
print('===== 桌面渐变采样（椭圆内部纵轴 x=720） =====')
for y in range(180,620,60):
    print(f'  y={y}: {tuple(int(v) for v in desk[y,720])}')
