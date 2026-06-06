# 仕様書 06 — 最小ソルバー（OR-Tools）

*最終更新: 2026-06-04*

---

## 概要

`SolverInput`（営業情報＋マスタ＋制約）を受け取り、OR-Tools（CP-SAT）で
**実際のシフト割当**を計算して `SolverOutput` を返すコンポーネント。

これが入って初めて「自然言語 → シフト表」が端から端まで繋がる。

**最小ソルバー版の対応タイプは3つ**（CLAUDE.md の最短着手順 step2 に対応）:

| type | Hard/Soft | 役割 |
|---|---|---|
| `headcount_requirement` | **Soft（不足は減点）** | 時間帯×ポジションの必要人数。不足は大きく減点（5000/人）。解けなくても暫定の最高点を出力。**`date`（任意）指定でその日だけ適用**（繁忙日・イベント日の上書き。省略時は全日） |
| `availability` | Hard | 出勤可能枠。枠外コマは割当不可（0固定） |
| `separate` | Soft | 同席したら罰金（weight 50〜1000） |

未対応タイプは**黙って捨てず** `warnings` に `"unhandled:<type>"` として明示する。

---

## 時間モデル — スロット（コマ）

時間を連続値ではなく、営業時間を `slot_minutes` 単位で刻んだ**コマの集合**として扱う。

```
営業 11:00〜14:00, slot_minutes=60
 → [11:00-12:00] [12:00-13:00] [13:00-14:00]  の3コマ
```

| 関数 | 役割 | ファイル |
|---|---|---|
| `hhmm_to_min` / `min_to_hhmm` | "HH:MM" ⇔ 分 の変換 | `src/solver/slots.py` |
| `date_range` | 期間を日付リストに展開 | 〃 |
| `build_day_slots` | 1日分のコマ列を生成 | 〃 |
| `Slot.is_within` | コマが時間帯に収まるか判定 | 〃 |

---

## 変数モデル（CP-SAT）

| 変数 | 意味 |
|---|---|
| `x[(person, day, slot, position)]` | その人がそのコマでそのポジションに入る（0/1） |
| `present[(person, day, slot)]` | そのコマに在席（= Σポジション x、`==present` で1コマ1ポジションを強制） |
| `work_day[(person, day)]` | その日に1コマでも入る（= コマの OR） |

**目的関数**: `Σ(separate罰金) + Σ(全割当数)`
最小化。総割当に係数1の軽い罰を付け、過剰配置を抑える（罰金 ≥50 が常に優先される）。

---

## ハンドラ（type → 制約翻訳）

`src/handlers/` がハンドラ辞書。**ここがエージェントの肝** — 将来 L2フローで
AIが生成した未知タイプのハンドラを `HANDLERS` 辞書に追記・永続登録する土台。

| ハンドラ | 翻訳内容 |
|---|---|
| `handle_headcount` | 対象時間帯の各コマで「そのポジションの人数合計 ≧ count」 |
| `handle_availability` | 可用枠を `ctx.availability` に蓄積（engineが枠外を0固定） |
| `handle_separate` | 罰金変数 `z ≧ (Aいる)+(Bいる)−1` を立て、目的関数に weight 分計上 |

> availability だけは「ある人の全枠が出そろってから複合判定」が必要なため、
> ハンドラは蓄積に徹し、`engine._apply_availability` が最後に一括適用する。

### availability の扱い（出勤希望ベース）

- 1件でも希望を出した人 → **出した枠の中だけ**入れる（希望日以外は終日不可）
- 希望を1件も出していない人 → 無制限（小さなサンプルでも動くように）

---

## 入出力

### POST /solver/run

`SolverInput` ＋ 任意の `pending_constraints` を受け取り `SolverOutput` を返す。

