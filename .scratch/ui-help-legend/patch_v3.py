# -*- coding: utf-8 -*-
# v3 定点复验脚本：仅 1024/320，文件名 -v3，结构探测加圆点 fill
import io
BASE = r"D:/AIProj/bloodkill/.scratch/ui-help-legend"
src = io.open(BASE + "/drive-v2.cjs", encoding="utf-8").read()

old_vp = "const VIEWPORTS = [1024, 768, 640, 480, 360, 320];"
new_vp = "const VIEWPORTS = [1024, 320];"
assert old_vp in src
src = src.replace(old_vp, new_vp)
assert src.count("}-v2.png") == 4
src = src.replace("}-v2.png", "}-v3.png")
assert "results-v2.json" in src
src = src.replace("results-v2.json", "results-v3.json")

old_s = """      pathStroke: p ? getComputedStyle(p).strokeWidth : null,"""
new_s = """      pathStroke: p ? getComputedStyle(p).strokeWidth : null,
      dotFill: cs[1] ? getComputedStyle(cs[1]).fill : null,"""
assert old_s in src
src = src.replace(old_s, new_s)

old_q = "    border: cs.borderTopWidth, color: cs.color };"
new_q = """    dotFill: svg && svg.querySelectorAll('circle')[1] ? getComputedStyle(svg.querySelectorAll('circle')[1]).fill : null,
    border: cs.borderTopWidth, color: cs.color };"""
assert old_q in src
src = src.replace(old_q, new_q)

io.open(BASE + "/drive-v3.cjs", "w", encoding="utf-8", newline="\n").write(src)

ink = io.open(BASE + "/ink_analysis_v2.py", encoding="utf-8").read()
ink = ink.replace("help-*-v2.png", "help-*-v3.png").replace("rules-q-*-v2.png", "rules-q-*-v3.png")
ink = ink.replace('r"help-(\d+)-v2"', 'r"help-(\d+)-v3"')
assert "help-*-v3.png" in ink and "rules-q-*-v3.png" in ink
io.open(BASE + "/ink_analysis_v3.py", "w", encoding="utf-8", newline="\n").write(ink)
print("PATCH_OK")
