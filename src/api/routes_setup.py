"""
セットアップ系エンドポイント（マスタ・営業情報）

月次シフト作成の「土台」となるデータを受け取って保存する。
- マスタ（人/役職/ポジション/スキル）… CSVアップロード由来
- 営業情報（frame: 期間・営業時間・ポリシー）… フォーム入力由来

Streamlit と FastAPI は別プロセスのため、必ずこのAPI経由で受け渡す。
保存先は現状インメモリ（storage.py）。本番では Supabase。
"""

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from src.models import Frame, Masters
from src.storage import get_frame, get_masters, save_frame, save_masters

router = APIRouter(prefix="/setup", tags=["セットアップ"])


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
