"""
ソルバーの入出力スキーマ

SolverInput  → ソルバーに渡す完全な仕様書
SolverOutput → ソルバーが返す結果（solved / infeasible / timeout）
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

# 「date」という名前のフィールドが型名 date をシャドーするのを避けるための別名
DateType = date

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
    shortage_penalty: int = 0  # 必要人数の不足による減点（0なら全ブロック充足）
    soft_penalty: int = 0   # ソフト制約の罰金合計（小さいほど希望が叶っている）
    assignment_units: int = 0  # 割当コマ数の合計（総労働コマ）

    # 100点満点の評価指標（充足率ベース）
    required_units: int = 0    # 必要だった人数の合計（コマ単位）
    shortage_units: int = 0    # 満たせなかった人数の合計（コマ単位）
    coverage_score: float = 100.0  # 充足スコア = (required - shortage) / required × 100


# ── 評価指標（完成シフトの良し悪しを多角的に見る） ───────────────


class PositionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_id: str
    required: int       # 必要だった人数（コマ単位）
    filled: int         # 満たせた人数（コマ単位）
    rate: float         # 充足率（%）


class StaffStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: str
    name: str
    assigned_slots: int           # 割り当てられたコマ数（総労働コマ）
    work_days: int                # 出勤日数
    offered_slots: Optional[int] = None  # 出勤希望として出した枠のコマ数（無制限の人はNone）
    utilization: Optional[float] = None  # 希望消化率（assigned/offered ×100）


class ShiftEvaluation(BaseModel):
    """完成シフトの評価指標まとめ。"""
    model_config = ConfigDict(extra="forbid")

    coverage_score: float                      # 全体の充足率（=meta.coverage_score）
    position_coverage: list[PositionCoverage] = []
    staff_stats: list[StaffStat] = []
    # 公平性（出勤コマ数の散らばり）
    fair_min: int = 0
    fair_max: int = 0
    fair_avg: float = 0.0
    soft_violations: int = 0                    # ソフト制約（separate等）の違反件数


# ── 不変条件チェック（バリデータ） ───────────────────────────────


class Violation(BaseModel):
    """守られるべき不変条件の違反（＝あってはいけない。バグ検出用）。"""
    model_config = ConfigDict(extra="forbid")

    type: str                       # out_of_availability / double_booking / out_of_hours / invalid_id
    person_id: str = ""
    date: Optional[DateType] = None
    detail: str


class ValidationResult(BaseModel):
    """完成シフトを生データから独立に再検算した結果。"""
    model_config = ConfigDict(extra="forbid")

    valid: bool                        # 違反0ならTrue
    violation_count: int = 0
    violations: list[Violation] = []
    warnings: list[str] = []           # 運用上の要注意（希望未提出スタッフ等）


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

    # 完成シフトの評価指標（solved時のみ）
    evaluation: Optional["ShiftEvaluation"] = None

    # 不変条件チェック（生データから独立に再検算）
    validation: Optional["ValidationResult"] = None

    # 管理者承認後に再計算が必要かのフラグ
    recalculation_needed: bool = False
