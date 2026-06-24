# Cloud Run デプロイ手順（T6）

FastAPI と Streamlit を **Cloud Run ×2** に出す手順。DBは **Supabase（接続済み）**、
秘密情報は **Secret Manager** で注入する。コマンドは **PowerShell**（行継続は `` ` ``）。

```
[ブラウザ:React提出者UI] ──fetch──▶ [api (FastAPI)] ──▶ Supabase / Gemini
[ブラウザ:管理者]        ──────────▶ [streamlit] ──server間──▶ [api]
```

> Streamlit→api は**サーバ間呼び出し**なので CORS 不要。CORS が要るのは**ブラウザのReact**だけ。

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

確認: `"$API_URL/health"` をブラウザで開く → `{"status":"正常", ...}` が出ればOK。

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

## 8. React 提出者UI（配信方法は要決定）

`frontend/` を `VITE_API_BASE=$API_URL` でビルドして配信する。配信先の候補:
- **(a) ローカル実行**: デモ時 `npm run dev`（`.env.local` に `VITE_API_BASE`）。デプロイ不要・最速。
- **(b) FastAPI に同梱**: `npm run build` の `dist/` を api が静的配信（サービス1つ減・URL統一）。
- **(c) 別ホスティング**: Firebase Hosting / Cloud Storage 等に静的配信。

→ 決まり次第ここを更新。**(b)/(c) で公開する場合は次の CORS 手順が必要**。

## 9. CORS（React を公開する場合のみ）

React の公開オリジンが決まったら api に環境変数を足して再デプロイ:

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
| 永続化がインメモリのまま | api のログに「Supabase を使用します」が出るか。Secret 3点が揃っているか |
