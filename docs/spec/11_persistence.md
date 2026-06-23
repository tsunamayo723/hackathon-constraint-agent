# 仕様書 11 — 永続化（保存口の差し替え）

*最終更新: 2026-06-23（T5土台：StateStore seam＋8バケット配線。実DB接続はT6とセット）*

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

## 残り（T5本接続・T6とセット）

1. Supabaseプロジェクト作成 → `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` を `.env` へ。
2. `db/schema.sql` を Supabase で実行。
3. 起動時に `_store` から各バケットを読み戻す処理（現状は書き込み口のみ／読み戻しは
   各 `get_*` がリクエスト毎に `_store.get` するので、Supabase化すれば自動で復元される）。
4. pending_queue / masters / frame を model_dump 経由で `_store` 越しに移す（＋該当テストの
   グローバル直参照を公開関数へ置き換え）。
5. SupabaseStore の in-place更新（manager_questionの回答反映）に `update` 口を足す。
