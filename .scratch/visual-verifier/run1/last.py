import numpy as np
from PIL import Image
def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(int)
mock=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-board-desktop.png')
mob=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-mobile-390.png')
R,G,B=mock[...,0],mock[...,1],mock[...,2]
crim=(R>35)&(R<110)&(G<45)&(B<60)&(R>G+20)&(R>B+15)
ys,xs=np.nonzero(crim)
print('参考稿桌面绯红 bbox: x[%d-%d] y[%d-%d] center=(%d,%d)'%(xs.min(),xs.max(),ys.min(),ys.max(),(xs.min()+xs.max())//2,(ys.min()+ys.max())//2))
# 移动端横幅金边
R,G,B=mob[...,0],mob[...,1],mob[...,2]
gold=(R>120)&(G>75)&(B<115)&(R>G+20)&(G>B+15)
for y0,y1,lab in [(60,130,'顶部待办横幅区'),(415,465,'等待横幅区')]:
    sub=gold[y0:y1]
    ys2,xs2=np.nonzero(sub)
    if len(xs2): print(f'移动端{lab}: 金px={len(xs2)} x[{xs2.min()+0}-{xs2.max()}] y[{ys2.min()+y0}-{ys2.max()+y0}]')
    else: print(f'移动端{lab}: 无金像素')
