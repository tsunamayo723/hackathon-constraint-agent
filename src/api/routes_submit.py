"""
提出者プレビュー系エンドポイント（デモの主役UIが呼ぶ）

1人の提出者が「カレンダーで出した希望(wishes・日ごとnote付き)」＋
「備考から確定したレシピ(recipe・overall note由来)」を送ると、
**備考を考慮しない/する** の2通りでシフトを解いて比較する。

  - 本人の割当がどう変わったか（personal: 自分の水曜が空いた 等）
  - 店舗の必要人数を満たせているか（store: 充足スコア・不足）
  - 日ごとnoteをAIがどう翻訳したか（note_results: ✅時間補正 / 🆕新ルール候補 / ⚠️申し送り）

これで「自分の要望も、店舗の要望も通った」を1画面で見せられる。

note の翻訳は ②CSV経路と同じ NoteAgent パイプライン（routes_setup の
_apply_note_results / _register_note_pending）を再利用する＝翻訳の頭は1つ。
  - ✅時間補正 … その日の枠を狭めて after の解に反映
  - 🆕新ルール候補 … 管理者の承認キューへ流す（L2へ橋渡し。preview では即適用しない）
  - ⚠️申し送り … 表示のみ

※ 非破壊: 本人の希望・他スタッフのデータは保存しない（this-solve 限定で重ねて解くだけ）。
  ただし新ルール候補の承認キュー登録だけは「提出者の要望を管理者に届ける」追記操作として行う。
"""

import copy
import logging

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from src import llm
from src.api.routes_solver import _assignment_key, _fmt_assignment
from src.models.solver_io import SolverInput, SolverOutput
from src.solver.engine import solve
from src.solver.recipe import validate_recipe
from src.storage import (
    clear_dynamic_constraints,
    get_availability,
    get_base_headcounts,
    get_demo_meta,
    get_dynamic_constraints,
    get_frame,
    get_masters,
    get_policy_constraints,
    save_availability,
    save_dynamic_constraints,
)

router = APIRouter(prefix="/submit", tags=["提出者チャット"])

logger = logging.getLogger("uvicorn.error")

# 提出者は「入れる日はできるだけ入りたい」人として優先配置する（prefer_person）。
# これで提出者が確実にシフトに乗り、note考慮あり/なしの差（例: 水曜が消える）が安定して見える。
PREFER_SUBMITTER_WEIGHT = 100


def _prefer_submitter(person_id: str | None) -> list[dict]:
    if not person_id:
        return []
    return [{"type": "prefer_person",
             "params": {"person_id": person_id, "weight": PREFER_SUBMITTER_WEIGHT}}]


_preview_examples = {
    "① 希望のみ（備考なし）": {
        "summary": "カレンダーの希望だけで暫定シフトを見る",
        "value": {
            "person_id": "p01",
            "wishes": [
                {"date": "2026-11-02", "start": "11:00", "end": "22:00"},
                {"date": "2026-11-04", "start": "11:00", "end": "22:00"},
            ],
            "recipe": None,
        },
    },
    "② 備考レシピつき（毎週水曜は終日NG）": {
        "summary": "note考慮あり/なしで本人の水曜が変わるのを見る",
        "value": {
            "person_id": "p01",
            "type_name": "recurring_day_off",
            "wishes": [
                {"date": "2026-11-02", "start": "11:00", "end": "22:00"},
                {"date": "2026-11-04", "start": "11:00", "end": "22:00"},
                {"date": "2026-11-11", "start": "11:00", "end": "22:00"},
            ],
            "recipe": {
                "operation": "forbid", "who": "person",
                "when": "weekday", "weekday": 2, "band": "all_day",
            },
        },
    },
}


def _wishes_to_availability(person_id: str, wishes: list[dict]) -> list[dict]:
    """カレンダーの希望（{date,start,end,note?}）を availability 制約に変換する。"""
    rows: list[dict] = []
    for w in wishes:
        if not all(w.get(k) for k in ("date", "start", "end")):
            raise HTTPException(status_code=422, detail="希望には date / start / end が必要です。")
        rows.append({
            "type": "availability",
            "params": {
                "person_id": person_id,
                "date": w["date"], "start": w["start"], "end": w["end"],
                "note": (w.get("note") or None),
            },
        })
    return rows


