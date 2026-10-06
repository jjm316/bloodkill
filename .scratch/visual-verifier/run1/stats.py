import sys, numpy as np
from PIL import Image

def lum(c):
    r,g,b = c[...,0].astype(float), c[...,1].astype(float), c[...,2].astype(float)
    return 0.2126*r+0.7152*g+0.0722*b

def region_mean(a, x0,y0,x1,y1):
    return a[y0:y1, x0:x1].reshape(-1, a.shape[2]).mean(axis=0)

files = {
 'board-desktop': r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-desktop-1440.png',
 'board-mobile':  r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\board-mobile-390.png',
 'lobby-desktop': r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\lobby-desktop-1440.png',
 'waiting-desktop': r'D:\AIProj\bloodkill\.scratch\ui-table-theme\shots\waiting-desktop-1440.png',
 'mock-board-desktop': r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-board-desktop.png',
 'mock-board-mobile':  r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-board-mobile.png',
 'mock-waiting-desktop': r'D:\AIProj\bloodkill\.scratch\ui-table-theme\mockups\after-waiting-desktop.png',
 'baseline-mobile': r'D:\AIProj\bloodkill\.scratch\ui-review\07-mobile-board.png',
}
for name, p in files.items():
    im = Image.open(p).convert('RGB')
    a = np.asarray(im)
    H,W = a.shape[:2]
    L = lum(a)
    k = max(20, W//20)
    corners = [L[:k,:k].mean(), L[:k,-k:].mean(), L[-k:,:k].mean(), L[-k:,-k:].mean()]
    center = L[H//2-40:H//2+40, W//2-40:W//2+40].mean()
    # dominant colors via coarse quantization
    q = (a//32*32).reshape(-1,3)
    colors, counts = np.unique(q, axis=0, return_counts=True)
    idx = np.argsort(-counts)[:6]
    top = [(tuple(int(v) for v in colors[i]), round(counts[i]/len(q)*100,1)) for i in idx]
    print(f'== {name} {W}x{H}')
    print(f'   corner-lum avg={np.mean(corners):.1f} (4角: {[round(c,1) for c in corners]}) center-lum={center:.1f} vignette_delta={center-np.mean(corners):.1f}')
    print(f'   top-colors(量化32): {top}')
