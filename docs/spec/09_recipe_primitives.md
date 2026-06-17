# 仕様書 09 — レシピ（操作×選択子）プリミティブ

*最終更新: 2026-06-17（生成フローのレシピ化まで実装）*

---

## なぜ（背景）

AIに生のPythonハンドラを書かせると、API誤用（CP-SAT変数をPythonの`if`で評価する等）や
存在しないキー参照でソルバーが落ちる。サンドボックスのスモークテストは小窓のため取りこぼす。

→ **AIに生のコードを書かせず、安全な「操作×選択子」の組み合わせ＝レシピ（データ）を出させ、
信頼できる固定インタプリタが制約に変換する**。これでAPI誤用バグが構造的に発生しなくなり、
AIコードの `exec` も不要になる（安全性も向上）。

詳細な意思決定は `docs/99_decisions_log.md` 2026-06-17 を参照。

---

## ファイル

| ファイル | 役割 |
|---|---|
| `src/solver/recipe.py` | `Recipe`モデル ＋ `apply_recipe()` インタプリタ ＋ `validate_recipe()`（in-process検証） |
| `src/agents/recipe_agent.py` ＋ `prompts/recipe_gen.txt` | 未知typeをレシピとして設計（Pro） |
| `src/api/routes_admin.py` | `/generate`（レシピ設計＋検証）・`/approve`（`_fill_recipes_and_store`） |
| `src/solver/engine.py` | dynamic_constraintsが`operation`付きなら`apply_recipe`で適用（execしない） |
| `tests/test_recipe.py` / `test_recipe_flow.py` | 5操作の翻訳（7件）／生成フロー（7件） |

---

## 操作（5個）

| 操作 | 種別 | 意味 | 内部実装（ctx API） |
|---|---|---|---|
| `forbid` | Hard | 選択枠に入れない | `work_day==0`（終日）/ `present==0`（時間帯） |
| `require` | Hard(best-effort) | 選択範囲に最低 `count` 人 | 不足変数＋`add_shortage`（足りなければ穴を正直に計上） |
| `limit_count` | Hard | 対象時間帯に入った「日数」を期間内 `max` 回まで | 日ごと active(OR) を作り `sum<=max` を期間ごと |
| `penalize` | Soft | 条件成立で `weight` 罰金 | `add_penalty`。pairは同席変数 z |
| `prefer` | Soft | 選択枠になるべく入れる | 非割当に `add_penalty`（入ると得） |

> Hard/Softは**操作の種類で固定**（forbid/require=Hard、penalize/prefer=Soft）。
> 「なるべく」を誤ってHardにする事故を構造的に防ぐ（CLAUDE.mdの設計ルール）。
> `weight` は 50〜1000 にクリップ。

## 選択子

| 軸 | 値 |
|---|---|
| 誰 `who` | person / role / skill / pair(2人) / all |
| 時 `when` | date / date_range / weekday(0=月..6=日) / always |
| 時間帯 `band` | window(`time_start`〜`time_end`) / all_day |
| 場所 `where` | position / any |
| 量 | count / max / weight / period(total/week/month) |

**1ルール = 1操作 ＋ 選択子の組み合わせ**。AIの仕事は「操作を選び選択子の値を埋める」だけ。

---

## type → レシピ 対応（網羅確認）

**✅ レシピで表現（約13型）**

| type | レシピ |
|---|---|
| recurring_day_off | forbid(person, weekday, all_day) |
| exam_period | penalize(person, date_range, all_day, weight) |
| max_late_shift_count | limit_count(person, band=window 22:00-, max, period=month) |
| headcount_requirement | require(all, band=window, where=position, count) |
| role_requirement / skill_requirement | require(role|skill, …) |
| separate / pair_together | penalize|prefer(pair, …) |
| prefer_person / time_preference / avoid_person_slot | prefer|penalize(person, …) |
| desired_workdays / demand_adjustment | prefer / require の応用 |

**⚠️ レシピ非対応（約5型・固定の手書き専用部品＝T3）**
`min_rest_interval`（前日終業〜翌始業）/ `limit_consecutive`（連勤）/ `break_rule`（休憩挿入）/
`mentor_pairing`（新人のみ禁止）/ `fairness`（全体の偏り）。`availability` は基盤として特別扱いを維持。

---

## 生成フロー（2026-06-17 実装済み）

```
[未知type検出（T1）] → /generate
   RecipeAgent(Pro) がレシピ（操作×選択子）を設計 → validate_recipe で
   小シナリオに当てて検証（execしない）→ suggested_recipe / test_results を格納
[管理者が承認] → /approve（レシピ方式）
   ParamsAgent(Flash) が各人の原文からレシピを埋める → 本人IDはoccurrenceで上書き
   → dynamic_constraints に {type, params:<完成レシピ>} を保存
[再計算（run-stored）]
   engine が operation付きparamsを apply_recipe で適用 → シフトに反映（暫定→確定）
```

旧Python方式（HandlerAgent＋exec＋subprocess sandbox）は後方互換で残すが、既定はレシピ方式。
レシピ方式では**任意コードのexecが無い**ため subprocess sandbox 不要・安全。

## データ実現可能性チェック＝正直な拒否（2026-06-17 実装済み）

RecipeAgent が生成前に「この部品セットで表現できるか」を判定する（分かったフリをしない）。
表現できない場合は `expressible=false` ＋ `reject_category` を返し、**レシピを作らず**正直に拒否する。

| reject_category | 例 |
|---|---|
| `negotiation_dependent` | 「他に休みたい人がいれば私は出ます」（他者の希望に依存） |
| `history_dependent` | 「先月と同じシフトにして」（過去の実績が必要） |
| `missing_data` | 「車で来られる日だけ夜遅くOK」（手持ちに無いデータ） |
| `subjective` | 「雰囲気の良いシフトに」（数値化できない） |
| `advanced_logic` | 「Aさんが入る日だけBさんも」（部品で表せない高度な条件） |

`/generate` が `expressible=false` を受けると `PendingTypeRequest.expressible/reject_category` に格納し、
⑤画面が「❌ このルールは表現できません（理由：…）」＋却下導線を出す（承認は出さない）。

## まだ未実装（次のステップ）

1. **チャット入力整備（Flash）**: 曖昧な選択子（早番=何時？）を聞き返して確定（意味の取り違え対策）。
   対話の置き場は**デモ主役UI（T9）**が自然（バッチCSVは本人不在のため）→ T9とセットで実装。
2. **③/⑤画面のレシピ表示の磨き込み**＋デモ主役UI（T9・Vite+React）。
