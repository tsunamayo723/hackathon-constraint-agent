# 制約管理エージェント｜ハッカソン引き継ぎ資料

> このファイルは、別 Claude セッションでハッカソン開発を進めるための **自己完結した引き継ぎ資料** です。
> 元になった姉妹プロダクト(AIシフト自動作成アプリ)のリポジトリ・コンテキストには依存しません。
> 姉妹プロダクトで構造検証まで通った設計を、ドメイン中立に正規化して転記しています。
> 最終更新: 2026-05-26

---

## 0. このプロジェクトは何か(30秒サマリ)

**自然言語の定性的な制約を、最適化ソルバーが食える数式(type付きJSON → ハンドラ → ソルバーAPI)に変換する汎用エージェント。**

ハッカソンのコア価値:
> AIが新しい要件を検出 → 自分で処理ロジック(ハンドラ)を書く → テストする → 動いたら人間に承認を求める、という**自律エージェントの振る舞い**が成立すること。

デモドメインは **人員シフト割当**(20〜30名規模の飲食店・スーパー、14日程度、期間上限31日が目安)。

---

## 1. 最重要の前提:姉妹プロダクトとは完全に切り分ける

- 当初は「姉妹プロダクト(シフトアプリ)に後から API で組み込む」構想だったが、**それをやるとハッカソン要件(自律性・自己拡張)を薄める**ため、**API連携は見送り、完全に独立したプロダクトとして開発する**(2026-05-26 決定)。
- したがって以下は**持ち込まない**(混同しないこと):
  - 認証 / RLS / 招待トークン / マルチテナント(`store_id` 等のテナント分離)
  - 「機密備考を24時間で物理削除」「外部送信禁止」「クライアント非保持」等のプライバシー規約
    - ※ 姉妹プロダクト固有の制約。**むしろ本ハッカソンは学習ループでデータを蓄積したいので逆方向**。本番個人情報は使わず**合成データ**で回す前提なら問題なし。
  - 広告モデル / 無料・有料プラン境界 / 既存UI画面 / middleware
- ソルバーは **Google OR-Tools(CP-SAT)** を採用(姉妹プロダクトは Deno 局所探索だったが、独立するので縛られない)。

---

## 2. 構成要素(6つ)と自動化レベル

| # | 要素 | 役割 |
|---|---|---|
| 1 | Gemini パーサ | 自然言語 → `{type, params}` JSON 変換。既知type一致判定/未知type検出/マスタ照合での正規化 |
| 2 | type辞書 | 各typeのJSONスキーマ定義。「同typeなら同構造」を厳守(§4 に初期セット) |
| 3 | マスタ | カテゴリ値の正規化辞書(例:別名統合)。type辞書はID参照のみ持ち、本体はテーブル管理 |
| 4 | ハンドラ辞書+関数 | typeごとの「JSON → ソルバーAPI翻訳係」。新typeはAIが1回だけ生成し永続登録、運用時は登録済みを呼ぶだけ |
| 5 | ソルバー | OR-Tools等の汎用エンジン。変数+不等式から最適解。本体は改修しない(§5 にI/O) |
| 6 | AIエージェント(管理人) | 未翻訳備考のクラスタリング/新type・スキーマ・ハンドラ生成/テスト生成・検証/人間承認依頼 |

### 自動化の階層(採否)

| 階層 | 内容 | 採否 |
|---|---|---|
| L1 | JSONスキーマ拡張提案(マスタ追加のみ) | ✅ 含む |
| **L2** | **ハンドラ関数の自動生成(コード生成・テスト・承認)** | ✅ **ここまでがコア** |
| L3 | ソフト制約の重み自動調整 | ⏸ 余裕があれば |
| L4 | 目的関数の修正 | ❌ 対象外 |
| L5 | ソルバーアルゴリズムの修正 | ❌ 非現実的 |

**L1 と L2 の決定的差**:L1だけだとマスタに名前が増えるだけでハンドラが無く処理できない。L2まで行くとAIがハンドラコードまで生成・テスト・承認を経て自動組込でき、人手改修なしで新制約に対応=「自律エージェント」として成立する。

---

## 3. データフロー

