# Cloud Run デプロイ手順（T6）

FastAPI と Streamlit を **Cloud Run ×2** に出す手順。DBは **Supabase（接続済み）**、
秘密情報は **Secret Manager** で注入する。コマンドは **PowerShell**（行継続は `` ` ``）。

```
[ブラウザ:提出者]  ──▶ [api (FastAPI + React同梱)] ──▶ Supabase / Gemini
                          └ "/"=React提出者UI  /about=説明  /docs=Swagger
[ブラウザ:管理者]  ──▶ [streamlit] ──server間──▶ [api]
```

> React は api に**同梱**（同一オリジン）なので **CORS は不要**。Streamlit→api もサーバ間なので CORS 不要。

---

## 0. 前提（最初に一度だけ）

- Google Cloud SDK（`gcloud`）をインストール
- ログイン（このセッションのプロンプトに貼ると出力が見えます）: `! gcloud auth login`
- 変数をセット（自分の値に）:

```powershell
$PROJECT_ID = "your-project-id"
$REGION     = "asia-northeast1"   # 東京。Supabaseも東京なので近い
$REPO       = "constraint-agent"
gcloud config set project $PROJECT_ID
```

## 1. 必要なAPIを有効化

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
  artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 2. Artifact Registry（イメージ置き場）を作成

```powershell
gcloud artifacts repositories create $REPO `
  --repository-format=docker --location=$REGION
```

## 3. 秘密情報を Secret Manager へ（.env の値）

```powershell
# 箱を作る
gcloud secrets create GEMINI_API_KEY            --replication-policy=automatic
gcloud secrets create SUPABASE_URL              --replication-policy=automatic
gcloud secrets create SUPABASE_SERVICE_ROLE_KEY --replication-policy=automatic

# 値を投入（コマンド履歴に残したくない場合は .env からコピペで）
"YOUR_GEMINI_KEY"            | gcloud secrets versions add GEMINI_API_KEY            --data-file=-
"https://xxx.supabase.co"    | gcloud secrets versions add SUPABASE_URL              --data-file=-
"sb_secret_xxxxxxxx"         | gcloud secrets versions add SUPABASE_SERVICE_ROLE_KEY --data-file=-
```

ランタイムのサービスアカウントに読み取り権限を付与（PROJECT_NUMBER は `gcloud projects describe $PROJECT_ID --format='value(projectNumber)'`）:

```powershell
$PNUM = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$PNUM-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

## 4. FastAPI をビルド＆push

```powershell
gcloud builds submit --config deploy/cloudbuild.api.yaml `
  --substitutions=_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/api:latest" .
```

> このビルドは**多段**で、内部で **React(`frontend/`) も `npm run build`** してイメージに同梱します
> （提出者UIは別途デプロイ不要）。初回は Node 依存の取得で数分かかることがあります。

## 5. FastAPI をデプロイ → URLを控える

```powershell
gcloud run deploy api `
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/api:latest" `
  --region $REGION --allow-unauthenticated `
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest"
```

出力された Service URL（例 `https://api-xxxx.a.run.app`）を次で使う:

```powershell
$API_URL = "https://api-xxxx.a.run.app"   # ← 実際のURLに（末尾スラッシュ無し）
```

確認（ブラウザで開く）:
- `"$API_URL/"` → **React提出者UI（メイン画面）**が表示される
- `"$API_URL/about"` → システム説明ページ
- `"$API_URL/health"` → `{"status":"正常", ...}`
- `"$API_URL/docs"` → Swagger UI

## 6. Streamlit をビルド＆push

```powershell
gcloud builds submit --config deploy/cloudbuild.streamlit.yaml `
  --substitutions=_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/streamlit:latest" .
```

## 7. Streamlit をデプロイ（API_URL を注入＝localhost回避）

```powershell
gcloud run deploy streamlit `
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/streamlit:latest" `
  --region $REGION --allow-unauthenticated `
  --set-env-vars "API_URL=$API_URL"
```

## 8. React 提出者UI（= (b) FastAPI同梱・追加作業なし）

**配信方法は (b) FastAPI同梱に決定済み**。手順4の api ビルド時に `frontend/` が
`VITE_API_BASE=""`（同一オリジン）で自動ビルドされ、イメージに同梱されます。
→ **提出者UIの個別デプロイは不要**。`"$API_URL/"` がそのまま提出者UIです。

> ローカル開発は従来どおり `npm --prefix frontend run dev`（:5173）＋ api を :8001 で動かす。
> 同梱(`frontend_dist/`)はビルド時だけ生成され、ローカルの `"/"` は説明ページ `/about` に誘導される。

## 9. CORS（同梱構成では不要）

(b)同梱は **React と api が同一オリジン**なので **CORS 設定は不要**です。
将来 React を別ホスティング（Firebase 等）に分離した場合のみ、公開オリジンを足して再デプロイ:

```powershell
gcloud run services update api --region $REGION `
  --update-env-vars "ALLOWED_ORIGINS=https://your-react-host"
```

---

## コスト・運用メモ

- **Cloud Run はゼロスケール**（呼ばれた時だけ課金）。デモ規模なら無料枠内に収まりやすい。
- **Supabase Free は7日無アクセスで一時停止** → デモ当日の朝に1回起こす。
- イメージは簡潔さ優先で **api/streamlit とも同じ `requirements.txt`**（streamlit と ortools が両方入る）。
  ビルドを軽くしたいなら API用/UI用に分割してよい。

## つまずき所

| 症状 | 原因/対処 |
|---|---|
| Streamlitで「APIに接続できない」 | `API_URL` が FastAPI の Service URL になっているか（末尾スラッシュ無し） |
| 起動時に Secret 読めず 500 | ランタイムSAに `secretAccessor` を付けたか（手順3末尾） |
| ビルドに src が無い等 | `.gcloudignore`/`.dockerignore` が `src/ data/ requirements.txt deploy/` を除外していないか |
| ortools の wheel が無い | ベースを `python:3.12-slim` に固定済み（3.14系は wheel 未提供のことがある） |
| 提出者UIが出ない/ビルド失敗 | api は多段ビルド。`npm --prefix frontend run build`（`tsc -b`）がローカルで通るか確認。`frontend/package-lock.json` がコミットされているか |
| 永続化がインメモリのまま | api のログに「Supabase を使用します」が出るか。Secret 3点が揃っているか |
