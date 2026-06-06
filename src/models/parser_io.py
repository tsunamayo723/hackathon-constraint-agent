"""
パーサ（自然言語→制約JSON変換器）の入出力スキーマ

設計の核心:
  - 翻訳できた制約と翻訳できなかった文言を**両方とも**返す
  - 未翻訳の文言は元の自然言語のまま保持し、ユーザー画面で「保留中」として表示できるようにする
  - これにより「AIが分かったフリをしない」UXを実現する
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .constraints import Constraint


# ── パーサ入力 ──────────────────────────────────────────────────────


class ParserInput(BaseModel):
    """パーサに渡す自然言語入力"""
    model_config = ConfigDict(extra="forbid")

    input_text: str             # スタッフが入力した自然言語の文章
    person_id: Optional[str] = None  # 誰の発言か（マスタ照合用）
    context_hint: Optional[str] = None  # 「シフト希望」「制約変更」等の文脈ヒント


# ── 翻訳できた制約 ──────────────────────────────────────────────────


class TranslatedConstraint(BaseModel):
    """翻訳に成功した制約（既知の16タイプのいずれか）"""
    model_config = ConfigDict(extra="forbid")

    constraint: Constraint              # 既存のConstraintユニオン
    source_text: str                    # 元の自然言語の該当部分
    confidence: float = Field(ge=0.0, le=1.0)  # Geminiの自信度（0.0〜1.0）


# ── 翻訳できなかった文言 ────────────────────────────────────────────


class UntranslatedConstraint(BaseModel):
    """翻訳できなかった自然言語の断片。L2自動生成フローの入り口になる。"""
    model_config = ConfigDict(extra="forbid")

    source_text: str                                # 翻訳できなかった元の文言
    suggested_type_name: Optional[str] = None       # AIが推測した新type名候補
    reason: str                                     # ユーザー向け説明文

    # 人が読んで承認判断するための補助（パース時にFlashが付与）
    summary: Optional[str] = None                   # 一言で何のルールか（日本語）
    ai_assessment: Optional[str] = None             # AIの見解（なぜ未知か／どう解釈したか）
    review_points: list[str] = []                   # 管理者に確認してほしい点

    status: Literal["pending_review", "approved", "rejected"] = "pending_review"
    pending_request_id: Optional[str] = None        # 管理者キューのレコードID


# ── パーサ出力 ──────────────────────────────────────────────────────


class ParserOutput(BaseModel):
    """パーサの最終出力"""
    model_config = ConfigDict(extra="forbid")

    input_text: str                             # 元の入力全体（監査用）
    translated: list[TranslatedConstraint]      # 翻訳できた制約一覧
    untranslated: list[UntranslatedConstraint]  # 翻訳できなかった文言一覧
    parsed_at: datetime                         # 解析した時刻

    @property
    def has_untranslated(self) -> bool:
        """未翻訳項目があるかどうか（ソルバー出力のshift_status判定に使う）"""
        return len(self.untranslated) > 0
