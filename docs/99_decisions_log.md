# 99. 決定事項ログ

時系列で決定事項を記録。新しい決定があれば末尾に追記。

---

## 2026-05-15〜16: 初期構想

- ハッカソン応募を決定
- アイデア3案を比較し、Idea 1「定性情報→JSON→プログラム変換」を採用
- 独立したプロダクトとして開発(疎結合パターンA)とする方針
- L2(ハンドラ自動生成)までを実装範囲とする

---

## 2026-05-25: ドメイン選定

- ドメイン候補を網羅的に検討
  - 看護師シフト、配送ルート、営業案件アサイン、プロジェクトアサイン、新人配属、CSMアサイン、マーケ予算配分、席割り等
- リスクと工数のバランスから **シフト一本で深掘り** に決定
- 看護師シフトを軸に検討開始

---

## 2026-05-26: 方針の大幅変更

- **外部サービスとのAPI連携を見送り**(要件不一致による)
- ハッカソン用は完全に独立したプロダクトとして開発する方針に変更
- 詳細設計の引き継ぎ資料(`docs/01_handover_original.md`)を作成

---

## 2026-05-27: ドメイン最終確定

- ドメインを **飲食店シフト・30名・1ヶ月分** に確定
- 30人規模のリアルさと共感度の高さを重視したため

---

## 2026-05-27: 技術スタック全項目確定

### 言語・フレームワーク
- **採用**: Python + FastAPI + Streamlit
- **理由**: OR-Tools公式サポート最強、AI関連ライブラリ豊富、Claude Code相性良

### デプロイ先
- **採用**: Cloud Run × 2(FastAPI用とStreamlit用)
- **理由**: 業界標準、無リクエスト時0円、60分タイムアウトに余裕

### 永続化
- **採用**: Supabase (PostgreSQL + JSONB)
- **理由**: JSON柔軟性とSQL集計力を両立、管理画面が便利、規約上OK
- **応募前確認事項**: Notion本文での規約再確認

### サンドボックス
- **採用**: Python subprocess + タイムアウト
- **設計**: `Sandbox` インターフェースで抽象化、将来Cloud Run Jobsに差し替え可能
- **理由**: ハッカソンのリスクモデルに十分、実装爆速

### Geminiモデル
- **採用**: Flash + Pro のモデルカスケード + 自信度ベースルーティング
- **自信度評価**: モデル自己申告方式(プロンプト指示)
- **LLM as a Judge**: COULD枠(余裕あれば)

---

## 2026-05-27: 入力フロー設計

- **入力経路**: 構造化データ(CSV)+ 自然言語のハイブリッド構成
- **出勤希望ベース**を採用(従来の希望休ベースから変更)
- **30分ブロック単位**を採用
- **再計算ラリー**: locked戦略をベースに、ユーザー指定lockedもデモでチラ見せ
- **As-Is / To-Be**: ハッカソン版はCSV経由、将来はスタッフUI経由

---

## 2026-05-27: 開発環境整備

