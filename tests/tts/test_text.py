import pytest

from lalk.tts import TextSegmenter
from lalk.tts.text import MarkdownSpeechNormalizer


def test_markdown_normalizer_preserves_plain_streaming_text() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("你好") == "你好"
    assert normalizer.push("，世界") == "，世界"
    assert normalizer.flush() == ""


def test_markdown_normalizer_handles_markup_split_across_deltas() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("# **你") == "你"
    assert normalizer.push("好**，看[文") == "好，看文"
    assert normalizer.push("档](https://example.com)。") == "档。"
    assert normalizer.flush() == ""


def test_markdown_normalizer_skips_fenced_code_and_resumes_text() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("说明。\n```py") == "说明。\n"
    assert normalizer.push("\nprint('x')\n```") == ""
    assert normalizer.push("\n继续。") == "\n继续。"
    assert normalizer.flush() == ""


def test_markdown_normalizer_supports_tilde_code_fences() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("之前。\n~~~text\n隐藏内容\n~~~\n之后。") == (
        "之前。\n\n之后。"
    )
    assert normalizer.flush() == ""


def test_markdown_normalizer_cleans_structural_lines() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("1. 第一项\n> 第二项\n---\n") == (
        "第一项\n第二项\n\n"
    )
    assert normalizer.flush() == ""


def test_markdown_normalizer_flushes_visible_pending_punctuation_and_resets() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("Hello!") == "Hello"
    assert normalizer.flush() == "!"
    assert normalizer.push("下一次") == "下一次"


def test_markdown_normalizer_drops_syntax_only_response() -> None:
    normalizer = MarkdownSpeechNormalizer()

    assert normalizer.push("```python\nprint('x')\n```") == ""
    assert normalizer.flush() == ""


@pytest.mark.parametrize("name", ["first_chunk_chars", "chunk_chars"])
def test_rejects_non_positive_limits(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        TextSegmenter(**{name: 0})


def test_releases_short_text_at_strong_break() -> None:
    segmenter = TextSegmenter()

    assert segmenter.push("你好！后面") == ["你好！"]
    assert segmenter.flush() == "后面"


def test_releases_soft_break_after_three_characters() -> None:
    segmenter = TextSegmenter()

    assert segmenter.push("你好呀，后面") == ["你好呀，"]
    assert segmenter.flush() == "后面"


def test_uses_shorter_limit_for_first_chunk() -> None:
    segmenter = TextSegmenter(first_chunk_chars=4, chunk_chars=6)

    assert segmenter.push("一二三四五六七八九十") == ["一二三四", "五六七八九十"]
    assert segmenter.flush() is None


def test_collects_deltas_until_a_break_is_available() -> None:
    segmenter = TextSegmenter(first_chunk_chars=6)

    assert segmenter.push("你好") == []
    assert segmenter.push("，世界") == ["你好，"]
    assert segmenter.flush() == "世界"


def test_flush_restores_the_first_chunk_limit() -> None:
    segmenter = TextSegmenter(first_chunk_chars=4, chunk_chars=8)

    assert segmenter.push("一二三四") == ["一二三四"]
    assert segmenter.push("五六七八") == []
    assert segmenter.flush() == "五六七八"
    assert segmenter.push("甲乙丙丁") == ["甲乙丙丁"]


def test_reset_discards_buffered_text() -> None:
    segmenter = TextSegmenter(first_chunk_chars=4)
    segmenter.push("一二三")

    segmenter.reset()

    assert segmenter.flush() is None
    assert segmenter.push("甲乙丙丁") == ["甲乙丙丁"]
