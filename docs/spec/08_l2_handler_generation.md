# 仕様書 08 — L2フロー：AIによるハンドラ自動生成（A1）

*最終更新: 2026-06-06*

> ℹ️ **現在の既定は「レシピ方式」（spec/09）**。本書が記す Python生成＋exec＋subprocess sandbox は**後方互換で残るが既定ではない**。L2の思想は現役・実装の主役は spec/09。

このプロジェクトの**主役**（審査で効く部分）。
「AIが未知ルールに出会うと、自分でそれを処理するコードを書き、自分でテストし、人間に承認を求める」を実装する。

---

## 1. これは何をする機能か（プレーンな説明）

スタッフが「毎週水曜は入れません」と書く。これは既存の16ルールに当てはまらない**未知タイプ**。
従来なら管理者が手作業でコードを書くしかない。この機能では：

1. パーサが「未知だ」と気づき、承認キューに積む
2. **AI（Gemini）が、その未知ルールを処理する関数（ハンドラ）のPythonコードを自分で書く**
3. 書いたコードを**安全な別プロセスで実際に動かしてテスト**する
4. 「生成コード・テスト結果・自信度」を承認キューに添える（→人が承認する材料）

つまり **「AIがコードを書いて、テストして、承認を求める」** までを自動化する。

---

## 2. 登場するファイルと役割

| ファイル | 何をするか | なぜ必要か |
|---|---|---|
| `src/agents/handler_agent.py` | 未知type情報を渡すと、AIが「ハンドラのコード・paramsの形・例・自信度・懸念点」を返す | コード生成の本体。Pro想定（無料枠都合で当面Flash） |
| `src/agents/prompts/handler.txt` | AIへの指示書。ソルバーの使い方(ctx API)と既存ハンドラの手本を載せる | AIが**正しい形のコード**を書けるようにするため。テキストなので調整が楽 |
| `src/sandbox.py` | 生成コードを**別プロセス＋タイムアウト**で実行する入口 | 生成コードは信用できないので隔離して動かす（暴走を時間切れで止める） |
| `src/_sandbox_harness.py` | 別プロセスの中で実際に動く検証スクリプト。小さな架空シフトに生成コードを適用して「解けるか」を見る | 「コードが動く・解ける」を機械的に確認するため |
| `src/api/routes_admin.py` の `POST /…/generate` | 上記を順に呼び、結果をキューに格納するAPI | 画面やSwaggerから1回叩けば全部走るようにする入口 |

---

## 3. 処理の流れ（1ステップずつ）

> ℹ️ **現行方式の補足（2026-06-17 / 2026-06-30）**: 生成は Python コード(exec)方式から
> **レシピ（操作×選択子）方式**に切替済み（`RecipeAgent`＋`validate_recipe`・任意コード実行なし。詳細は
> `docs/99_decisions_log.md 2026-06-17`）。下記①〜③は旧Python方式の記述。
> また、生成後の**作り直し相談**は、ルールごとの feedback 欄ではなく
> **④承認画面下の「まとめチャット」1つ**（`POST /admin/pending-types/chat`・`RecipeChatAgent`）に統一した
> （生成済みルール全部を1会話で扱い、AIが該当ルールだけ作り直す。`docs/spec/04_admin_workflow.md` 参照）。

```
POST /admin/pending-types/{id}/generate
  │
  ├─ ① HandlerAgent.generate(req)        … AIがコード一式を生成
  │      入力: type名 / ユーザーの言い回し / 要約 / AI見解
  │      出力: handler_code, param_schema, example_params, explanation, confidence, concerns
  │
  ├─ ② run_handler_test(code, example)   … サンドボックスでテスト
  │      ・別プロセスで _sandbox_harness を起動（タイムアウト8秒）
  │      ・3名×1週間の小さなシフトを用意 → 生成コードを適用 → ソルバーで解く
  │      ・エラーなく解けたら passed=True
  │
  └─ ③ 結果を PendingTypeRequest に格納
         suggested_handler_code / suggested_schema / confidence / concerns / test_results
```

