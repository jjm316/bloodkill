import sys, json
from rapidocr_onnxruntime import RapidOCR
engine = RapidOCR()
src, dst = sys.argv[1], sys.argv[2]
res, _ = engine(src)
out = []
if res:
    for box, text, score in res:
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append({'x': round(min(xs)), 'y': round(min(ys)), 'x2': round(max(xs)), 'y2': round(max(ys)), 'cx': round((min(xs)+max(xs))/2), 'cy': round((min(ys)+max(ys))/2), 'text': text, 'score': round(float(score),3)})
json.dump(out, open(dst,'w',encoding='utf-8'), ensure_ascii=False, indent=0)
print(f'{len(out)} boxes -> {dst}')
