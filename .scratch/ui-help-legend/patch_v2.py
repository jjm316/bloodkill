# -*- coding: utf-8 -*-
# 由一轮脚本生成 v2 版本：文件名加 -v2、RULESQ_EXPR 改 svg 感知、加 structure 探测
import re, sys, io

BASE = r"D:/AIProj/bloodkill/.scratch/ui-help-legend"
src = io.open(BASE + "/drive.cjs", encoding="utf-8").read()

# 1) 文件名与结果文件加 v2
n1 = src.count("}.png")
src = src.replace("}.png", "}-v2.png")
assert n1 == 4, f"expect 4 png names, got {n1}"
assert "results.json" in src
src = src.replace("results.json", "results-v2.json")

# 2) RULESQ_EXPR 改为 svg 感知
old_q = """    x: +r.left.toFixed(1), y: +r.top.toFixed(1), text: q.textContent.trim(),
    border: cs.borderTopWidth, bg: cs.backgroundColor, color: cs.color,
    fontFamily: cs.fontFamily, display: cs.display };"""
new_q = """    x: +r.left.toFixed(1), y: +r.top.toFixed(1), text: q.textContent.trim(),
    hasSvg: !!svg, hasCircle: !!(svg && svg.querySelector('circle')),
    hasPath: !!(svg && svg.querySelector('path')), hasText: !!(svg && svg.querySelector('text')),
    bareText: [...q.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()),
    circleCount: svg ? svg.querySelectorAll('circle').length : 0,
    border: cs.borderTopWidth, color: cs.color };"""
assert old_q in src, "RULESQ_EXPR body not found"
src = src.replace(old_q, new_q)

old_qh = """  const q = document.querySelector('.rules-modal .rules-q');
  if (!q) return null;
  const r = q.getBoundingClientRect();
  const cs = getComputedStyle(q);"""
new_qh = """  const q = document.querySelector('.rules-modal .rules-q');
  if (!q) return null;
  const r = q.getBoundingClientRect();
  const svg = q.querySelector('svg');
  const cs = getComputedStyle(q);"""
assert old_qh in src, "RULESQ_EXPR head not found"
src = src.replace(old_qh, new_qh)

# 3) 在 metrics 后插入结构探测
old_m = "  res.metrics = await evalJS(cdp, METRICS_EXPR);"
new_m = old_m + """
  res.structure = await evalJS(cdp, `(() => {
    const s = document.querySelector('.room-header .help-button svg');
    if (!s) return null;
    const cs = s.querySelectorAll('circle');
    const p = s.querySelector('path');
    return { circles: cs.length, paths: s.querySelectorAll('path').length, texts: s.querySelectorAll('text').length,
      circleR: cs[0] ? cs[0].getAttribute('r') : null, dotR: cs[1] ? cs[1].getAttribute('r') : null,
      pathD: p ? p.getAttribute('d') : null,
      ringStroke: cs[0] ? getComputedStyle(cs[0]).strokeWidth : null,
      pathStroke: p ? getComputedStyle(p).strokeWidth : null,
      strokeColor: cs[0] ? getComputedStyle(cs[0]).stroke : null };
  })()`);"""
assert old_m in src, "metrics line not found"
src = src.replace(old_m, new_m)

io.open(BASE + "/drive-v2.cjs", "w", encoding="utf-8", newline="\n").write(src)

# 4) ink_analysis v2：glob/regex 匹配 -v2 文件
ink = io.open(BASE + "/ink_analysis.py", encoding="utf-8").read()
ink = ink.replace('glob.glob(os.path.join(OUT, "help-*.png"))', 'glob.glob(os.path.join(OUT, "help-*-v2.png"))')
ink = ink.replace('r"help-(\d+)"', 'r"help-(\d+)-v2"')
ink = ink.replace('glob.glob(os.path.join(OUT, "rules-q-*.png"))', 'glob.glob(os.path.join(OUT, "rules-q-*-v2.png"))')
assert "help-*-v2.png" in ink and "rules-q-*-v2.png" in ink
io.open(BASE + "/ink_analysis_v2.py", "w", encoding="utf-8", newline="\n").write(ink)
print("PATCH_OK")
