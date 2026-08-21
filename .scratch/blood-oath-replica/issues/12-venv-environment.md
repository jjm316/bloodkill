# 用本机 Python 3.11 搭建开发 venv

Type: task
Blocked by: 无
Status: resolved

问题：开发机 `python` 默认解析到 Python 3.8.6 (32-bit)，`str.removeprefix`（3.9+）等语法在 3.8 失败，FastAPI 服务端无法启动。本机已装 Python 3.11 (64-bit)（`C:\Users\wisdom\AppData\Local\Programs\Python\Python311\`，经 `py -3.11` 可达），但不在 `python` 默认 PATH。

输出：仓库根目录 `.venv`（基于 `py -3.11`），`.gitignore` 增加 `.venv/`，全量单测在 3.11 下通过。

完成条件：`py -3.11 -m venv .venv` 建成；`.venv/Scripts/python.exe --version` 为 3.11；`.venv/Scripts/python.exe -m unittest discover -v` 全绿；服务端 `pip install -r server/requirements.txt` 后可导入。

## Answer

已交付：

- `py -3.11 -m venv .venv` 建成，`.venv/Scripts/python.exe` = Python 3.11.4。
- `.gitignore` 增加 `.venv/`。
- `.venv/Scripts/python.exe -m unittest discover -v`：**31 项全部通过**（含此前 3.8 下失败的 `test_paused_game_and_debug_link_round_trip`）。
- 后续所有测试/服务端命令统一用 `.venv/Scripts/python.exe`，或激活 `.venv` 后执行。