```
[自然言語入力]
   ↓ Gemini Flash(安価・高頻度)
[JSON変換 {type, params}]
   ↓ type照合
 ├─ 既知 → ハンドラ辞書から関数取得 → 実行
 └─ 未知 → AIエージェント(管理人)起動
            ↓ Gemini Pro(高品質・低頻度)
            クラスタリング → 新type/スキーマ/ハンドラ生成
            ↓
            サンドボックスで自動テスト
            ↓
            人間承認(自信度に応じてゲート)
            ↓
            ハンドラ辞書に永続登録
   ↓
[ハンドラ関数が ソルバーAPI を呼ぶ]  例: model.Add(x[A][d]+x[B][d] <= 1)
   ↓
[solver.solve()]
   ↓
[最適解 → シフト表に整形]
   ↓
[ユーザーフィードバック(次元別評価)]
   ↓
[学習・改善ループ:soft重み調整/怪しいハンドラのフラグ/矛盾type検出]
```

**モデル階層化(コスト最適化)**:NL→JSONは Flash(毎回)、ハンドラ生成・自信度評価・テスト生成は Pro(新type登場時のみ=稀)。LLM as a Judge(Flash翻訳→Proが検証→NGなら書き直し)はオプション。

---

## 4. type辞書(スキーマレジストリ)初期セット

### 表記ルール

- 各 type は `{ type, params }` のタグ付きユニオン。**同じ type は必ず同じ params 構造**。
- `class` … `hard`(ソルバーが絶対遵守)/ `soft`(罰金変数で表現、目的関数で最小化)。
- ID系(`person_id` 等)の値レベル正規化は**マスタ**側が担当。type辞書はID参照のみ。
- `weight`(soft用) … **50〜1000 に必ずクリップ**してソルバーへ渡す(NL→数値変換の暴走・プロンプト注入対策)。

### グローバル設定(制約ではなく実行フレーム)

個別レコードではなくソルバー実行全体の枠。`spec.frame` に1つだけ持つ。

| キー | 構造 | 役割 |
|---|---|---|
| `period` | `{ start: date, end: date }` | 対象期間(上限31日が目安) |
| `operating_window` | `{ open:"HH:MM", close:"HH:MM", slot_minutes: 30\|60 }` | 時間グリッド。枠外割当を禁止 |
| `policy_mode` | `"wishes" \| "cost" \| "balance"` | soft群の重み配分プリセット(希望優先/コスト優先/公平優先) |

### Hard 制約 type(8種)

```
### type: headcount_requirement
- class: hard
- 説明: ある時間帯・ポジションに必要な人数
- params: { slot_label, time_start:"HH:MM", time_end:"HH:MM", position_id, count:int }
- 例: 「ランチ(11:00–14:00)のホールに4名」
- handler出力(CP-SAT例): 各スロットtで Σ_person x[person][position][t] == count

### type: role_requirement
- class: hard
- 説明: あるポジションの必要人数のうち特定役職を最低何名(ポジション内の交差制約)
- params: { slot_label, position_id, role_id, count:int }
- 例: 「ホール4名のうち1名はリーダー」

### type: skill_requirement
- class: hard
- 説明: あるポジション内で特定スキル保持者を最低何名
- params: { slot_label, position_id, skill_id, count:int }
- 例: 「ホール内にレジ可を1名」

### type: availability
- class: hard
- 説明: その人が勤務可能な時間帯。枠外には割当不可
- params: { person_id, date, start:"HH:MM", end:"HH:MM" }
- 例: 「Aさんは11/1は10:00–15:00だけ可」

### type: min_rest_interval
- class: hard
- 説明: 連続勤務日の終業〜翌始業の最小空き時間
- params: { hours:int }
- 例: 「終業から次の始業まで11時間空ける」

### type: break_rule
- class: hard
- 説明: 一定時間以上の勤務に休憩を自動付与(複数段は配列で)
- params: { threshold_hours:number, break_minutes:int }
- 例: 「6h以上で45分、8h以上で60分」

### type: mentor_pairing
- class: hard
- 説明: 新人だけのスロットを禁止し、熟練/一般を必ず同席
- params: { newbie_role_id, requires_role_ids:[role_id...] }
- 例: 「新人だけの時間帯を作らない」

### type: demand_adjustment
- class: hard
- 説明: 特定日の必要人数の増減(繁忙/閑散)。targetで役職/スキル単位の増減も可
- params: { date, slot_label, position_id, diff:int, target?: { kind:"role"|"skill", id } }
- 例: 「11/3のランチ・ホールを+1、うちリーダーも+1」
```

