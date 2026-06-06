"""
Gemini 動作確認スクリプト

.env にキーを設定したあと、これ1つで「ちゃんと動くか」を確認する。
  ① キーが有効か（モデル一覧を取得できるか）
  ② サンプル文がパーサで正しく既知/未知に振り分けられるか

実行: python scripts/check_gemini.py
（キーは表示しない。秘密情報なので）
"""

from src import llm
from src.agents import ParserAgent
from src.models import ParserInput


def main() -> None:
    print("=" * 56)
    print("Gemini 動作確認")
    print("=" * 56)

    # ── ① キーの有無 ──────────────────────────────────────────
    if not llm.is_available():
        print("✗ APIキーが未設定です。.env の GEMINI_API_KEY を確認してください。")
        return
    print(f"✓ APIキー検出 / Flash={llm.FLASH_MODEL} / Pro={llm.PRO_MODEL}")

    # ── ② モデル一覧（キーが有効かの確認） ────────────────────
    try:
        names = llm.list_models()
        print(f"✓ モデル一覧を取得（{len(names)}件）。キーは有効です。")
        flash_ok = any(llm.FLASH_MODEL in n for n in names)
        print(f"  - 設定中のFlashモデルが一覧にある: {'はい' if flash_ok else 'いいえ（モデル名を確認）'}")
    except Exception as exc:
        print(f"✗ モデル一覧の取得に失敗（キーが無効かもしれません）: {exc}")
        return

    # ── ③ サンプル文をパース ──────────────────────────────────
    sample = "ランチに4人入れて。毎週水曜は習い事で休みです。"
    print("\n" + "-" * 56)
    print(f"サンプル入力: 「{sample}」")
    print("-" * 56)
    try:
        out = ParserAgent().parse(ParserInput(input_text=sample, person_id="p01"))
    except Exception as exc:
        print(f"✗ パース呼び出しに失敗: {exc}")
        return

    print(f"✅ 反映済み（translated）: {len(out.translated)} 件")
    for t in out.translated:
        print(f"   - 「{t.source_text}」→ {t.constraint.type}（確信度 {t.confidence:.2f}）")
        print(f"     params: {t.constraint.params.model_dump()}")

    print(f"⏳ 確認中（untranslated）: {len(out.untranslated)} 件")
    for u in out.untranslated:
        print(f"   - 「{u.source_text}」→ 推定: {u.suggested_type_name}")
        print(f"     理由: {u.reason}")

    print("\n" + "=" * 56)
    print("判定の目安: 『ランチに4人』が translated（headcount_requirement）、")
    print("           『毎週水曜は休み』が untranslated（recurring_day_off）に")
    print("           分かれていれば成功です。")
    print("=" * 56)


if __name__ == "__main__":
    main()
