# 仕様書 01 — データモデル定義

*最終更新: 2026-05-28*

---

## 概要

シフト計算に必要な全データの「型」を Pydantic で定義したもの。
パーサ・ソルバー・API すべてがこの型を通してデータをやり取りする。

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `src/models/master.py` | スタッフ・ポジション・役職・スキルの台帳モデル |
| `src/models/constraints.py` | 制約16種の型定義 + KNOWN_TYPES 定数 |
| `src/models/solver_io.py` | ソルバー入出力（SolverInput / SolverOutput）|
| `src/models/__init__.py` | 全モデルをまとめてimportできる窓口 |

---

## マスタモデル（master.py）

### Person（スタッフ）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| id | str | ✅ | 一意なID（例: "p1"）|
| name | str | ✅ | 氏名 |
| role_id | str \| None | — | 役職ID（Noneで無役職）|
| skill_ids | list[str] | — | 保有スキルIDのリスト |

### Position / Role / Skill

共通フィールド: `id: str`, `name: str`

### Masters（全台帳）

```json
{
  "persons":   [...],
  "positions": [...],
  "roles":     [...],
  "skills":    [...]
}
```

---

## 制約モデル（constraints.py）

### 共通構造

```json
{ "type": "<タイプ名>", "params": { ... } }
```

`type` フィールドで Pydantic が自動的に正しいモデルを選択する（Discriminated Union）。

### Hard 制約 8種

#### headcount_requirement
```json
{
  "type": "headcount_requirement",
  "params": {
    "slot_label": "ランチ",
    "time_start": "11:00",
    "time_end":   "14:00",
    "position_id": "pos_hall",
    "count": 4
  }
}
```

#### role_requirement
```json
{
  "type": "role_requirement",
  "params": { "slot_label": "ランチ", "position_id": "pos_hall", "role_id": "r_leader", "count": 1 }
}
```

#### skill_requirement
```json
{
  "type": "skill_requirement",
  "params": { "slot_label": "ランチ", "position_id": "pos_hall", "skill_id": "sk_cash", "count": 1 }
}
```

#### availability
```json
{
  "type": "availability",
  "params": { "person_id": "p1", "date": "2026-11-01", "start": "10:00", "end": "15:00" }
}
```

#### min_rest_interval
```json
{ "type": "min_rest_interval", "params": { "hours": 11 } }
```

#### break_rule
```json
{ "type": "break_rule", "params": { "threshold_hours": 6, "break_minutes": 45 } }
```

#### mentor_pairing
```json
{
  "type": "mentor_pairing",
  "params": { "newbie_role_id": "r_newbie", "requires_role_ids": ["r_leader", "r_general"] }
}
```

#### demand_adjustment
```json
{
  "type": "demand_adjustment",
  "params": {
    "date": "2026-11-03", "slot_label": "ランチ", "position_id": "pos_hall", "diff": 1,
    "target": { "kind": "role", "id": "r_leader" }
  }
}
```

### Soft 制約 8種

**weight**: 50〜1000（範囲外は自動クリップ）。大きいほど優先度高。

| タイプ | 主なパラメータ |
|---|---|
| separate | person_a, person_b, scope("day"\|"slot"), weight |
| pair_together | person_a, person_b, scope, weight |
| prefer_person | person_id, weight |
| avoid_person_slot | person_id, scope, target?, weight |
| time_preference | person_id, preferred_start?, preferred_end?, weight |
| limit_consecutive | person_id(None=全員), max_consecutive_days, weight |
| fairness | dimension("shifts"\|"hours"), weight |
| desired_workdays | person_id, kind("range"\|"as_many"\|"as_few"\|"none"), min?, max?, weight |

### KNOWN_TYPES

```python
KNOWN_TYPES: frozenset[str]  # 上記16種のtype名の集合
```

パーサが `type_name not in KNOWN_TYPES` で未知タイプを検出し、L2自律生成フローへ渡す。

---

## ソルバー入出力（solver_io.py）

### SolverInput

```json
{
  "frame": {
    "period": { "start": "2026-11-01", "end": "2026-11-14" },
    "operating_window": { "open": "10:00", "close": "22:00", "slot_minutes": 30 },
    "policy_mode": "wishes"
  },
  "masters": { "persons": [...], "positions": [...], "roles": [...], "skills": [...] },
  "constraints": [...]
}
```

**policy_mode の意味**:
- `wishes` … スタッフの希望をできるだけ優先
- `cost` … 労働コストを最小化
- `balance` … 全員の出勤を均等に

### SolverOutput（計画）

```json
{
  "status": "solved",
  "meta": { "seed": 42, "elapsed_ms": 3200, "objective": 1200 },
  "assignments": [
    {
      "date": "2026-11-01", "person_id": "p1", "position_id": "pos_hall",
      "start": "10:00", "end": "15:00",
      "break_start": "13:00", "break_end": "13:45",
      "locked": false
    }
  ],
  "warnings": [],
  "blocking_constraints": []
}
```

**status の種類**:
- `solved` … 計算成功
- `infeasible` … 条件が厳しすぎて解なし（blocking_constraintsに原因が入る）
- `timeout` … 8秒以内に解が見つからなかった

---

## 実装メモ

- `extra="forbid"` を全モデルに設定 → 定義外のフィールドを受け取るとエラーになり、誤入力を早期検出できる
- `from __future__ import annotations` は Python 3.14 との相性問題があるため使用しない
- soft制約の `weight` クリップは `_SoftParams` 基底クラスで一元管理
