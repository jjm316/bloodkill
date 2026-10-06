import numpy as np
from PIL import Image
from collections import Counter
import colorsys
a=np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)

def sat_colors(x0,y0,x1,y1,label,minsat=0.3,minv=0.35):
    reg=a[y0:y1,x0:x1].reshape(-1,3)
    out=Counter()
    for c in reg:
        r,g,b=c/255.0
        h,s,v=colorsys.rgb_to_hsv(r,g,b)
        if s>=minsat and v>=minv:
            out[(round(h*360)//15*15, round(s,1))]+=1
    print(f'--- {label} 饱和色(hue,sat)->count (v>=0.35):')
    for k,v in out.most_common(12): print('   hue~%d sat~%.1f x%d'% (k[0],k[1],v))
    if not out: print('   无饱和像素 -> 单色线性图标')

sat_colors(634,150,658,182,'团子卡图标紧域')
sat_colors(182,352,208,380,'小兽卡图标紧域')
sat_colors(940,496,960,520,'大猫卡匕首紧域')

# 阿紫卡精确边界：垂直扫描 x=720 y480-670
print('--- 阿紫卡垂直扫描 x=720 ---')
prev=None;run=0
for y in range(480,670):
    q=tuple(int(v)//10*10 for v in a[y,720])
    if q==prev: run+=1
    else:
        if prev is not None and run>=3: print(f'   y={y-run}-{y-1} {prev}')
        prev=q;run=1
print('--- 阿紫卡水平扫描 y=575 / y=530 ---')
for yy in (530,575,620):
    prev=None;run=0
    line=f'   y={yy}: '
    for x in range(560,880):
        q=tuple(int(v)//10*10 for v in a[yy,x])
        if q==prev: run+=1
        else:
            if prev is not None and run>=6: line+=f'x{x-run}-{x-1}:{prev} '
            prev=q;run=1
    print(line)
# 横幅底边检查
R,G,B=a[...,0],a[...,1],a[...,2]
weak=(R>=85)&(R<=175)&(G>=55)&(B<=110)&(R>G+18)&(G>B+12)
for y in range(400,420):
    n=weak[y,500:940].sum()
    if n>30: print(f'横幅底边候选 y={y}: {n}px')
