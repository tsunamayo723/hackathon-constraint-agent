# 03. 技術スタック

*最終更新: 2026-05-27*
*ステータス: 全項目確定*

> ℹ️ **一部変更あり**: 提出者UIは Streamlit →**React/Vite**（2026-06-17・spec/10）。ハンドラ生成は exec+subprocess →**レシピ方式**（spec/09）。最新は spec/ と [99_decisions_log.md] が正。

---

## 全体構成

| レイヤー | 採用 | 役割 |
|---|---|---|
| 言語 | Python | 統一(コード生成・ソルバー・LLM呼び出しすべて) |
| バックエンドAPI | FastAPI | エージェント本体のAPIサーバー |
| デモUI | Streamlit | 承認画面・シフト表示等 |
| ソルバー | OR-Tools (CP-SAT) | 制約充足・最適化計算 |
| LLM | Gemini API | NL→JSON変換、ハンドラ生成 |
| デプロイ先 | Cloud Run × 2 | FastAPI用とStreamlit用に分離 |
| DB | Supabase (PostgreSQL + JSONB) | データ永続化 |
| サンドボックス | Python subprocess | 生成コードの安全な実行 |

---

## 1. 言語・フレームワーク

### Python採用

**理由**:
- OR-Toolsの公式メインサポートがPython
- Gemini SDKの充実度がトップ
- AIエージェント系ライブラリが豊富
- Claude Codeとの相性も最良

### FastAPI + Streamlit のバランス構成

**役割分担**:
- **FastAPI**: バックエンドのAPI(パース、ハンドラ生成、ソルバー呼び出し)
- **Streamlit**: デモ用UI(承認ゲート、シフト表示、CSV投入)

**理由**:
- APIとして外部公開できる(「とどける」の評価軸対応)
- Streamlitでデモ映え確保
- 両方Pythonなので開発スムーズ

---

## 2. デプロイ先: Cloud Run × 2

### 構成

```
[Streamlit on Cloud Run]  ← フロント
        ↓ APIコール
[FastAPI on Cloud Run]    ← バックエンド
```

### 選定理由

- 業界標準で情報量多い
- リクエスト無い時は課金ゼロ
- 60分タイムアウトでソルバー実行に余裕
- Dockerコンテナ化で何でも動く
- Claude Codeが詳しい

### 不採用案

| 候補 | 不採用理由 |
|---|---|
| Cloud Functions | 9分タイムアウトが厳しい、複数機能を持つアプリには小さい |
| GCE | OS管理が必要、運用面倒、常時課金 |
| App Engine | Cloud Runに役目を譲りつつある、新規選択の理由薄い |
| Vertex AI Agent Builder | ノーコード寄りでカスタムロジック収まり悪い |

---

## 3. 永続化: Supabase

### 採用理由

- PostgreSQL + JSONB で **JSON柔軟性とSQL集計力を両立**
- 管理画面が便利、開発効率高い
- 無料枠でハッカソン完走可能
- ハッカソン規約上問題なし(DBは要件外)

### データ設計の方針

- マスタ(persons / positions / roles / skills) → 普通のテーブル
- type辞書 → メタ情報はカラム、params_schema・handler_code は JSONB
- 制約データ → type_name カラム + params は JSONB
- 承認ログ・実行履歴 → 普通のテーブル + 結果は JSONB

### 不採用案

| 候補 | 不採用理由 |
|---|---|
| Firestore | テーブル結合・集計クエリが弱い、SQL慣れた人には不便 |
| Cloud SQL | 常時起動課金、設定面倒 |
| ローカルSQLite | Cloud Run再起動で消える(致命的) |

### 注意点

- 応募前にハッカソン規約を再確認(DBサービス縛りがないか)
- もし縛りが見つかれば Cloud SQL に移植可能(両方PostgreSQLなので半日仕事)

---

## 4. サンドボックス: subprocess + タイムアウト

### MVP実装

```python
result = subprocess.run(
    ['python', '-c', generated_code],
    timeout=5,
    capture_output=True
)
```

### 設計方針

`Sandbox` インターフェースで抽象化し、将来差し替え可能に。

