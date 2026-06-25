"""
制約管理エージェント — FastAPI アプリ本体

エンドポイントは役割ごとにルーターに分割している:
  - routes_parser.py … 自然言語パース
  - routes_admin.py  … サイト管理者の承認キュー
"""

import os

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from src.models import (
    Constraint,
    KNOWN_TYPES,
    SolverInput,
)
from src.api.routes_parser import router as parser_router
from src.api.routes_admin import router as admin_router
from src.api.routes_chat import router as chat_router
from src.api.routes_setup import router as setup_router
from src.api.routes_solver import router as solver_router
from src.api.routes_submit import router as submit_router


tags_metadata = [
    {
        "name": "システム",
        "description": "サーバーの状態確認など、運用用のエンドポイント。",
    },
    {
        "name": "セットアップ",
        "description": (
            "月次シフト作成の**土台**を登録します。\n\n"
            "- **マスタ**（人/役職/ポジション/スキル）… CSVアップロード由来\n"
            "- **営業情報**（期間/営業時間/ポリシー）… フォーム入力由来\n\n"
            "Streamlitの「① セットアップ画面」から呼ばれます。"
        ),
    },
    {
        "name": "パーサ",
        "description": (
            "自然言語をパースして既知/未知の制約に振り分けます。\n\n"
            "**未翻訳の文言**は元の自然言語のまま残し、ユーザー画面で「保留中」として表示できる設計です。"
        ),
    },
    {
        "name": "制約管理",
        "description": (
            "シフトの「条件・ルール」を管理するエンドポイント。\n\n"
            "**既知の16タイプ**はそのまま検証。"
            "**未知のタイプ**は `is_new_type: true` を返し、AIによる自動ハンドラ生成フロー（L2）へ進みます。"
        ),
    },
    {
        "name": "ソルバー",
        "description": (
            "OR-Tools（最適化エンジン）でシフトを計算します。\n\n"
            "- `/solver/run` … 実際のシフト計算（最小ソルバー: headcount/availability/separate 対応）\n"
            "- `/solver/validate-input` … 入力データの形式チェックのみ"
        ),
    },
    {
        "name": "管理者承認",
        "description": (
            "**サイト管理者向け**の未知タイプ承認キュー。\n\n"
            "実サービスではプロダクト提供側のスタッフが横断的に承認します。"
            "ハッカソンデモではこの画面を見せて「実運用ではここが管理者画面です」と説明します。"
        ),
    },
    {
        "name": "提出者チャット",
        "description": (
            "**提出者向け**の備考(note)確認チャット。\n\n"
            "デモの主役UI（React）から呼ばれます。Gemini(Flash)が曖昧な備考を短く聞き返し、"
            "はっきりしたら確定要約を返します。表現できない要望は正直に拒否します。"
        ),
    },
]


app = FastAPI(
    title="制約管理エージェント API",
    description="""
## このAPIは何をするものか

**自然言語で書かれたシフトの条件を、最適化ソルバーが計算できる形式に変換するエージェントのバックエンドです。**

---

### 処理の流れ

```
スタッフの要望（自然言語）
  ↓
[パーサ] 既知タイプ → 翻訳済みリストへ / 未知タイプ → 未翻訳リスト + 管理者キューへ
  ↓
[ソルバー] 翻訳済みだけで暫定シフトを計算
  ↓
[ユーザー画面] 「✅ 反映済み」と「⏳ 確認中」を両方表示
  ↓
[サイト管理者] 未知タイプを承認 → 自動再計算 → ユーザー通知
```

---

### 設計の核心 — AIは分かったフリをしない

未翻訳の文言を黙って無視せず、元の自然言語のままユーザーに見せます。
「あなたの要望のうち、これは反映できました/これは確認中です」を明示するUX。
""",
    version="0.2.0",
    openapi_tags=tags_metadata,
)

