# 仕様書 07 — Geminiエージェント構成

*最終更新: 2026-06-20*

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
| 自然言語→JSON変換（パーサ） | **Flash**（安い・思考オフ） | 毎回・高頻度 | ✅ 実装（ParserAgent） |
| 備考(note)のバッチ解釈・3分類 | **Flash**（安い・思考オフ） | ②のボタン押下時のみ | ✅ 実装（NoteAgent） |
| 提出者の備考を対話で確認（聞き返し） | **Flash**（安い・思考オフ） | 提出者UIでの会話ごと | ✅ 実装（ChatAgent・T9） |
| 未知typeのレシピ設計（＋表現可否判定） | **Pro**（高精度） | 新type時のみ | ✅ 実装（RecipeAgent） |
| ハンドラ生成（旧Python方式・後方互換） | **Pro**（高精度） | 新type時のみ | ✅ 実装（HandlerAgent） |

> **⚠️ 無料枠ではProが使えない（2026-06時点）**: `gemini-2.5-pro` は無料枠で `limit: 0`。
> 現在は課金済みのため `gemini-2.5-pro` を使用中。無料枠に戻す場合は
> `.env` の `GEMINI_PRO_MODEL=gemini-2.5-flash` に向ければよい（コード変更不要）。
> **思考トークンに注意**: Flashの思考(thinking)は出力扱いで課金され、コストの主因になる。
> 高頻度のParser/NoteAgentは `thinking_budget=0`（思考オフ）で運用する。

**APIキーは1つ**でよい（モデルはキー共通、呼び出し時の引数で切替）。
`.env` の `GEMINI_API_KEY` に設定。未設定時はスタブにフォールバック。
モデル名は `GEMINI_FLASH_MODEL` / `GEMINI_PRO_MODEL` で上書き可能。

---

## ファイル構成

```
src/llm.py                  … Gemini接続の共通土台（キー読込・モデル呼び出し・構造化出力・リトライ）
src/usage.py                … トークン消費・概算料金のセッション集計
src/agents/
  __init__.py               … エージェントの公開
  base.py                   … GeminiAgent 基底 ＋ load_prompt()
  _context.py               … 実マスタをプロンプトへ注入する文脈づくり（masters_context）
  parser_agent.py           … ParserAgent（Flash）: 自然言語→制約JSON＋未知type検出
  note_agent.py             … NoteAgent（Flash）: 備考(note)のバッチ解釈・3分類
  chat_agent.py             … ChatAgent（Flash）: 提出者の備考を対話で確認（T9）
  recipe_agent.py           … RecipeAgent（Pro）: 未知typeのレシピ設計＋表現可否判定
  handler_agent.py          … HandlerAgent（Pro）: 未知typeのハンドラコード生成（旧方式）
  prompts/
    parser.txt              … パーサのプロンプト（テキストで編集可能）
    note.txt                … 備考解釈のプロンプト
    chat_clarify.txt        … 提出者チャットのプロンプト
    recipe_gen.txt          … レシピ設計のプロンプト
    handler.txt             … ハンドラ生成のプロンプト
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

### 実マスタの動的注入（存在しないID捏造の防止）

`src/agents/_context.py` の `masters_context()` が、現在のマスタを
**「position_id = 名前」の一覧テキスト**にして返す。これを `$masters` 変数で
`parser.txt` / `recipe_gen.txt` に注入する。

- 狙い: 以前はプロンプトに `ホール=pos_hall` 等を**固定で書いていた**ため、AIが
  デモに存在しないID（`pos_hall`）を出力し、人数要件が幻のポジションに付いて
  **無効化される**不具合があった。実マスタ（`pos_floor` / `pos_counter` 等）を渡すことで
  AIは実在IDだけを選ぶようになり、この不具合を**構造的に**根絶した。
- 対象: position_id を生成する **ParserAgent**（毎回）と **RecipeAgent**（新type時）。
  note解釈/チャットはIDを出さないため注入不要。
- マスタ未登録時は安全なフォールバック文（「一般的なIDで推定してよい」）を返し、
  プロンプトを壊さない（`safe_substitute` で未解決変数も残さない）。

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

## NoteAgent — 備考(note)のバッチ解釈・3分類（2026-06-10更新）

出勤希望CSVの**日ごと備考(note)** を `CHUNK_SIZE=40` 件ずつまとめて解釈し、各備考を3分類する:

| 分類 | 条件 | 行き先 |
|---|---|---|
| ✅ **時間補正** | その日の出勤可能枠を狭める内容（「お迎えで17時まで」） | `start/end` を補正（枠の内側のみ・広げない） |
| 🆕 **新ルール候補** | 1日の時間補正で表せない「仕組みのルール」（「毎週水曜NG」） | **管理者の承認キューへ**（②と同じクラスタリング） |
| ⚠️ **申し送り** | どちらでもない（挨拶・連絡事項） | 未反映として正直に可視化（④で要確認表示） |

信頼性ガード（分かったフリをしない＋誤検出防止）:
- プロンプトに既知16typeの名前一覧を渡し「既知で表せるものは新typeにしない」と指示
- さらにPython側でも `suggested_type_name in KNOWN_TYPES` なら新type扱いを却下（二重ガード）
- 新ルール候補は同じtype名で1キューに集約（クラスタリング）。**再解釈しても二重登録しない**
  （person+date+原文で重複判定）

承認キュー（`PendingTypeRequest`）には `occurrences`（person_id/date/原文/出どころ）を
構造化記録する。承認後に「誰の要望か」をparams化する材料（T2）。

---

## ChatAgent — 提出者の備考を対話で確認（2026-06-18・T9）

提出者UI（デモ主役画面）で、1人の提出者が書いた**備考(note)** をその場で確認する対話エージェント。
NoteAgentが「CSVの備考をまとめてバッチ解釈」するのに対し、ChatAgentは**本人と1往復ずつ対話**する。

- **モデルはFlash**（ユーザー指示: 要望整理にソルバー生成ほどの賢さは不要）。思考オフ。
- **ステートレス**: 会話履歴(`history`)を毎リクエストで丸ごと渡す（サーバーに状態を持たない）。
- 出力 `ChatTurn`: `reply`（画面に出す返答）/ `needs_clarification`（さらに聞き返すか）/
  `understood_summary`（確定要約）/ `is_rule`・`suggested_type_name` / `expressible`・`reject_category`
  （正直な拒否）/ `recipe_json`（確定したルールのレシピ＝操作×選択子。`person_id`は空でよい）。
- 確定時（`needs_clarification=false` かつ `expressible` かつ `is_rule`）に**レシピを直接出力**する。
  提出者の備考は単純な単一人ルールが多く、Flashで十分かつ安価（Proの`RecipeAgent`は管理者の
  未知type設計に温存）。レシピの解釈は共通の固定インタプリタ `apply_recipe` が担う（安全性は同じ）。

エンドポイント: `POST /chat/clarify-note`（`routes_chat.py`）。詳細は `docs/spec/10_submitter_ui.md`。

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
