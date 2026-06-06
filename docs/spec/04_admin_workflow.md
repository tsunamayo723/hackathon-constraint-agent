# 仕様書 04 — サイト管理者の承認フロー

*最終更新: 2026-06-06*

---

## 概要

パーサで検出された**未知タイプ**を、サイト管理者（プロダクト提供側のスタッフ）が
横断的にレビュー・承認する仕組み。

**店長ではなくサイト管理者が行う理由**:
- AIが生成したハンドラコードの品質判定は専門知識が必要
- 1店舗で生まれた新タイプは他店舗でも使える「資産」になる
- 店長にコード判断を求めるのは現実的でない

---

## ファイル

| ファイル | 役割 |
|---|---|
| `src/models/admin_queue.py` | PendingTypeRequest / TestResult モデル |
| `src/storage.py` | インメモリのモックストレージ（本番は Supabase）|
| `src/api/routes_admin.py` | `/admin/*` エンドポイント群 |

---

## PendingTypeRequest

サイト管理者画面で表示する1件分のデータ。

```json
{
  "id": "req_a1b2c3d4",
  "suggested_type_name": "recurring_day_off",
  "source_texts": [
    "毎週水曜は習い事で休みです",
    "水曜は基本入れません",
    "水曜だけは無理です"
  ],
  "occurrence_count": 3,
  "suggested_schema": { ... },
  "suggested_handler_code": "def handler(model, params, ctx): ...",
  "test_results": {
    "passed": true,
    "total": 5,
    "passed_count": 5,
    "elapsed_ms": 320
  },
  "confidence": 0.82,
  "concerns": ["曜日名の解釈に依存する"],
  "status": "pending",
  "created_at": "2026-05-28T12:30:00",
  "reviewed_at": null,
  "reviewer_id": null,
  "review_comment": null,
  "affected_shift_ids": ["shift_001", "shift_007"]
}
```

### 主要フィールド

| フィールド | 説明 |
|---|---|
| source_texts | 同じ未知タイプに該当する自然言語の集合（クラスタリング結果） |
| occurrence_count | 何件のリクエストで現れたか（優先度判断に使う） |
| **summary** | このルールが一言で何を求めているか（人が読む用・日本語） |
| **ai_assessment** | AIの見解（なぜ未知と判断したか／どう解釈したか） |
| **review_points** | 管理者に確認してほしい点のリスト（解釈の曖昧さ等） |
| suggested_schema / suggested_handler_code | Gemini Pro が生成（A1） |
| test_results | サンドボックスで自動テストした結果（A1） |
| concerns | AI自身が「ここが不安」と申告する内容（A1） |
| affected_shift_ids | 承認時に再計算すべき暫定シフトのID一覧 |

> **summary / ai_assessment / review_points**（2026-06-06追加）は、UIが無くても
> 生JSONのまま承認判断できるようにするためのフィールド。パース時（Flash）に付与する。
> `suggested_schema` 以下は A1（ハンドラ生成・Pro）で埋まる。

---

## API エンドポイント

### GET /admin/pending-types

承認待ち一覧。`status` で絞り込み可能（pending / approved / rejected）。

### GET /admin/pending-types/{req_id}

1件の詳細。

### POST /admin/pending-types/{req_id}/approve

**承認時の処理**:
1. status を "approved" に変更
2. 新typeをハンドラ辞書に永続登録（実装予定）
3. `affected_shift_ids` を再計算キューに入れる
4. ユーザーに「保留中だった要望が反映されました」と通知（実装予定）

### POST /admin/pending-types/{req_id}/reject

**却下時の処理**:
1. status を "rejected" に変更
2. ユーザーに「この要望は対応できません」と通知（実装予定）

---

## クラスタリング（同種の未知タイプをまとめる）

設計方針: **`suggested_type_name` が一致するものを1リクエストに集約**する
（複雑なembeddingは使わない。型名一致で十分）。

- 既存の同type pending があれば、新規レコードを作らず `source_texts` に原文を追記し
  `occurrence_count` を +1 する。
- 結果、承認は**タイプ単位で1回**になり、画面も「同じ内容が別IDで並ぶ」状態を解消できる。

**現状（〜2026-06-06）**: 未実装。各未翻訳項目ごとに別レコードを作っている
（同 recurring_day_off が複数IDで並ぶ）。出力リッチ化と同時に実装する。

---

## 管理者UI（④ admin.py）設計

データ（PendingTypeRequest）が読みやすくなった前提で、Streamlitで作る。

```
┌ 承認待ちキュー（status=pending を上に） ─────────────────┐
│ [recurring_day_off]  occurrence: 3                       │
│  要約: 毎週水曜は終日出勤不可にしたい繰り返しルール        │
│  AI見解: 曜日パターン。既存availabilityでは表現不可と判断  │
│  確認してほしい点:                                        │
│   - 対象は毎週「水曜」で合っているか                      │
│   - 終日不可か時間帯限定か（本文は終日と解釈）            │
│  元の発言: 「毎週水曜は習い事で…」「水曜は基本入れません」 │
│  [▼ 生成コード/テスト結果を見る（A1で表示）]              │
│  [▼ JSONで見る]                                          │
│  [ 承認 ]  [ 却下 ]  （コメント入力可）                   │
└──────────────────────────────────────────────────────┘
```

- 上部に要約・AI見解・確認ポイントを大きく出し、コード/テスト/JSONは折りたたみ。
- 承認/却下は `POST /admin/pending-types/{id}/approve|reject` を呼ぶ。
- **JSON表示トグル**を必ず付ける（生JSONでの確認を好むため）。
- A1完成後は `suggested_handler_code`（シンタックスハイライト）と `test_results` を展開表示。

---

## 承認後の再計算フロー

```
[承認] → [新type登録] → [affected_shift_idsを再計算キューへ]
                          ↓
            [バックグラウンドジョブ] 各シフトを再計算
                          ↓
            shift_status: provisional → confirmed
            pending_constraints: [] に更新
                          ↓
            ユーザーに通知（プッシュ通知 or 画面の差分表示）
```

現状はモックストレージで `mark_shift_for_recalc()` を呼ぶだけ。
実際の再計算は次フェーズ（OR-Tools実装）と同時に実装する。