- ハッカソン用リポジトリを **独立した場所** に作成
- `C:\projects\hackathon-constraint-agent\` で git init
- Claude.aiでの議論から **Claude Codeへの移行** を決定
- CLAUDE.md + docs/ファイル群を作成

---

## 2026-05-27: デモ用「未知type」3つに確定

- **決定内容**: L2フローのデモで使う未知typeを以下3つに確定
  - `recurring_day_off`（毎週◯曜日は入れない）
  - `max_late_shift_count`（夜遅いシフトは月◯回まで）
  - `exam_period`（試験期間は出勤を減らしてほしい）
- **理由**: 既存16typeと構造が明確に異なる（曜日パターン展開 / 集計型カウント / 期間限定soft重み）。口頭で自然に出てくる言葉で、審査員が「なるほど、これは既存typeでは無理だ」と直感できる
- **影響範囲**: `docs/01_handover_original.md 付録A`、`docs/05_remaining_tasks.md §2`、`CLAUDE.md`

---

## 2026-06-06: 完成版の定義と承認まわりの改修方針

- **完成版の定義（重要）**: シフト生成の入力は「②の全体方針テキスト」だけでなく、
  **出勤希望CSVの日ごと備考（note）もAIが解釈する**ことを完成条件に含める。
  - 構造化（start/end）はAI不要でavailabilityに直変換。
  - note（付いている行だけ）は**バッチでパーサ(Flash)に通す**→追加/修正の制約に展開。
  - **理由**: 30人×30日でnoteを全解釈してもFlashなら月次1回あたり数円オーダーでコスト問題なし
    （試算で確認）。懸念は「呼び出し回数（バッチ化で解決）」であってコストではない。
  - L1（構造化のみ・noteはAI解釈しない）は踏み台であり完成形ではない。

- **承認まわりの出力リッチ化（JSON-first承認）**: UIの前に「データ自体を読んで分かる形」にする。
  未翻訳項目・承認キューに次を追加:
  - `summary`（一言で何のルールか）/ `ai_assessment`（AIの見解・なぜ未知と判断したか）
    / `review_points`（人に確認してほしい点のリスト）
  - **理由**: 生JSON（Swagger）でもサッと承認判断でき、UIは後でそれを表示するだけにできる。
    AI側とUI側を切り分けて進める。

- **クラスタリング**: 同じ `suggested_type_name` は1リクエストに集約し `source_texts` に追記、
  `occurrence_count` を加算。承認はタイプ単位で1回（複雑なembeddingは使わず型名一致で十分）。

- **管理者UI(④ admin.py)**: 上記でデータが読みやすくなった後に実装。JSON表示トグルも付ける。

- **影響範囲**: `docs/spec/04_admin_workflow.md`、`docs/spec/03_parser_io.md`、
  `docs/04_input_flow.md`、`docs/05_remaining_tasks.md`、`src/models/parser_io.py`、`src/models/admin_queue.py`

---

## 2026-06-06: 自然言語入力は2系統（全体方針／日ごとコメント）

- 自然言語→JSONの入力は2パターンある:
  - **(A) 全体の作成方針・横断ルール**（例「新人はキッチン優先」「AとBは別シフト」「毎週水曜休み」）
    → **②画面**（店長が入れる）。**既に拾える**（検証済み: 既知ならマッピング、未知ならL2へ）。
  - **(B) 個別・日ごとコメント**（例「11/5はお迎えで18時まで」）
    → **出勤希望CSVのnote列**（CSV開通時に実装）。
- ②は「CSVコメントの疑似再現」ではなく、(A)専用の本番チャネル。CSV開通前に②を(A)向けに明確化した
  （タイトル「シフト作成の要望」・全体方針のサンプル追加）。
- 検証: 「新人はキッチン優先」→未知 role_position_preference、「ベテランと新人はペア」→既知 mentor_pairing 等。

---

## 2026-06-06: デモフロー（作成者と承認者の分離）

実運用では**作成者（店長）と承認者（サイト管理者）は別人**。デモはこの順が綺麗:

1. **①〜③まで登録 → ⑤で実行** → 既知だけで計算。**未知があれば暫定シフト**（provisionalバッジ＋未反映リスト）
2. 未知タイプの**承認を管理者に依頼**（②送信時に自動でキュー登録済み）
3. **④で管理者がAI生成ハンドラを承認**
4. **⑤で再作成** → 確定シフト

実装状況:
- 1（暫定作成）✅: `run-stored` が pending(未承認) を検出して provisional にする
- 2,3（キュー・承認）✅
- 4（再作成で**実際に反映**）⚠️ **未完**: 承認でハンドラは登録されるが、その制約**インスタンス**
  （例: p01×水曜）が未保存のため、再作成しても新ルールがシフトに反映されない。
  → **A1c**: パーサが未知から候補paramsも抽出して保存し、run-stored が approved な動的制約として適用する必要がある。

### 関連で直したこと
- ①営業情報フォームの初期値をサンプル(2026年11月)に合わせた（期間ミスマッチで人数不足になる事故を防止）
- ⑤に「使う制約の件数・内訳」表示と「方針・出勤希望リセット」ボタンを追加
- infeasibleで詰まり箇所が無いとき、よくある原因（期間外・蓄積・人数）を案内

---

## 2026-06-06: 必要人数の入力＋ソルバーを「常に暫定解を出す」方式に

- **必要人数(headcount)の構造化入力を追加**: ①セットアップに「③必要人数」フォーム
  （時間帯×ポジション×人数）。`POST /setup/headcounts` で保存し run-stored が使う。
  これが無いとソルバーに需要が無く空シフトになる、という穴を塞いだ。
- **headcount を Hard→Soft（不足は減点）に変更**: 人が足りなくても infeasible にせず、
  **不足を最小化した暫定シフトを必ず出力**する（不足1人=5000減点、警告 understaffed）。
  理由: ユーザー要望「パズルが解けなくても暫定の最高得点を出し、そこからラリーで改善」。
- メタに `shortage_penalty` を追加。スコア＝不足減点＋ソフト罰金＋割当数。
- 画面順をデモ動線（設定→出勤希望→要望→計算→承認）に並べ替え。③要望→④計算へ st.switch_page 導線。
- ②要望パースのUIタイムアウトを15→90秒（Gemini応答＋リトライ待ち対策）。
- 残: A1c（承認→再作成で新ルール実反映）。

---

## 2026-06-06: 必要人数の日付指定＋B/Cサンプル複雑化（Phase A）

- **必要人数を特定日付で指定可能に**（ユーザー決定: 曜日でなく特定日付）。
  `HeadcountParams.date`（任意）追加。指定日のみ適用／省略で全日。ハンドラ・①入力・CSV・④表示まで対応。
  - 実装注意: フィールド名 `date` が型 `date` をシャドーし `Optional[date]=None` が壊れる → 別名 `DateType=date` で回避。
- **B/Cサンプル複雑化**: headcounts に時間帯(ランチ/アイドル/ディナー)＋特定日付の上書き行。
  desired_shifts は人ごとに出勤日数・時間帯をばらつかせた。pattern_b headcounts=15行(基本8/日付7)。
- 効果: pattern_b で充足スコア95.7点（不足は上書き日 11/03・11/07 に集中）＝**評価が意味を持つ難易度**に。
- 残（Phase B）: 評価指標の拡充（ポジション別充足/スタッフ別稼働/公平性/出勤希望消化率）。
  ※ time_preference等の希望合致率は該当ソフトハンドラ実装が前提。

---

## 2026-06-06: 「良いシフト」の定義＝不変条件＋検証器（availability厳格化）

- 課題: best-effortソルバーが「実際は入れない人を入れた」シフトを出すと現実に穴が開く（最悪）。
- 「良いシフト」を2層で定義: **不変条件（絶対）** ＋ 最適化（スコア）。良い＝不変条件ゼロ違反＋高スコア＋穴は捏造しない。
- **ユーザー決定**: 希望を1件も出していないスタッフ＝**出勤不可**（無制限フォールバック廃止）。
  → `_apply_availability` を厳格化。穴は穴として正直に出す。
- **シフト検証器（バリデータ）**: `src/solver/validator.py`。出力を生データから独立に再検算し
  out_of_availability/double_booking/out_of_hours/invalid_id を検出（0が正常）。未提出スタッフを要注意警告。
  `SolverOutput.validation` に格納、④に「スコアとセット」で表示。
- テスト: 小テストの想定が「未提出＝不可」に変わるため、p1/p2にフル可用を付与して調整。バリデータのテスト追加。全45緑。
- 検証: pattern_b で valid=True・違反0（＝枠外配置が起きないことを独立に証明）。
- フィールド名 `date` が型 `date` をシャドーする問題（再発）→ solver_io にも別名 DateType を用意。

---

## 2026-06-09: 出勤希望の備考(note)をAIでバッチ解釈（B2b・完成版の定義を達成）

- 日ごと備考(note)を **Gemini(Flash・思考オフ)でバッチ解釈**し、出勤可能枠(start/end)を補正。
  - 「お迎えで17時まで」→ end=17:00、「夕方から」→ start=17:00、「ランチだけ」→ 〜15:00、「午前不可」→ 13:00〜。
  - 時間と無関係な備考は interpretable=false で枠を変えない。
- **コスト対策**: 1件ずつでなく CHUNK_SIZE=40 でまとめて呼ぶ。オンデマンド（③のボタン）で課金タイミングを制御。
  - 実測: 5件を1呼び出し・970トークン・¥0.11。
- 構成: `src/agents/note_agent.py`＋`prompts/note.txt`（NoteAgent）、`POST /setup/interpret-notes`、③画面にボタン。
  元の枠の内側に収まる補正だけ適用（枠は広げない）。
- これで「②方針＋**CSVのnoteもAI解釈**＋未知→生成→承認」という**完成版の定義**を満たした。

---

## 2026-06-09: 未反映note（解釈できなかった日ごと備考）の可視化

- 課題: B2bで解釈できなかった/枠に反映されなかったnoteを件数だけ数えてサイレント無視 → 核「AIは分かったフリをしない」に反する。
- **方針**: 日ごとnoteは件数が多く②の管理者キュー(L2)に流すと溢れる → **L2には送らない**。
  ハッカソンでは「未反映を正直に出力＝要確認の申し送り」で十分（自動解決はしない）。むしろ核の価値を補強。
- 実装: `interpret-notes` が各noteを **✅適用/⚠️未反映** に分類し storage に保存（`get_note_results`）。
  `/setup/summary` に「未反映の備考」を追加。③で✅/⚠️一覧、⑤で「未反映の備考（要確認）」＋スタッフ別詳細に「未反映の希望」列。
  追加のGemini呼び出しは無し（応答の再利用）。reset-constraintsでクリア。
- 検証: 4件→反映2(時間系)/未反映2(ポジション希望・人間関係)。reset後0。

---

## 2026-06-10: デモの核を確定（方針転換あり）＋タスクT1〜T6

- **デモの核（ユーザー言語化）**: 「未知の要望（自然文）を高速処理し、システム改修の手間なく取り込める」を見せる。
  シフトは**少人数×複雑要件で"完全に満たせた"**ことを証明する（規模の大きさでは勝負しない）。
- **方針転換: noteもL2に送る**（06-09の「L2には送らない」を撤回）。
  理由: デモの主役は未知データの高速処理。日ごとの時間補正で表せない「仕組みのルール」
  （毎週○曜NG等）はnote由来でも未知タイプとして検出→ハンドラ生成の対象にする。
  キュー溢れ対策は「同じtype名へのクラスタリング集約」で解決（N件→1キュー）。
- **ハンドラは網羅+予約**: 既知16typeのハンドラは手書き＋テストで網羅（残り13）。
  デモ用未知タイプ3つ（recurring_day_off / max_late_shift_count / exam_period）は辞書に入れず予約。
- **Supabaseはやる。ただしデプロイ(T6)とセットで6月下旬**。storage.py 1ファイルに保存口を
  集約済みなので移行コストは小さい。先に核（L2ループ一周）を完成させる。
- タスク: T1 note→未知検出 / T2 承認→制約化→自動再計算(A1c) / T3 ハンドラ網羅 /
  T4 少人数×複雑サンプル+台本 / T5 Supabase / T6 Cloud Run+提出物。

---

## 2026-06-10: T1実装 — noteから未知タイプ検出→承認キューに接続

- **NoteAgentの判定を2択→3択に**（Gemini呼び出し回数は同じ・バッチ1回）:
  ✅時間補正（従来） / 🆕新ルール候補（`is_new_type`+`suggested_type_name`） / ⚠️申し送り。
  プロンプトに「既知16typeで表せるものは新typeにしない」ガード＋コード側でも `KNOWN_TYPES` で二重ガード。
- **キュー登録**: ②と同じクラスタリング（同type名は1件に集約）。再解釈しても二重登録しない
  （person+date+原文で重複判定）。`PendingTypeRequest.occurrences` を新設し
  「誰の・いつの・どの原文か」を構造化記録 → **T2のparams化の材料**（②方針ルートにも記録）。
- 実装: `note_agent.py` / `prompts/note.txt` / `routes_setup.py`（純関数 `_apply_note_results`
  / `_register_note_pending` に分離） / `admin_queue.py` / ②画面3グループ表示。
- 検証: 実Gemini E2Eで「習い事」「大学の授業」の**別表現が同じ `recurring_day_off` に集約**
  （出現2回・同一req_id）、exam_period検出、挨拶は未反映、再解釈で増えず。コスト2回で¥0.35。
  テスト53件緑（新規8: 3分類・枠外補正拒否・集約・重複防止）。

---

## 2026-06-10: T2実装 — 承認→制約化→自動再計算（L2ループ一周が完成）

- **切れていた所**: 承認するとハンドラ関数は登録されるが、各人の原文を変換した
  **params（材料）が無く**、`run-stored` も `dynamic_constraints` を渡していなかった → 再計算しても効かない。
- **配線4つ**:
  1. **ParamsAgent**（Flash・思考オフ・バッチ）: 承認時に occurrence の原文 → params化。
     生成時の `tested_params`（見本）に形式を固定し、ハンドラが期待する形に一致させる。
  2. **storage に dynamic_constraints**（`save/get/clear`）。reset-constraintsで併せてクリア。
  3. **approve_pending** が登録後にparams化→保存。Gemini無し/失敗でも承認は壊さず警告で返す。
  4. **run-stored** が dynamic_constraints を反映＋ **`POST /solver/preview-rule-effect`** 新設
     （type除外あり/なしで2回solveしdiff）。⑤画面が承認直後に before/after を自動表示。
- **UI**: `render_shift_table` を `src/ui/_shift_table.py` に共有util化（④⑤で再利用）。
  ⑤は session_state でループ最後の差分を保持し、最上部に「🔁このルールで変わった割り当て」を表示。
- **方針**: `_DYNAMIC_HANDLERS`/dynamic_constraints はインメモリ（再起動で消える）。
  デモ1セッションは可。永続化はT5(Supabase)。
- **検証**: 単体5件（dynamic反映で水曜消滅・params化保存・run-stored反映・diff）。全58件緑。
  実Gemini E2E（`scripts/check_t2_live.py`）: recurring_day_off 承認→params化2件→
  **p01の水曜(11-04)の昼夜の割当が before/after で消える**ことを確認。

---

## 2026-06-17: ハンドラ品質問題の根治方針＝「部品化（レシピ）」＋デモUI刷新

- **問題の再定義**: 「ハンドラに反映できないコメントが多い」を3つに分解 —
  (a)入力が曖昧 / (b)新typeにすべきでない(既知に寄せるべき) / (c)生成コードがバグる。
  さらに(c)は「(C-1)API誤用＝書き方の問題」と「(C-2)存在しないデータ参照＝そもそも不可能」に分かれる。
- **根治方針（折衷案）**: AIに生のPythonを書かせず、**安全な「操作×選択子」プリミティブの
  組み合わせ＝レシピ（データ）**を出させ、信頼できる固定インタプリタが制約に変換する。
  → C-1が構造的に発生不能＋AIコードのexecも消滅（安全性向上）。見せ方は「AIが部品でルールを組む」。
- **操作5×選択子5**: forbid/require/limit_count/penalize/prefer × who/when/band/where/amount。
  机上検証で既知16の大半＋デモ3typeを表現可能と確認。乗らない5型（min_rest/limit_consecutive/
  break_rule/mentor_pairing/fairness）は固定の手書き専用部品＝T3に縮小。
- **残る限界の扱い**: 意味の取り違え(a)は**チャットで聞き返し**確定（早番=何時？）。
  データ欠落(C-2)は**正直に拒否**。デモではあえて拒否させる枠を3カテゴリ仕込む
  （交渉依存「他に休む人がいれば出る」／履歴依存「先月と同じシフトに」／データ欠落「車で来れる日だけ」）。
  ※「先月入れなかったので今月多めに」は理由を剥がせば`desired_workdays`で翻訳可。要望と理由を分離する原則。
- **デモUI刷新（確定）**: 提出者の主役画面は**Vite+React+Tailwind**で作る。
  CSVアップ・シフト実行・管理者承認はStreamlit据え置き。バックエンドFastAPIは不変。
  → CLAUDE.mdの「Streamlit確定/Next.js不要」を更新予定（T9）。順番は**エンジン先・UI後**。
- **実装①（本日）**: `src/solver/recipe.py` にレシピ・インタプリタを実装（5操作）。
  Gemini不要の単体7件で検証（forbidで水曜消滅・requireで充足・penalizeで回避・pairで分離・
  limit_countで回数上限・preferで引き込み）。全66テスト緑。
  次: ②生成フローをレシピ出力に変更 ③チャット整備 ④データ実現可能性チェック（拒否理由分類）。

---

## 2026-06-17: 生成フローをレシピ方式に切替（exec廃止・C-1を構造的に根絶）

- **/generate**: HandlerAgent(Python生成)→**RecipeAgent(Pro・レシピ設計)**に変更。
  検証は subprocess sandbox(exec)→**`validate_recipe`（プロセス内・小シナリオに当てる）**へ。
  任意コード実行が消え、安全性・速度・安定性が向上。
- **/approve**: `_fill_recipes_and_store`（ParamsAgent・Flash）が各人の原文からレシピを埋め、
  本人IDはoccurrenceで確実に上書き。dynamic_constraintsに`{type, params:<完成レシピ>}`で保存。
- **engine**: dynamic_constraintsのparamsが`operation`付きなら`apply_recipe`で適用（execしない）。
  旧Python方式（get_handler）も後方互換で残す。`PendingTypeRequest.suggested_recipe`を追加。
- **admin.py**: 「生成コード」表示→「レシピ（操作×選択子）」表示に対応。ボタン文言も設計/検証に。
- **検証**: 全73テスト緑。新規`test_recipe_flow.py`7件（engine適用・validate合否・
  埋め込みで本人ID上書き・/generateレシピ方式・**承認→埋め込み→run-storedで水曜消滅＆確定版**）。
  ＝Gemini無し（エージェントモック）で真のL2一周を再現。
- 残: チャット入力整備（意味の取り違え）／データ実現可能性チェック（正直な拒否・理由分類）／T9主役UI。

---

## 2026-06-17: 実Gemini検証＋「正直な拒否」（データ実現可能性チェック）

- **実Gemini検証（de-risk成功）**: `scripts/check_recipe_live.py`。デモ3typeとも
  RecipeAgent(Pro)が**構造的に正しいレシピ**を生成（confidence 1.0）。recurring_day_off は
  承認→反映まで完全動作。C-1バグはレシピ方式で構造的に消滅と実機確認。Gemini 5call ¥13。
- **検証バグ修正**: validate_recipe が固定窓（11月・11:00-22:00）のため、例レシピが
  12月の日付や22:00以降を指すと偽陰性。→ レシピの選択子に合わせて期間・営業時間を組むよう修正。
- **正直な拒否（実装）**: RecipeAgentに `expressible`/`reject_category` を出させ、表現できない
  ルールは**レシピを作らず**理由つきで拒否（negotiation_dependent/history_dependent/missing_data/
  subjective/advanced_logic）。⑤画面で「❌表現できません（理由）」＋却下導線。核「分かったフリをしない」直結。
- **チャット入力整備の置き場**: バッチCSVは本人不在のため、対話はT9（提出者UI・Vite+React）と
  セットで実装が自然。**モデルはFlash**（ユーザー指示・ソルバー生成ほど高度不要）。
- 全76テスト緑（正直な拒否のテスト追加）。

---

## 2026-06-18: 提出者の主役UI（T9）— React導入＋提出者プレビュー＋Flashチャット

- **見せ方の転換**: 「全備考にAIが順番に話す」のは間延びする。デモは**1人の提出者**として
  希望＋備考を出し、**note考慮あり/なし**を比較して「自分も店舗も要望が通った」を見せる体験にする。
- **フロント = Vite + React + Tailwind**（`frontend/`）。提出者画面だけ操作感が要るためStreamlitをやめReact化。
  裏方（CSVアップ・シフト実行・管理者承認）はStreamlit据え置き。CLAUDE.mdの「Streamlit確定/Next.js不要」を更新。
  認証は作らずマスタからの選択で代用（本デモに不要な実装を持ち込まないルール準拠）。
- **CORS**: React開発サーバー(:5173)からFastAPI(:8000)を叩けるよう `main.py` に許可を追加。
- **ChatAgent（Flash・新規）**: 提出者の備考の曖昧さを対話で確認。`POST /chat/clarify-note`（ステートレス）。
  確定時に**レシピ（操作×選択子）も直接出力**（単一人ルールはFlashで十分・安価。Proの`RecipeAgent`は
  管理者の未知type設計に温存）。表現できない要望は `expressible=false` で正直に拒否。
- **/submit/preview（新規・非破壊）**: 本人の希望で availability を差し替え、
  `before=承認済みdynamicのみ` / `after=＋本備考レシピ` を解いて、本人差分＋店舗充足を返す。
  既存 `preview-rule-effect` は承認済みtype専用のため流用不可と判明し、提出者用に新設。
  レシピ検証は本人IDのままだと p1〜p3 シナリオで「対象が居ない」偽陰性になるため `person_id="p1"` で当てる。
- **検証**: 全87テスト緑（chat 5件・submit 6件を追加）。フロントは `npm run build`（型チェック＋本番ビルド）通過。
  実Geminiでのチャット品質はユーザーが画面で確認予定。
- 詳細: `docs/spec/10_submitter_ui.md`、`docs/spec/07_gemini_agents.md`（ChatAgent節）。

---

## 2026-06-20: 提出体験の作り込み＋デモ運用の軽量化

- **ポート統一**: Streamlit裏方6画面はすべて `:8001`、T9のReactは `:8000` を見ていて噛み合わず
  「APIに接続できない」が出た。**FastAPIは:8001に統一**（フロント既定も `:8001` に修正）。
- **日ごとnoteはAIが翻訳してソルバーに組み込む（誤解の訂正）**: 提出画面のメモを「表示だけ」に
  しかけたが、これは肝の毀損。②CSV経路と同じ `NoteAgent`（✅時間補正/🆕新ルール候補/⚠️申し送り）を
  `/submit/preview` で再利用する設計に。`before=生の希望`／`after=時間補正＋overall noteレシピ`。
- **意見2（背骨）= 新種ルールnoteは即適用せず承認キューへ**: 提出者の「毎週水曜」等の新種は
  `_register_note_pending` で管理者の承認キューへ流す（preview非破壊の例外として追記のみ実施）。
  → 1つの提出体験から「note翻訳」と「未知→L2」が派生。提出者UI＝個人体験(Flash)、L2承認＝肝(Pro・承認ゲート)の**2幕**に分ける。
- **「もたつき」の正体**: ソルバー速度ではなく**提出者が30日分も手入力する負担**。→ デモを
  **10人×10日×3パターン**にコンパクト化（`data/demo/`・`scripts/gen_demo_data.py`で生成）。
- **ワンクリック投入**: `GET /setup/demo-patterns`＋`POST /setup/load-demo`（一括登録）。Streamlit①に
  プルダウン追加。提出者UIは `GET /submit/demo-wishes` で「デモ希望読込／自分で記入」を選択可。
- **提出カレンダー作り直し**: プリセット＋**開始終了を30分刻みで指定**＋**日ごとメモ**。結果画面に
  AIの備考解釈（✅🆕⚠️）を表示。
- **品質チェックルールを明文化**: アウトプット前にセルフチェック→問題は告知の上で承認不要で再検証
  （CLAUDE.md「アウトプット品質チェック」）。
- **検証**: 全93テスト緑（demo-load 6件追加）。フロント `npm run build` 通過。
  デモデータは `scripts/verify_demo_data.py` でソルバー実測（3パターンとも 水曜before/after・店舗不足0）をPASS。
- 詳細: `docs/spec/10_submitter_ui.md`（全面更新）。

---

## 2026-06-23: レシピのライブ堅牢化＋永続化の差し替え土台（T5）

- **レシピのライブ堅牢化**: 実Geminiが選択子を揺れた形で出してもデモが落ちないよう構造的に吸収。
  `Recipe.weekday` を `int|list[int]` 受け（「週末＝[5,6]」が通る）、`extra="forbid"→"ignore"`（幻フィールド
  `min`等で落ちない・`validate_recipe` が無視を承認時に警告で可視化）。実Geminiで[5,6]出力→検証合格を確認。
- **永続化の差し替え土台（T5・接続情報はまだ無い）**: `src/persistence.py` に `StateStore`（InMemory/Supabase）を置き、
  `storage.py` を**公開関数を変えずに** `_store` 越しへ配線。Supabaseキーが揃えば自動切替（無ければInMemoryにフォールバック）。
  - 配線済み（永続化対象）: dynamic_constraints / manager_questions / availability / policy_constraints /
    base_headcounts / note_results / demo_meta / shift_status（JSONネイティブ）。
  - 据え置き: pending_queue / masters / frame（Pydantic直列化＋テスト直参照のため、実DB接続フェーズで移す）。
  - テーブル定義 `db/schema.sql`（単一 `app_state(key,value jsonb)`）。RLSは使わない（単一店舗・service_role）。
- **理由**: Supabaseプロジェクト未作成で実DB検証ができず、方針も「T5はT6デプロイとセット」。
  そこで**ブロックされない土台**を先に作り、キー到着で即切替できる状態にした。
- **影響範囲**: storage公開APIは不変→ルート/テスト無改修。全105テスト緑（レシピ+4・persistence+4）。
- 詳細: `docs/spec/11_persistence.md`、`docs/spec/09_recipe_primitives.md`（堅牢性節）。

---

## 2026-06-24: Supabase 本接続（T5の実DB化）

- **決定**: T5土台に実Supabaseを接続し、**アプリ公開関数経由でJSONBを永続化できる状態**にした。
  `storage.save_dynamic_constraints` 等が `app_state(key, value jsonb)` に書き込み→読み戻すのを実機確認。
  審査員が Table Editor で「AIが生成した typed JSON」を直接見られる＝デモの説得材料が1つ増えた。
- **やったこと**: `.env` に Project URL＋秘密鍵を設定／`db/schema.sql` 実行でテーブル作成／
  `supabase` パッケージ導入（pyprojectに宣言済みだったが環境に未導入）／
  **`tests/conftest.py` 新規**＝全テストを毎回 `InMemoryStore` に固定し**実DBを汚さない**。
- **つまずき所（備忘）**: ①URLは Project URL（`https://<ref>.supabase.co`）。ダッシュボードのページURLを
  貼ると404(HTML)。②鍵は秘密鍵（`sb_secret_…`）を `SUPABASE_SERVICE_ROLE_KEY` 名で
  （`ANON`名は「公開可」と誤解しやすいので回避）。③`PGRST205`=テーブル未作成のサイン。