### Soft 制約 type(8種)

```
### type: separate
- class: soft
- 説明: 2名を同一スコープに同時配置しない(できれば避ける)
- params: { person_a, person_b, scope:"day"|"slot", weight }
- 例: 「AさんとBさんは同じ日に入れないで」
- handler出力(CP-SAT例): 各スコープで penalty >= x[a]+x[b]-1、目的関数でΣ(penalty*weight)を最小化

### type: pair_together
- class: soft
- 説明: 2名をできるだけ同じスコープに(引き継ぎペア等)
- params: { person_a, person_b, scope:"day"|"slot", weight }

### type: prefer_person
- class: soft
- 説明: 特定の人をできるだけ多く配置
- params: { person_id, weight }

### type: avoid_person_slot
- class: soft
- 説明: 特定の人を特定スコープにできるだけ入れない
- params: { person_id, scope:"day"|"slot", target?, weight }

### type: time_preference
- class: soft
- 説明: 個人の時間帯選好(できればこの時間帯)
- params: { person_id, preferred_start?:"HH:MM", preferred_end?:"HH:MM", weight }

### type: limit_consecutive
- class: soft
- 説明: 連続勤務日数の偏りを抑える
- params: { person_id?:ID|null, max_consecutive_days:int, weight }   // null=全員

### type: fairness
- class: soft
- 説明: 出勤回数/時間の偏りを最小化(分散最小化)
- params: { dimension:"shifts"|"hours", weight }

### type: desired_workdays
- class: soft
- 説明: 本人の希望出勤日数レンジ
- params: { person_id, kind:"range"|"as_many"|"as_few"|"none", min?:int, max?:int, weight }
```

> 初期辞書 = **Hard 8 / Soft 8 = 16 type**。「シフトの soft 制約は 10〜15 種で 9 割カバー」という実地の見立てに沿う。
> これ以外の備考はパーサが `is_new_type: true` で検出 → 管理人(L2)の自律生成ルートへ。
> = **コールドスタート用の合成データは、この16typeを母体に生成すればよい**。

---

## 5. ソルバー入出力スキーマ

### 入力:制約仕様書(parse結果+マスタ+フレーム)

```json
{
  "frame": {
    "period": { "start": "2026-11-01", "end": "2026-11-14" },
    "operating_window": { "open": "10:00", "close": "22:00", "slot_minutes": 30 },
    "policy_mode": "wishes"
  },
  "masters": {
    "persons":   [{ "id": "p1", "name": "Aさん", "role_id": "r_general", "skill_ids": ["sk_cashier"] }],
    "positions": [{ "id": "pos_hall", "name": "ホール" }],
    "roles":     [{ "id": "r_leader", "name": "リーダー" }],
    "skills":    [{ "id": "sk_cashier", "name": "レジ" }]
  },
  "constraints": [
    { "type": "headcount_requirement",
      "params": { "slot_label": "ランチ", "time_start": "11:00", "time_end": "14:00",
                  "position_id": "pos_hall", "count": 4 } },
    { "type": "separate",
      "params": { "person_a": "p1", "person_b": "p2", "scope": "day", "weight": 600 } }
  ]
}
```

- `constraints[]` は **type辞書に登録済みのtypeのみ**。未知typeはソルバー手前で管理人ルートが解決済みであること。
- マスタはID解決のため同梱。ソルバーはID整合のみ検証し、値の正規化はしない。

### 出力:解(割当)+ 警告

```json
{
  "status": "solved",                 // "solved" | "infeasible" | "timeout"
  "meta": { "seed": 42, "elapsed_ms": 5120, "objective": 1830 },
  "assignments": [
    { "date": "2026-11-01", "person_id": "p1", "position_id": "pos_hall",
      "start": "10:00", "end": "15:00",
      "break_start": "13:00", "break_end": "14:00",
      "locked": false }
  ],
  "warnings": [
    { "type": "understaffed", "date": "2026-11-03", "time": "21:00", "shortage": 1 }
  ]
}
```

