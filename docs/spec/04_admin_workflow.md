# 仕様書 04 — サイト管理者の承認フロー

*最終更新: 2026-06-10*

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

**承認時の処理**（2026-06-10 T2で配線完了）:
1. 生成ハンドラを `register_dynamic_handler` で**ハンドラ辞書に登録**（以降ソルバーが使える）
2. **params化**: `req.occurrences`（誰の・いつの・原文）を ParamsAgent(Flash) で
   `{person_id, weekday, ...}` 等の params に変換し、`save_dynamic_constraints` で保存（＝ハンドラに渡す「材料」）。
   生成時の `tested_params`（見本）に形式を揃えることで、ハンドラが期待する形に一致させる。
3. status を "approved" に変更（→ run-stored で pending から外れ、シフトが暫定→確定に近づく）
4. `affected_shift_ids` を再計算キューに入れる
- ※ Gemini未設定／params化失敗時は、ハンドラ登録だけ成功させ `警告` を返す（承認自体は壊さない）。

### POST /solver/preview-rule-effect（承認直後の差分表示用）

`{type_name}` を受け、その type を**除いた状態**と**含めた状態**で2回 `solve()` し、
変わった割当（removed/added）と before/after の assignments を返す。
⑤画面が承認直後にこれを呼び、「このルールで p01 の水曜が消えた」を可視化する。

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

**実装済み（2026-06-10）**: `find_pending_by_type` で同type名の pending を探し、
あれば `source_texts` / `occurrences` に追記して `occurrence_count` を +1 する。
②の方針入力・③のnote由来の両方で集約される（別の言い回しが1キューにまとまる）。

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

## 承認後の再計算フロー（2026-06-10 実装）

```
[承認] → register_dynamic_handler（ハンドラ登録）
       → ParamsAgent で原文→params化 → save_dynamic_constraints（材料を保存）
       → status=approved（pendingから外れる）
              ↓
[⑤画面] preview-rule-effect を即時呼び出し → before/after 差分を表示
              ↓
[④画面] run-stored を再実行 → dynamic_constraints が反映され、
        pending が無くなれば shift_status: provisional → confirmed
```

`_DYNAMIC_HANDLERS` と dynamic_constraints は**インメモリ**（プロセス再起動で消える）。
デモ1セッション中は問題なし。永続化（起動時の再登録）は T5(Supabase) で対応する。
