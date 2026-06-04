"""
ソルバー文脈（SolverContext）

ハンドラ関数が共有する「作業台」。
- CP-SATモデル本体
- 割当変数 x[(人, 日, コマ, ポジション)]
- present / work_day などの補助変数
- ソフト制約の罰金項リスト
- 可用枠（availabilityハンドラが書き込み、最後にまとめて適用）

ハンドラは「この作業台に制約や罰金を足していく」だけ。
CP-SAT本体には触れずに済むようにしている（＝ソルバーはブラックボックス）。
"""

from datetime import date

from ortools.sat.python import cp_model

from src.models.master import Masters
from .slots import Slot


class SolverContext:
    def __init__(
        self,
        model: cp_model.CpModel,
        days: list[date],
        slots: list[Slot],
        masters: Masters,
    ):
        self.model = model
        self.days = days
        self.slots = slots
        self.masters = masters

        self.person_ids = [p.id for p in masters.persons]
        self.position_ids = [p.id for p in masters.positions]

        # 割当変数: (person_id, day_index, slot_index, position_id) -> BoolVar
        self.x: dict[tuple, cp_model.IntVar] = {}
        # 在席変数: (person_id, day_index, slot_index) -> BoolVar（=そのコマで何かのポジションにいる）
        self.present: dict[tuple, cp_model.IntVar] = {}
        # 出勤変数: (person_id, day_index) -> BoolVar（=その日に1コマでも入る）
        self.work_day: dict[tuple, cp_model.IntVar] = {}

        # ソフト制約の罰金項: (係数, 変数) のリスト。目的関数で最小化する。
        self.penalties: list[tuple[int, cp_model.IntVar]] = []

        # availability ハンドラが書き込む可用枠:
        #   person_id -> {day_index -> [(start_min, end_min), ...]}
        # 1件でも登録された人は「出勤希望ベース」で枠外に入れなくなる。
        self.availability: dict[str, dict[int, list[tuple[int, int]]]] = {}

    def add_penalty(self, weight: int, var: cp_model.IntVar) -> None:
        """ソフト制約の罰金を1項追加する（weightはモデル側で50〜1000にクリップ済み）"""
        self.penalties.append((weight, var))
