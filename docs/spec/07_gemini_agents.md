# 仕様書 07 — Geminiエージェント構成

*最終更新: 2026-06-06*

---

## 概要

Geminiが担う役割（パーサ / ハンドラ生成 / テスト生成 …）を、
**1役割＝1エージェント**として `src/agents/` に整理した。

狙い:
- 役割ごとに「使うモデル・プロンプト・出力スキーマ」が1か所に集まる → 改修が楽
- モデルを変える = そのエージェントの `model` を1行変えるだけ
- プロンプトはテキストファイルに分離 → コードを触らず文面を調整できる

---

## モデルの使い分け（CLAUDE.md準拠）

| 役割 | モデル | 頻度 | 状態 |
|---|---|---|---|
| 自然言語→JSON変換（パーサ） | **Flash**（安い） | 毎回・高頻度 | ✅ 実装（ParserAgent） |
| ハンドラ生成・テスト生成・自信度評価 | **Pro**（高精度） | 新type時のみ | 🔜 次フェーズ |

**APIキーは1つ**でよい（モデルはキー共通、呼び出し時の引数で切替）。
`.env` の `GEMINI_API_KEY` に設定。未設定時はスタブにフォールバック。
モデル名は `GEMINI_FLASH_MODEL` / `GEMINI_PRO_MODEL` で上書き可能。

---

## ファイル構成

```
src/llm.py                  … Gemini接続の共通土台（キー読込・モデル呼び出し・構造化出力）
src/agents/
  __init__.py               … エージェントの公開
  base.py                   … GeminiAgent 基底 ＋ load_prompt()
  parser_agent.py           … ParserAgent（Flash）: 自然言語→制約JSON
  prompts/
    parser.txt              … パーサのプロンプト（テキストで編集可能）
```

### GeminiAgent 基底

各エージェントは3つを宣言するだけ:

```python
class ParserAgent(GeminiAgent):
    model = llm.FLASH_MODEL     # 使うモデル
    schema = _ParseResult       # 構造化出力スキーマ
    prompt_name = "parser"      # prompts/parser.txt
```

`run_structured(**vars)` がプロンプト組み立て→Gemini呼び出し→Pydantic検証済みオブジェクト返却まで行う。

---

## プロンプトの置き場

`src/agents/prompts/<name>.txt` にテキストで置く。

- **穴埋めは `$変数` 形式**（`string.Template`）。
  理由: プロンプト内にJSONの `{ }` が多く、`.format()` だと波括弧と衝突するため。
- 例: `parser.txt` 末尾は `発言者のスタッフID: $person_id` ／ `「$input_text」`。

---

## パーサの信頼性設計

- Geminiには**ゆるい中間フォーマット**（`is_known` / `type_name` / `params_json` / `confidence`）で出させる。
- **params の厳密検証は Python 側**（Pydantic `Constraint`）で行い、AIのJSONブレを吸収。
  検証に失敗したら未翻訳（untranslated）へ落とす。
- **確信度 < 0.5 は未翻訳扱い**（分かったフリをしない）。

```
Gemini Flash（ゆるく分類）
   ↓ items[]
Python: KNOWN_TYPES判定 → params厳密検証 → confidence判定
   ↓
translated / untranslated に振り分け（ParserOutput）
```

---

## 動作の切替（キーの有無）

`src/api/routes_parser.py` の `_run_parse`:

| 状態 | 挙動 |
|---|---|
| `GEMINI_API_KEY` 設定済み | ParserAgent（本物のGemini Flash） |
| 未設定／プレースホルダ／非ASCII | スタブ（キーワードマッチ）にフォールバック |
| Gemini呼び出し失敗 | HTTP 502 で明示（握りつぶさない） |

---

## 今後の拡張

同じ `GeminiAgent` の型で、次の役割を載せる:

- `HandlerAgent`（Pro）: 未知typeのハンドラ関数コードを生成
- `TestAgent`（Pro）: 生成ハンドラのテストコードを生成
- `ConfidenceAgent`（Pro）: 生成物の自信度・懸念点を評価

いずれも `prompts/` にプロンプトを足し、`model = llm.PRO_MODEL` を宣言するだけ。
