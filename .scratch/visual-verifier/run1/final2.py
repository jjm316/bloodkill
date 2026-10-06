import numpy as np
from PIL import Image
def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(int)
wai=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\waiting-desktop-1440.png')
mwait=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-waiting-desktop.png')
lob=load(r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\lobby-desktop-1440.png')

def find_box(img, cx, cy, half=90, label=''):
    # 从中心向外找背景突变确定盒子边
    row=img[cy]; bg=tuple(img[cy,cx])
    def scan(line, start, step):
        bgt=np.array(bg)
        for i in range(start, start+step*200, step):
            if not (0<=i<len(line)): return None
            if abs(int(line[i][0])-bgt[0])+abs(int(line[i][1])-bgt[1])+abs(int(line[i][2])-bgt[2])>60:
                return i
        return None
    l=scan(row,cx,-1); r=scan(row,cx,1)
    col=img[:,cx]
    t=scan(col,cy,-1); b=scan(col,cy,1)
    print(f'  {label} 中心({cx},{cy}) 盒约 x[{l}-{r}] y[{t}-{b}] 中心bg={bg}')
    return l,r,t,b

print('===== 等待房自己行盒检测 =====')
# 实拍 团子(你) 文本 (143-225, 262-278) -> 中心 (184,270)
l,r,t,b=find_box(wai,184,270,label='实拍-团子(你)行')
if l and t:
    for pos,lab in [((t+2,l+2),'左上内'),('t','上边'),('l','左边')]:
        pass
    # 上/左边颜色
    print('    上边色样本 y={} x{}-{}: {}'.format(t, l, r, [tuple(int(v) for v in wai[t,x]) for x in range(l+5,min(r,l+90),20)]))
    print('    左边色样本 x={} y{}-{}: {}'.format(l, t, b, [tuple(int(v) for v in wai[y,l]) for y in range(t+3,min(b,t+18),4)]))
# 实拍 大猫行 文本 (120-231, 228) -> 中心 (176,228)
l2,r2,t2,b2=find_box(wai,176,228,label='实拍-大猫行(对照)')
if t2:
    print('    上边色样本 y={} x{}-{}: {}'.format(t2, l2, r2, [tuple(int(v) for v in wai[t2,x]) for x in range(l2+5,min(r2,l2+90),20)]))
# 参考稿 阿玫(你) (312,163) 文本带 y~150-178
l3,r3,t3,b3=find_box(mwait,240,163,label='参考-阿玫(你)行')
if t3:
    print('    上边色样本 y={} x{}-{}: {}'.format(t3, l3, r3, [tuple(int(v) for v in mwait[t3,x]) for x in range(l3+5,min(r3,l3+90),20)]))
    print('    行内均色:', tuple(round(float(v)) for v in mwait[t3+4:b3-4, l3+6:r3-6].reshape(-1,3).mean(axis=0)))

print('===== 大厅按钮/输入框边框 =====')
# 创建房间 文本 (688-754, 215-232) 中心 (721,222)
l,r,t,b=find_box(lob,721,222,label='创建房间按钮')
if l and t:
    print('    边框色 上/左/右/下:', tuple(int(v) for v in lob[t,721]), tuple(int(v) for v in lob[222,l]), tuple(int(v) for v in lob[222,r]), tuple(int(v) for v in lob[b,721]))
# 房间号输入框 placeholder (538-642,292) 中心 (590,292)
l,r,t,b=find_box(lob,590,292,label='房间号输入框')
if l and t:
    print('    边框色 上/左/右/下:', tuple(int(v) for v in lob[t,590]), tuple(int(v) for v in lob[292,l]), tuple(int(v) for v in lob[292,r]), tuple(int(v) for v in lob[b,590]))

# 参考稿等待房也截一张对照自己行金边？已有。桌面对比结束。