def _prepare_recipe(person_id: str, recipe: dict | None) -> tuple[dict | None, bool, str]:
    """備考レシピ（overall note由来）に本人IDを差し込み、検証する。

    検証は p1〜p3 の固定シナリオで行うため、本人IDのまま検証すると
    「対象が居ない」偽陰性になる。→ 検証用コピーは person_id=p1 で当て、
    実際に解くレシピには本人IDを差し込む。
    返り値: (適用するレシピ or None, 適用したか, メッセージ)
    """
    if not recipe:
        return None, False, "備考レシピはありません"

    real = dict(recipe)
    if real.get("who", "person") == "person":
        real["person_id"] = person_id

    probe = dict(recipe)
    if probe.get("who", "person") == "person":
        probe["person_id"] = "p1"  # 検証シナリオに居る人で当てる

    ok, msg = validate_recipe(probe)
    if not ok:
        return None, False, msg
    return real, True, msg


def _translate_notes(avail: list[dict], register: bool = True) -> tuple[list[dict], int]:
    """availability の per-day note を NoteAgent で翻訳する（②CSV経路と同じ頭を再利用）。

    渡したリスト内の **note付き全行** を対象にする（本人だけでも全員でも可）。

    - ✅時間補正: avail の枠を狭める（その場で破壊的に編集＝after の解に効く）
    - 🆕新ルール候補: register=True のとき管理者の承認キューへ登録（L2へ橋渡し）
    - ⚠️申し送り: 何もしない（表示のみ）

    返り値: (note_results, 時間補正した件数)。noteが無ければ ([], 0)。
    """
    from src.agents import NoteAgent
    from src.api.routes_setup import _apply_note_results, _register_note_pending

    items: list[dict] = []
    noted_idx: list[int] = []
    for i, a in enumerate(avail):
        note = (a["params"].get("note") or "").strip()
        if note:
            p = a["params"]
            items.append({
                "index": len(items), "person_id": p["person_id"], "date": p["date"],
                "current_start": p["start"], "current_end": p["end"], "note": note,
            })
            noted_idx.append(i)

    if not items:
        return [], 0

    results = NoteAgent().interpret(items)
    note_results, adjusted = _apply_note_results(avail, noted_idx, items, results)
    if register:
        _register_note_pending(note_results)  # 新ルール候補→承認キュー（L2へ橋渡し）
    return note_results, adjusted


def _side(out: SolverOutput) -> dict:
    """片側（before/after）のシフト要約。申し送り用に不足・ソフト違反も含める。"""
    understaffed = [
        f"{w.affected_date} {w.affected_time}（{w.shortage}人不足）"
        for w in out.warnings
        if w.type == "understaffed" and w.affected_date
    ][:12]
    return {
        "status": out.status,
        "assignments": [_fmt_assignment(a) for a in out.assignments],
        "coverage_score": out.meta.coverage_score if out.meta else None,
        "shortage_units": out.meta.shortage_units if out.meta else None,
        "understaffed": understaffed,
        "soft_violations": out.evaluation.soft_violations if out.evaluation else 0,
    }


@router.get(
    "/demo-wishes",
    summary="デモ用：ある提出者の希望（日ごとnote付き）と overall note を返す",
    description=(
        "投入済みデータから、指定スタッフの出勤希望（date/start/end/note）を返します。"
        "提出者UIの「デモの希望を読み込む」でカレンダーを自動入力するのに使います。\n\n"
        "投入がデモデータ（load-demo）で、その人が主役(demo_submitter)なら overall_note も返します。"
    ),
)
def demo_wishes(person_id: str):
    masters = get_masters()
    if masters is None:
        raise HTTPException(status_code=404, detail="マスタが未登録です。先にデモデータを投入してください。")
    if person_id not in {p.id for p in masters.persons}:
        raise HTTPException(status_code=422, detail=f"スタッフID '{person_id}' がマスタに存在しません。")

    wishes = []
    for a in get_availability():
        p = a["params"]
        if p.get("person_id") == person_id:
            wishes.append({
                "date": p["date"], "start": p["start"], "end": p["end"],
                "note": p.get("note") or "",
            })
    wishes.sort(key=lambda w: w["date"])

    meta = get_demo_meta() or {}
    sub = meta.get("demo_submitter", {})
    overall_note = sub.get("overall_note", "") if sub.get("person_id") == person_id else ""

    return {"person_id": person_id, "wishes": wishes, "overall_note": overall_note}


