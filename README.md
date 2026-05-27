# 制約管理エージェント

> 自然言語の定性的な制約を、最適化ソルバー(OR-Tools)が理解できる数式に変換する汎用エージェント

DevOps × AI Agent Hackathon 2026 への応募作品。

---

## このプロダクトは何か

新しい要件をAIが検出 → 自分で処理ロジック(ハンドラ)を書く → テストする → 動いたら人間に承認を求める、という**自律エージェント**。

デモドメインは **飲食店シフト**(30人 × 1ヶ月)。

---

## クイックスタート(開発時)

```bash
# 仮想環境(後で整備)
python -m venv venv
source venv/bin/activate  # Mac/Linux
.\venv\Scripts\activate   # Windows

# 依存インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .env を編集してAPIキー等を設定

# ローカル起動(後で実装)
# uvicorn app.main:app --reload
# streamlit run app/ui.py
```

---

## ドキュメント

| ファイル | 内容 |
|---|---|
| [CLAUDE.md](./CLAUDE.md) | Claude Code向けプロジェクトコンテキスト |
| [docs/00_overview.md](./docs/00_overview.md) | プロジェクト全体像 |
| [docs/01_handover_original.md](./docs/01_handover_original.md) | 設計詳細(type辞書、ソルバーI/O等) |
| [docs/02_hackathon_rules.md](./docs/02_hackathon_rules.md) | ハッカソン要項 |
| [docs/03_tech_stack.md](./docs/03_tech_stack.md) | 技術スタック詳細 |
| [docs/04_input_flow.md](./docs/04_input_flow.md) | 入力フロー設計 |
| [docs/05_remaining_tasks.md](./docs/05_remaining_tasks.md) | 残タスク一覧 |
| [docs/99_decisions_log.md](./docs/99_decisions_log.md) | 決定事項ログ |

---

## 技術スタック

- Python 3.11+
- FastAPI(バックエンドAPI)
- Streamlit(デモUI)
- OR-Tools(CP-SAT ソルバー)
- Gemini API(Flash + Pro カスケード)
- Cloud Run(デプロイ先)
- Supabase(PostgreSQL + JSONB)

---

## ライセンス

未定(ハッカソン応募完了後に決定)

---

## 作者

(個人開発)
