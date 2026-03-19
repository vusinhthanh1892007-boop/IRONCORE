"""
IronCore V2 — Phase 3 Tests: Token Compression
===============================================
Tests cho ironcore/optimizer/token_compressor.py

Chạy: python -m pytest tests/test_phase3_optimizer_compression.py -v

Test coverage:
  - TOONCodec: compress whitespace, blank lines, repeated punct, ngrams
  - LLMLinguaCompressor: prune câu ít quan trọng, giữ đúng keep_ratio
  - TokenCompressor.compress AUTO/TOON/LLMLINGUA
  - Threshold: text < min_tokens → skip compression (method=NONE)
  - compress_batch xử lý concurrent
  - Stats accumulation chính xác
  - Non-breaking: compress("") → trả về rỗng
  - keep_ratio=1.0 → không prune gì

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from ironcore.optimizer.token_compressor import (
    CompressionMethod,
    CompressedPayload,
    CompressionStats,
    LLMLinguaCompressor,
    TOONCodec,
    TokenCompressor,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _long_text(n_words: int = 600) -> str:
    """Tạo text đủ dài để vượt min_tokens threshold (mặc định 2000 tokens = ~8000 chars)."""
    base = "This is a sample sentence with multiple words and some numbers like 42. "
    return (base * (n_words // 12 + 1))[:n_words * 5]


def _make_compressor(min_tokens: int = 10, keep_ratio: float = 0.70) -> TokenCompressor:
    """TokenCompressor với threshold thấp để test dễ."""
    return TokenCompressor(
        min_tokens=min_tokens,
        default_keep_ratio=keep_ratio,
        default_method=CompressionMethod.AUTO,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test: TOONCodec
# ──────────────────────────────────────────────────────────────────────────────


def test_toon_collapses_multiple_spaces():
    """Multiple spaces → single space."""
    codec = TOONCodec()
    result = codec.compress("hello   world   foo")
    assert "  " not in result
    assert "hello world foo" == result


def test_toon_collapses_blank_lines():
    """3+ blank lines → 2 blank lines max."""
    codec = TOONCodec()
    text = "line1\n\n\n\n\nline2"
    result = codec.compress(text)
    assert "\n\n\n" not in result


def test_toon_collapses_repeated_punctuation():
    """... → … , !!! → ! , ??? → ?"""
    codec = TOONCodec()
    result = codec.compress("wait... really!!! are you sure???")
    assert "..." not in result
    assert "!!!" not in result
    assert "???" not in result
    assert "…" in result
    assert "!" in result
    assert "?" in result


def test_toon_strips_trailing_spaces_per_line():
    """Trailing spaces trên mỗi dòng phải bị xóa."""
    codec = TOONCodec()
    text = "hello   \nworld   \nfoo   "
    result = codec.compress(text)
    for line in result.split("\n"):
        assert not line.endswith(" "), f"Line has trailing space: {repr(line)}"


def test_toon_output_shorter_or_equal():
    """TOON output phải ngắn hơn hoặc bằng input."""
    codec = TOONCodec()
    text = "  hello   world   ...\n\n\n\nfoo!!!   "
    result = codec.compress(text)
    assert len(result) <= len(text)


def test_toon_empty_string():
    """Empty string → trả về empty."""
    codec = TOONCodec()
    assert codec.compress("") == ""


def test_toon_ngram_collapse():
    """Cụm từ lặp lại >= 3 lần → compact notation."""
    codec = TOONCodec()
    phrase = "step one do something then verify "
    text = (phrase * 4).strip()
    result = codec.compress(text)
    # Kết quả phải ngắn hơn — ngram đã bị collapse
    assert len(result) < len(text)
    # Phải có marker [×N]
    assert "[×" in result


def test_toon_preserves_meaning_keywords():
    """Các từ quan trọng không bị mất sau TOON."""
    codec = TOONCodec()
    text = "Error: Connection failed at port 8080. Retry  with  timeout=30."
    result = codec.compress(text)
    assert "Error" in result
    assert "8080" in result
    assert "Retry" in result


# ──────────────────────────────────────────────────────────────────────────────
# Test: LLMLinguaCompressor
# ──────────────────────────────────────────────────────────────────────────────


def test_llmlingua_reduces_text():
    """LLMLingua với keep_ratio=0.5 phải cho kết quả ngắn hơn input."""
    comp = LLMLinguaCompressor()
    text = (
        "This sentence is important. It contains critical errors. "
        "However, this one is just filler without much value. "
        "Another filler sentence goes here with no data. "
        "The result is that we only keep half of the sentences. "
        "Connection established at port 443 with timeout 30. "
        "This conclusion is very important and must be retained."
    )
    result = comp.compress(text, keep_ratio=0.5)
    assert len(result) < len(text)


def test_llmlingua_keep_ratio_1_returns_all():
    """keep_ratio=1.0 → không prune câu nào, trả về nguyên vẹn."""
    comp = LLMLinguaCompressor()
    sentences = [
        "First sentence here.",
        "Second sentence here.",
        "Third sentence here.",
    ]
    text = " ".join(sentences)
    result = comp.compress(text, keep_ratio=1.0)
    # Khi keep_ratio=1.0, tất cả câu được giữ
    assert len(result) >= len(text) * 0.95  # Cho phép ~5% sai số từ join


def test_llmlingua_short_text_no_prune():
    """Text chỉ có 2 câu → không prune."""
    comp = LLMLinguaCompressor()
    text = "Hello world. This is it."
    result = comp.compress(text, keep_ratio=0.5)
    # 2 sentences → không prune (guard: len(sentences) <= 2)
    assert result == text


def test_llmlingua_keeps_high_importance():
    """Câu chứa số và từ khóa quan trọng phải được ưu tiên giữ."""
    comp = LLMLinguaCompressor()
    important = "Error: 500 internal server error occurred at line 42."
    filler1 = "This is just some random words without much meaning."
    filler2 = "Another sentence that does not contain key information."
    filler3 = "More filler text to make the document longer and longer."
    text = f"{important} {filler1} {filler2} {filler3}"
    result = comp.compress(text, keep_ratio=0.40)
    # Câu quan trọng phải được giữ
    assert "Error" in result or "500" in result


def test_llmlingua_empty_string():
    """Empty text → trả về empty."""
    comp = LLMLinguaCompressor()
    assert comp.compress("") == ""


# ──────────────────────────────────────────────────────────────────────────────
# Test: TokenCompressor Façade
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compress_auto_reduces_long_text():
    """AUTO mode compress text dài → output ngắn hơn."""
    comp = _make_compressor(min_tokens=10)
    text = _long_text(300)
    result = await comp.compress(text)

    assert result.compressed_tokens <= result.original_tokens
    assert len(result.compressed_text) > 0
    assert result.method in (
        CompressionMethod.AUTO,
        CompressionMethod.TOON,
        CompressionMethod.LLMLINGUA,
    )


@pytest.mark.asyncio
async def test_compress_toon_only():
    """Method=TOON → chỉ TOON, không LLMLingua."""
    comp = _make_compressor(min_tokens=5)
    text = "hello   world   foo   bar   baz   qux   quux   corge   grault"
    result = await comp.compress(text, method=CompressionMethod.TOON)
    assert result.method == CompressionMethod.TOON
    assert "  " not in result.compressed_text


@pytest.mark.asyncio
async def test_compress_none_skips_everything():
    """Method=NONE → pass-through, không nén gì."""
    comp = _make_compressor(min_tokens=1)
    text = "this is  some   text"
    result = await comp.compress(text, method=CompressionMethod.NONE)

    assert result.method == CompressionMethod.NONE
    assert result.compressed_text == text
    assert result.tokens_saved == 0
    assert result.compression_ratio == 1.0


@pytest.mark.asyncio
async def test_compress_skips_short_text():
    """Text < min_tokens threshold → trả về NONE method, unchanged."""
    comp = TokenCompressor(min_tokens=10_000)  # Threshold cực cao
    short_text = "just a few words"
    result = await comp.compress(short_text)

    assert result.method == CompressionMethod.NONE
    assert result.compressed_text == short_text
    assert result.tokens_saved == 0


@pytest.mark.asyncio
async def test_compress_empty_text():
    """Empty text → không crash, trả về empty."""
    comp = _make_compressor(min_tokens=1)
    result = await comp.compress("")
    assert result.compressed_text == ""


@pytest.mark.asyncio
async def test_compress_stats_accumulate():
    """Gọi compress nhiều lần → stats accumulate đúng."""
    comp = _make_compressor(min_tokens=10)
    text = _long_text(200)

    for _ in range(3):
        await comp.compress(text, method=CompressionMethod.TOON)

    stats = comp.stats
    assert stats.total_calls == 3
    assert stats.toon_calls == 3
    assert stats.total_tokens_in > 0


@pytest.mark.asyncio
async def test_compress_batch_concurrent():
    """compress_batch xử lý nhiều texts cùng lúc, trả về đúng thứ tự."""
    comp = _make_compressor(min_tokens=10)
    texts = [_long_text(150) for _ in range(4)]

    results = await comp.compress_batch(texts, method=CompressionMethod.TOON)

    assert len(results) == 4
    for r in results:
        assert isinstance(r, CompressedPayload)
        assert r.method == CompressionMethod.TOON


@pytest.mark.asyncio
async def test_compress_llmlingua_only():
    """Method=LLMLINGUA → chỉ LLMLingua pass."""
    comp = _make_compressor(min_tokens=5, keep_ratio=0.50)
    text = (
        "This is a very important sentence with error code 42. "
        "This one is useless filler. "
        "Another filler here. "
        "Connection to server 192.168.1.1 was successful. "
        "Just another throwaway sentence here. "
        "Critical result: SUCCESS at timestamp 1234567890."
    )
    result = await comp.compress(text, method=CompressionMethod.LLMLINGUA)

    assert result.method == CompressionMethod.LLMLINGUA
    assert len(result.compressed_text) < len(text)


@pytest.mark.asyncio
async def test_compressed_payload_savings_pct():
    """CompressedPayload.savings_pct tính đúng."""
    payload = CompressedPayload(
        compressed_text="shorter",
        original_tokens=1000,
        compressed_tokens=700,
        method=CompressionMethod.TOON,
        compression_ratio=0.70,
        tokens_saved=300,
    )
    assert payload.savings_pct == pytest.approx(0.30, abs=0.001)


def test_reset_stats():
    """reset_stats() xóa sạch tất cả counters."""
    comp = _make_compressor()
    comp._stats.total_calls = 10
    comp._stats.total_tokens_saved = 5000
    comp.reset_stats()
    assert comp.stats.total_calls == 0
    assert comp.stats.total_tokens_saved == 0