@router.post(
    "/preview",
    summary="提出者の希望＋備考で『note考慮あり/なし』のシフトを比較する",
    description=(
        "1人の提出者の希望(wishes・日ごとnote付き)と、備考から確定したレシピ(recipe)を受け取り、"
        "**備考を考慮しない/する** の2通りでシフトを計算して比較します。\n\n"
        "- `personal`: 本人の割当の before/after と差分（消えた/増えた）\n"
        "- `store`: 店舗の必要人数の充足（before/after の coverage_score・不足）\n"
        "- `note_results`: 日ごとnoteのAI翻訳結果（✅時間補正 / 🆕新ルール候補 / ⚠️申し送り）\n\n"
        "after は「日ごとnoteの時間補正 ＋ overall noteのレシピ」を反映した解です。"
        "新ルール候補は管理者の承認キューへ流れます（preview では即適用しません）。\n\n"
        "非破壊（本人・他スタッフのデータは保存しません）。事前に必要人数・他スタッフが登録済みである前提です。"
    ),
)
def submit_preview(body: dict = Body(openapi_examples=_preview_examples)):
    person_id = (body or {}).get("person_id")
    wishes = (body or {}).get("wishes") or []
    recipe_in = (body or {}).get("recipe")
    type_name = (body or {}).get("type_name") or "submitter_note"

    if not person_id:
        raise HTTPException(status_code=422, detail="person_id が必要です。")

    masters = get_masters()
    frame = get_frame()
    if masters is None or frame is None:
        raise HTTPException(status_code=404, detail="マスタ／営業情報が未登録です。先にセットアップしてください。")
    if person_id not in {p.id for p in masters.persons}:
        raise HTTPException(status_code=422, detail=f"スタッフID '{person_id}' がマスタに存在しません。")

    # 店舗側の固定材料（必要人数・②方針・他スタッフの希望・承認済みの新type）
    others = [a for a in get_availability() if a["params"].get("person_id") != person_id]
    base = get_base_headcounts() + get_policy_constraints()
    dynamic_base = [{"type": d["type"], "params": d["params"]} for d in get_dynamic_constraints()]

    # 本人の希望（生）。before はこれで解く（note考慮なし）。
    my_raw = _wishes_to_availability(person_id, wishes)

    prefer = _prefer_submitter(person_id)  # 提出者を優先配置（水曜が安定して出る）

    def _solve(my_avail: list[dict], dynamic: list[dict]) -> SolverOutput:
        spec = SolverInput.model_validate({
            "frame": frame.model_dump(mode="json"),
            "masters": masters.model_dump(mode="json"),
            "constraints": base + others + my_avail + prefer,
            "dynamic_constraints": dynamic,
        })
        return solve(spec)

    try:
        before = _solve(my_raw, dynamic_base)  # note考慮なし
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # overall note のレシピを本人IDで当てる
    note_recipe, recipe_applied, note_msg = _prepare_recipe(person_id, recipe_in)

    # 日ごとnoteを翻訳（時間補正は my_corrected に反映・新ルール候補はキューへ）
    my_corrected = copy.deepcopy(my_raw)
    note_results: list[dict] = []
    adjusted = 0
    note_translation_error = ""
    if llm.is_available():
        try:
            note_results, adjusted = _translate_notes(my_corrected)
        except Exception as exc:  # 翻訳失敗で比較自体を壊さない（recipeだけで続行）
            logger.exception("提出者の備考翻訳に失敗")
            note_translation_error = str(exc)
            my_corrected = copy.deepcopy(my_raw)

    # after = note考慮あり（時間補正 ＋ overall noteレシピ）。効果が何も無ければ before を流用。
    after_dynamic = dynamic_base + ([{"type": type_name, "params": note_recipe}] if recipe_applied else [])
    if recipe_applied or adjusted > 0:
        try:
            after = _solve(my_corrected, after_dynamic)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors())
    else:
        after = before

    # 本人にしぼった差分（消えた割当＝休めた・増えた割当＝入った）
    mine_before = [a for a in before.assignments if a.person_id == person_id]
    mine_after = [a for a in after.assignments if a.person_id == person_id]
    before_keys = {_assignment_key(a) for a in mine_before}
    after_keys = {_assignment_key(a) for a in mine_after}
    removed = [_fmt_assignment(a) for a in mine_before if _assignment_key(a) not in after_keys]
    added = [_fmt_assignment(a) for a in mine_after if _assignment_key(a) not in before_keys]

    def _store_ok(out: SolverOutput) -> bool:
        return out.status == "solved" and bool(out.meta) and out.meta.shortage_units == 0

    return {
        "person_id": person_id,
        "note_applied": recipe_applied or adjusted > 0,  # 何らかの備考効果が出たか
        "recipe_applied": recipe_applied,                # overall note のレシピが効いたか
        "notes_adjusted": adjusted,                      # 日ごとnoteの時間補正の件数
        "note_message": note_msg,
        "note_recipe": note_recipe,
        "note_results": note_results,                    # ✅/🆕/⚠️ の分類（日ごとnote）
        "note_translation_error": note_translation_error,
        "before": _side(before),
        "after": _side(after),
        "personal": {
            "before": [_fmt_assignment(a) for a in mine_before],
            "after": [_fmt_assignment(a) for a in mine_after],
            "diff": {"removed": removed, "added": added},
        },
        "store": {
            "before_ok": _store_ok(before),
            "after_ok": _store_ok(after),
            "before_coverage": before.meta.coverage_score if before.meta else None,
            "after_coverage": after.meta.coverage_score if after.meta else None,
        },
    }


