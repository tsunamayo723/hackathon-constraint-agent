"""
ソルバー実行エンドポイント

POST /solver/run : SolverInput を受け取り、OR-Tools で実際にシフトを計算する。

最小ソルバー版で対応する制約は3タイプ:
  headcount_requirement / availability / separate
（未対応タイプは warnings に "unhandled:<type>" として明示し、無視せず可視化する）

未翻訳の要望（pending_constraints）を一緒に渡すと、結果は「暫定版」になる。
"""

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from src.models.parser_io import UntranslatedConstraint
from src.models.solver_io import SolverInput, SolverOutput
from src.solver.engine import solve
from src.storage import (
    get_availability,
    get_base_headcounts,
    get_frame,
    get_masters,
    get_policy_constraints,
    list_pending_requests,
)

router = APIRouter(prefix="/solver", tags=["ソルバー"])


_run_examples = {
    "① 必要人数だけ（確定シフト）": {
        "summary": "2名・ランチにホール1名 → confirmed",
        "value": {
            "frame": {
                "period": {"start": "2026-11-01", "end": "2026-11-03"},
                "operating_window": {"open": "11:00", "close": "14:00", "slot_minutes": 60},
                "policy_mode": "balance",
            },
            "masters": {
                "persons": [
                    {"id": "p1", "name": "スタッフ01", "role_id": "r_staff", "skill_ids": []},
                    {"id": "p2", "name": "スタッフ02", "role_id": "r_staff", "skill_ids": []},
                ],
                "positions": [{"id": "pos_hall", "name": "ホール"}],
                "roles": [{"id": "r_staff", "name": "スタッフ"}],
                "skills": [],
            },
            "constraints": [
                {
                    "type": "headcount_requirement",
                    "params": {
                        "slot_label": "ランチ",
                        "time_start": "11:00",
                        "time_end": "14:00",
                        "position_id": "pos_hall",
                        "count": 1,
                    },
                },
                # 希望未提出＝出勤不可なので、p1 の出勤希望を入れておく（無いと空シフトになる）
                {"type": "availability", "params": {"person_id": "p1", "date": "2026-11-01", "start": "11:00", "end": "14:00"}},
                {"type": "availability", "params": {"person_id": "p1", "date": "2026-11-02", "start": "11:00", "end": "14:00"}},
                {"type": "availability", "params": {"person_id": "p1", "date": "2026-11-03", "start": "11:00", "end": "14:00"}},
            ],
        },
    },
    "② separate（同席を避ける）＋ availability": {
        "summary": "p1とp2は同じ日に入れたくない / p2は1日目だけ可用",
        "value": {
            "frame": {
                "period": {"start": "2026-11-01", "end": "2026-11-02"},
                "operating_window": {"open": "11:00", "close": "14:00", "slot_minutes": 60},
                "policy_mode": "wishes",
            },
            "masters": {
                "persons": [
                    {"id": "p1", "name": "スタッフ01", "role_id": "r_staff", "skill_ids": []},
                    {"id": "p2", "name": "スタッフ02", "role_id": "r_staff", "skill_ids": []},
                ],
                "positions": [{"id": "pos_hall", "name": "ホール"}],
                "roles": [{"id": "r_staff", "name": "スタッフ"}],
                "skills": [],
            },
            "constraints": [
                {
                    "type": "headcount_requirement",
                    "params": {
                        "slot_label": "ランチ", "time_start": "11:00", "time_end": "14:00",
                        "position_id": "pos_hall", "count": 1,
                    },
                },
                {
                    "type": "availability",
                    "params": {"person_id": "p2", "date": "2026-11-01", "start": "11:00", "end": "14:00"},
                },
                {
                    "type": "separate",
                    "params": {"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 600},
                },
            ],
        },
    },
}


@router.post(
    "/run",
    summary="シフトを計算する（OR-Tools 実行）",
    response_model=SolverOutput,
    description=(
        "セットアップ済みのマスタ・営業情報・制約から、実際のシフトを計算します。\n\n"
        "- **status**: solved / infeasible / timeout\n"
        "- **shift_status**: confirmed（確定）/ provisional（暫定：未翻訳の要望あり）\n"
        "- **assignments**: 誰が・いつ・どのポジションに入るか\n\n"
        "最小ソルバー版の対応タイプ: `headcount_requirement` / `availability` / `separate`。\n"
        "未対応タイプは warnings に明示します（黙って無視しません）。\n\n"
        "`pending_constraints` を一緒に渡すと結果は暫定版になります。"
    ),
)
def run_solver(body: dict = Body(openapi_examples=_run_examples)) -> SolverOutput:
    # 未翻訳の要望は SolverInput とは別キーで受け取る（任意）
    pending_raw = body.pop("pending_constraints", [])

    try:
        spec = SolverInput.model_validate(body)
        pending = [UntranslatedConstraint.model_validate(p) for p in pending_raw]
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    return solve(spec, pending)


@router.post(
    "/run-stored",
    summary="保存済みデータからシフトを計算（一気通貫）",
    response_model=SolverOutput,
    description=(
        "セットアップ済みのマスタ・営業情報・②の方針・③の出勤希望をまとめて使い、"
        "シフトを計算します。各画面で登録した内容がそのまま反映されます。\n\n"
        "- マスタ／営業情報が未登録なら 404\n"
        "- 制約 = ②の翻訳済み制約 ＋ ③の出勤希望（availability）"
    ),
)
def run_solver_stored() -> SolverOutput:
    masters = get_masters()
    frame = get_frame()
    if masters is None:
        raise HTTPException(status_code=404, detail="マスタが未登録です。① セットアップで登録してください。")
    if frame is None:
        raise HTTPException(status_code=404, detail="営業情報が未登録です。① セットアップで登録してください。")

    constraints = get_base_headcounts() + get_policy_constraints() + get_availability()
    try:
        spec = SolverInput.model_validate({
            "frame": frame.model_dump(mode="json"),
            "masters": masters.model_dump(mode="json"),
            "constraints": constraints,
        })
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # 未承認の未知タイプが残っていれば「暫定シフト」にする（承認後に再作成で確定）
    pending = [
        UntranslatedConstraint(
            source_text=p.source_texts[0] if p.source_texts else "",
            suggested_type_name=p.suggested_type_name,
            reason=p.summary or "管理者の承認待ち（暫定シフトに未反映）",
        )
        for p in list_pending_requests(status="pending")
    ]

    return solve(spec, pending)
