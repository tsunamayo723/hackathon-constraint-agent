# 仕様書 12 — デプロイ（Cloud Run ×2）の下ごしらえ

*最終更新: 2026-06-25（React配信方法を (b) FastAPI同梱に決定し、Dockerfile.api を多段ビルド化。実デプロイは未実施）*

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
| `deploy/Dockerfile.api` を多段ビルド化＋`src/api/main.py` で静的配信 | **React提出者UIをFastAPIに同梱**（配信方法(b)）。①Nodeの箱で `npm run build`→②Python箱に `dist/` だけコピー。`"/"`＝React提出者UI / `/about`＝システム説明 / `/docs`＝Swagger |
| `frontend/src/api.ts` のAPIベース既定 | `\|\|`→`??` に変更。同梱時に `VITE_API_BASE=""`（空文字＝同一オリジンの相対パス）を尊重するため。未指定時のローカル既定 `http://localhost:8001` は不変 |

> Streamlit→api は**サーバ間呼び出し**なので CORS 不要。CORS 対象はブラウザで動く **React だけ**。

## 構成ファイル

```
deploy/
  Dockerfile.api          # 多段: ①node で React build → ②python:3.12-slim に dist 同梱 + uvicorn（$PORT待受）
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

## 決定・残り

1. ✅ **React の配信方法 = (b) FastAPI同梱に決定**（2026-06-25）。`"/"`がReact、`/about`が説明、`/docs`がSwagger。
   **同一オリジンなので React 用の CORS は不要**（`ALLOWED_ORIGINS` は将来の別ホスティング用に残置）。
2. 据え置き永続化3バケット（pending_queue/masters/frame）の本配線（[[11_persistence]]）。
3. 実デプロイ（ビルド→デプロイ→疎通）と提出物（URL・READMEなど）。Cloud Run は **api / streamlit の2サービス**（Reactは api に同梱）。
