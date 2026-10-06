import numpy as np
from PIL import Image
a=np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)
R,G,B=a[...,0],a[...,1],a[...,2]
weak=(R>=85)&(R<=175)&(G>=55)&(B<=110)&(R>G+18)&(G>B+12)

# 1) 阿紫自身卡四周弱金扫描（卡约 x608-832, y500-640）
print('--- 阿紫卡边缘弱金 ---')
for band,lab in [((500,515),'上'),((630,645),'下')]:
    ys=range(band[0],band[1])
    xs=np.nonzero(weak[band[0]:band[1],600:840].any(axis=0))[0]+600
    print(f'  {lab}边带 y{band[0]}-{band[1]}: 金色列 x={xs.tolist()[:40] if len(xs) else "无"} (count={len(xs)})')
for x in range(600,616):
    col=np.nonzero(weak[500:650,x])[0]
    if len(col)>8: print(f'  左缘 x={x}: {len(col)}px y{500+col.min()}-{500+col.max()}')
for x in range(824,840):
    col=np.nonzero(weak[500:650,x])[0]
    if len(col)>8: print(f'  右缘 x={x}: {len(col)}px y{500+col.min()}-{500+col.max()}')

# 2) 图标区域颜色分析（是否多色 emoji）
def iconstat(x0,y0,x1,y1,label):
    reg=a[y0:y1,x0:x1].reshape(-1,3)
    r,g,b=reg[:,0],reg[:,1],reg[:,2]
    lit=reg[(r+g+b)>180]  # 亮像素（图标笔画）
    if len(lit)==0: print(f'  {label}: 无亮像素'); return
    import colorsys
    hues=[]
    for c in lit:
        h,s,v=colorsys.rgb_to_hsv(*(c/255.0))
        if s>0.15: hues.append(round(h*360))
    from collections import Counter
    hc=Counter(h//30*30 for h in hues)
    blue_green=sum(v for k,v in hc.items() if 150<=k<=300)
    mean=tuple(round(float(x)) for x in lit.mean(axis=0))
    print(f'  {label}: 亮像素{len(lit)} 均色{mean} 色相分布{dict(sorted(hc.items()))} 蓝绿系占比{blue_green/max(1,len(hues))*100:.0f}%')
print('--- 图标区域颜色（找 emoji 特征：蓝/绿/多彩） ---')
iconstat(630,148,665,185,'团子卡图标')
iconstat(178,348,215,385,'小兽卡图标')
iconstat(512,352,562,388,'待办横幅图标')
iconstat(938,494,962,520,'大猫卡匕首图标')
iconstat(112,693,140,748,'等待横幅图标')
iconstat(866,548,890,585,'阿紫卡右下(徽记图标区)')

# 3) 对比度抽查（WCAG）
def ratio(c1,c2):
    def L(c):
        r,g,b=[x/255 for x in c]
        f=lambda u: u/12.92 if u<=0.03928 else ((u+0.055)/1.055)**2.4
        return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)
    l1,l2=L(c1),L(c2)
    hi,lo=max(l1,l2),min(l1,l2)
    return (hi+0.05)/(lo+0.05)
def region_col(x0,y0,x1,y1,bright_thresh=150):
    reg=a[y0:y1,x0:x1].reshape(-1,3)
    lit=reg[reg.mean(axis=1)>bright_thresh]; dark=reg[reg.mean(axis=1)<=80]
    return (lit.mean(axis=0) if len(lit) else None),(dark.mean(axis=0) if len(dark) else None)
print('--- 对比度（文字亮像素 vs 局部暗背景） ---')
for (x0,y0,x1,y1,lab) in [(520,360,900,412,'待办横幅文字'),(135,710,570,735,'等待横幅文字'),(119,25,1320,50,'顶部房间头'),(620,540,800,615,'阿紫卡文字'),(120,120,640,285,'等待房名册文字')]:
    pass
# 用具体截图重新载入等待房/大厅
w=np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\waiting-desktop-1440.png').convert('RGB')).astype(int)
l=np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\lobby-desktop-1440.png').convert('RGB')).astype(int)
def cr(img,x0,y0,x1,y1,lab,thresh=150):
    reg=img[y0:y1,x0:x1].reshape(-1,3)
    lit=reg[reg.mean(axis=1)>thresh]; dark=reg[reg.mean(axis=1)<=80]
    if len(lit)==0 or len(dark)==0: print(f'  {lab}: 样本不足'); return
    r=ratio(lit.mean(axis=0),dark.mean(axis=0))
    print(f'  {lab}: 亮均色{tuple(round(float(v)) for v in lit.mean(axis=0))} vs 暗均色{tuple(round(float(v)) for v in dark.mean(axis=0))} 对比度={r:.1f}:1')
cr(a,520,360,900,412,'桌面待办横幅文字')
cr(a,135,710,570,735,'桌面等待横幅文字')
cr(a,119,25,1320,50,'桌面顶部房间头')
cr(a,620,540,800,615,'阿紫自身卡文字')
cr(w,120,120,640,285,'等待房名册文字')
cr(l,528,75,665,100,'大厅标题文字')
cr(l,524,255,645,300,'大厅输入框文字')
