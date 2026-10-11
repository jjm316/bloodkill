from PIL import Image
V="D:/AIProj/bloodkill/.scratch/e2e-inspect/verify"
im=Image.open(f"{V}/board-cdp-1440x950.png").convert("RGB")
px=im.load()
def hx(p): return '#%02x%02x%02x'%p
pts={"阿玫 badge center":(576,171),"阿玫 eye center":(585,180),"咪咪 badge center":(964,171),"咪咪 eye center":(972,180),
     "阿玫 name text zone":(420,185),"memo(阿玫) center":(606,171)}
for k,(x,y) in pts.items(): print(k, hx(px[x,y]))
im.crop((395,145,630,245)).resize((705,300)).save(f"{V}/seat-阿玫-full-3x.png")
im.crop((782,145,1017,245)).resize((705,300)).save(f"{V}/seat-咪咪-full-3x.png")
im3=Image.open(f"{V}/board-cdp-390x844.png").convert("RGB")
im3.crop((0,95,199,205)).resize((597,330)).save(f"{V}/seat-阿玫-mobile-3x.png")
im3.crop((0,373,199,483)).resize((597,330)).save(f"{V}/seat-咪咪-mobile-3x.png")
print("seat crops saved")
