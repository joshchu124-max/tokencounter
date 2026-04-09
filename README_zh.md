# TokenCounter

<p align="center">
  <strong>一款轻量级 Windows 桌面工具，用于本地 Token 计数。</strong><br>
  在任意应用中选中文本，双击 Ctrl，即刻查看 Token 数。
</p>

<p align="center">
  <a href="https://github.com/joshchu124-max/tokencounter/releases/tag/0.1.0"><img alt="Release" src="https://img.shields.io/github/v/release/joshchu124-max/tokencounter?style=flat-square"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010+-0078d4?style=flat-square&logo=windows">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white">
</p>

<p align="center">
  <a href="README.md">English</a> | <strong>中文</strong>
</p>

---

## 功能特性

- **双击 Ctrl 触发** — 在任意应用中选中文本，双击 Ctrl 即可查看 Token 数
- **100% 本地运行** — 所有分词通过 [tiktoken](https://github.com/openai/tiktoken) 在本地完成，无网络请求
- **多种分词器** — 支持 GPT-4o (`o200k_base`) 和 GPT-4 (`cl100k_base`) 切换
- **悬浮提示框** — 现代深色主题，自动淡出，可调停留时间
- **系统托盘** — 常驻系统托盘，右键菜单配置所有选项
- **单文件分发** — 打包为单个 `.exe`，开箱即用

## 快速开始

### 方式一：下载 exe

从 [Releases](https://github.com/joshchu124-max/tokencounter/releases) 页面下载 `TokenCounter.exe`，双击运行，无需安装。

### 方式二：从源码运行

```bash
git clone https://github.com/joshchu124-max/tokencounter.git
cd tokencounter
pip install -r requirements.txt
python -m tokencounter
```

### 构建独立 exe

```bash
pip install -r requirements-dev.txt
# 先缓存 tiktoken 数据：
python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"
# 构建：
pyinstaller tokencounter.spec
# 输出：dist/TokenCounter.exe
```

## 使用方法

1. 启动 `TokenCounter.exe` — 系统托盘出现图标
2. 在**任意应用**中选中文本
3. **快速双击 Ctrl** — 弹出悬浮提示框，显示 Token 数、字符数和当前分词器
4. 右键托盘图标可以：
   - 启用 / 禁用
   - 切换分词器（GPT-4o / GPT-4）
   - 调整提示框停留时间（1–5 秒）
   - 从剪贴板计算
   - 退出

## 配置

设置保存在 `%APPDATA%\TokenCounter\config.json`：

| 键名 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tokenizer` | `string` | `"o200k_base"` | 当前分词编码 |
| `hotkey_vk` | `int` | `0xA2` | 触发键的虚拟键码（左 Ctrl） |
| `enabled` | `bool` | `true` | 总开关 |
| `tooltip_display_s` | `float` | `2.0` | 提示框停留秒数 |
| `blacklist` | `string[]` | `[]` | 需忽略的进程名列表 |

## 项目结构

```
src/tokencounter/
├── __main__.py           # 入口 & 单实例互斥锁
├── app.py                # 应用编排 & Win32 消息循环
├── hooks.py              # 全局键盘钩子（双击 Ctrl 检测）
├── acquisition.py        # 文本获取（模拟 Ctrl+C）
├── tokenizer_adapter.py  # 分词器抽象 + tiktoken 后端
├── tooltip.py            # 悬浮提示窗口（Win32 GDI）
├── tray.py               # 系统托盘图标 & 右键菜单
├── config.py             # 配置持久化（JSON）
├── constants.py          # 共享常量
└── utils.py              # DPI 感知、屏幕几何、日志
```

## 开发

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## 许可证

本项目基于 [GNU Affero General Public License v3.0](LICENSE) 许可。

Copyright (c) 2026 Josh Chu
