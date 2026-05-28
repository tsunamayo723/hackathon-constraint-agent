# 仕様書 03 — パーサ入出力

*最終更新: 2026-05-28*

---

## 概要

自然言語のシフト要望を、既知の制約タイプ（16種）と未知の文言に振り分けるコンポーネント。

**設計の核心**: 翻訳できなかった文言を**捨てない**。元の自然言語のまま `source_text` として残し、ユーザー画面で「保留中」表示に使う。

将来 Gemini Flash に差し替えるが、現状はキーワードマッチのスタブ。
入出力スキーマは変えない。

---

## ファイル

| ファイル | 役割 |
|---|---|
| `src/models/parser_io.py` | 入出力モデル定義 |
| `src/parser_stub.py` | スタブ実装（キーワードマッチ） |
| `src/api/routes_parser.py` | `/parser/parse` エンドポイント |

---

## ParserInput

```json
{
  "input_text": "10時から入れます。毎週水曜は習い事で休みです。",
  "person_id": "p1",
  "context_hint": "シフト希望"
}
```

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| input_text | str | ✅ | 自然言語の入力文 |
| person_id | str \| None | — | 誰の発言か（マスタ照合用） |
| context_hint | str \| None | — | 「シフト希望」「制約変更」等の文脈 |

---

## ParserOutput

```json
{
  "input_text": "...",
  "translated": [
    {
      "constraint": { "type": "headcount_requirement", "params": {...} },
      "source_text": "ランチに4人入れて",
      "confidence": 0.85
    }
  ],
  "untranslated": [
    {
      "source_text": "毎週水曜は習い事で休みです",
      "suggested_type_name": "recurring_day_off",
      "reason": "毎週○曜日のような繰り返しパターンは現在AIが対応ルールを準備中です",
      "status": "pending_review",
      "pending_request_id": "req_a1b2c3d4"
    }
  ],
  "parsed_at": "2026-05-28T12:30:00"
}
```

### TranslatedConstraint

| フィールド | 説明 |
|---|---|
| constraint | 既存の Constraint Union（16タイプのいずれか） |
| source_text | 翻訳元の自然言語の該当部分 |
| confidence | Geminiの自信度（0.0〜1.0） |

### UntranslatedConstraint

| フィールド | 説明 |
|---|---|
| source_text | 翻訳できなかった元の文言 |
| suggested_type_name | AIが推測した新type名候補（推測不能なら None） |
| reason | ユーザー向けの説明文（日本語） |
| status | pending_review / approved / rejected |
| pending_request_id | 管理者キューのレコードID（登録後にセット） |

---

## 振る舞い

1. `input_text` を句点で分割
2. 各文を判定:
   - 既知タイプにマッチ → `translated` に追加
   - 未知タイプにマッチ → `untranslated` に追加
3. `untranslated` の各項目を**自動で管理者キューに登録**し、`pending_request_id` を埋める

---

## スタブ実装の判定ルール（現状）

| 文の特徴 | 判定 |
|---|---|
| 「ランチ」+ 「人」/「名」 | `headcount_requirement` |
| 「毎週」「毎日」 | `recurring_day_off` 候補 |
| 「22時」「深夜」「月×回」 | `max_late_shift_count` 候補 |
| 「試験」「テスト期間」 | `exam_period` 候補 |
| 上記いずれでもない | type名不明の未翻訳項目 |

Gemini接続後はこの判定ロジックを置き換える。スキーマは不変。