- **据え置き（T6前）**: pending_queue / masters / frame の model_dump 配線、manager_question 更新口、
  Cloud Run への Secret 注入。理由: 再起動耐性が本当に要るのはデプロイ時で、接続成立を先に確定したかった。
- **影響範囲**: storage 公開APIは不変。`tests/conftest.py` 追加のみでテスト挙動は安全側に。全105テスト緑。
- 詳細: `docs/spec/11_persistence.md`（本接続済み節）。

---

## 2026-06-30: デモ磨き上げ 4 件（ソルバー1ライン化・note表示・まとめチャット・役職参照）

ユーザーの改修要望4件に対応。1・2・4 は前セッションで実装済みだったものを検証してまとめ、3 を新規実装。

- **要望1: シフトは「連続1ライン・基本最大8時間」を前提条件に**（現実の実態に合わせ、2回に分けて入る細切れを廃止）。
  `src/solver/engine.py` の `_apply_shift_shape` を `SHIFT_MAX_BLOCKS_PER_DAY=1`＋`SHIFT_MAX_HOURS_PER_DAY=8`（在席コマ合計に上限）に変更。
  これに合わせ**デモデータを店ごとに営業時間をばらけさせて再生成**（cafe 11–20 / diner 11–23 / izakaya 16–24）。
  店舗選択時に**営業時間・必要人数（基本編成）を表示**（`/setup/demo-patterns` が operating_window＋headcounts を返し、StoreStep/setup.py が表示）。
  `scripts/verify_demo_data.py` で3パターンとも「水曜before配置／after消去／店舗不足0」を実測 PASS。
