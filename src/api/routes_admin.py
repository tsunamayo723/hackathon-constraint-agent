"""
サイト管理者向けエンドポイント

未知タイプの承認キュー管理。
本番ではここに認可（管理者ロールチェック）を追加する。
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from src import llm
from src.handlers import register_dynamic_handler
from src.models import PendingTypeRequest
from src.models.admin_queue import TestResult
from src.storage import (
    get_pending_request,
    list_pending_requests,
    mark_shift_for_recalc,
    save_dynamic_constraints,
    update_pending_request,
)

router = APIRouter(prefix="/admin", tags=["管理者承認"])

logger = logging.getLogger("uvicorn.error")

# 「表現できない」理由カテゴリ → 日本語ラベル（正直な拒否の表示用）
REJECT_LABELS = {
    "negotiation_dependent": "他者の希望に依存（交渉が必要）",
    "history_dependent": "過去の実績データが必要",
    "missing_data": "手持ちに無いデータが必要",
    "subjective": "主観的で数値化できない",
    "advanced_logic": "高度な条件ロジックが必要（現在の部品で表現不可）",
}


def reject_label(category: Optional[str]) -> str:
    return REJECT_LABELS.get(category or "", "表現できない理由は不明")


def _loads_dict(s: str) -> dict:
    """JSON文字列を dict に。失敗時は空 dict（AIが空や壊れた文字列を返しても落ちない）。"""
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def _store_generated(req: PendingTypeRequest, gen) -> dict:
    """生成結果（GeneratedRecipe / RecipeUpdate＝同形）を req に格納し、固定インタプリタで検証する。

    `/generate`（1件生成）と まとめチャット（複数件まとめて更新）の**共通保存ロジック**。
    任意コード実行は無く、レシピを validate_recipe に当てるだけ（安全）。
    返り値（表示用）: {expressible, passed, detail, recipe}。
    """
    from src.solver.recipe import validate_recipe

    req.confidence = max(0.0, min(1.0, gen.confidence))
    req.concerns = list(gen.concerns)

    # 表現できない＝正直に拒否（分かったフリをしない）。レシピは作らない。
    if not gen.expressible:
        req.expressible = False
        req.reject_category = gen.reject_category or None
        req.suggested_recipe = None
        req.tested_params = None
        req.test_results = TestResult(
            passed=False, total=1, passed_count=0,
            failed_cases=[f"表現できません（{reject_label(gen.reject_category)}）"],
            detail=gen.explanation,
        )
        update_pending_request(req)
        return {"expressible": False, "passed": None, "detail": gen.explanation, "recipe": None}

    # 例レシピを固定インタプリタで検証（execしない）
    recipe_template = _loads_dict(gen.recipe_template_json)
    example_recipe = _loads_dict(gen.example_recipe_json)
    # 検証シナリオは固定の人(p1/p2)。AIが実在ID(p01等)を入れても「対象が居ない」で
    # 偽陰性にならないよう、who=person/pair の person_id を検証用にそろえる（_chat_recipe と同じ発想）。
    _who = example_recipe.get("who", "person")
    if _who == "person":
        example_recipe["person_id"] = "p1"
    elif _who == "pair":
        example_recipe["person_id"] = "p1"
        example_recipe["person_id_b"] = "p2"
    ok, message = validate_recipe(example_recipe)
    req.expressible = True
    req.reject_category = None
    req.suggested_recipe = recipe_template
    req.tested_params = example_recipe
    req.test_results = TestResult(
        passed=ok, total=1, passed_count=1 if ok else 0,
        failed_cases=[] if ok else [message], detail=message,
    )
    update_pending_request(req)
    return {"expressible": True, "passed": ok, "detail": message, "recipe": recipe_template}


@router.get(
    "/usage",
    summary="Gemini利用量・概算料金（セッション内）",
    description=(
        "このサーバー起動中に消費したGeminiのトークン数と概算料金を返します。\n\n"
        "DB不要のインメモリ集計（再起動で消える）。後でSupabaseに貯めれば日次/月次ダッシュボードに拡張できます。\n"
        "※ 単価は概算（`src/usage.py` の PRICING_USD_PER_1M を公式pricingで更新してください）。"
    ),
)
def get_usage():
    from src import usage
    return usage.session_summary()


@router.get(
    "/pending-types",
    summary="承認待ちの未知タイプ一覧",
    description="サイト管理者が見る承認キュー。statusで絞り込みできます。",
)
def list_pending(
    status: Optional[str] = Query(
        default=None,
        description="絞り込み: pending / approved / rejected",
    ),
) -> list[PendingTypeRequest]:
    return list_pending_requests(status=status)


@router.get(
    "/pending-types/{req_id}",
    summary="承認待ちの詳細",
)
def get_pending(req_id: str) -> PendingTypeRequest:
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    return req


@router.post(
    "/pending-types/{req_id}/generate",
    summary="AIにレシピ（操作×選択子）を設計させて検証する（L2フローの主役）",
    description=(
        "未知タイプに対し、Gemini Pro が\n"
        "- レシピ（操作＋選択子）/ 例レシピ / 自信度 / 懸念点\n"
        "を設計し、**固定インタプリタに当ててプロセス内で検証**します（任意コード実行なし＝安全）。\n\n"
        "結果（レシピ・検証合否）はこのリクエストに格納され、承認画面で確認できます。"
    ),
)
def generate_handler(req_id: str, feedback: str = ""):
    from src.agents import RecipeAgent
    from src.solver.recipe import validate_recipe

    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")

    # ②のチャットが既にレシピを設計済み & 再生成でないなら、Proを呼ばず検証だけ。
    # ＝必要情報は②で引き切る構造。④での再質問・Pro待ちが無くなる。
    if req.suggested_recipe and not feedback.strip():
        ok, msg = validate_recipe(req.tested_params or req.suggested_recipe)
        req.expressible = True
        req.reject_category = None
        req.confidence = 0.9
        req.test_results = TestResult(
            passed=ok, total=1, passed_count=1 if ok else 0,
            failed_cases=[] if ok else [msg], detail=msg,
        )
        update_pending_request(req)
        return {
            "結果": "②で設計済みのレシピを検証しました",
            "タイプ名": req.suggested_type_name,
            "表現可能": True,
            "テスト": "合格" if ok else f"不合格（{msg}）",
            "自信度": req.confidence,
            "レシピ": req.suggested_recipe,
        }

    if not llm.is_available():
        raise HTTPException(
            status_code=400,
            detail="Gemini未設定のため生成できません（.env の GEMINI_API_KEY を設定してください）。",
        )

    # ① Pro でレシピ（操作×選択子）を設計（feedback は再生成時の管理者の補足）
    try:
        gen = RecipeAgent().generate(req, feedback=feedback)
    except Exception as exc:
        logger.exception("レシピ生成に失敗")
        raise HTTPException(status_code=502, detail=f"レシピ生成に失敗しました: {exc}")

    # ② 生成結果を格納＋検証（まとめチャットと共通の保存ロジック）
    res = _store_generated(req, gen)

    # ②a 表現できない＝正直に拒否
    if not res["expressible"]:
        return {
            "結果": "表現できませんでした",
            "タイプ名": req.suggested_type_name,
            "表現可能": False,
            "理由": reject_label(req.reject_category),
            "説明": gen.explanation,
            "自信度": req.confidence,
        }

    # ②b 設計・検証完了
    return {
        "結果": "設計・検証完了",
        "タイプ名": req.suggested_type_name,
        "表現可能": True,
        "説明": gen.explanation,
        "テスト": "合格" if res["passed"] else f"不合格（{res['detail']}）",
        "自信度": req.confidence,
        "懸念点": req.concerns,
        "レシピ": res["recipe"],
        "例レシピ": req.tested_params,
    }


@router.post(
    "/pending-types/chat",
    summary="生成済みルールをまとめて1つの会話で仕上げる（L2・まとめチャット）",
    description=(
        "承認画面の**生成済みルール全部を1つの会話**で調整します（ルールごとに別々ではなく横断）。\n\n"
        "管理者の発言を Gemini Pro が読み、**どのルールの話か**を判断して該当ルールのレシピだけ作り直します。\n"
        "ステートレス（会話履歴 `history` は毎回渡す）。承認/却下はこのAPIでは行いません（従来どおり個別）。\n\n"
        "body: `{ message: 管理者の発言, history: [{role:'user'|'ai', text}] }`\n"
        "返り値: `{ reply, updated_ids（作り直したルールのreq_id）, history（次回そのまま渡す） }`"
    ),
)
def chat_pending(body: dict = Body(...)):
    from src.agents import RecipeChatAgent

    message = ((body or {}).get("message") or "").strip()
    history = (body or {}).get("history") or []
    if not message:
        raise HTTPException(status_code=422, detail="メッセージが空です。直したい内容を入力してください。")
    if not llm.is_available():
        raise HTTPException(
            status_code=400,
            detail="Gemini未設定のため相談できません（.env の GEMINI_API_KEY を設定してください）。",
        )

    # 会話の対象＝「生成済み（検証まで走った）」承認待ちルール。フロントの generated 判定と揃える。
    reqs = [r for r in list_pending_requests(status="pending") if r.test_results is not None]
    if not reqs:
        raise HTTPException(
            status_code=400,
            detail="まだ仕上げ対象のルールがありません。先に「🤖 全部のレシピを生成」でレシピを作ってください。",
        )

    try:
        turn = RecipeChatAgent().chat(reqs, message, history)
    except Exception as exc:
        logger.exception("まとめチャットに失敗")
        raise HTTPException(status_code=502, detail=f"相談に失敗しました: {exc}")

    # AIが「直す」と判断したルールだけ、共通保存ロジックで更新＋再検証
    by_id = {r.id: r for r in reqs}
    updated: list[str] = []
    for up in turn.updates:
        req = by_id.get(up.req_id)
        if req is None:
            continue  # 一覧に無いidは無視（AIの取り違え対策）
        _store_generated(req, up)
        updated.append(req.id)

    new_history = list(history) + [
        {"role": "user", "text": message},
        {"role": "ai", "text": turn.reply},
    ]
    return {"reply": turn.reply, "updated_ids": updated, "history": new_history}


def _paramize_and_store(req: PendingTypeRequest) -> int:
    """承認された新typeの各原文を params化し、dynamic_constraints として保存する。

    ハンドラ生成時の見本（tested_params）と同じ形式に揃えることで、
    登録済みハンドラ handle(params, ctx) が期待する params の形に一致させる。
    保存した制約インスタンスの件数を返す。
    """
    from src.agents import ParamsAgent

    occurrences = [
        {
            "index": i,
            "person_id": o.get("person_id"),
            "date": o.get("date"),
            "source_text": o.get("source_text", ""),
        }
        for i, o in enumerate(req.occurrences)
    ]

    results = ParamsAgent().convert(
        type_name=req.suggested_type_name,
        param_schema_json=json.dumps(req.suggested_schema or {}, ensure_ascii=False),
        example_params_json=json.dumps(req.tested_params or {}, ensure_ascii=False),
        occurrences=occurrences,
    )
    by_index = {r.index: r for r in results}

    items: list[dict] = []
    for occ in occurrences:
        r = by_index.get(occ["index"])
        if r is None:
            continue
        try:
            params = json.loads(r.params_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(params, dict):
            continue
        items.append({
            "type": req.suggested_type_name,
            "params": params,
            "source": {
                "person_id": occ["person_id"], "date": occ["date"],
                "source_text": occ["source_text"],
            },
        })

    save_dynamic_constraints(items)
    return len(items)


def _fill_recipes_and_store(req: PendingTypeRequest) -> int:
    """承認された新typeのレシピを、各人の原文で埋めて dynamic_constraints に保存する。

    生成時の example_recipe（見本）に形式を揃え、各occurrenceの原文から選択子の値
    （weekday=水曜 等）を埋めて**完成レシピ**にする。本人IDはoccurrenceの値で上書き。
    保存した件数を返す。
    """
    from src.agents import ParamsAgent

    occurrences = [
        {
            "index": i,
            "person_id": o.get("person_id"),
            "date": o.get("date"),
            "source_text": o.get("source_text", ""),
        }
        for i, o in enumerate(req.occurrences)
    ]

    results = ParamsAgent().convert(
        type_name=req.suggested_type_name,
        param_schema_json=json.dumps(req.suggested_recipe or {}, ensure_ascii=False),
        example_params_json=json.dumps(req.tested_params or {}, ensure_ascii=False),
        occurrences=occurrences,
    )
    by_index = {r.index: r for r in results}

    items: list[dict] = []
    for occ in occurrences:
        r = by_index.get(occ["index"])
        if r is None:
            continue
        try:
            recipe = json.loads(r.params_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(recipe, dict) or "operation" not in recipe:
            continue
        # 本人IDは原文解釈に頼らず、occurrenceの確かな値で上書きする
        if recipe.get("who", "person") == "person" and occ["person_id"]:
            recipe["person_id"] = occ["person_id"]
        items.append({
            "type": req.suggested_type_name,
            "params": recipe,
            "source": {
                "person_id": occ["person_id"], "date": occ["date"],
                "source_text": occ["source_text"],
            },
        })

    save_dynamic_constraints(items)
    return len(items)


@router.post(
    "/pending-types/{req_id}/approve",
    summary="承認: 生成ハンドラをソルバーに登録し、影響シフトを再計算キューへ",
    description=(
        "未知タイプを承認します。承認後は:\n\n"
        "1. 生成済みハンドラコードを**動的ハンドラとして登録**（以降ソルバーが使える）\n"
        "2. `affected_shift_ids` に登録されているシフトを再計算キューに入れる\n"
        "3. ユーザーに「保留中だった要望が反映されました」と通知（実装予定）\n\n"
        "※ 生成（/generate）が未実施だと登録するコードが無いため、登録はスキップされます。"
    ),
)
def approve_pending(req_id: str, reviewer_id: str = "admin", comment: str = ""):
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"このリクエストは既に処理済みです（現在: {req.status}）",
        )

    # レシピ方式（推奨）: インタプリタが処理するのでハンドラ登録は不要。常に使える。
    # 旧Python方式: 生成コードを動的ハンドラとして登録する（後方互換）。
    recipe_mode = bool(req.suggested_recipe)
    usable = recipe_mode
    register_label = "不要（レシピ方式・インタプリタが処理）"
    if not recipe_mode and req.suggested_handler_code:
        try:
            register_dynamic_handler(req.suggested_type_name, req.suggested_handler_code)
            usable = True
            register_label = "完了（ソルバーで使えます）"
        except Exception as exc:
            logger.exception("ハンドラ登録に失敗")
            raise HTTPException(
                status_code=500,
                detail=f"承認しましたがハンドラ登録に失敗しました: {exc}",
            )
    elif not recipe_mode:
        register_label = "スキップ（生成物が無い）"

    # 各人の原文を埋めて制約インスタンスとして保存（＝ソルバーに渡す「材料」を用意）
    paramized = 0
    params_warning = None
    if usable and req.occurrences:
        if not llm.is_available():
            params_warning = "Gemini未設定のため原文の埋め込みをスキップしました（定義は登録済み）。"
        else:
            try:
                paramized = _fill_recipes_and_store(req) if recipe_mode else _paramize_and_store(req)
            except Exception as exc:
                logger.exception("制約インスタンス化に失敗")
                params_warning = f"定義は登録しましたが、原文の埋め込みに失敗しました: {exc}"

    req.status = "approved"
    req.reviewed_at = datetime.now()
    req.reviewer_id = reviewer_id
    req.review_comment = comment
    update_pending_request(req)

    # 影響シフトを再計算キューへ
    for shift_id in req.affected_shift_ids:
        mark_shift_for_recalc(
            shift_id=shift_id,
            reason=f"未知タイプ '{req.suggested_type_name}' が承認されたため",
        )

    result = {
        "結果": "承認しました",
        "タイプ名": req.suggested_type_name,
        "方式": "レシピ" if recipe_mode else "Python（旧）",
        "ハンドラ登録": register_label,
        "反映した要望(params)件数": paramized,
        "再計算キューに入れたシフト数": len(req.affected_shift_ids),
    }
    if params_warning:
        result["警告"] = params_warning
    return result


@router.post(
    "/pending-types/{req_id}/reject",
    summary="却下: このタイプは対応しないことを記録",
)
def reject_pending(req_id: str, reviewer_id: str = "admin", comment: str = ""):
    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"このリクエストは既に処理済みです（現在: {req.status}）",
        )

    req.status = "rejected"
    req.reviewed_at = datetime.now()
    req.reviewer_id = reviewer_id
    req.review_comment = comment
    update_pending_request(req)

    return {
        "結果": "却下しました",
        "タイプ名": req.suggested_type_name,
        "メッセージ": "ユーザーに「対応できません」と通知します（実装予定）",
    }
