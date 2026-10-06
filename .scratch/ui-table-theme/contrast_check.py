# -*- coding: utf-8 -*-
"""WCAG 对比度抽查（ui-table-theme spec 用户故事 10：正文/界面文字 ≥4.5:1）。
色值与 client/src/styles.css 的主题变量同步维护。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BG = "#0e0709"
CARD = "#1f1219"
GOLD_DIM = "#2a1c0d"
TEXT = "#f2e7ea"
MUTED = "#b9a3ac"
GOLD_TEXT = "#f0c060"
GOLD = "#f5c518"
DANGER = "#ff8a80"
DIM = "#937f88"  # slot.empty.dim
ROSE_BG = "#8e2723"
BEAST_BG = "#33608f"
CATS = {"匕首": "#d05a50", "干涉": "#f5c518", "技能": "#9a6fd0", "亮牌": "#4fae7a", "资源": "#4f9bd0", "流程": "#8a91a6"}


def lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PAIRS = [
    ("正文 text / 页面底 bg", TEXT, BG),
    ("正文 text / 卡片 card", TEXT, CARD),
    ("辅助 muted / 页面底 bg", MUTED, BG),
    ("辅助 muted / 卡片 card", MUTED, CARD),
    ("等级字 gold-text / 卡片 card", GOLD_TEXT, CARD),
    ("等级字 gold-text / 金底 gold-dim", GOLD_TEXT, GOLD_DIM),
    ("警示 danger / 页面底 bg", DANGER, BG),
    ("暗记字 dim / 卡片 card", DIM, CARD),
    ("跳转链/选中页签 深字 bg / 金底 gold", BG, GOLD),
    ("玫槽白字 / 玫红底", "#ffffff", ROSE_BG),
    ("兽槽白字 / 兽蓝底", "#ffffff", BEAST_BG),
    *[("页签未选中字 " + name + " / bg", color, BG) for name, color in CATS.items()],
    *[("页签选中深字 bg / " + name + " 底", BG, color) for name, color in CATS.items()],
]

failed = 0
for label, fg, bg in PAIRS:
    r = ratio(fg, bg)
    ok = r >= 4.5
    failed += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {r:5.2f}:1  {label} ({fg} on {bg})")
print("\n结果:", "全部 ≥4.5:1" if failed == 0 else f"{failed} 项不达标")
sys.exit(1 if failed else 0)
