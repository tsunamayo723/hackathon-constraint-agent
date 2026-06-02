# 仕様書 05 — セットアップ入出力（マスタ・営業情報）

*最終更新: 2026-06-02*

---

## 概要

月次シフト作成の**土台**を登録するコンポーネント。

ソルバー入力 `SolverInput` は `frame` / `masters` / `constraints` の3ブロックで構成される。
このうち **`masters`（マスタ）** と **`frame`（営業情報）** をここで登録する。

| ブロック | 入力経路 | 入力UI |
|---|---|---|
| masters | CSVアップロード | セットアップ画面 ①マスタ設定 |
| frame | フォーム入力 | セットアップ画面 ②営業情報 |
| constraints | CSV（出勤希望）＋ 自然言語 | 別画面（実装予定 / staff.py） |

---

## 重要な設計判断 — なぜAPI経由か

**Streamlit と FastAPI は別プロセス**（将来Cloud Runで別サービス）。
Streamlit側のメモリに保存してもFastAPI（ソルバー）からは見えない。
したがってマスタ・営業情報は**必ず `POST /setup/*` 経由**でバックエンドに保存する。

```
[Streamlit セットアップ画面]
   │ CSVパース / フォーム入力
   ↓ POST /setup/masters, /setup/frame
[FastAPI] バリデーション + 整合性チェック
   ↓
[storage.py] インメモリ保存（本番: Supabase）
```

---

## ファイル

| ファイル | 役割 |
|---|---|
| `src/api/routes_setup.py` | `/setup/*` エンドポイント |
| `src/storage.py` | `save_masters` / `get_masters` / `save_frame` / `get_frame` |
| `src/ui/setup.py` | セットアップ画面（CSVアップロード＋フォーム） |
| `data/sample/*.csv` | デモ用サンプルCSV（4種） |

---

## CSVスキーマ（マスタ）

モデル（`Person` / `Position` / `Role` / `Skill`）に合わせた列構成。

### roles.csv / positions.csv / skills.csv

```csv
id,name
r_leader,リーダー
```

### staff.csv

```csv
id,name,role_id,skill_ids
p01,田中花子,r_leader,sk_cashier;sk_bar;sk_open;sk_close
```

| 列 | 説明 |
|---|---|
| id | スタッフID |
| name | 氏名 |
| role_id | 役職ID（roles.csv のidを参照） |
| skill_ids | スキルIDを **`;`（セミコロン）区切り**。空欄可 |

> `skill_ids` の区切りに `;` を使うのは、CSV区切りの `,` と衝突させないため。

---

## API エンドポイント

### POST /setup/masters

マスタ4種をまとめて登録。**ID参照の整合性チェック**を行う。

- `person.role_id` が roles に存在するか
- `person.skill_ids` の各IDが skills に存在するか

不整合があれば `422` で日本語エラーを返す（登録は行わない）。

### GET /setup/masters

登録済みマスタを取得。未登録なら `404`。

### POST /setup/frame

営業情報を登録。`period.end < period.start` なら `422`。

```json
{
  "period": {"start": "2026-11-01", "end": "2026-11-30"},
  "operating_window": {"open": "10:00", "close": "23:00", "slot_minutes": 30},
  "policy_mode": "balance"
}
```

### GET /setup/frame

登録済み営業情報を取得。未登録なら `404`。

---

## モデル改修（2026-06-02）

`AvailabilityParams` に **`note` 列を追加**した。

```python
class AvailabilityParams(BaseModel):
    person_id: str
    date: date
    start: str
    end: str
    note: Optional[str] = None  # 日ごとの自由記述（例: "この日は3時間だけ"）
```

**理由**: スタッフが出勤希望を出すとき「この日は3時間だけ」のような
日ごとの自然言語コメントを保持する場所が必要なため（外部サービス流の備考欄に相当）。
`note` はパーサが解釈して制約に展開する想定。

---

## 既知の設計の穴（未対応・記録）

突き合わせで判明した、今後埋めるべきモデルの穴：

| # | 穴 | 内容 | 対応予定 |
|---|---|---|---|
| 1 | headcountに曜日軸がない | 「曜日×時間帯の必要人数マトリクス」を表現できない。現状はフラットな人数のみ | 営業情報フォーム拡張時 |
| 2 | availabilityにpriorityがない | CSVの `must/prefer/available` を入れる場所がない（Hard/Soft分岐に必要） | 出勤希望CSV画面の実装時 |