@router.post(
    "/commit",
    summary="個人の希望を店舗にマージ保存（最終計算の前段・破壊的）",
    description=(
        "提出者の希望（日ごとnote付き）と備考レシピを、保存済みデータに実際に反映します。\n\n"
        "- 本人の出勤希望(availability)を差し替え（他スタッフはそのまま）\n"
        "- 日ごとnoteを翻訳（✅時間補正は反映 / 🆕新ルール候補は承認キューへ）\n"
        "- 本人の毎週/期間ルール（表現可能なら）を dynamic 制約として登録（同一本人の旧submitは置換）\n\n"
        "この後 `/solver/run-stored` を呼ぶと、本人の希望を含めた全体シフトが計算されます。"
    ),
)
def submit_commit(body: dict = Body(...)):
    person_id = (body or {}).get("person_id")
    wishes = (body or {}).get("wishes") or []
    recipe_in = (body or {}).get("recipe")
    type_name = (body or {}).get("type_name") or "submitter_note"

    if not person_id:
        raise HTTPException(status_code=422, detail="person_id が必要です。")

    masters = get_masters()
    frame = get_frame()
    if masters is None or frame is None:
        raise HTTPException(status_code=404, detail="マスタ／営業情報が未登録です。先に店舗を準備してください。")
    if person_id not in {p.id for p in masters.persons}:
        raise HTTPException(status_code=422, detail=f"スタッフID '{person_id}' がマスタに存在しません。")

    # 本人の希望で availability を差し替え（他スタッフはそのまま）
    others = [a for a in get_availability() if a["params"].get("person_id") != person_id]
    mine = _wishes_to_availability(person_id, wishes)

    # 日ごとnoteを翻訳（時間補正は mine に反映・新ルール候補は承認キューへ）
    note_results: list[dict] = []
    notes_adjusted = 0
    if llm.is_available() and mine:
        try:
            note_results, notes_adjusted = _translate_notes(mine)
        except Exception:
            logger.exception("commit時の備考翻訳に失敗")
    save_availability(others + mine)

    # 本人の毎週/期間ルール（本人のavailability的ルール）を dynamic に登録。
    # 同一本人の過去のsubmit分は置換し、承認済みtypeや他人の分は残す。
    note_recipe, recipe_ok, _ = _prepare_recipe(person_id, recipe_in)
    keep = [
        d for d in get_dynamic_constraints()
        if not (d.get("source", {}).get("origin") == "submit"
                and d.get("source", {}).get("person_id") == person_id)
    ]
    clear_dynamic_constraints()
    if keep:
        save_dynamic_constraints(keep)
    if recipe_ok:
        save_dynamic_constraints([{
            "type": type_name, "params": note_recipe,
            "source": {"person_id": person_id, "origin": "submit"},
        }])

    return {
        "結果": "個人の希望を反映しました",
        "person_id": person_id,
        "出勤希望の行数": len(mine),
        "recipe_applied": recipe_ok,
        "notes_adjusted": notes_adjusted,
        "note_results": note_results,
    }


