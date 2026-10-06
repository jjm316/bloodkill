import numpy as np
from PIL import Image
a=np.asarray(Image.open(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png').convert('RGB')).astype(int)
R,G,B=a[...,0],a[...,1],a[...,2]
weak=(R>=85)&(G>=50)&(B<=115)&(R>G+15)&(G>B+8)
def count(mask,x0,y0,x1,y1): return int(mask[y0:y1,x0:x1].sum())
print('阿紫卡边弱金计数:')
print('  上边 y524-532 x625-820:', count(weak,625,524,820,532))
print('  下边 y630-646 x625-820:', count(weak,625,630,820,646))
print('  左边 x612-628 y528-640:', count(weak,612,528,628,640))
print('  右边 x818-832 y528-640:', count(weak,818,528,832,640))
print('对比-大猫金边卡(参照):')
print('  上边 y486-492 x940-1128:', count(weak,940,486,1128,492))
print('  左边 x928-936 y492-552:', count(weak,928,492,936,552))
print('对比-普通卡(阿玫 约 x262-394 y185-262):')
print('  全框弱金:', count(weak,258,180,400,268))
