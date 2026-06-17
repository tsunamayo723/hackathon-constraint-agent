"""
サイト管理者向けエンドポイント

未知タイプの承認キュー管理。
本番ではここに認可（管理者ロールチェック）を追加する。
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

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
def generate_handler(req_id: str):
    from src.agents import RecipeAgent
    from src.solver.recipe import validate_recipe

    req = get_pending_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"見つかりません: {req_id}")
    if not llm.is_available():
        raise HTTPException(
            status_code=400,
            detail="Gemini未設定のため生成できません（.env の GEMINI_API_KEY を設定してください）。",
        )

    # ① Pro でレシピ（操作×選択子）を設計
    try:
        gen = RecipeAgent().generate(req)
    except Exception as exc:
        logger.exception("レシピ生成に失敗")
        raise HTTPException(status_code=502, detail=f"レシピ生成に失敗しました: {exc}")

    # ② 例レシピを取り出して固定インタプリタで検証（execしない）
    def _loads(s: str) -> dict:
        try:
            v = json.loads(s) if s else {}
            return v if isinstance(v, dict) else {}
        except json.JSONDecodeError:
            return {}

    recipe_template = _loads(gen.recipe_template_json)
    example_recipe = _loads(gen.example_recipe_json)
    ok, message = validate_recipe(example_recipe)

    # ③ 生成結果と検証結果をリクエストに格納
    req.suggested_recipe = recipe_template
    req.tested_params = example_recipe
    req.confidence = max(0.0, min(1.0, gen.confidence))
    req.concerns = gen.concerns
    req.test_results = TestResult(
        passed=ok,
        total=1,
        passed_count=1 if ok else 0,
        failed_cases=[] if ok else [message],
        detail=message,
    )
    update_pending_request(req)

    return {
        "結果": "設計・検証完了",
        "タイプ名": req.suggested_type_name,
        "説明": gen.explanation,
        "テスト": "合格" if ok else f"不合格（{message}）",
        "自信度": req.confidence,
        "懸念点": req.concerns,
        "レシピ": recipe_template,
        "例レシピ": example_recipe,
    }


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