- 休憩なしの割当は `break_start` / `break_end` を **キーごと省略**(`null` を入れない)。
- `locked: true` の割当は再計算時も動かさない(人手固定の尊重)。
- `warnings[].type` … `understaffed` / `interval_violation` / `mentor_absent` / `role_absent` 等。

### 充足不能時(infeasible)の返却

空配列を返さず、**どのHard制約で詰まったか**を返す(UIが「11/3の21時台が1名足りません」と具体表示できるように)。

```json
{
  "status": "infeasible",
  "blocking_constraints": [
    { "type": "headcount_requirement",
      "where": { "date": "2026-11-03", "slot_label": "ディナー", "position_id": "pos_hall" },
      "detail": "必要4名に対し可用3名" }
  ]
}
```

### エンジニアリング要件(非機能)

- **8秒フェイルセーフ**:超過したら安全に打ち切り `status:"timeout"`+暫定解 or `blocking_constraints` を返す。探索ステップごとに経過時間チェック。
- **決定性**:`seed` 固定で同一入力→同一出力(デモ再現性・デバッグ容易性)。`meta.seed` に実値を出力。
- **soft重み**:`weight` は受領時に **50〜1000 へクリップ**してから目的関数へ。
- ソルバー本体は型・スキーマで保護された入力のみ受け取り、未検証JSONを直接食わない。

---

## 6. 信頼できる自動化(安全網)

「ハンドラ生成の精度劣化」リスクへの対処。L2を商用品質に近づける肝。

### 翻訳精度の階層(Tier)

| Tier | 例 | 対処 |
|---|---|---|
| 1: きれい | AとBは同日NG → `x[A][d]+x[B][d]<=1` | 自動承認OK |
| 2: 分解可能 | なるべく公平に → 分散最小化 | テスト通過で承認 |
| 3: 無理あり | 「なるべく離す」を強制ルール化 | 自信度低→人間レビュー |
| 4: 翻訳不能 | 「臨機応変に」「雰囲気を悪くしない」 | エスカレーション |

### 防御メカニズム

- **A. 自信度スコアリング**:ハンドラ生成時に `confidence` と `concerns` を出力。
  ```json
  { "handler": "...", "confidence": 0.65, "concerns": ["「なるべく」をハード制約として扱った"] }
  ```
- **B. ソフト制約化**:無理に `<=1` にせず罰金変数を導入(「絶対ダメ」でなく「できれば避けて」を表現)。
- **C. 自動テスト生成**:期待動作のテストも同時生成。例「AとBが同日→penalty増/別日→penalty=0」。不通過なら却下。
- **D. エスカレーション**:翻訳不能は潔く人間へ(「外部データが必要なため翻訳できません」)。
- **E. 監査ログ**:誰のどの承認で何が変わったかを追跡可能に。

> **設計の核心(なぜ承認ゲートが要るかの論拠)**:完全自動のスキーマ進化は (1) ソルバーが新パラメータの意味を解釈できない、(2)「離す」と「離れて配置」等の重複登録を止められない、(3) 新制約が"正しく動いているか"の評価正解がない、という3点で**商用品質に届かない**。だからこそ **テスト+自信度+人間承認の安全網** でL2を成立させにいくのが本プロダクトの主張。

### 3層バリデーション(安全網の実装パターン)

姉妹プロダクトで使った「壊れた値の混入」防止の3層を流用:
1. **スキーマ検証**(Zod等):パーサ出力JSONを型検証してから受ける。
2. **値域CHECK**:`policy_mode` 列挙・`slot_minutes`(30/60)・`weight`(50–1000) 等をDB/コードの二重で強制。
3. **マスタ照合エラー**:未知のID/カテゴリ値は弾く(正規化できない値を通さない)。

---

## 7. フィードバックループ(まわす)