### 生成ハンドラの「契約」（必ずこの形）
```python
def handle(params, ctx):
    # params: このルールのパラメータ（dict）
    # ctx   : ソルバーの作業台（変数・モデル）。ctx.model.Add(...) で制約を足す
    ...
```
既存ハンドラ（headcount / availability / separate）と同じ `ctx` を使う。
プロンプトにこの `ctx` の使い方と既存3つの手本を載せているので、AIは同じ流儀で書ける。

### 安全対策（重要）
- 生成コードは `exec` で実行するため、**必ず別プロセス＋タイムアウト**で隔離（CLAUDE.md方針）。
- 無限ループ → タイムアウトで打ち切り。例外 → 失敗として捕捉。`handle` 未定義 → 失敗。
- 子プロセスの出力は**UTF-8固定**（ASCII-safe JSON＋環境変数）で、起動元による文字化けを防ぐ。

---

## 4. 確認ポイント（手順つき）

### A. Swagger UI で通す（http://127.0.0.1:8001/docs）
1. `POST /parser/parse` に「毎週水曜は習い事で入れません」を送る
2. `GET /admin/pending-types` で出た `id` をコピー
3. `POST /admin/pending-types/{id}/generate` を Execute
   - レスポンスに **「テスト: 合格」「自信度」「説明」** が出れば成功
4. `GET /admin/pending-types/{id}` で
   - `suggested_handler_code`（生成されたPythonコード）
   - `test_results.passed = true`
   が入っていることを確認

> 429が出たら**Gemini無料枠の上限**。数分待つか、キーを空にしてスタブで継続。

### B. 自動テスト（Gemini不要）
```
python -m pytest tests/test_sandbox.py -q
```
- 正しいコード→合格 / 無限ループ→タイムアウト / 例外→失敗 / handle無し→失敗 の4件が通る

---

## 5. 承認後の動的登録（A1b・実装済み）

承認すると、生成ハンドラが**実際にソルバーで使えるようになる**。

| 仕組み | 内容 |
|---|---|
| `register_dynamic_handler(type, code)` | 承認時に呼ばれ、生成コードを exec して動的ハンドラ辞書に登録 |
| `get_handler` | 「組み込み→動的」の順で探す。承認済みtypeはここで見つかる |
| `SolverInput.dynamic_constraints` | 新type用の入り口（`{type, params}`の配列）。既知16typeのunion外なので別チャネル |
| engine | dynamic_constraints を動的ハンドラで適用。未登録typeは `warnings` に `unregistered:<type>` |

```
承認 → register_dynamic_handler() → 以降 /solver/run に
   dynamic_constraints=[{"type":"recurring_day_off","params":{...}}] を渡すと適用される
```

- **安全境界**: 承認されたコードは本番プロセスで exec される。**人の承認がゲート**。
- 登録は当面インメモリ（再起動で消える。永続化はSupabase段階）。
- テスト: `tests/test_dynamic_handler.py`（登録後に適用される／未登録は警告）。

### まだやっていないこと（次フェーズ）

| 残り | 内容 |
|---|---|
| **A1c 自動再計算＋通知** | 承認後、影響シフトに dynamic_constraint を自動付与して再計算し、暫定→確定に更新・ユーザー通知 |

---

## 6. モデルについての注意

- 設計上はハンドラ生成に **Pro（高精度）** を使いたい。
- ただし **無料枠では `gemini-2.5-pro` が使えない（limit:0）**。
- 当面 `.env` の `GEMINI_PRO_MODEL=gemini-2.5-flash` でFlashに向けている（Flashでも正しく生成できることを確認）。
- 課金を有効化したら `.env` の1行を `gemini-2.5-pro` に戻すだけ（コード変更不要）。
