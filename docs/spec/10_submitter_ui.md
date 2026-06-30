# 仕様書 10 — 提出者の主役UI（Vite + React + Tailwind）

*最終更新: 2026-06-20（提出画面の作り直し：日ごとnote翻訳＋30分刻み時間指定＋デモデータ投入）*

---

## なぜ（背景）

デモの見せ方を「全備考にAIが順番に話しかける」から、**1人の提出者の体験**に変える。

> 自分のシフト希望（時間）と備考を出す → シフト作成 → **note考慮あり/なし**を比較し、
> 「自分の要望も、店舗の要望も通った」と1画面で確認できる。

この提出者画面だけは操作感が要るので **Streamlitではなく React** で作る
（裏方＝CSVアップ・シフト実行・管理者承認は Streamlit 据え置き）。

---

## 構成（開発時はサーバー2〜3つ）

```
[React 提出者UI :5173]  ──fetch──>  [FastAPI :8001]  ──>  OR-Tools / Gemini(Flash)
[Streamlit :8501（裏方）] ─────────────^   （デモ投入・CSVアップ・シフト実行・管理者承認）
```

- FastAPIは **:8001**（Streamlit裏方と同じインスタンスを共有）。React開発サーバーからのアクセス用に **CORS** を許可（`main.py`）。
- フロントの接続先は `VITE_API_BASE`（既定 `http://localhost:8001`）。本番(T6)では Vite をビルドし、配信元の origin を CORS に足す。

### フロント（`frontend/`）

| ファイル | 役割 |
|---|---|
| `src/api.ts` | FastAPIへのfetchラッパ（`getMasters`/`getFrame`/`getDemoWishes`/`clarifyNote`/`submitPreview`） |
| `src/types.ts` | バックエンドと共有する型（`DayWish`/`WishMap`/`DemoWishes`/`NoteResultItem`/`PreviewResult`…） |
| `src/lib/shift.ts` | 日付・時間ヘルパー（カレンダー生成・`slotOptions`30分刻み・`bandFor`プリセット・`emptyWish`） |
| `src/components/PersonPicker.tsx` | ①本人選択（マスタから） |
| `src/components/WishCalendar.tsx` | ②カレンダー月表示。日ごと **出勤可/休み・開始終了を30分刻みで指定・その日のメモ** |
| `src/components/NoteChat.tsx` | ③備考（毎週/期間のルール）＋AIチャット（Flash・`/chat/clarify-note`）。`initialNote` で初期備考 |
| `src/components/ResultCompare.tsx` | ⑤比較（自分＋店舗＋**日ごとnoteのAI翻訳結果**） |
| `src/App.tsx` | 全体フロー（デモ/手動トグル・①〜④の番号つきセクション） |

スタック: Vite 8 / React 19 / TypeScript 6 / Tailwind v4（`@tailwindcss/vite` プラグイン）。

---

## 画面フロー

```
① あなたは誰？        マスタからドロップ（認証は作らない＝不要な実装を持ち込まない）
   └ トグル：「デモの希望を読み込む」（人を選ぶと希望＋備考が自動入力）/「自分で記入」
② 希望カレンダー       日をクリック→ 終日OK/早番/遅番/休み・開始終了を30分刻みで指定・その日のメモ
③ 備考＋AIチャット     毎週/期間のルールを Flash が確認→確定でレシピ取得／表現不可は正直に拒否
④ シフトを作成して比較  /submit/preview を叩く
⑤ 比較表示            自分の差分（水曜が休みに）＋店舗の充足（必要人数100%）＋AIの備考解釈（✅🆕⚠️）
```

希望→時間帯: 終日OK=営業時間まるごと / 早番=前半 / 遅番=後半 / 休み=枠なし / **時間指定=30分刻みドロップダウン**。

---

## デモデータ（10人 × 10日 × 3パターン）

入力負担を減らすため、提出者が大量に手入力しなくても始められるよう **コンパクトなデモデータ**を用意（`data/demo/`）。
生成は `scripts/gen_demo_data.py`（再生成可能）、肝の検証は `scripts/verify_demo_data.py`。

