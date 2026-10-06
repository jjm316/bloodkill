import numpy as np
from PIL import Image
def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(int)
a = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png')
m = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-board-desktop.png')

def fine(img,y,x0,x1,label):
    print(f'--- {label} y={y} x{x0}-{x1} (量化//8)')
    prev=None;run=0
    for x in range(x0,x1):
        q=tuple(int(v)//8*8 for v in img[y,x])
        if q==prev: run+=1
        else:
            if prev is not None and run>=3: print(f'   x={x-run:4}-{x-1:4} {prev} len={run}')
            prev=q;run=1
    print(f'   x={x1-run:4}-{x1-1:4} {prev} len={run}')

def vfine(img,x,y0,y1,label):
    print(f'--- {label} x={x} y{y0}-{y1} (量化//8)')
    prev=None;run=0
    for y in range(y0,y1):
        q=tuple(int(v)//8*8 for v in img[y,x])
        if q==prev: run+=1
        else:
            if prev is not None and run>=3: print(f'   y={y-run:4}-{y-1:4} {prev} len={run}')
            prev=q;run=1
    print(f'   y={y1-run:4}-{y1-1:4} {prev} len={run}')

print('===== 实截图 阿玫(顶左座) =====')
fine(a,224,250,420,'实拍-阿玫横')
vfine(a,328,150,300,'实拍-阿玫纵')
print('===== 参考稿 顶左座 =====')
# 参考稿布局可能不同，先看参考稿 OCR