- **次元別フィードバック**(帰属問題対策):総合点1つでは原因特定不能なので観点別に評価をもらう(公平性/希望反映/繁忙期対応/納得感)。上級者向けに「問題箇所をクリックで指摘」も。
- **学習対象**:ソフト制約の**重み調整**(★ハッカソン採用候補、線形回帰/ベイズ最適化で実装可)。ハンドラ品質ランキング・矛盾検出は余裕があれば。完全再生成判定は対象外。
- **コールドスタート**:初期は**合成データ**で起動 → 実データで上書き → ハイブリッド。合成データは §4 の16typeを母体に生成。

---

## 8. ハッカソン審査ポイントとの対応

| 審査軸 | 対応 |
|---|---|
| AIエージェントが価値の中心 | 自然言語理解+コード生成+承認管理が中核 |
| 自律的な振る舞い | 未知typeを自分で検出→生成→検証→提案 |
| AIである必然性 | コード生成と意味解釈はAIでないと不可能 |
| つくる | 制約管理エージェントそのもの |
| まわす | CI/CD的にハンドラ・重みを継続改善(自走DevOpsサイクル) |
| とどける | Google Cloud(Vertex AI / Cloud Functions)へデプロイし汎用APIとして提供 |

---

## 9. 用語集

| 用語 | 意味 |
|---|---|
| type | JSONレコードの構造を示す目印(タグ付きユニオン) |
| ハンドラ関数 | JSONをソルバーAPI呼び出しに翻訳する関数 |
| ソルバー | 制約を満たす最適解を計算する汎用エンジン(OR-Tools等) |
| マスタ | カテゴリ値の正規化辞書 |
| サンドボックス | 生成コードを本番影響なしで試す環境 |
| ソフト制約 | 「絶対ダメ」でなく「なるべく避ける」程度の制約(罰金変数で表現) |
| 自信度スコア | AIが自身の出力の確信度を数値化したもの |
| モデルカスケード | 役割ごとに別モデルを使い分けるパターン(Flash↔Pro) |
| LLM as a Judge | LLMにLLM出力を評価させるパターン |
| 帰属問題 | スコアからどの要素が原因か特定できない問題 |
| コールドスタート問題 | 初期データ不足で学習が動かない問題 |

---

## 付録A:デモ用「未知type」(確定済み・2026-05-27)

既存16typeには含まれない、自然に発生する制約として以下3つを採用。

| type名 | 入力例 | 構造上の理由 |
|---|---|---|
| `recurring_day_off` | 「毎週水曜は習い事があって入れません」 | **曜日パターン展開**。`availability`は個別日付指定だが、これは対象期間の全曜日一致日に自動展開する |
| `max_late_shift_count` | 「22時以降まで働くシフトは月3回までにして」 | **集計型カウント制約**。条件付きシフトの個数を数えて上限を設ける構造。既存typeに相当なし |
| `exam_period` | 「12/10〜20が試験期間なので極力入れないで」 | **期間限定のsoft重み変動**。`desired_workdays`は月全体の希望だが、これは特定日付範囲のみ出勤最小化 |

**デモシナリオ(3本立て)**:
1. 「毎週水曜は習い事」→ `recurring_day_off` 未知検出 → L2フロー → 承認 → 登録 → 再計算
2. 「22時以降は月3回まで」→ `max_late_shift_count` 未知検出 → L2フロー → 承認 → 登録 → 再計算
3. 「試験期間は極力入れないで」→ `exam_period` 未知検出 → L2フロー → 承認 → 登録 → 最終シフト完成

---

## 付録B:開発の最短着手順(推奨)

1. **§4 の16type辞書をコード化**(type名+paramsスキーマ=Pydantic)。ここが全ての土台。
2. **§5 のソルバーI/Oを固定**し、OR-Tools で `headcount_requirement` + `availability` + `separate` の3typeだけ通る最小ソルバーを作る(縦に1本通す)。
3. **Geminiパーサ**:既知16typeへの分類+未知検出(`is_new_type`)まで。
4. **L2の自律生成フロー**:付録Aの3typeを順番に検出→ハンドラ生成→自動テスト→承認→登録まで通す=**デモの主役**。
5. 余裕があれば L3(重み調整)とフィードバックUI。
