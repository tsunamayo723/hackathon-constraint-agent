"""
セットアップ系エンドポイント（マスタ・営業情報）

月次シフト作成の「土台」となるデータを受け取って保存する。
- マスタ（人/役職/ポジション/スキル）… CSVアップロード由来
- 営業情報（frame: 期間・営業時間・ポリシー）… フォーム入力由来

Streamlit と FastAPI は別プロセスのため、必ずこのAPI経由で受け渡す。
保存先は現状インメモリ（storage.py）。本番では Supabase。
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from src import llm
from src.models import Frame, Masters, PendingTypeRequest
from src.models.constraints import KNOWN_TYPES, AvailabilityParams, HeadcountParams
from src.storage import (
    add_pending_request,
    clear_availability,
    clear_dynamic_constraints,
    clear_manager_questions,
    clear_note_results,
    clear_pending_requests,
    clear_policy_constraints,
    find_pending_by_type,
    get_availability,
    get_base_headcounts,
    get_frame,
    get_masters,
    get_note_results,
    get_policy_constraints,
    save_availability,
    save_base_headcounts,
    save_demo_meta,
    save_frame,
    save_masters,
    save_note_results,
    update_pending_request,
)

# デモデータ置き場（data/demo/<pattern>/）
DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"

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
    save_demo_meta(None)  # 手動CSV投入はデモではないので、デモメタをクリア
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


# ── デモデータ（プルダウンでワンクリック投入） ──────────────────────

def _read_csv(path: Path) -> list[dict]:
    """CSVを辞書のリストに読み込む（UTF-8）。"""
    with path.open(encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


@router.get(
    "/demo-patterns",
    summary="投入できるデモデータの一覧",
    description=(
        "data/demo/ にあるデモパターンを返します（key/label/description＋営業時間＋必要人数の概要）。"
        "Streamlitや提出者UIのプルダウン用。選択時に『この店は何時〜何時／何人必要か』を見せるため、"
        "営業時間(operating_window)と基本の必要人数(headcounts)も含めます。"
    ),
)
def list_demo_patterns():
    patterns = []
    if DEMO_DIR.exists():
        for d in sorted(DEMO_DIR.iterdir()):
            meta_path = d / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ow = meta.get("frame", {}).get("operating_window", {}) or {}

            # ポジションIDを名前に（選択時点ではマスタ未投入なのでCSVから引く）
            pos_path = d / "positions.csv"
            pos_name = {r["id"]: r["name"] for r in _read_csv(pos_path)} if pos_path.exists() else {}

            # 必要人数の概要（基本編成＝date空の行のみ。特定日上書きは概要から除外）
            headcounts = []
            hc_path = d / "headcounts.csv"
            if hc_path.exists():
                for r in _read_csv(hc_path):
                    if (r.get("date") or "").strip():
                        continue
                    headcounts.append({
                        "slot_label": r["slot_label"],
                        "time_start": r["time_start"],
                        "time_end": r["time_end"],
                        "position": pos_name.get(r["position_id"], r["position_id"]),
                        "count": int(r["count"]),
                    })

            patterns.append({
                "key": meta.get("key", d.name),
                "label": meta.get("label", d.name),
                "description": meta.get("description", ""),
                "operating_window": (
                    {"open": ow.get("open"), "close": ow.get("close")} if ow else None
                ),
                "headcounts": headcounts,
            })
    return {"patterns": patterns}


@router.post(
    "/load-demo",
    summary="デモデータを一括投入（マスタ＋営業情報＋必要人数＋出勤希望）",
    description=(
        "data/demo/<pattern>/ のCSV＋meta.jsonをまとめて登録します。"
        "CSVを毎回アップロードしなくてもデモを始められます。\n\n"
        "**既存の方針・出勤希望・承認キューはクリアしてから投入**します（クリーンな状態でデモ開始）。"
        "マスタ・営業情報・必要人数も投入分で置き換わります。"
    ),
)
def load_demo(body: dict = Body(..., openapi_examples={
    "カフェ（標準）": {"value": {"pattern": "cafe_easy"}},
    "定食屋（タイト）": {"value": {"pattern": "diner_tight"}},
    "居酒屋（遅番多め）": {"value": {"pattern": "izakaya_late"}},
})):
    key = (body or {}).get("pattern")
    if not key:
        raise HTTPException(status_code=422, detail="pattern を指定してください。")
    pdir = DEMO_DIR / key
    if not (pdir / "meta.json").exists():
        raise HTTPException(status_code=404, detail=f"デモデータ '{key}' が見つかりません。")

    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))

    # マスタ（staff.csv の skill_ids は ; 区切り）
    persons = []
    for r in _read_csv(pdir / "staff.csv"):
        skills = [s for s in (r.get("skill_ids") or "").split(";") if s.strip()]
        persons.append({
            "id": r["id"], "name": r["name"],
            "role_id": r.get("role_id") or None, "skill_ids": skills,
        })

    try:
        masters = Masters.model_validate({
            "persons": persons,
            "positions": _read_csv(pdir / "positions.csv"),
            "roles": _read_csv(pdir / "roles.csv"),
            "skills": _read_csv(pdir / "skills.csv"),
        })
        frame = Frame.model_validate(meta["frame"])

        headcounts = []
        for r in _read_csv(pdir / "headcounts.csv"):
            params = {
                "slot_label": r["slot_label"], "time_start": r["time_start"],
                "time_end": r["time_end"], "position_id": r["position_id"],
                "count": int(r["count"]),
            }
            if (r.get("date") or "").strip():
                params["date"] = r["date"]
            headcounts.append({
                "type": "headcount_requirement",
                "params": HeadcountParams.model_validate(params).model_dump(mode="json"),
            })

        availability = []
        for r in _read_csv(pdir / "desired_shifts.csv"):
            params = AvailabilityParams.model_validate({
                "person_id": r["person_id"], "date": r["date"],
                "start": r["start"], "end": r["end"], "note": (r.get("note") or None),
            })
            availability.append({"type": "availability", "params": params.model_dump(mode="json")})
    except (ValidationError, ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"デモデータの読み込みに失敗しました: {e}")

    # 既存データをクリアしてから投入（クリーンな状態でデモを開始）
    clear_policy_constraints()
    clear_availability()
    clear_note_results()
    clear_dynamic_constraints()
    clear_pending_requests()
    clear_manager_questions()
    save_masters(masters)
    save_frame(frame)
    save_base_headcounts(headcounts)
    save_availability(availability)
    save_demo_meta(meta)

    return {
        "結果": f"デモデータ「{meta.get('label', key)}」を投入しました",
        "概要": {
            "スタッフ数": len(persons),
            "対象期間": f"{frame.period.start} 〜 {frame.period.end}",
            "必要人数の行数": len(headcounts),
            "出勤希望の行数": len(availability),
            "提出者(主役)": meta.get("demo_submitter", {}).get("person_id"),
        },
    }


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
        "未反映の備考": [n for n in get_note_results() if n["status"] == "unreflected"],
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
    clear_dynamic_constraints()
    return {"結果": "方針と出勤希望をクリアしました"}


def _apply_note_results(availability, noted_idx, items, results):
    """NoteAgentの解釈結果を出勤可能枠に適用し、備考ごとの分類を作る（純ロジック・テスト可能）。

    各備考を status で3分類する:
      "applied"     … A: その日の時間補正を出勤可能枠に反映できた
      "pending"     … B: 新ルール候補（suggested_type_name付き。キュー登録は呼び出し側）
      "unreflected" … C: どちらでもない（申し送りとして可視化）
    ※ AとBの両方に該当する備考は status="applied" ＋ suggested_type_name付きになる。

    返り値: (note_results, 補正した件数)
    """
    from src.solver.slots import hhmm_to_min

    by_index = {r.index: r for r in results}
    note_results: list[dict] = []
    adjusted = 0
    for item in items:
        rec = availability[noted_idx[item["index"]]]["params"]
        r = by_index.get(item["index"])

        # A: 時間補正（元の枠の内側に収まる補正だけ適用。枠は広げない）
        changed = False
        if r is not None and r.interpretable:
            cur_s, cur_e = hhmm_to_min(rec["start"]), hhmm_to_min(rec["end"])
            if r.new_start and cur_s <= hhmm_to_min(r.new_start) <= cur_e:
                rec["start"] = r.new_start
                changed = True
            if r.new_end and cur_s <= hhmm_to_min(r.new_end) <= cur_e:
                rec["end"] = r.new_end
                changed = True

        # B: 新ルール候補（既知タイプ名を提案してきたらAIの誤検出なので除外）
        is_new = bool(
            r is not None and r.is_new_type and r.suggested_type_name
            and r.suggested_type_name not in KNOWN_TYPES
        )

        summary = (r.note_summary if r and r.note_summary else item["note"])
        if changed:
            adjusted += 1
            summary = f"{summary}（{rec['start']}〜{rec['end']} に補正）"

        entry = {
            "person_id": item["person_id"], "date": item["date"], "note": item["note"],
            "status": "applied" if changed else ("pending" if is_new else "unreflected"),
            "summary": summary,
        }
        if is_new:
            entry["suggested_type_name"] = r.suggested_type_name
        note_results.append(entry)
    return note_results, adjusted


def _register_note_pending(note_results: list[dict]) -> int:
    """新ルール候補（suggested_type_name付き）を管理者の承認キューに登録する。

    ②の方針入力と同じく、同じtype名は1件に集約（クラスタリング）。
    同じ備考（person+date+原文）を再解釈しても二重登録しない。
    キューに反映した件数を返す。
    """
    registered = 0
    for n in note_results:
        tname = n.get("suggested_type_name")
        if not tname:
            continue
        occurrence = {
            "person_id": n["person_id"], "date": n["date"],
            "source_text": n["note"], "origin": "note",
        }
        display_text = f"（{n['person_id']}・{n['date']}の備考）{n['note']}"

        existing = find_pending_by_type(tname)
        if existing is not None:
            n["pending_request_id"] = existing.id
            if occurrence in existing.occurrences:
                continue  # 再実行による重複は登録しない
            existing.source_texts.append(display_text)
            existing.occurrence_count += 1
            existing.occurrences.append(occurrence)
            if not existing.summary and n.get("summary"):
                existing.summary = n["summary"]
            update_pending_request(existing)
        else:
            req_id = f"req_{uuid4().hex[:8]}"
            n["pending_request_id"] = req_id
            add_pending_request(PendingTypeRequest(
                id=req_id,
                suggested_type_name=tname,
                source_texts=[display_text],
                occurrence_count=1,
                occurrences=[occurrence],
                summary=n.get("summary"),
                ai_assessment="出勤希望CSVの備考から検出（日ごとの時間補正では表せないルール）",
                confidence=0.0,
                created_at=datetime.now(),
            ))
        registered += 1
    return registered


@router.post(
    "/interpret-notes",
    summary="出勤希望の備考(note)をAIでまとめて解釈し、出勤可能枠に反映",
    description=(
        "保存済み出勤希望のうち**備考(note)付きの行だけ**を集め、Gemini(Flash)で"
        "**バッチ解釈**します。各備考は3つに分類されます。\n\n"
        "- ✅ **反映**: その日の時間補正（例「お迎えで17時まで」→ end=17:00）\n"
        "- 🆕 **新ルール候補**: 仕組みとしてのルール（例「毎週水曜NG」）→ 管理者の承認キューへ\n"
        "- ⚠️ **未反映**: どちらでもない → 申し送りとして可視化\n\n"
        "コスト対策で数十件ずつまとめて呼びます（追加の呼び出しなし）。"
    ),
)
def interpret_notes():
    from src.agents import NoteAgent

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

    # 分類（✅時間補正 / 🆕新ルール候補 / ⚠️未反映）→ 新ルール候補は承認キューへ
    note_results, _adjusted = _apply_note_results(availability, noted_idx, items, results)
    _register_note_pending(note_results)

    save_availability(availability)
    save_note_results(note_results)

    applied = [n for n in note_results if n["status"] == "applied"]
    new_rules = [n for n in note_results if n.get("suggested_type_name")]
    unreflected = [n for n in note_results if n["status"] == "unreflected"]
    return {
        "結果": "備考を解釈しました",
        "解釈件数": len(items),
        "反映した備考": applied,
        "新ルール候補": new_rules,
        "未反映の備考": unreflected,
    }
