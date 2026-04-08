"""Module 3: Tokenizer abstraction layer with tiktoken implementations.

All tokenization is performed locally with no network calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import tiktoken


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class TokenizerProvider(ABC):
    """Interface that every tokenizer must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name, e.g. 'GPT-4o (o200k_base)'."""

    @property
    @abstractmethod
    def encoding_name(self) -> str:
        """Internal encoding identifier, e.g. 'o200k_base'."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Return the number of tokens for *text*."""

    @abstractmethod
    def encode(self, text: str) -> list[int]:
        """Return the list of token IDs for *text*."""


# ---------------------------------------------------------------------------
# tiktoken implementation
# ---------------------------------------------------------------------------

class TiktokenProvider(TokenizerProvider):
    """Wraps a tiktoken encoding as a :class:`TokenizerProvider`."""

    def __init__(self, encoding_name: str, display_name: str) -> None:
        self._encoding_name = encoding_name
        self._display_name = display_name
        self._enc = tiktoken.get_encoding(encoding_name)

    @property
    def name(self) -> str:
        return self._display_name

    @property
    def encoding_name(self) -> str:
        return self._encoding_name

    def count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def encode(self, text: str) -> list[int]:
        return self._enc.encode(text)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TokenizerRegistry:
    """Manages available tokenizer providers and the currently active one."""

    def __init__(self) -> None:
        self._providers: dict[str, TokenizerProvider] = {}
        self._active_key: str | None = None

        # Register built-in providers
        self._register_builtins()

    # -- public API ----------------------------------------------------------

    @property
    def providers(self) -> dict[str, TokenizerProvider]:
        return dict(self._providers)

    @property
    def active(self) -> TokenizerProvider:
        if self._active_key is None or self._active_key not in self._providers:
            raise RuntimeError("No active tokenizer set")
        return self._providers[self._active_key]

    def set_active(self, encoding_name: str) -> None:
        if encoding_name not in self._providers:
            raise ValueError(
                f"Unknown encoding: {encoding_name}. "
                f"Available: {list(self._providers.keys())}"
            )
        self._active_key = encoding_name

    def register(self, provider: TokenizerProvider) -> None:
        self._providers[provider.encoding_name] = provider

    # -- internals -----------------------------------------------------------

    def _register_builtins(self) -> None:
        self.register(TiktokenProvider("o200k_base", "GPT-4o (o200k_base)"))
        self.register(TiktokenProvider("cl100k_base", "GPT-4 (cl100k_base)"))
        # Default to o200k_base (GPT-4o)
        self._active_key = "o200k_base"
