"""
Tests for ``count_tokens`` — token counting with tiktoken / fallback.
"""

import pytest
from unittest.mock import patch


class TestCountTokens:
    def test_count_tokens_tiktoken(self):
        """Test with real tiktoken if available, otherwise skip."""
        try:
            import tiktoken
        except ImportError:
            pytest.skip("tiktoken not installed")
        from qdrant_proxy_final import count_tokens, TOKEN_METHOD

        assert TOKEN_METHOD == "tiktoken (exact)"
        assert count_tokens("") == 0
        assert count_tokens("hello world") > 0

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("", 0 if None else None),
            ("hello world", None),
            ("a " * 1000, None),
            ("café résumé 日本語", None),
        ],
    )
    def test_count_tokens_fallback(self, text, expected):
        """Force the fallback estimator by removing tiktoken, then restore."""
        with patch.dict("sys.modules", {"tiktoken": None}):
            import importlib
            import qdrant_proxy_final

            importlib.reload(qdrant_proxy_final)
            from qdrant_proxy_final import count_tokens, TOKEN_METHOD

            assert TOKEN_METHOD == "estimate ±5%"
            result = count_tokens(text)
            assert isinstance(result, int)
            assert result >= 0
            if not text:
                assert result == 0

        importlib.reload(qdrant_proxy_final)