```python
class Sandbox:
    def execute(self, code: str, test_inputs: list) -> TestResult: ...

class SubprocessSandbox(Sandbox): ...   # MVP
class CloudRunJobsSandbox(Sandbox): ... # 将来
```

### 採用理由

- ハッカソンのリスクモデル(攻撃者なし、自分しか使わない)に十分
- Python標準ライブラリだけで実現、追加インフラ不要
- テスト実行が即座に終わる(数百ms)→ デモのテンポ良好
- 商用化時はCloud Run Jobsに差し替え可能

### 不採用案

| 候補 | 不採用理由 |
|---|---|
| Docker コンテナ | Cloud Run内でDocker動かすのが面倒(Docker-in-Docker) |
| Cloud Run Jobs | 起動に数秒〜十数秒、デモのテンポ悪化 |
| RestrictedPython | OR-Tools使うので制限緩めると意味薄い |
| Cloud Functions | 関数ごとにデプロイし直しが必要 |

---

## 5. Geminiモデル使い分け

### モデルカスケード方針

| 処理 | 必要な賢さ | 頻度 | 推奨モデル |
|---|---|---|---|
| NL → JSON 変換 | 中 | 高(毎回) | **Flash** |
| 既知typeへの分類 | 中 | 高 | **Flash** |
| マスタ正規化 | 低〜中 | 中 | **Flash** |
| 未知type検出 | 中 | 中 | **Flash** |
| 新typeのスキーマ設計 | 高 | 低(新type時のみ) | **Pro** |
| ハンドラPythonコード生成 | 高 | 低 | **Pro** |
| テストコード生成 | 高 | 低 | **Pro** |
| 自信度評価・concerns出力 | 高 | 低 | **Pro** |

### 自信度ベースのルーティング

| 処理 | 自信度閾値 | 動作 |
|---|---|---|
| NL→JSON (Flash) | >= 0.8 | そのまま採用 |
| 〃 | 0.5 - 0.8 | Pro で再変換 |
| 〃 | < 0.5 | 人間に言い直し依頼 |
| ハンドラ生成 (Pro) | >= 0.9 + 全テスト合格 | 自動承認(MVP外でも可) |
| 〃 | 0.7 - 0.9 | 自動テスト → 人間レビュー必須 |
| 〃 | < 0.7 | 即人間レビュー、警告表示 |

### 自信度評価方式

**方式1: モデルに自己申告させる**(プロンプトで `confidence` と `concerns` を出力させる)を採用。

理由:
- 実装が爆速
- concerns(自然言語)がデモで効く
- 300ドルクレジット余裕あるので必要に応じて方式3(複数サンプリング)併用可

### LLM as a Judge

COULD枠(余裕あれば実装、Pro→Pro検証)。MVPには含めない。

---

## 評価軸との対応マップ

| 評価軸 | 技術スタックでの貢献 |
|---|---|
| **1. AIエージェント中心性** | Gemini Pro でハンドラ自動生成 = 自律性の中核 |
| **2. 課題アプローチ** | (デモシナリオで詰める) |
| **3. ユーザビリティ** | Streamlit で直感的UI |
| **4. 実用性・体験価値** | 30人規模対応、再計算ラリー |
| **5. 実装力** | Cloud Run × 2 + Supabase + OR-Tools + サンドボックス抽象化 |

---

## 環境構築チェックリスト

開発開始前に必要なもの:

- [ ] Python 3.11+ インストール
- [ ] Poetry または uv(パッケージ管理)
- [ ] Google Cloud アカウント + プロジェクト作成
- [ ] Google Cloud SDK (gcloud) インストール
- [ ] Cloud Run有効化、課金有効化
- [ ] 300ドルクレジット適用
- [ ] Gemini APIキー取得
- [ ] Supabaseアカウント + プロジェクト作成
- [ ] Supabase接続情報取得
- [ ] `.env` ファイル準備
- [ ] `.gitignore` に `.env` 追加

---

## 主要パッケージ(想定)

```
# requirements.txt 想定
fastapi
uvicorn
streamlit
google-generativeai      # Gemini SDK
ortools                  # OR-Tools
supabase                 # Supabase Python client
pydantic                 # 型検証
python-dotenv            # .env読み込み
pandas                   # CSV処理
```