| key | 内容 |
|---|---|
| `cafe_easy` | カフェ・余裕あり（主役）。`毎週水曜NG`が反映され店舗も充足100%が綺麗に見える |
| `diner_tight` | 定食屋・必要人数が多くタイト。制約の効き目が見える |
| `izakaya_late` | 居酒屋・ディナー偏重＆遅番多め。深夜系ルールが映える |

- 期間 **2026-11-02〜11-11（10日・水曜が2回：11/04, 11/11）**、営業 11:00-22:00・30分スロット。
- 各 `meta.json` に `frame` と `demo_submitter`（主役 p01 と overall_note「毎週水曜は習い事…」）を持つ。
- **ソルバー実測検証済み**: 3パターンとも before で p01 が水曜に入り、after（水曜forbid）で消え、店舗の不足は 0。

---

## 新規エンドポイント

### `GET /setup/demo-patterns`（`routes_setup.py`）
投入できるデモパターン（`key`/`label`/`description`）の一覧。Streamlit・提出者UIのプルダウン用。

### `POST /setup/load-demo`（`routes_setup.py`）
`{pattern}` を受け、`data/demo/<pattern>/` のCSV＋`meta.json`を**一括登録**（マスタ＋営業情報＋必要人数＋出勤希望）。
既存の方針・出勤希望・承認キューはクリアしてから投入（クリーンな状態でデモ開始）。`meta` は `save_demo_meta` で保持。

### `GET /submit/demo-wishes`（`routes_submit.py`）
`?person_id=` の希望（`date`/`start`/`end`/`note`）を返す。投入がデモデータでその人が主役なら `overall_note` も返す。
提出者UIの「デモの希望を読み込む」でカレンダーを自動入力するのに使う。

### `POST /chat/clarify-note`（`routes_chat.py`・Flash）
提出者の備考（毎週/期間のルール）の曖昧さを対話で確認する。詳細は `docs/spec/07_gemini_agents.md` の ChatAgent 節。

- body: `{note, history:[{role:"user"|"ai", text}]}`（ステートレス）
- 返り: `ChatTurn`（`reply`/`needs_clarification`/`understood_summary`/`is_rule`/
  `suggested_type_name`/`expressible`/`reject_category`/`recipe_json`）

### `POST /submit/preview`（`routes_submit.py`・非破壊）

1人の提出者の希望（日ごとnote付き）＋備考レシピで、**備考を考慮しない/する**の2通りでシフトを解いて比較する。

- body: `{person_id, wishes:[{date,start,end,note?}], recipe:<レシピ>|null, type_name?}`
- 処理:
  1. 本人の希望（生）で stored availability を差し替え（他スタッフはそのまま）
  2. `before = solve(承認済みdynamicのみ)` … **note考慮なし**（生の希望）
  3. **日ごとnoteを翻訳**（②CSV経路と同じ `NoteAgent` パイプラインを再利用）:
     - ✅ **時間補正** … その日の枠を狭めて after の解に反映
     - 🆕 **新ルール候補** … 管理者の承認キューへ流す（L2へ橋渡し。preview では即適用しない）
     - ⚠️ **申し送り** … 表示のみ
  4. `after = solve(承認済みdynamic ＋ overall noteレシピ)` … **note考慮あり**（時間補正＋レシピ反映）
  5. 本人にしぼった差分（removed=休めた / added=入った）と、店舗の充足、note分類を返す
- レシピの本人ID差し込み: `who="person"` なら `person_id` を本人に上書き。
  **検証は p1〜p3 のシナリオで行う**ため、検証用コピーは `person_id="p1"` で当てる
  （本人IDのまま検証すると「対象が居ない」偽陰性になるのを回避）。
