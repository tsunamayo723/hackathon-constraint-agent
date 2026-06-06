"""
LLM呼び出しの一時エラー判定（リトライ対象か）のテスト

Geminiは呼ばない。_is_transient の分類だけを確認する。
- 503/500/UNAVAILABLE/overloaded → リトライ対象（True）
- 429/RESOURCE_EXHAUSTED（枠切れ） → リトライ対象外（False）
"""

from src.llm import _is_transient


class FakeError(Exception):
    def __init__(self, message: str, code=None):
        super().__init__(message)
        self.code = code


def test_503_message_is_transient():
    assert _is_transient(FakeError("503 UNAVAILABLE. high demand")) is True


def test_code_503_is_transient():
    assert _is_transient(FakeError("server error", code=503)) is True


def test_overloaded_is_transient():
    assert _is_transient(FakeError("The model is overloaded")) is True


def test_429_is_not_transient():
    assert _is_transient(FakeError("429 RESOURCE_EXHAUSTED. quota")) is False


def test_400_is_not_transient():
    assert _is_transient(FakeError("400 INVALID_ARGUMENT")) is False
