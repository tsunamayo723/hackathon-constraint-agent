# CLAUDE.md — 制約管理エージェント

このファイルは Claude Code が最初に読む設定ファイルです。プロジェクトの全体像・設計判断・開発ルールをまとめています。

---

## プロジェクトの30秒サマリ

**自然言語の定性的な制約 → typed JSON → ハンドラ関数 → OR-Tools ソルバー** というパイプラインを持つ自律エージェント。

コアバリュー:
> 「AIが新要件を検出 → 自分でハンドラ(処理コード)を書く → テスト → 人間に承認を求める」という自律的な振る舞いを実現する。

- **デモドメイン**: 飲食店シフト(30名 × 1ヶ月)
- **ハッカソン**: DevOps × AI Agent Hackathon 2026(提出: 2026-07-10)
- **個人目標**: 入賞ではなく、自分が面白いと思うものを作ること

---

## 技術スタック(全項目確定済み)

| レイヤー | 採用 |
|---|---|
| 言語 | Python 3.11+ |
| バックエンドAPI | FastAPI |
| デモUI（裏方） | Streamlit（CSVアップ・シフト実行・管理者承認） |
| デモUI（提出者の主役画面） | Vite + React + Tailwind（`frontend/`・T9） |
| ソルバー | OR-Tools (CP-SAT) |
| LLM | Gemini API (Flash + Pro カスケード) |
| デプロイ | Cloud Run × 2(FastAPI用 / Streamlit用) |
| DB | Supabase (PostgreSQL + JSONB) |
| サンドボックス | Python subprocess + タイムアウト |

---

## 設計の最重要ルール

### やってはいけないこと

- **本デモに不要な作り込みを持ち込まない**: 認証(ログイン/権限管理)・マルチテナント・広告モデルなどは作らない。提出者UIはReact(Vite)で作るが（T9）、ログイン認証は作らずマスタからの選択で代用する（Next.js も使わない）。
- **ソルバー本体を改修しない**: OR-Toolsはブラックボックスとして使う。変えるのはハンドラ関数だけ。
- **weightを50〜1000の範囲でクリップしない実装**: プロンプトインジェクション対策のため必須。

### 設計の核心

- **同一typeは必ず同一paramsスキーマ**: スキーマが変わるなら新しいtypeを作る。
- **ハンドラ生成は1typeにつき1回**: 新type初登場時だけAIが生成→辞書に永続登録→以降はコード実行。毎回AIを呼ばない。
- **Hard制約 vs Soft制約の区別を厳守**: Hardはソルバーが絶対遵守、Softは罰金変数(50〜1000クリップ)。「なるべく」をHardに翻訳するのは禁止。

---

## アウトプット品質チェック(必須・作業の進め方)

- **実装の前に**: 何を作るかを必ず説明し、方針を合意してから着手する。
- **アウトプットを出す前に**: 自分で品質をセルフチェックする(設計の核心・既存仕様との整合・「肝」を壊していないか・読みやすさ・日本語出力)。
- **問題を見つけたら**: ユーザーに「ここに問題があったので直す」と**告知した上で**、**承認を待たずに**自分で再検証・修正してから出す。問題を隠したまま出さない。
- 検証していないことを「できました」と言わない。未検証なら未検証と正直に書く。

---

## システム構成(6要素)

```
[自然言語入力]
   ↓ Gemini Flash
[①パーサ] NL → {type, params} JSON + 既知/未知判定
   ↓
 既知16type → [④ハンドラ関数] → [⑤OR-Tools] → 最適解
 未知type   → [⑥AIエージェント]
                  ↓ Gemini Pro
                  新typeスキーマ設計 → ハンドラ生成 → テスト → 承認ゲート → 登録
```

