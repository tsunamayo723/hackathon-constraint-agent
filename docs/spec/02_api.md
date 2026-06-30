# 仕様書 02 — API エンドポイント定義

*最終更新: 2026-05-28*

> ⚠️ **本書は陳腐化（初期版）**。当時「未実装・今後追加予定」とした `/solver/*` `/parser/*` `/setup/*` `/admin/*` `/chat/*` `/submit/*` は**すべて実装済**。**現在のAPIの真実は稼働中の Swagger `/docs`**。本書は参照しないこと。

---

## 概要

FastAPI で実装した HTTP API。
現時点はデータの形式チェック機能のみ。ソルバー実行は今後追加予定。

ベースURL（ローカル開発）: `http://127.0.0.1:8001`
起動コマンド: `python -m uvicorn src.api.main:app --reload --port 8001`
API仕様書（自動生成）: `http://127.0.0.1:8001/docs`

---

## エンドポイント一覧

### GET /health — サーバー起動確認

**レスポンス例**
```json
{ "status": "正常", "登録済み制約タイプ数": 16 }
```

---

### POST /constraints/validate — 制約データの形式チェック

**リクエスト**: 制約JSON（type + params）

**レスポンス — 既知タイプの場合**
```json
{
  "有効": true,
  "未知のタイプ": false,
  "タイプ名": "separate",
  "パラメータ": { "weight": 600, "person_a": "p1", "person_b": "p2", "scope": "day" }
}
```
※ weight が範囲外の場合、パラメータ内で自動補正された値が返る

**レスポンス — 未知タイプの場合**
```json
{
  "有効": false,
  "未知のタイプ": true,
  "タイプ名": "recurring_day_off",
  "メッセージ": "未登録のタイプです: 'recurring_day_off' → AIが新しいハンドラを自動生成します"
}
```

**レスポンス — 形式エラーの場合**
HTTP 422 + Pydantic のバリデーションエラー詳細

---

### POST /solver/validate-input — ソルバー入力全体の形式チェック

**リクエスト**: SolverInput（frame + masters + constraints 全体）

**レスポンス例**
```json
{
  "有効": true,
  "概要": {
    "対象期間": "2026-11-01 〜 2026-11-14",
    "スタッフ数": 5,
    "制約数": 3,
    "制約タイプ一覧": ["headcount_requirement", "availability", "separate"]
  }
}
```

---

## 今後追加予定のエンドポイント

| URL | 内容 | 優先度 |
|---|---|---|
| `POST /solver/run` | 実際にシフト計算を実行する | ★★★ |
| `POST /parser/parse` | 自然言語 → 制約JSON変換（Gemini） | ★★★ |
| `POST /agent/generate-handler` | 未知タイプのハンドラ自動生成（L2フロー）| ★★★ |
| `GET /handlers` | 登録済みハンドラ一覧 | ★★ |