# React開発サーバー(Vite)からのアクセスを許可する（CORS）。
# 本番(T6)の配信元は環境変数 ALLOWED_ORIGINS（カンマ区切り）で追加する。
#   例: ALLOWED_ORIGINS="https://my-react.web.app,https://example.com"
# ※ Streamlit→API はサーバ間呼び出しなので CORS 不要。対象はブラウザで動くReactだけ。
_default_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173",  # Vite 既定
    "http://localhost:3000", "http://127.0.0.1:3000",
]
_extra_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(setup_router)
app.include_router(parser_router)
app.include_router(solver_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(submit_router)


# ── システム説明ページ（/about）─────────────────────────────────────
# 本番では "/" を React 提出者UI が占有するため、システム説明はここに置く。

@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
def about():
    return """
    <html>
    <head>
      <meta charset="utf-8">
      <title>制約管理エージェント API</title>
      <style>
        body { font-family: sans-serif; max-width: 760px; margin: 60px auto; padding: 0 20px; color: #333; line-height:1.6; }
        h1 { color: #1a56db; }
        h2 { color: #1e3a8a; margin-top: 28px; }
        .flow { background:#f8fafc; padding:14px 20px; border-left:4px solid #1a56db; border-radius:4px; }
        a.btn { display:inline-block; background:#1a56db; color:white;
                padding:10px 24px; border-radius:6px; text-decoration:none;
                margin-top:16px; font-size:15px; }
        code { background:#f4f4f4; padding:2px 6px; border-radius:3px; }
        ul { padding-left:22px; }
      </style>
    </head>
    <body>
      <h1>🤖 制約管理エージェント API</h1>
      <p>自然言語のシフト要望を最適化ソルバー用 JSON に変換するAIエージェントです。</p>

      <h2>処理の流れ</h2>
      <div class="flow">
        <p>① スタッフが自然言語で要望を入力<br>
        ② <strong>パーサ</strong>が既知/未知に振り分け<br>
        ③ ソルバーが暫定シフトを計算（未翻訳は保留）<br>
        ④ ユーザー画面で「反映済み」「確認中」を両方表示<br>
        ⑤ サイト管理者が未知タイプを承認 → 自動再計算</p>
      </div>

      <h2>デモシナリオを試す</h2>
      <p>Swagger UIで <code>POST /parser/parse</code> を開き、Examplesから
      「② 既知 + 未知の混在」を選んで「Execute」を押してみてください。</p>
      <ul>
        <li>「ランチに4人」 → translated に headcount_requirement</li>
        <li>「毎週水曜は習い事で休み」 → untranslated に recurring_day_off候補</li>
      </ul>
      <p>続けて <code>GET /admin/pending-types</code> を見ると、
      未知タイプが自動で管理者キューに登録されているのが確認できます。</p>

      <a class="btn" href="/docs">📄 APIドキュメントを開く（Swagger UI）</a>
      <a class="btn" href="/">🎯 提出者UI（メイン画面）へ</a>
    </body>
    </html>
    """


# ── ヘルスチェック ──────────────────────────────────────────────────

@app.get(
    "/health",
    summary="サーバーの起動確認",
    description="サーバーが正常に起動しているか確認します。登録済みの制約タイプ数も返します。",
    tags=["システム"],
)
def health():
    return {"status": "正常", "登録済み制約タイプ数": len(KNOWN_TYPES)}


# ── 制約バリデーション ──────────────────────────────────────────────

_constraint_examples = {
    "① ホールに4名必要（Hard制約）": {
        "summary": "ランチ時間帯にホールスタッフが4名必要",
        "value": {
            "type": "headcount_requirement",
            "params": {
                "slot_label": "ランチ",
                "time_start": "11:00",
                "time_end": "14:00",
                "position_id": "pos_hall",
                "count": 4,
            },
        },
    },
    "② AさんとBさんは同じ日に入れない（Soft制約）": {
        "summary": "2人を同じ日に配置しない（weight=600）",
        "value": {
            "type": "separate",
            "params": {
                "person_a": "p1",
                "person_b": "p2",
                "scope": "day",
                "weight": 600,
            },
        },
    },
    "③ 田中さんの出勤希望（Soft制約）": {
        "summary": "月10〜15日の出勤を希望",
        "value": {
            "type": "desired_workdays",
            "params": {
                "person_id": "p1",
                "kind": "range",
                "min": 10,
                "max": 15,
                "weight": 400,
            },
        },
    },
    "④ 【デモ】毎週水曜は入れない → 未知タイプ検出": {
        "summary": "未知タイプ: recurring_day_off（AIが自動生成するタイプ）",
        "value": {
            "type": "recurring_day_off",
            "params": {"person_id": "p1", "weekday": "wednesday"},
        },
    },
}


@app.post(
    "/constraints/validate",
    summary="制約データの形式チェック・未知タイプ検出",
    description=(
        "1件の制約JSONを受け取り、既知16タイプか未知かを判定します。\n\n"
        "通常フローでは `/parser/parse` を使ってください。これは単発の形式チェック用です。"
    ),
    tags=["制約管理"],
)
def validate_constraint(body: dict = Body(openapi_examples=_constraint_examples)):
    type_name = body.get("type", "")

    if type_name not in KNOWN_TYPES:
        return {
            "有効": False,
            "未知のタイプ": True,
            "タイプ名": type_name,
            "メッセージ": f"未登録のタイプです: '{type_name}' → AIが新しいハンドラを自動生成します",
        }

    ta = TypeAdapter(Constraint)
    try:
        constraint = ta.validate_python(body)
        return {
            "有効": True,
            "未知のタイプ": False,
            "タイプ名": constraint.type,
            "パラメータ": constraint.params.model_dump(),
        }
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())


