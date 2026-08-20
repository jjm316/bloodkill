# 建立内容数据与原创占位素材管线

Type: task
Status: resolved
Blocked by: 01, 03

问题：将卡牌、能力、单位、版图、图标和文本做成数据驱动资源；区分规则 ID、显示文案、素材引用和本地化键，避免把未授权原文硬编码进客户端。

输出：内容 schema、校验器、最小占位牌组/地图、资源许可证清单、中文/英文 i18n 结构和数据版本策略。

完成条件：新增一张卡/一个单位无需改引擎代码；缺失/重复 ID 在构建时失败；占位素材可完整支撑 MVP 对局。

## Answer

已完成 `blood_bound/content/` 内容目录和 `blood_bound.content` 纯标准库加载/校验 API：

- `catalog.json` 用稳定的规则 ID（如 `unit.rose.01`）、i18n 显示键和素材 ID 分别描述 19 个身份单元、10 个能力、3 个阵营、5 个资源以及供应区/牌桌/座位占位区；新增展示单元或区域只需新增数据记录，不改引擎代码。
- `locales/en.json` 与 `locales/zh-Hans.json` 提供独立中英文本；`licenses.json` 为每个占位素材引用记录来源和许可边界。所有文本和素材都是项目原创占位，不含官方规则书文案、卡牌插画、Logo、扫描件或 trade dress。
- `validate_content()` 在读取时拒绝 schema/ruleset 不匹配、重复或缺失 ID、不完整的 1--9 双家族加审判官牌组、悬空能力/素材引用、缺失翻译和没有许可证记录的素材；`load_content()` 可接收 fixture 目录，适合构建期或 CI 使用。
- 两个已有引擎行为 (`grant-quill`、`damage-two`) 与审判官诅咒分发有明确 `implementation` 标记；来源 C 尚未覆盖的 rank 3--9 均标记为 `unimplemented`，不通过占位内容猜测规则效果。

数据版本策略与使用方式见 [内容目录说明](../../../blood_bound/content/README.md)。测试扩展至内容加载、双语解析、重复 ID、缺失翻译和缺失许可证；`python -m unittest discover -v` 通过 12 项。

## Comments

- 2026-08-20：从 frontier 认领并完成；内容 schema 刻意与权威 `EngineState` 分离，游戏的 `rulesetVersion` 不会被内容更新静默重解释。
