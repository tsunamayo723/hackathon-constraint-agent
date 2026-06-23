"""
レシピ堅牢化のライブ最終証明（2026-06-23）。

以前ライブで「週末は…」が weekday=[5,6]（配列）／幻フィールドで落ちていた。
実Gemini(RecipeAgent/Pro)に「週末は終日入れません」を通し、AIが配列で出しても
validate_recipe が「レシピの形式エラー」を出さず**合格**することを確認する。

前提: .env に GEMINI_API_KEY 設定済み（llm.py が load_dotenv で自動読込）。
実行: python scripts/check_weekend_live.py
"""

import json
import os
import sys
from datetime import datetime

# Windowsでも日本語出力が化けないように（reference_ps_utf8 の方針）
sys.stdout.reconfigure(encoding="utf-8")

# scripts/ から直接実行しても src を import できるよう、プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents import RecipeAgent
from src.models.admin_queue import PendingTypeRequest
from src.solver.recipe import validate_recipe

req = PendingTypeRequest(
    id="weekend_live",
    suggested_type_name="weekend_day_off",
    source_texts=["週末（土日）は終日シフトに入れません"],
    created_at=datetime.now(),
)

print("RecipeAgent(Pro) にレシピ設計を依頼中…（実Gemini）")
gen = RecipeAgent().generate(req)

print(f"\nexpressible={gen.expressible} / confidence={gen.confidence}")
print(f"説明: {gen.explanation}")
print(f"例レシピ: {gen.example_recipe_json}")

recipe = json.loads(gen.example_recipe_json)
wd = recipe.get("weekday")
print(f"\nweekday の値 = {wd!r}（型: {type(wd).__name__}）")

ok, msg = validate_recipe(recipe)
print(f"\n検証結果: {'✅ 合格' if ok else '❌ 不合格'}")
print(f"メッセージ: {msg}")

# 終了コードで合否を表す（合格=0）
sys.exit(0 if ok else 1)
