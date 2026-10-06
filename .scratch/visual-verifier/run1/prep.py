import sys
from PIL import Image, ImageOps
src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert('L')
im = ImageOps.invert(im)          # 暗底亮字 -> 亮底暗字
im = ImageOps.autocontrast(im, cutoff=1)
im = im.resize((im.width*2, im.height*2), Image.LANCZOS)
im.save(dst)
print(dst, im.size)
