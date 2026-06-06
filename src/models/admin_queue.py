"""
サイト管理者の承認キューモデル

役割:
  - パーサで検出された「未知タイプ」を一元管理
  - 同じ未知タイプを複数文言で受けた場合に source_texts に集約（クラスタリング）
  - Gemini Pro が生成した新type候補・スキーマ・ハンドラコード・テスト結果を保持
  - 承認/却下の状態管理
  - 承認時に再計算すべきシフトIDを affected_shift_ids で追跡
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TestResult(BaseModel):
    """サンドボックスで実行したテストの結果"""
    model_config = ConfigDict(extra="forbid")

    passed: bool                # すべてのテストが通ったか
    total: int                  # テストケース数
    passed_count: int           # 通った数
    failed_cases: list[str] = []  # 失敗したケースの説明
    elapsed_ms: int = 0


class PendingTypeRequest(BaseModel):
    """サイト管理者の承認待ち1件分"""
    model_config = ConfigDict(extra="forbid")

    id: str
    suggested_type_name: str             # AIが提案する新type名（例: "recurring_day_off"）
    source_texts: list[str]              # 同じ未知タイプに該当する自然言語の集合（クラスタリング結果）
    occurrence_count: int = 1            # 何件のリクエストで現れたか

    # 人が読んで承認判断するための補助（パース時にFlashが付与）
    summary: Optional[str] = None        # 一言で何のルールか（日本語）
    ai_assessment: Optional[str] = None  # AIの見解（なぜ未知か／どう解釈したか）
    review_points: list[str] = []        # 管理者に確認してほしい点

    # Gemini Pro が生成した内容
    suggested_schema: Optional[dict] = None       # 新typeのJSONスキーマ
    suggested_handler_code: Optional[str] = None  # ハンドラ関数のPythonコード
    test_results: Optional[TestResult] = None     # サンドボックスでのテスト結果
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    concerns: list[str] = []             # AIが自己申告する懸念点

    # ワークフロー状態
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewer_id: Optional[str] = None
    review_comment: Optional[str] = None

    # 再計算対象の追跡
    affected_shift_ids: list[str] = []   # この承認で再計算が必要なシフトID一覧
