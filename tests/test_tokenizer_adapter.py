"""Tests for the tokenizer adapter module."""

import pytest

_tiktoken_available = False
try:
    import tiktoken
    tiktoken.get_encoding("o200k_base")
    _tiktoken_available = True
except Exception:
    pass

requires_tiktoken = pytest.mark.skipif(
    not _tiktoken_available,
    reason="tiktoken encoding data not available (needs network on first run)",
)

from tokencounter.tokenizer_adapter import (
    TokenizerProvider,
    TokenizerRegistry,
)


@requires_tiktoken
class TestTiktokenProvider:
    def _make(self, enc="o200k_base", name="GPT-4o"):
        from tokencounter.tokenizer_adapter import TiktokenProvider
        return TiktokenProvider(enc, name)

    def test_o200k_basic(self):
        provider = self._make("o200k_base", "GPT-4o")
        count = provider.count_tokens("hello world")
        assert count > 0
        assert isinstance(count, int)

    def test_cl100k_basic(self):
        provider = self._make("cl100k_base", "GPT-4")
        count = provider.count_tokens("hello world")
        assert count > 0

    def test_encode_returns_list(self):
        provider = self._make("o200k_base", "GPT-4o")
        tokens = provider.encode("hello world")
        assert isinstance(tokens, list)
        assert all(isinstance(t, int) for t in tokens)
        assert len(tokens) == provider.count_tokens("hello world")

    def test_empty_string(self):
        provider = self._make("o200k_base", "GPT-4o")
        assert provider.count_tokens("") == 0
        assert provider.encode("") == []

    def test_unicode_text(self):
        provider = self._make("o200k_base", "GPT-4o")
        count = provider.count_tokens("你好世界 🌍")
        assert count > 0

    def test_long_text(self):
        provider = self._make("o200k_base", "GPT-4o")
        text = "The quick brown fox jumps over the lazy dog. " * 100
        count = provider.count_tokens(text)
        assert count > 100

    def test_name_and_encoding_name(self):
        provider = self._make("o200k_base", "GPT-4o (o200k_base)")
        assert provider.name == "GPT-4o (o200k_base)"
        assert provider.encoding_name == "o200k_base"

    def test_different_encodings_different_counts(self):
        text = "This is a test sentence with some words."
        o200k = self._make("o200k_base", "GPT-4o")
        cl100k = self._make("cl100k_base", "GPT-4")
        assert o200k.count_tokens(text) > 0
        assert cl100k.count_tokens(text) > 0

    def test_is_tokenizer_provider(self):
        provider = self._make("o200k_base", "GPT-4o")
        assert isinstance(provider, TokenizerProvider)


class TestTokenizerRegistry:
    @requires_tiktoken
    def test_builtins_registered(self):
        registry = TokenizerRegistry()
        providers = registry.providers
        assert "o200k_base" in providers
        assert "cl100k_base" in providers

    @requires_tiktoken
    def test_default_active(self):
        registry = TokenizerRegistry()
        active = registry.active
        assert active.encoding_name == "o200k_base"

    @requires_tiktoken
    def test_set_active(self):
        registry = TokenizerRegistry()
        registry.set_active("cl100k_base")
        assert registry.active.encoding_name == "cl100k_base"

    @requires_tiktoken
    def test_set_active_invalid(self):
        registry = TokenizerRegistry()
        with pytest.raises(ValueError, match="Unknown encoding"):
            registry.set_active("nonexistent_encoding")

    @requires_tiktoken
    def test_register_custom(self):
        from tokencounter.tokenizer_adapter import TiktokenProvider
        registry = TokenizerRegistry()
        custom = TiktokenProvider("o200k_base", "Custom Name")
        registry.register(custom)
        assert registry.providers["o200k_base"].name == "Custom Name"

    @requires_tiktoken
    def test_count_via_active(self):
        registry = TokenizerRegistry()
        count = registry.active.count_tokens("hello")
        assert count > 0
