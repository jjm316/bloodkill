import numpy as np
from PIL import Image
def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(int)
a = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png')
m = load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-board-desktop.png')

def fine(img,y,x0,x1,label,thresh=2):
    print(f'--- {label} y={y} x{x0}-{x1}')
    prev=None;run=0
    for x in range(x0,x1):
        q=tuple(int(v)//12*12 for v in img[y,x])
        if q==prev: run+=1
        else:
            if prev is not None and run>=thresh: print(f'   x={x-run:4}-{x-1:4} {prev} len={run}')
            prev=q;run=1
    print(f'   x={x1-run:4}-{x1-1:4} {prev} len={run}')

# 参考稿 阿玫 (334,220)
fine(m,220,260,420,'参考稿-阿玫横')
# 参考稿 阿紫自己 (710,542)
fine(m,560,560,860,'参考稿-阿紫自己横')
# 实拍 阿紫自己 (709,548) 横剖面更细
fine(a,548,560,860,'实拍-阿紫自己横')
# 实拍 大猫 (971,509) vs 参考稿 大猫 (955,492) —— 匕首持有者?
fine(a,509,880,1080,'实拍-大猫横')
fine(m,492,880,1080,'参考稿-大猫横')