@router.post(
    "/interpret-wishes",
    summary="日ごとメモをAIで解釈して分類だけ返す（②のフィードバック用・非破壊）",
    description=(
        "提出者の日ごとメモ(note)を NoteAgent で解釈し、件数と分類を返します。\n\n"
        "- ✅ 時間補正（その日の枠を狭める）\n"
        "- 🆕 新ルール候補（毎週○曜など）\n"
        "- ⚠️ 申し送り（どちらでもない）\n\n"
        "非破壊（保存もキュー登録もしません）。「メモを反映」ボタンの確認表示に使います。"
    ),
)
def interpret_wishes(body: dict = Body(...)):
    person_id = (body or {}).get("person_id")
    wishes = (body or {}).get("wishes") or []
    if not person_id:
        raise HTTPException(status_code=422, detail="person_id が必要です。")
    if not llm.is_available():
        raise HTTPException(status_code=400, detail="Gemini未設定のため解釈できません（.env の GEMINI_API_KEY）。")

    mine = _wishes_to_availability(person_id, wishes)
    # register=True: 新ルール候補（毎週○曜・22時以降月◯回 等）は管理者の承認キュー(④)へ送る
    note_results, _ = _translate_notes(copy.deepcopy(mine), register=True)
    applied = [n for n in note_results if n["status"] == "applied"]
    new_rules = [n for n in note_results if n.get("suggested_type_name")]
    unreflected = [n for n in note_results if n["status"] == "unreflected"]
    return {
        "counts": {"applied": len(applied), "new_rules": len(new_rules), "unreflected": len(unreflected)},
        "applied": applied,
        "new_rules": new_rules,
        "unreflected": unreflected,
    }


@router.post(
    "/store-compare",
    summary="全体シフトを『note考慮あり/なし』で計算して比較する（⑤用・非破壊）",
    description=(
        "店全体のシフトを2通りで計算して返します。\n\n"
        "- **before（note考慮なし）**: AIが備考を読まない＝生の出勤可能枠のみ（毎週水曜・17時まで等は無視）\n"
        "- **after（note考慮あり）**: AIが**全スタッフの備考を翻訳**して反映（時間補正＋本人の毎週/期間ルール）\n\n"
        "本人の希望(wishes)を渡すと、その分は本人の入力で差し替えて比較します。"
        "非破壊（保存しません）・承認キューにも積みません。"
    ),
)
def store_compare(body: dict = Body(...)):
    person_id = (body or {}).get("person_id")
    wishes = (body or {}).get("wishes") or []
    recipe_in = (body or {}).get("recipe")
    type_name = (body or {}).get("type_name") or "submitter_note"

    masters = get_masters()
    frame = get_frame()
    if masters is None or frame is None:
        raise HTTPException(status_code=404, detail="マスタ／営業情報が未登録です。先に店舗を準備してください。")

    # availability = 他スタッフ（保存済み）＋ 本人の希望（渡されていれば差し替え）
    if person_id:
        if person_id not in {p.id for p in masters.persons}:
            raise HTTPException(status_code=422, detail=f"スタッフID '{person_id}' がマスタに存在しません。")
        others = [a for a in get_availability() if a["params"].get("person_id") != person_id]
        all_avail = others + _wishes_to_availability(person_id, wishes) + _prefer_submitter(person_id)
    else:
        all_avail = get_availability()

    base = get_base_headcounts() + get_policy_constraints()
    # 承認済みの店舗ルール（noteではない）は両方に効かせる。本人のsubmitレシピは除外。
    approved_dynamic = [
        {"type": d["type"], "params": d["params"]}
        for d in get_dynamic_constraints()
        if d.get("source", {}).get("origin") != "submit"
    ]

    def _solve(avail: list[dict], dynamic: list[dict]) -> SolverOutput:
        spec = SolverInput.model_validate({
            "frame": frame.model_dump(mode="json"),
            "masters": masters.model_dump(mode="json"),
            "constraints": base + avail,
            "dynamic_constraints": dynamic,
        })
        return solve(spec)

    try:
        # before: note考慮なし（生の枠・note由来ルールなし）
        before = _solve(all_avail, approved_dynamic)

        # after: note考慮あり（全員の備考を翻訳＋本人の毎週/期間ルール）
        after_avail = copy.deepcopy(all_avail)
        note_results: list[dict] = []
        if llm.is_available():
            try:
                note_results, _ = _translate_notes(after_avail, register=False)
            except Exception:
                logger.exception("store-compare の備考翻訳に失敗")
        note_recipe, recipe_ok, _ = (
            _prepare_recipe(person_id, recipe_in) if person_id else (None, False, "")
        )
        after_dynamic = approved_dynamic + (
            [{"type": type_name, "params": note_recipe}] if recipe_ok else []
        )
        after = _solve(after_avail, after_dynamic)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    def _store_ok(out: SolverOutput) -> bool:
        return out.status == "solved" and bool(out.meta) and out.meta.shortage_units == 0

    return {
        "before": _side(before),
        "after": _side(after),
        "note_results": note_results,
        "store": {
            "before_ok": _store_ok(before),
            "after_ok": _store_ok(after),
            "before_coverage": before.meta.coverage_score if before.meta else None,
            "after_coverage": after.meta.coverage_score if after.meta else None,
        },
    }
