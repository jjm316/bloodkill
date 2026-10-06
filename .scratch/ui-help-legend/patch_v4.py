# -*- coding: utf-8 -*-
# v4 回归脚本：恢复六档、文件名 -v4、结构探测加 CSS 变量/computed 尺寸
import io
BASE = r"D:/AIProj/bloodkill/.scratch/ui-help-legend"
src = io.open(BASE + "/drive-v3.cjs", encoding="utf-8").read()

old_vp = "const VIEWPORTS = [1024, 320];"
new_vp = "const VIEWPORTS = [1024, 768, 640, 480, 360, 320];"
assert old_vp in src
src = src.replace(old_vp, new_vp)
assert src.count("}-v3.png") == 4
src = src.replace("}-v3.png", "}-v4.png")
assert "results-v3.json" in src
src = src.replace("results-v3.json", "results-v4.json")

old_h = """    const s = document.querySelector('.room-header .help-button svg');
    if (!s) return null;"""
new_h = """    const s = document.querySelector('.room-header .help-button svg');
    if (!s) return null;
    const b = document.querySelector('.room-header .help-button');
    const bcs = getComputedStyle(b);"""
assert old_h in src
src = src.replace(old_h, new_h)

old_r = "    return { circles: cs.length, paths: s.querySelectorAll('path').length, texts: s.querySelectorAll('text').length,"
new_r = """    return { cssVar: getComputedStyle(document.documentElement).getPropertyValue('--help-badge-size').trim(),
      btnCssW: bcs.width, btnCssH: bcs.height, btnMinH: bcs.minHeight,
      circles: cs.length, paths: s.querySelectorAll('path').length, texts: s.querySelectorAll('text').length,"""
assert old_r in src
src = src.replace(old_r, new_r)

io.open(BASE + "/drive-v4.cjs", "w", encoding="utf-8", newline="\n").write(src)

ink = io.open(BASE + "/ink_analysis_v3.py", encoding="utf-8").read()
ink = ink.replace("help-*-v3.png", "help-*-v4.png").replace("rules-q-*-v3.png", "rules-q-*-v4.png")
ink = ink.replace('r"help-(\d+)-v3"', 'r"help-(\d+)-v4"')
assert "help-*-v4.png" in ink and "rules-q-*-v4.png" in ink
io.open(BASE + "/ink_analysis_v4.py", "w", encoding="utf-8", newline="\n").write(ink)
print("PATCH_OK")
