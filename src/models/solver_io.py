"""
ソルバーの入出力スキーマ

SolverInput  → ソルバーに渡す完全な仕様書
SolverOutput → ソルバーが返す結果（solved / infeasible / timeout）
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from .constraints import Constraint, Frame
from .master import Masters
from .parser_io import UntranslatedConstraint


class SolverInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame: Frame
    masters: Masters
    constraints: list[Constraint]

    # AIが生成・承認した「動的タイプ」の制約。既知16typeのunion外なので別チャネルで受ける。
    # 各要素は {"type": <新type名>, "params": {...}}。登録済みハンドラがあれば適用される。
    dynamic_constraints: list[dict] = []


# ── 出力: 割当レコード ────────────────────────────────────────────


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    person_id: str
    position_id: str
    start: str              # "HH:MM"
    end: str                # "HH:MM"
    break_start: str | None = None  # 休憩なしはキーごと省略（None）
    break_end: str | None = None
    locked: bool = False    # True = 手動固定（再計算で動かさない）


# ── 出力: 警告レコード ────────────────────────────────────────────


class SolverWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str                           # "understaffed" / "interval_violation" / "mentor_absent" 等
    affected_date: Optional[date] = None
    affected_time: Optional[str] = None
    shortage: Optional[int] = None


# ── 出力: 充足不能時の詰まり箇所 ─────────────────────────────────


class BlockingConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    where: dict             # どの日付・スロット・ポジションで詰まったか
    detail: str             # 例: "必要4名に対し可用3名"


# ── 出力: メタ情報 ────────────────────────────────────────────────


class SolverMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    elapsed_ms: int
    objective: int          # 目的関数値（小さいほど良い）


# ── ソルバー出力（3ステータス） ───────────────────────────────────


class SolverOutput(BaseModel):
    """
    ソルバーの計算結果。

    shift_status:
      - "confirmed": すべての要望が反映されている確定版
      - "provisional": 一部の要望が未翻訳のため、保留中の暫定版
    """
    status: Literal["solved", "infeasible", "timeout"]
    shift_status: Literal["confirmed", "provisional"] = "confirmed"
    meta: SolverMeta | None = None
    assignments: list[Assignment] = []
    warnings: list[SolverWarning] = []
    blocking_constraints: list[BlockingConstraint] = []  # infeasible 時に使う

    # 未翻訳項目（暫定シフトの場合のみ非空）
    pending_constraints: list[UntranslatedConstraint] = []

    # 管理者承認後に再計算が必要かのフラグ
    recalculation_needed: bool = False
