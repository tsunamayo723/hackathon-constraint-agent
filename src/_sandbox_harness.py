"""
サンドボックス実行ハーネス（subprobessの中で動く側）

AIが生成したハンドラコードを、小さな架空シナリオに適用して
「エラーなく動くか／解けるか」を確かめる。結果はJSON1行でstdoutに出す。

このファイルは sandbox.py から
  python -m src._sandbox_harness <code_file> <params_file>
の形で別プロセスとして起動される（タイムアウトはsandbox側で管理）。

※ 生成コードを exec するため、必ず別プロセス＋タイムアウトで隔離して使うこと。
"""

import json
import sys
import traceback
from datetime import date

from ortools.sat.python import cp_model

from src.handlers.builtin import handle_headcount
from src.models.constraints import HeadcountParams
from src.models.master import Masters
from src.solver.context import SolverContext
from src.solver.engine import _build_variables
from src.solver.slots import build_day_slots, date_range


def _build_tiny_context() -> SolverContext:
    """3名×5日×ホール1ポジションの小さな検証用シナリオ。"""
    masters = Masters.model_validate({
        "persons": [
            {"id": "p1", "name": "A"},
            {"id": "p2", "name": "B"},
            {"id": "p3", "name": "C"},
        ],
        "positions": [{"id": "pos_hall", "name": "ホール"}],
        "roles": [],
        "skills": [],
    })
    days = date_range(date(2026, 11, 2), date(2026, 11, 8))  # 月〜日を含む1週間
    slots = build_day_slots("11:00", "20:00", 60)
    ctx = SolverContext(model=cp_model.CpModel(), days=days, slots=slots, masters=masters)
    _build_variables(ctx)
    return ctx


def main() -> None:
    result = {"passed": False, "message": ""}
    try:
        handler_code = open(sys.argv[1], encoding="utf-8").read()
        example_params = json.load(open(sys.argv[2], encoding="utf-8"))

        ctx = _build_tiny_context()

        # 生成コードを実行して handle 関数を取り出す
        namespace: dict = {}
        exec(handler_code, namespace)
        handle = namespace.get("handle")
        if not callable(handle):
            result["message"] = "handle(params, ctx) 関数が定義されていません"
            print(json.dumps(result, ensure_ascii=True))
            return

        # 生成ハンドラを適用
        handle(example_params, ctx)

        # 何か解くものが必要なので、ベースの必要人数（ホール1名）を足す
        handle_headcount(
            HeadcountParams(slot_label="L", time_start="11:00", time_end="12:00",
                            position_id="pos_hall", count=1),
            ctx,
        )
        ctx.model.Minimize(
            sum(w * z for (w, z) in ctx.penalties) + sum(ctx.x.values())
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        status = solver.Solve(ctx.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result["passed"] = True
            result["message"] = "生成ハンドラを適用してソルバーが解けました（エラーなし）"
        elif status == cp_model.INFEASIBLE:
            result["passed"] = False
            result["message"] = "ハンドラ適用後に解なし（制約が強すぎる可能性）"
        else:
            result["passed"] = False
            result["message"] = "時間内に解けませんでした"

    except Exception as exc:
        result["passed"] = False
        result["message"] = f"実行エラー: {exc}"
        result["traceback"] = traceback.format_exc()[-1200:]

    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
