import numpy as np
from PIL import Image
def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(int)
mob=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-mobile-390.png')
base=load(r'D:\AIProj\bloodkill\.scratch\ui-review\07-mobile-board.png')
wai=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\waiting-desktop-1440.png')
mwait=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-waiting-desktop.png')
lob=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\lobby-desktop-1440.png')

# 1) 移动端列结构：对每行座位文本带，探测卡片亮块边界（卡片bg比page亮）
print('===== 移动端列结构 =====')
def cols_at(img,ys,ye,label,lo=20,hi=90):
    reg=img[ys:ye].mean(axis=0)  # 每列均色亮度
    R=reg[:,0];G=reg[:,1];Bb=reg[:,2]
    m=(R>lo)&(G>8)&(Bb>10)&(R<hi)
    groups=[];inseg=False
    for x,v in enumerate(m):
        if v and not inseg: s=x;inseg=True
        elif not v and inseg:
            if x-s>40: groups.append((s,x))
            inseg=False
    print(f'  {label} y[{ys}-{ye}] 亮块列: {groups}')
# 用 OCR 座位行: 新主题 阿玫(77,172)/小兽(225,188)带 y160-200; 阿紫卡带 y315-395; 大猫(336,318)
for ys,ye,lab in [(155,205,'第1带'),(300,340,'第2带'),(345,400,'第3带(阿紫宽卡)')]:
    cols_at(mob,ys,ye,'新 '+lab)
for ys,ye,lab in [(150,180,'基线第1带'),(228,262,'基线第2带'),(358,378,'基线第3带')]:
    cols_at(base,ys,ye,'基线 '+lab)

# 2) 右缘截断对比
print('===== 等待行右缘 =====')
for img,lab,y0,y1 in [(mob,'新',428,448),(base,'基线',436,456)]:
    lit=(img[y0:y1].mean(axis=2)>80)
    cols=lit.sum(axis=0)
    edge=[int(v) for v in cols[378:390]]
    print(f'  {lab} y[{y0}-{y1}] x378-389 亮像素/列: {edge} 最右亮列: {int(np.nonzero(cols)[0].max())}')

# 3) 等待房 团子(你) 行 vs 参考稿同位置
print('===== 等待房 团子行对照 =====')
def rowbox(img,y0,y1,x0=100,x1=250,label=''):
    reg=img[y0:y1,x0:x1].reshape(-1,3)
    R,G,Bb=reg[:,0],reg[:,1],reg[:,2]
    gold=(R>110)&(G>70)&(Bb<110)&(R>G+20)&(G>Bb+15)
    print(f'  {label} 均色{tuple(round(float(v)) for v in reg.mean(axis=0))} 金px={int(gold.sum())}')
# 实拍行位置: 团子(你) y262-278; 参考稿 OCR 团子行位置先取同区间
rowbox(wai,258,282,110,240,'实拍-团子行')
rowbox(wai,222,244,110,240,'实拍-阿飞行')
rowbox(mwait,258,282,110,240,'参考-团子行(同坐标)')
# 参考稿 OCR:找团子行真实位置
import json
try:
    d=json.load(open(r'D:\AIProj\bloodkill\.scratch\visual-verifier\run1\r-mock-waiting-desktop.json',encoding='utf-8'))
    for b in d:
        if '团子' in b['text'] or '你' in b['text']:
            print('  参考稿团子行 OCR:', b['x'],b['y'],b['x2'],b['y2'],b['text'])
except FileNotFoundError:
    print('  (参考稿等待房未OCR,跳过)')

# 4) 大厅按钮边框剖面
print('===== 大厅创建房间按钮剖面 y=222 x670-770 =====')
prev=None;run=0
for x in range(670,775):
    q=tuple(int(v)//12*12 for v in lob[222,x])
    if q==prev: run+=1
    else:
        if prev is not None and run>=2: print(f'   x={x-run}-{x-1} {prev}')
        prev=q;run=1
print('===== 大厅输入框剖面 y=290 x520-690 =====')
prev=None;run=0
for x in range(520,695):
    q=tuple(int(v)//12*12 for v in lob[290,x])
    if q==prev: run+=1
    else:
        if prev is not None and run>=2: print(f'   x={x-run}-{x-1} {prev}')
        prev=q;run=1

# 5) 大厅标题色
reg=lob[75:98,528:660].reshape(-1,3)
lit=reg[reg.mean(axis=1)>140]
print('===== 大厅标题亮色 =====', tuple(round(float(v)) for v in lit.mean(axis=0)) if len(lit) else '无')
