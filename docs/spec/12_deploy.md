# 仕様書 12 — デプロイ（Cloud Run ×2）の下ごしらえ

*最終更新: 2026-06-24（T6着手：Dockerfile・ビルド設定・環境変数化まで。実デプロイは未実施）*

---

## ねらい

FastAPI と Streamlit を **Cloud Run ×2** に出せる状態にする。デプロイ未経験でも
「ほぼコマンドを順に叩くだけ」になるよう、コード側の前提も整えた。実手順は
[`deploy/README.md`](../../deploy/README.md) を参照（このファイルは設計の記録）。

## 何を変えたか（コード側の前提）

| 変更 | 理由 |
|---|---|
| `src/ui/_api_config.py` 新規＋6画面が参照 | Streamlit の `API_URL` を環境変数化。**別サービスのFastAPIを呼ぶ**ため localhost 固定では繋がらない。既定はローカル `http://localhost:8001`（挙動不変） |
| `src/api/main.py` の CORS | 本番Reactの配信元を環境変数 `ALLOWED_ORIGINS`（カンマ区切り）で追加可能に。ローカルのVite/3000は既定で許可のまま |
| `requirements.txt` 新規 | イメージ用の実行時依存（`pyproject.toml` と一致）。簡潔さ優先で api/streamlit 共用 |

> Streamlit→api は**サーバ間呼び出し**なので CORS 不要。CORS 対象はブラウザで動く **React だけ**。

## 構成ファイル

```
deploy/
  Dockerfile.api          # FastAPI（python:3.12-slim, uvicorn, $PORT待受）
  Dockerfile.streamlit    # Streamlit（--server.port=$PORT --server.address=0.0.0.0 --headless）
  cloudbuild.api.yaml      # Dockerfile.api をビルド→Artifact Registry へ push
  cloudbuild.streamlit.yaml
  README.md                # 実デプロイ手順（gcloud コマンド一式）
.dockerignore / .gcloudignore  # .env 等の秘密と node_modules/tests/docs を除外
```

- **Python 3.12 固定**: ローカルは 3.14 だが、ortools 等の wheel 提供が安定している 3.12 をイメージに採用。
- **秘密情報**: `GEMINI_API_KEY` / `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` は
  `.env` を**イメージに入れず** Secret Manager から注入（`.dockerignore`/`.gcloudignore` で `.env` 除外）。
- **リージョン**: `asia-northeast1`（東京）。Supabase も東京リージョンで近接。

## 未決定・残り

1. **React の配信方法**（ローカル実行 / FastAPI同梱 / 別ホスティング）。決まり次第 README 8章とCORSを確定。
2. 据え置き永続化3バケット（pending_queue/masters/frame）の本配線（[[11_persistence]]）。
3. 実デプロイ（ビルド→デプロイ→疎通）と提出物（URL・READMEなど）。
