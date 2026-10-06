import numpy as np
from PIL import Image
a = np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)

def rowprofile(y, x0, x1, step=4, label=''):
    print(f'--- 行 y={y} ({label}) x{x0}-{x1}')
    prev=None; run=0
    for x in range(x0,x1):
        c=tuple(a[y,x])
        q=tuple(v//24*24 for v in c)
        if q==prev: run+=1
        else:
            if prev is not None and run>=step:
                print(f'   x={x-run:4}-{x-1:4} color~{prev} len={run}')
            prev=q; run=1
    print(f'   x={x1-run:4}-{x1-1:4} color~{prev} len={run}')

# 阿玫 座位 (OCR cx=328, cy=224)
rowprofile(224, 180, 480, label='阿玫座位横剖面')
# 阿紫 自己座位 (cx=709, cy=548-610)
rowprofile(560, 560, 860, label='阿紫自己座位横剖面')
# 顶部 团子 (cx=644, cy=167)
rowprofile(167, 480, 820, label='团子座位横剖面')
