# 贡献指南

感谢你对 TokenCounter 的关注！以下是参与贡献的方法。

## 开发环境搭建

```bash
git clone https://github.com/JoshChu/tokencounter.git
cd tokencounter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## 运行测试

```bash
pytest tests/ -v
```

## 构建 Exe

```bash
python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"
pyinstaller tokencounter.spec
```

## Pull Request 规范

1. 从 `main` 分支创建功能分支
2. 保持变更聚焦 — 每个 PR 只解决一个功能或修复
3. 如有需要，添加或更新测试
4. 提交前确保所有测试通过
5. 编写清晰的 commit message

## 问题反馈

- 使用 GitHub Issues
- 注明你的 Windows 版本和 Python 版本
- 如有相关，附上日志文件 `%APPDATA%\TokenCounter\tokencounter.log`

## 许可证

参与贡献即表示你同意你的贡献代码将以 AGPL-3.0 许可证发布。
