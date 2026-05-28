# 仕様書 04 — サイト管理者の承認フロー

*最終更新: 2026-05-28*

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
| suggested_schema / suggested_handler_code | Gemini Pro が生成 |
| test_results | サンドボックスで自動テストした結果 |
| concerns | AI自身が「ここが不安」と申告する内容 |
| affected_shift_ids | 承認時に再計算すべき暫定シフトのID一覧 |

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

設計方針: **embedding ベースの類似度**で、`suggested_type_name` が同じものを1件にまとめる。

現状のスタブはクラスタリング未実装で、各リクエストごとに別レコードを作る。
Gemini接続時に同時実装する。

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