- **要望2: 結果画面で note の扱いを全件表示し、無視は明示／充足スコア廃止**。
  `ResultStep.tsx` が `store-compare` の `note_results` を「🤖 備考の扱い」で全件表示（✅時間補正/🆕承認待ち/⚠️申し送り）、
  `unreflected` があれば下部に明示。意味の薄かった「充足スコア(100点満点)」は React/Streamlit 双方から削除し、
  「必要人数を満たせています/⚠️N コマ不足」の一言表示に。
- **要望3: 生成ハンドラの作り直し相談を「個別→全部まとめて1つの会話」に**（新規）。
  従来は④承認画面でルールごとに feedback 入力欄が並び、`/generate?feedback=` を1件ずつ叩く形（履歴なし）だった。
  これを**1つのマルチターン会話**に統一。新設 `POST /admin/pending-types/chat`（ステートレス・履歴は毎回渡す＝
  提出者チャット `/chat/clarify-note` と同方式）。`RecipeChatAgent`(Pro)＋`recipe_chat.txt` が生成済みルール一覧＋会話履歴を読み、
  **どのルールの話かを判断して該当ルールのレシピだけ作り直す**。承認/却下はルール単位のまま。
  生成結果の保存は `/generate` と共通の `_store_generated()` に切り出して再利用。
  実Geminiで疎通確認（単一更新＋複数ルールの選択的ルーティング＝指定1件だけ更新・他は不変）。