# ── ソルバー入力バリデーション ──────────────────────────────────────

_solver_input_example = {
    "シフト計算の全データ（サンプル）": {
        "summary": "2名・2制約の最小サンプル",
        "value": {
            "frame": {
                "period": {"start": "2026-11-01", "end": "2026-11-14"},
                "operating_window": {"open": "10:00", "close": "22:00", "slot_minutes": 30},
                "policy_mode": "wishes",
            },
            "masters": {
                "persons": [
                    {"id": "p1", "name": "田中", "role_id": "r_leader", "skill_ids": ["sk_cash"]},
                    {"id": "p2", "name": "鈴木", "role_id": "r_general", "skill_ids": []},
                ],
                "positions": [{"id": "pos_hall", "name": "ホール"}],
                "roles": [
                    {"id": "r_leader", "name": "リーダー"},
                    {"id": "r_general", "name": "一般"},
                ],
                "skills": [{"id": "sk_cash", "name": "レジ"}],
            },
            "constraints": [
                {
                    "type": "headcount_requirement",
                    "params": {
                        "slot_label": "ランチ",
                        "time_start": "11:00",
                        "time_end": "14:00",
                        "position_id": "pos_hall",
                        "count": 1,
                    },
                },
                {
                    "type": "separate",
                    "params": {"person_a": "p1", "person_b": "p2", "scope": "day", "weight": 600},
                },
            ],
        },
    }
}


@app.post(
    "/solver/validate-input",
    summary="ソルバー入力全体の形式チェック",
    description=(
        "シフト計算に必要なデータが揃っているか確認します。\n\n"
        "実際のシフト計算は `/solver/run`（実装予定）で行います。"
    ),
    tags=["ソルバー"],
)
def validate_solver_input(body: dict = Body(openapi_examples=_solver_input_example)):
    try:
        spec = SolverInput.model_validate(body)
        return {
            "有効": True,
            "概要": {
                "対象期間": f"{spec.frame.period.start} 〜 {spec.frame.period.end}",
                "計算方針": spec.frame.policy_mode,
                "スタッフ数": len(spec.masters.persons),
                "制約数": len(spec.constraints),
                "制約タイプ一覧": [c.type for c in spec.constraints],
            },
        }
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())


# ── React 提出者UI（本番は FastAPI に同梱して "/" で配信）──────────────
# ビルド済みフロント（frontend_dist/）が在れば "/" に静的マウントする。
#   ・本番(Cloud Run): Dockerfile.api が React をビルドして frontend_dist/ を同梱 → "/" がReact画面
#   ・ローカル開発:    dist が無い → マウントせず、"/" は説明ページ /about へ誘導
#                     （開発時の提出者UIは Vite の :5173 を別途使う）
# ※ このマウントは全ルーター登録の "後" に置く＝API窓口や /docs を邪魔しない（"/" は最後の受け皿）。
_FRONTEND_DIST = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend_dist")
)
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def _dev_root():
        # ビルド済みフロントが無い開発時は、説明ページへ誘導する。
        return RedirectResponse("/about")
