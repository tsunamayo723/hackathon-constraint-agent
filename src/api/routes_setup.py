"""
セットアップ系エンドポイント（マスタ・営業情報）

月次シフト作成の「土台」となるデータを受け取って保存する。
- マスタ（人/役職/ポジション/スキル）… CSVアップロード由来
- 営業情報（frame: 期間・営業時間・ポリシー）… フォーム入力由来

Streamlit と FastAPI は別プロセスのため、必ずこのAPI経由で受け渡す。
保存先は現状インメモリ（storage.py）。本番では Supabase。
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from src import llm
from src.models import Frame, Masters
from src.models.constraints import AvailabilityParams, HeadcountParams
from src.storage import (
    clear_availability,
    clear_note_results,
    clear_policy_constraints,
    get_availability,
    get_base_headcounts,
    get_frame,
    get_masters,
    get_note_results,
    get_policy_constraints,
    save_availability,
    save_base_headcounts,
    save_frame,
    save_masters,
    save_note_results,
)

router = APIRouter(prefix="/setup", tags=["セットアップ"])

logger = logging.getLogger("uvicorn.error")


# ── マスタ ──────────────────────────────────────────────────────────

@router.post(
    "/masters",
    summary="マスタ登録（人/役職/ポジション/スキル）",
    description=(
        "CSVから読み込んだマスタ4種をまとめて登録します。\n\n"
        "ID参照（person.role_id など）の整合性もチェックします。"
    ),
)
def post_masters(masters: Masters):
    # ID参照の整合性チェック（存在しない役職/スキルを参照していないか）
    role_ids = {r.id for r in masters.roles}
    skill_ids = {s.id for s in masters.skills}
    errors: list[str] = []

    for p in masters.persons:
        if p.role_id is not None and p.role_id not in role_ids:
            errors.append(f"{p.name}({p.id}) の役職ID '{p.role_id}' がroles に存在しません")
        for sk in p.skill_ids:
            if sk not in skill_ids:
                errors.append(f"{p.name}({p.id}) のスキルID '{sk}' がskills に存在しません")

    if errors:
        raise HTTPException(status_code=422, detail={"整合性エラー": errors})

    save_masters(masters)
    return {
        "結果": "マスタを登録しました",
        "概要": {
            "スタッフ数": len(masters.persons),
            "ポジション数": len(masters.positions),
            "役職数": len(masters.roles),
            "スキル数": len(masters.skills),
        },
    }


@router.get(
    "/masters",
    summary="登録済みマスタの取得",
)
def fetch_masters() -> Masters:
    masters = get_masters()
    if masters is None:
        raise HTTPException(status_code=404, detail="マスタが未登録です。先に登録してください。")
    return masters


# ── 営業情報（frame） ────────────────────────────────────────────────

@router.post(
    "/frame",
    summary="営業情報の登録（期間・営業時間・ポリシー）",
    description=(
        "月次シフト作成の枠を登録します。\n\n"
        "- period: 対象期間（開始日〜終了日）\n"
        "- operating_window: 営業時間とスロット単位（30分/60分）\n"
        "- policy_mode: 希望優先 / コスト優先 / バランス"
    ),
)
def post_frame(frame: Frame):
    # 期間の前後関係チェック
    if frame.period.end < frame.period.start:
        raise HTTPException(
            status_code=422,
            detail="終了日が開始日より前になっています。",
        )

    save_frame(frame)
    return {
        "結果": "営業情報を登録しました",
        "概要": {
            "対象期間": f"{frame.period.start} 〜 {frame.period.end}",
            "営業時間": f"{frame.operating_window.open} 〜 {frame.operating_window.close}",
            "スロット単位": f"{frame.operating_window.slot_minutes}分",
            "ポリシー": frame.policy_mode,
        },
    }


@router.get(
    "/frame",
    summary="登録済み営業情報の取得",
)
def fetch_frame() -> Frame:
    frame = get_frame()
    if frame is None:
        raise HTTPException(status_code=404, detail="営業情報が未登録です。先に登録してください。")
    return frame


# ── 出勤希望（desired_shifts CSV → availability制約） ────────────────

@router.post(
    "/desired-shifts",
    summary="出勤希望の登録（CSV由来のavailability）",
    description=(
        "出勤希望CSVの各行（person_id / date / start / end / note）を availability制約に変換して保存します。\n\n"
        "CSVに記載のない日時は『出勤不可』として扱われます（出勤希望ベース）。"
    ),
)
def post_desired_shifts(records: list[dict]):
    masters = get_masters()
    known_person_ids = {p.id for p in masters.persons} if masters else None

    availability: list[dict] = []
    errors: list[str] = []
    for i, row in enumerate(records, start=1):
        try:
            params = AvailabilityParams.model_validate(row)
        except ValidationError as e:
            msg = e.errors()[0].get("msg", "形式エラー")
            errors.append(f"{i}行目: {msg}")
            continue
        if known_person_ids is not None and params.person_id not in known_person_ids:
            errors.append(f"{i}行目: スタッフID '{params.person_id}' がマスタに存在しません")
            continue
        availability.append({"type": "availability", "params": params.model_dump(mode="json")})

    if errors:
        raise HTTPException(status_code=422, detail={"出勤希望エラー": errors})

    save_availability(availability)
    return {"結果": "出勤希望を登録しました", "件数": len(availability)}


@router.get(
    "/desired-shifts",
    summary="登録済み出勤希望の取得",
)
def fetch_desired_shifts():
    items = get_availability()
    return {"件数": len(items), "items": items}


@router.post(
    "/headcounts",
    summary="必要人数の登録（時間帯×ポジションの人数）",
    description="基本の必要人数を登録します。各行: slot_label / time_start / time_end / position_id / count。",
)
def post_headcounts(records: list[dict]):
    masters = get_masters()
    known_pos = {p.id for p in masters.positions} if masters else None

    items: list[dict] = []
    errors: list[str] = []
    for i, row in enumerate(records, start=1):
        try:
            params = HeadcountParams.model_validate(row)
        except ValidationError as e:
            errors.append(f"{i}行目: {e.errors()[0].get('msg', '形式エラー')}")
            continue
        if known_pos is not None and params.position_id not in known_pos:
            errors.append(f"{i}行目: ポジションID '{params.position_id}' がマスタに存在しません")
            continue
        items.append({"type": "headcount_requirement", "params": params.model_dump(mode="json")})

    if errors:
        raise HTTPException(status_code=422, detail={"必要人数エラー": errors})

    save_base_headcounts(items)
    return {"結果": "必要人数を登録しました", "件数": len(items)}


@router.get(
    "/summary",
    summary="シフト計算に使う保存内容の要約",
    description="マスタ・営業情報・②の方針・③の出勤希望の登録状況をまとめて返す（⑤の確認用）。",
)
def setup_summary():
    masters = get_masters()
    frame = get_frame()
    policy = get_policy_constraints()
    avail = get_availability()
    # 方針制約をtypeごとに数える
    type_counts: dict[str, int] = {}
    for c in policy:
        type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1
    # 必要人数（headcount）の一覧（⑤の需要サマリ用）。①フォーム由来＋②NL由来の両方。
    base = get_base_headcounts()
    demands = [
        {
            "date": c["params"].get("date") or "毎日",
            "slot_label": c["params"].get("slot_label"),
            "time": f"{c['params'].get('time_start')}〜{c['params'].get('time_end')}",
            "position_id": c["params"].get("position_id"),
            "count": c["params"].get("count"),
        }
        for c in (base + [p for p in policy if p["type"] == "headcount_requirement"])
    ]
    return {
        "マスタ登録": masters is not None,
        "スタッフ数": len(masters.persons) if masters else 0,
        "営業情報登録": frame is not None,
        "対象期間": f"{frame.period.start} 〜 {frame.period.end}" if frame else None,
        "方針の制約数": len(policy),
        "方針の内訳": type_counts,
        "必要人数": demands,
        "出勤希望(availability)件数": len(avail),
        "未反映の備考": [n for n in get_note_results() if not n["applied"]],
    }


@router.post(
    "/reset-constraints",
    summary="②の方針と③の出勤希望をクリア（やり直し）",
    description="蓄積された方針制約と出勤希望を消去します。マスタ・営業情報は残ります。",
)
def reset_constraints():
    clear_policy_constraints()
    clear_availability()
    clear_note_results()
    return {"結果": "方針と出勤希望をクリアしました"}


@router.post(
    "/interpret-notes",
    summary="出勤希望の備考(note)をAIでまとめて解釈し、出勤可能枠に反映",
    description=(
        "保存済み出勤希望のうち**備考(note)付きの行だけ**を集め、Gemini(Flash)で"
        "**バッチ解釈**して出勤可能枠（start/end）を補正します。\n\n"
        "例:「お迎えで17時まで」→ end=17:00。コスト対策で数十件ずつまとめて呼びます。"
    ),
)
def interpret_notes():
    from src.agents import NoteAgent
    from src.solver.slots import hhmm_to_min

    if not llm.is_available():
        raise HTTPException(status_code=400, detail="Gemini未設定のため解釈できません（.env の GEMINI_API_KEY）。")

    availability = get_availability()
    # 備考付きの行を集める（noted[i] = availabilityリスト内のindex）
    items: list[dict] = []
    noted_idx: list[int] = []
    for i, c in enumerate(availability):
        note = (c["params"].get("note") or "").strip()
        if note:
            p = c["params"]
            items.append({
                "index": len(items),
                "person_id": p["person_id"], "date": p["date"],
                "current_start": p["start"], "current_end": p["end"], "note": note,
            })
            noted_idx.append(i)

    if not items:
        return {"結果": "備考付きの出勤希望がありません", "解釈件数": 0, "調整件数": 0}

    try:
        results = NoteAgent().interpret(items)
    except Exception as exc:
        logger.exception("備考の解釈に失敗")
        raise HTTPException(status_code=502, detail=f"備考の解釈に失敗しました: {exc}")

    # 結果をindex順に引けるようにする
    by_index = {r.index: r for r in results}

    note_results: list[dict] = []   # ✅適用 / ⚠️未反映 の分類（保存・表示用）
    adjusted = 0
    for item in items:
        rec = availability[noted_idx[item["index"]]]["params"]
        r = by_index.get(item["index"])
        changed = False
        if r is not None and r.interpretable:
            cur_s, cur_e = hhmm_to_min(rec["start"]), hhmm_to_min(rec["end"])
            # 元の枠の内側に収まる補正だけ適用（枠は広げない）
            if r.new_start and cur_s <= hhmm_to_min(r.new_start) <= cur_e:
                rec["start"] = r.new_start
                changed = True
            if r.new_end and cur_s <= hhmm_to_min(r.new_end) <= cur_e:
                rec["end"] = r.new_end
                changed = True

        summary = (r.note_summary if r and r.note_summary else item["note"])
        if changed:
            adjusted += 1
            summary = f"{summary}（{rec['start']}〜{rec['end']} に補正）"
        note_results.append({
            "person_id": item["person_id"], "date": item["date"],
            "note": item["note"], "applied": changed, "summary": summary,
        })

    save_availability(availability)
    save_note_results(note_results)

    applied = [n for n in note_results if n["applied"]]
    unreflected = [n for n in note_results if not n["applied"]]
    return {
        "結果": "備考を解釈しました",
        "解釈件数": len(items),
        "反映した備考": applied,
        "未反映の備考": unreflected,
    }