- **要望4: 反映できない要望は正直に伝える／同内容ラリーを防ぐ／役職(新人)をDB参照**。
  `routes_chat.py` に `MAX_USER_TURNS=4`（上限で「反映が難しい/情報不足」を伝えて打ち切り）。
  `_context.masters_context()` が**在籍スタッフ＋役職ごとの所属**を出力し、`chat_clarify.txt` が「新人は…」を
  `who="role"`+role_id で出すよう指示。経路: AI→`_chat_recipe`（role_id 保持）→承認キュー→`_resolve_persons`（recipe.py）。
- **検証時の追加修正（堅牢化）**: まとめチャットの疎通で、AIが例レシピに実在ID `person_id="p01"` を入れると
  `validate_recipe`（固定検証シナリオは p1〜p5）で「対象が居ない」偽陰性になることを発見。`_store_generated` で
  検証前に who=person/pair の person_id を検証用(p1/p2)へそろえる正規化を追加（`_chat_recipe` と同じ発想・`/generate` 経路も堅牢化）。
- **影響範囲**: storage 公開APIは不変。全105テスト緑・`scripts/verify_demo_data.py` PASS・`npm run build` 通過。
- 詳細: `docs/spec/04_admin_workflow.md`（まとめチャット）／`docs/spec/06_solver.md`（シフトの形）／`docs/spec/10_submitter_ui.md`。

---

## 今後追記用フォーマット

```markdown
## YYYY-MM-DD: タイトル

- 決定内容
- 理由
- 影響範囲
```
