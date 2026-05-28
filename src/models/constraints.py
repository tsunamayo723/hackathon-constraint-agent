"""
制約 type 辞書 — 初期 16 type (Hard 8 / Soft 8)

設計ルール:
  - 同じ type は必ず同じ params 構造
  - Soft 制約の weight は 50〜1000 に必ずクリップ（プロンプトインジェクション対策）
  - Hard 制約をソルバーが絶対遵守 / Soft は罰金変数で表現
"""

from datetime import date
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ═══════════════════════════════════════════════════════════════════
#  グローバルフレーム（制約ではなく、ソルバー実行全体の枠）
# ═══════════════════════════════════════════════════════════════════


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date


class OperatingWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: str               # "HH:MM"
    close: str              # "HH:MM"
    slot_minutes: Literal[30, 60]


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Period
    operating_window: OperatingWindow
    policy_mode: Literal["wishes", "cost", "balance"]


# ═══════════════════════════════════════════════════════════════════
#  ハード制約 params (8種)
# ═══════════════════════════════════════════════════════════════════


class HeadcountParams(BaseModel):
    """ある時間帯・ポジションに必要な人数"""
    model_config = ConfigDict(extra="forbid")

    slot_label: str
    time_start: str     # "HH:MM"
    time_end: str       # "HH:MM"
    position_id: str
    count: int


class RoleRequirementParams(BaseModel):
    """あるポジション内で特定役職を最低何名"""
    model_config = ConfigDict(extra="forbid")

    slot_label: str
    position_id: str
    role_id: str
    count: int


class SkillRequirementParams(BaseModel):
    """あるポジション内で特定スキル保持者を最低何名"""
    model_config = ConfigDict(extra="forbid")

    slot_label: str
    position_id: str
    skill_id: str
    count: int


class AvailabilityParams(BaseModel):
    """その人が勤務可能な時間帯。枠外には割当不可"""
    model_config = ConfigDict(extra="forbid")

    person_id: str
    date: date
    start: str          # "HH:MM"
    end: str            # "HH:MM"


class MinRestIntervalParams(BaseModel):
    """連続勤務日の終業〜翌始業の最小空き時間"""
    model_config = ConfigDict(extra="forbid")

    hours: int


class BreakRuleParams(BaseModel):
    """一定時間以上の勤務に休憩を自動付与"""
    model_config = ConfigDict(extra="forbid")

    threshold_hours: float
    break_minutes: int


class MentorPairingParams(BaseModel):
    """新人だけのスロットを禁止し、熟練/一般を必ず同席させる"""
    model_config = ConfigDict(extra="forbid")

    newbie_role_id: str
    requires_role_ids: list[str]


class DemandTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["role", "skill"]
    id: str


class DemandAdjustmentParams(BaseModel):
    """特定日の必要人数を増減（繁忙日・閑散日対応）"""
    model_config = ConfigDict(extra="forbid")

    date: date
    slot_label: str
    position_id: str
    diff: int                           # 正=増員 / 負=減員
    target: DemandTarget | None = None  # 役職/スキル単位の増減（省略可）


# ═══════════════════════════════════════════════════════════════════
#  ソフト制約 params (8種) — weight は 50〜1000 にクリップ
# ═══════════════════════════════════════════════════════════════════


class _SoftParams(BaseModel):
    """ソフト制約の共通基底。weightを自動クリップする。"""

    weight: int

    @field_validator("weight")
    @classmethod
    def clip_weight(cls, v: int) -> int:
        return max(50, min(1000, v))


class SeparateParams(_SoftParams):
    """2名を同一スコープに同時配置しない（できれば避ける）"""
    model_config = ConfigDict(extra="forbid")

    person_a: str
    person_b: str
    scope: Literal["day", "slot"]


class PairTogetherParams(_SoftParams):
    """2名をできるだけ同じスコープに配置（引き継ぎペア等）"""
    model_config = ConfigDict(extra="forbid")

    person_a: str
    person_b: str
    scope: Literal["day", "slot"]


class PreferPersonParams(_SoftParams):
    """特定の人をできるだけ多く配置"""
    model_config = ConfigDict(extra="forbid")

    person_id: str


class AvoidSlotTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["role", "skill"]
    id: str


class AvoidPersonSlotParams(_SoftParams):
    """特定の人を特定スコープにできるだけ入れない"""
    model_config = ConfigDict(extra="forbid")

    person_id: str
    scope: Literal["day", "slot"]
    target: AvoidSlotTarget | None = None


