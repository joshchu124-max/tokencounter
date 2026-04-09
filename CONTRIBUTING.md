# Contributing to TokenCounter

> [中文版](CONTRIBUTING_zh.md)

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/joshchu124-max/tokencounter.git
cd tokencounter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Running Tests

```bash
pytest tests/ -v
```

## Building the Exe

```bash
python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"
pyinstaller tokencounter.spec
```

## Pull Request Guidelines

1. Fork the repository and create a feature branch from `main`
2. Keep changes focused — one feature or fix per PR
3. Add or update tests if applicable
4. Ensure all tests pass before submitting
5. Write clear commit messages

## Reporting Issues

- Use GitHub Issues
- Include your Windows version and Python version
- Attach the log file at `%APPDATA%\TokenCounter\tokencounter.log` if relevant

## License

By contributing, you agree that your contributions will be licensed under the AGPL-3.0 license.
