# 仕様書 11 — 永続化（保存口の差し替え）

*最終更新: 2026-06-24（**Supabase 本接続済み**。8バケットが実DBに永続化。据え置き3バケットはT6前）*

---

## なぜ

承認した新type（`dynamic_constraints`）や責任者への質問（`manager_questions`）は
**インメモリ**で持っており、プロセス再起動で消える。本番デモを安定させるには永続化が要る。

ただしSupabaseの接続情報はまだ無い（プロジェクト未作成）。そこで今回は
**「保存先を差し替えられる土台」だけ**を作り、キーが入った瞬間に Supabase へ切り替わるようにした。

---

## 設計：StateStore（保存口）

`src/persistence.py` に、キー（バケット名）→ JSON値 の最小KVS `StateStore` を定義する。

| 実装 | いつ使う | 保存先 |
|---|---|---|
| `InMemoryStore` | **既定**（Supabaseキー無し） | プロセス内 dict（再起動で消える） |
| `SupabaseStore` | `SUPABASE_URL`＋キーが揃ったとき | Supabase `app_state` テーブル（JSONB・upsert） |

`get_store()` が環境変数を見て自動選択する。雛形値（`https://your-project...` 等）・空・非ASCIIは
「未設定」とみなし InMemory にフォールバックする（誤接続でデモを止めない）。

```
storage.py  ──（公開関数は不変）──>  _store: StateStore  ──>  InMemory / Supabase
```

- `storage.py` の各関数の**名前・引数・戻り値は一切変えていない** → ルートもテストも無改修（全105テスト緑）。
- テーブル定義は `db/schema.sql`（Supabase の SQL Editor で一度実行）。
- 認証/RLSは使わない（CLAUDE.md：単一店舗デモ・service_role キー）。

---

## 現状の配線範囲（重要）

| バケット | 配線 | 備考 |
|---|---|---|
| dynamic_constraints / manager_questions | ✅ `_store` 越し | **再起動で消えて困るL2成果**。最優先で永続化対象に |
| availability / policy_constraints / base_headcounts / note_results / demo_meta / shift_status | ✅ `_store` 越し | いずれも JSONネイティブ（list/dict）でそのまま置ける |
| **pending_queue / masters / frame** | ⏸ インメモリ据え置き | Pydantic直列化（model_dump/model_validate）が必要＋テストが
これらのグローバルを直接触る。**実DB接続フェーズ（T6とセット）**で同様に `_store` 越しへ移す |

> 据え置きの3つは「デモ開始時のセットアップで毎回入れ直す」性質のデータなので、
> 当面インメモリでも実害は小さい。L2の成果（新ルール）は確実に保存口を通る。

---

## ✅ 本接続済み（2026-06-24）

実際に Supabase へ接続し、**アプリの公開関数（`storage.save_dynamic_constraints` 等）経由で
JSONB を書き込み→読み戻しできること**を確認した。`app_state` に
`{"type":"recurring_day_off","params":{"person_id":"p01","weekday":2},...}` が入るのを
Table Editor で目視できる（＝「自然言語→typed JSON→DB」が見える化）。

| 済んだこと | 内容 |
|---|---|
| プロジェクト＋鍵 | `.env` に `SUPABASE_URL`（Project URL）/ `SUPABASE_SERVICE_ROLE_KEY`（秘密鍵 `sb_secret_…`） |
| テーブル作成 | `db/schema.sql` を SQL Editor で実行（`app_state(key, value jsonb, updated_at)`） |
| パッケージ | `supabase` を導入（pyproject に宣言済みだったが環境に未導入だった） |
| **テスト隔離** | `tests/conftest.py` で全テストを毎回 `InMemoryStore` に固定 → **pytest が実DBを汚さない**。全105緑 |

### つまずき所と対処（次回・デプロイ時の備忘）

- **URL は「Project URL」**（`https://<ref>.supabase.co`）。ダッシュボードのページURL
  （`supabase.com/dashboard/project/<ref>/…`）を貼ると REST ではなく Web に飛び 404（HTML）になる。
- 貼る鍵は**秘密鍵（service_role / `sb_secret_…`）**。変数名は `SUPABASE_SERVICE_ROLE_KEY`
  （`ANON` 名だと「公開可」と誤解しやすいので避ける。値は同じでもコードは両方読む）。
- 接続できているのにエラーなら `PGRST205`（テーブル未作成）を確認 → `db/schema.sql` 実行。

## 残り（T6デプロイとセット）

1. pending_queue / masters / frame を model_dump 経由で `_store` 越しに移す（＋該当テストの
   グローバル直参照を公開関数へ置き換え）。※ デモ開始毎に入れ直す性質なので当面インメモリでも実害小。
2. SupabaseStore の in-place更新（manager_questionの回答反映）に `update` 口を足す。
3. Cloud Run の環境変数（`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`）を Secret で注入。