| # | 要素 | 役割 |
|---|---|---|
| ① | Geminiパーサ | NL→JSON変換、既知type分類、未知type検出(`is_new_type`) |
| ② | type辞書(16種) | Hard 8 / Soft 8 のJSONスキーマ定義 |
| ③ | マスタ | persons/positions/roles/skillsの正規化辞書 |
| ④ | ハンドラ辞書+関数 | type→ソルバーAPI翻訳。AIが生成・永続登録 |
| ⑤ | ソルバー(OR-Tools) | 変数+制約から最適解を計算 |
| ⑥ | AIエージェント | 未知type対応(L2自律生成フロー) |

---

## 16 type 初期辞書(コード化の土台)

詳細スキーマは `docs/01_handover_original.md §4` を参照。

**Hard 8**: `headcount_requirement` / `role_requirement` / `skill_requirement` / `availability` / `min_rest_interval` / `break_rule` / `mentor_pairing` / `demand_adjustment`

**Soft 8**: `separate` / `pair_together` / `prefer_person` / `avoid_person_slot` / `time_preference` / `limit_consecutive` / `fairness` / `desired_workdays`

## デモ用「未知type」(確定済み・3つ)

これらは16typeに含まれず、L2フローで自動生成させる対象。詳細は `docs/01_handover_original.md 付録A`。

| type名 | 入力例 |
|---|---|
| `recurring_day_off` | 「毎週水曜は習い事があって入れません」 |
| `max_late_shift_count` | 「22時以降まで働くシフトは月3回までにして」 |
| `exam_period` | 「12/10〜20が試験期間なので極力入れないで」 |

---

## 自動化レベル(L1〜L5)

| 階層 | 内容 | 採否 |
|---|---|---|
| L1 | マスタ追加提案 | ✅ |
| **L2** | **ハンドラ自動生成 + テスト + 承認** | ✅ **コア** |
| L3 | soft重み自動調整 | ⏸ 余裕あれば |
| L4以上 | 対象外 | ❌ |

---

## Geminiモデル使い分け

| 処理 | モデル | 頻度 |
|---|---|---|
| NL→JSON変換、既知type分類 | Flash | 毎回(高頻度) |
| ハンドラ生成、テストコード生成、自信度評価 | Pro | 新type時のみ(低頻度) |

自信度ベースルーティング: Flash >= 0.8 → 採用 / 0.5〜0.8 → Proで再変換 / < 0.5 → ユーザーに言い直し依頼

---

## 開発の最短着手順

1. **16 typeをPydanticモデルでコード化** (`docs/01_handover_original.md §4`)
2. **最小ソルバー**: `headcount_requirement` + `availability` + `separate` の3typeだけ通す
3. **Geminiパーサ**: NL→JSON変換 + `is_new_type` 検出
4. **L2フロー1本通す**: 未知type1つ(例: `time_preference`を辞書から抜いておく)で検出→生成→テスト→承認→登録
5. 余裕があれば: L3(重み調整)、フィードバックUI

---

## ドキュメント構成

| ファイル | 内容 |
|---|---|
| `docs/00_overview.md` | プロジェクト全体像・現在地マップ |
| `docs/01_handover_original.md` | **設計詳細の本体** (type辞書/ソルバーI/O/L2仕様) ★ |
| `docs/02_hackathon_rules.md` | ハッカソン要項・評価軸 |
| `docs/03_tech_stack.md` | 技術スタック詳細・選定理由 |
| `docs/04_input_flow.md` | 入力フロー設計(CSV+自然言語ハイブリッド) |
| `docs/05_remaining_tasks.md` | 残タスク一覧(優先度付き) |
| `docs/99_decisions_log.md` | 決定事項ログ(時系列) |
| `docs/reference/` | 原本ファイル群(参照用) |

---

## ユーザー情報(コード生成スタイルの参考)

- 非エンジニア(本職: データアナリスト / マーケティング)
- Python経験: あり(データ分析レベル)
- Web開発経験: 個人開発程度
- 目標: 楽しく作ること。入賞より「面白いと思うものを作る」
- → **コードは読みやすさ優先、難しい構文より明快な書き方を選ぶ。エラーメッセージも日本語で出力する。**