```jsonc
// レスポンス（抜粋）
{
  "status": "solved",            // solved / infeasible / timeout
  "shift_status": "provisional", // confirmed / provisional（未翻訳あり）
  "assignments": [
    {"date": "2026-11-01", "person_id": "p2", "position_id": "pos_hall",
     "start": "11:00", "end": "14:00"}
  ],
  "warnings": [],
  "blocking_constraints": [],    // infeasible時のみ
  "pending_constraints": [],     // 暫定時のみ非空
  "meta": {"seed": 42, "elapsed_ms": 22, "objective": 9}
}
```

- 連続するコマは1つの勤務ブロックに**自動マージ**して出力（6行ではなく1行）。
- `pending_constraints` が非空 → `shift_status="provisional"`（暫定版）。
- `infeasible` 時は `blocking_constraints` に「必要N名に対し可用M名」を簡易診断。

---

## 不変条件チェック（SolverOutput.validation）

「良いシフト＝**不変条件ゼロ違反** ＋ スコア高」。最適化（スコア）とは別レイヤーで、
**守られるべき不変条件**をソルバー出力から**独立に再検算**する（`src/solver/validator.py`）。

- **availability は Hard・厳格**: 希望を1件も出していない人は**出勤不可**（present=0全コマ）。
  足りなければ穴は穴として出す（headcountはSoft）。＝「入れない人を入れる」を原理的に起こさない。
- バリデータの違反（0が正常・あればバグ）: `out_of_availability` / `double_booking` /
  `out_of_hours` / `invalid_id`。
- 要注意（運用警告）: 希望未提出スタッフ一覧（配置対象外＝希望を集めきれていない）。
- 出力 `SolverOutput.validation`（valid / violation_count / violations / warnings）。④画面に表示。

---

## 評価指標（SolverOutput.evaluation）

完成シフトを多角的に評価する（solved時）。`engine._evaluate()` が集計。

| 指標 | 内容 |
|---|---|
| 充足スコア | (必要−不足)/必要×100（100点満点） |
| ポジション別充足率 | position_coverage（required/filled/rate） |
| スタッフ別 | staff_stats（出勤コマ/出勤日数/希望枠/消化率） |
| 公平性 | 出勤コマ数の 最小/最大/平均（開きが小さいほど公平） |
| 希望消化率 | 出した枠のうち実際に入った割合（assigned/offered） |
| ソフト違反 | separate等のソフト制約が破られた件数 |

> 注: `time_preference`/`desired_workdays` 等の「希望合致率」を厳密に出すには、それらの
> ソフトハンドラ実装が前提（現状ソルバーは headcount/availability/separate のみ）。

---

## ファイル

| ファイル | 役割 |
|---|---|
| `src/solver/slots.py` | スロット展開・時刻計算 |
| `src/solver/context.py` | SolverContext（変数置き場・罰金リスト） |
| `src/solver/engine.py` | 変数組み立て → 求解 → SolverOutput 生成 |
| `src/handlers/__init__.py` | type名 → ハンドラ辞書（L2の登録先） |
| `src/handlers/builtin.py` | 3タイプのハンドラ実装 |
| `src/api/routes_solver.py` | `POST /solver/run` |
| `tests/test_solver.py` | 9ケースの自動テスト |

---

## 設計ルールの遵守

- **ソルバー本体は無改修**: CpModel/CpSolver はブラックボックス。変えるのはハンドラのみ。
- **Hard/Softの厳守**: headcount/availability は絶対遵守、separate は罰金（解を妨げない）。
- **weightクリップ**: 50〜1000 はモデル（`_SoftParams`）側で既に強制。

---

## 既知の制限（最小版ゆえ）

| # | 制限 | 今後 |
|---|---|---|
| 1 | 対応は3タイプのみ | 残り13タイプのハンドラを順次追加（L2で自動生成も） |
| 2 | min_rest_interval / break / 役職・スキル要件は未対応 | ハンドラ追加で対応 |
| 3 | policy_mode は目的関数に未反映 | wishes/cost/balance で重み配分を変える拡張余地 |
| 4 | 充足不能診断は近似（厳密な不能証明ではない） | 必要なら IIS 風の絞り込みを検討 |