class TimePreferenceParams(_SoftParams):
    """個人の時間帯選好（できればこの時間帯に入れて）"""
    model_config = ConfigDict(extra="forbid")

    person_id: str
    preferred_start: str | None = None  # "HH:MM"
    preferred_end: str | None = None    # "HH:MM"


class LimitConsecutiveParams(_SoftParams):
    """連続勤務日数の偏りを抑える"""
    model_config = ConfigDict(extra="forbid")

    person_id: str | None = None    # None = 全員に適用
    max_consecutive_days: int


class FairnessParams(_SoftParams):
    """出勤回数/時間の偏りを最小化"""
    model_config = ConfigDict(extra="forbid")

    dimension: Literal["shifts", "hours"]


class DesiredWorkdaysParams(_SoftParams):
    """本人の希望出勤日数レンジ"""
    model_config = ConfigDict(extra="forbid")

    person_id: str
    kind: Literal["range", "as_many", "as_few", "none"]
    min: int | None = None  # kind="range" のときのみ使用
    max: int | None = None  # kind="range" のときのみ使用


# ═══════════════════════════════════════════════════════════════════
#  ハード制約 型（type フィールドを持つラッパー）
# ═══════════════════════════════════════════════════════════════════


class HeadcountRequirement(BaseModel):
    type: Literal["headcount_requirement"] = "headcount_requirement"
    params: HeadcountParams


class RoleRequirement(BaseModel):
    type: Literal["role_requirement"] = "role_requirement"
    params: RoleRequirementParams


class SkillRequirement(BaseModel):
    type: Literal["skill_requirement"] = "skill_requirement"
    params: SkillRequirementParams


class Availability(BaseModel):
    type: Literal["availability"] = "availability"
    params: AvailabilityParams


class MinRestInterval(BaseModel):
    type: Literal["min_rest_interval"] = "min_rest_interval"
    params: MinRestIntervalParams


class BreakRule(BaseModel):
    type: Literal["break_rule"] = "break_rule"
    params: BreakRuleParams


class MentorPairing(BaseModel):
    type: Literal["mentor_pairing"] = "mentor_pairing"
    params: MentorPairingParams


class DemandAdjustment(BaseModel):
    type: Literal["demand_adjustment"] = "demand_adjustment"
    params: DemandAdjustmentParams


# ═══════════════════════════════════════════════════════════════════
#  ソフト制約 型
# ═══════════════════════════════════════════════════════════════════


class Separate(BaseModel):
    type: Literal["separate"] = "separate"
    params: SeparateParams


class PairTogether(BaseModel):
    type: Literal["pair_together"] = "pair_together"
    params: PairTogetherParams


class PreferPerson(BaseModel):
    type: Literal["prefer_person"] = "prefer_person"
    params: PreferPersonParams


class AvoidPersonSlot(BaseModel):
    type: Literal["avoid_person_slot"] = "avoid_person_slot"
    params: AvoidPersonSlotParams


class TimePreference(BaseModel):
    type: Literal["time_preference"] = "time_preference"
    params: TimePreferenceParams


class LimitConsecutive(BaseModel):
    type: Literal["limit_consecutive"] = "limit_consecutive"
    params: LimitConsecutiveParams


class Fairness(BaseModel):
    type: Literal["fairness"] = "fairness"
    params: FairnessParams


class DesiredWorkdays(BaseModel):
    type: Literal["desired_workdays"] = "desired_workdays"
    params: DesiredWorkdaysParams


# ═══════════════════════════════════════════════════════════════════
#  全 16 type ユニオン（パーサ出力やソルバー入力で使う型）
# ═══════════════════════════════════════════════════════════════════

Constraint = Annotated[
    Union[
        # Hard 8
        HeadcountRequirement,
        RoleRequirement,
        SkillRequirement,
        Availability,
        MinRestInterval,
        BreakRule,
        MentorPairing,
        DemandAdjustment,
        # Soft 8
        Separate,
        PairTogether,
        PreferPerson,
        AvoidPersonSlot,
        TimePreference,
        LimitConsecutive,
        Fairness,
        DesiredWorkdays,
    ],
    Field(discriminator="type"),
]

# type 名の一覧（パーサが "is_new_type" 判定に使う）
KNOWN_TYPES: frozenset[str] = frozenset({
    "headcount_requirement",
    "role_requirement",
    "skill_requirement",
    "availability",
    "min_rest_interval",
    "break_rule",
    "mentor_pairing",
    "demand_adjustment",
    "separate",
    "pair_together",
    "prefer_person",
    "avoid_person_slot",
    "time_preference",
    "limit_consecutive",
    "fairness",
    "desired_workdays",
})