- 返り（抜粋）:
  ```
  { note_applied, recipe_applied, notes_adjusted,
    note_results:[{date,note,status,summary,suggested_type_name?}],
    before/after:{status,assignments,coverage_score,shortage_units},
    personal:{ before, after, diff:{removed,added} },
    store:{ before_ok, after_ok, before_coverage, after_coverage } }
  ```
  `store.after_ok = (status==solved かつ shortage_units==0)` ＝「必要人数を満たせた」。

> 非破壊（本人・他スタッフのデータは保存しない）。ただし新ルール候補の承認キュー登録だけは
> 「提出者の要望を管理者に届ける」追記操作として行う。永続的な提出保存は T5(Supabase) で対応予定。

---

## 比較が成立する仕組み（デモの肝）

提出者が水曜も「終日OK」にしておき、備考「毎週水曜は習い事で入れません」を出すと:

- **考慮なし(before)**: ソルバーは水曜にも本人を入れうる
- **考慮あり(after)**: overall noteのレシピ `forbid(person, weekday=水, all_day)` で本人の水曜が消える
- **店舗**: 控えスタッフが水曜を埋めれば充足100%のまま

→ 「自分の要望（水曜休み）」と「店舗の要望（必要人数）」が**両立**しているのが1画面で見える。
日ごとnote（「17時まで」等）は ✅時間補正として after に効き、新種ルールは 🆕 として管理者へ流れる。

---

## なぜ「2幕」に分けるか（提出者UI と L2承認の関係）

- **提出者UI** = 個人の体験。Flash が即翻訳して before/after を見せる（速い・気持ちいい）。
- **L2承認（管理者・Streamlit）** = 自律エージェントの肝。Pro が未知typeのレシピを生成→テスト→**承認ゲート**→登録。
- 提出者の **新種ルールnote** は即適用せず承認キューへ流す（`_register_note_pending`）。
  → 1つの提出体験から「note翻訳」と「未知→L2」が自然に派生し、エンジンは無改修のまま2幕がつながる。

---

## テスト

| ファイル | 内容 |
|---|---|
| `tests/test_demo_load.py` | demo-patterns一覧／load-demo一括投入／demo-wishes（希望＋overall_note）／投入データでの水曜before/after・店舗充足／日ごとnoteの時間補正（NoteAgentモック） |
| `tests/test_chat_clarify.py` | 聞き返し／確定／正直な拒否／入力検証（ChatAgentモック） |
| `tests/test_submit_preview.py` | 水曜が after で消える／控えで店舗充足維持／備考なしは無変化／効かないレシピは未適用／未登録・存在しない人 |

フロントは `npm run build`（`tsc -b && vite build`）で型チェック＋本番ビルドが通ることを確認。

---

## 結果画面・チャットの磨き上げ（2026-06-30）

- **店舗選択(①StoreStep)で営業時間・必要人数を表示**: `/setup/demo-patterns` が `operating_window`＋
  基本編成 `headcounts` を返し、店ごとに違う営業時間（cafe 11–20 / diner 11–23 / izakaya 16–24）と必要人数を選択時に見せる。
- **結果画面(⑤ResultStep)で note の扱いを全件表示**: `store-compare` の `note_results` を「🤖 備考の扱い」で
  ✅時間補正 / 🆕承認待ち / ⚠️申し送り に分類表示し、**無視(unreflected)があれば下部に明示**（「シフトには未反映」）。
- **充足スコア廃止**: 毎回ほぼ100でロジックも分かりにくかった「充足スコア(100点満点)」を React/Streamlit 双方から削除し、
  「必要人数を満たせています／⚠️N コマ不足」の一言に。
- **個人希望チャット(②)の堅牢化**: 反映できない要望は正直に伝え、同内容のラリーは `MAX_USER_TURNS=4` で打ち切る。
  マスタ文脈に**在籍スタッフ＋役職**を載せ、「新人は…」を `who="role"`+role_id で解決できるようにした。
- **承認画面(④)の作り直し相談**: ルールごとの入力欄を**まとめチャット1つ**に統一（`docs/spec/04_admin_workflow.md` 参照）。
