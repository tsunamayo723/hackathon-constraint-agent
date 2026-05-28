"""
パーサ・管理者キュー・拡張SolverOutputのモデル動作確認
"""

from datetime import datetime

from src.models import (
    HeadcountRequirement,
    ParserOutput,
    PendingTypeRequest,
    SolverOutput,
    TestResult,
    TranslatedConstraint,
    UntranslatedConstraint,
)


# ── 翻訳できた制約 ──────────────────────────────────────────────────

def test_translated_constraint_basic():
    tc = TranslatedConstraint(
        constraint=HeadcountRequirement(params={
            "slot_label": "ランチ",
            "time_start": "11:00",
            "time_end": "14:00",
            "position_id": "pos_hall",
            "count": 4,
        }),
        source_text="ランチに4人入れて",
        confidence=0.95,
    )
    assert tc.constraint.type == "headcount_requirement"
    assert tc.source_text == "ランチに4人入れて"


# ── 翻訳できなかった文言 ────────────────────────────────────────────

def test_untranslated_constraint_pending_by_default():
    uc = UntranslatedConstraint(
        source_text="毎週水曜は習い事があって入れません",
        suggested_type_name="recurring_day_off",
        reason="毎週○曜日という繰り返しパターンは現在対応中のルールです",
    )
    assert uc.status == "pending_review"  # デフォルト
    assert uc.pending_request_id is None  # キュー登録前


# ── パーサ出力 ──────────────────────────────────────────────────────

def test_parser_output_has_untranslated_flag():
    output = ParserOutput(
        input_text="10時から入れます。毎週水曜は習い事で休みです。",
        translated=[],
        untranslated=[
            UntranslatedConstraint(
                source_text="毎週水曜は習い事で休みです",
                reason="繰り返しパターンは対応中です",
            )
        ],
        parsed_at=datetime(2026, 5, 28, 12, 0),
    )
    assert output.has_untranslated is True


def test_parser_output_no_untranslated():
    output = ParserOutput(
        input_text="ランチに4人",
        translated=[
            TranslatedConstraint(
                constraint=HeadcountRequirement(params={
                    "slot_label": "ランチ", "time_start": "11:00", "time_end": "14:00",
                    "position_id": "pos_hall", "count": 4,
                }),
                source_text="ランチに4人",
                confidence=0.9,
            )
        ],
        untranslated=[],
        parsed_at=datetime(2026, 5, 28, 12, 0),
    )
    assert output.has_untranslated is False


# ── 管理者キュー ────────────────────────────────────────────────────

def test_pending_type_request_basic():
    req = PendingTypeRequest(
        id="req_001",
        suggested_type_name="recurring_day_off",
        source_texts=[
            "毎週水曜は習い事で休みです",
            "水曜は基本入れません",
        ],
        occurrence_count=2,
        confidence=0.78,
        concerns=["「習い事」の意味的解釈に依存"],
        created_at=datetime(2026, 5, 28, 12, 0),
    )
    assert req.status == "pending"  # デフォルト
    assert req.reviewed_at is None
    assert len(req.source_texts) == 2


def test_test_result_passed():
    tr = TestResult(passed=True, total=5, passed_count=5, elapsed_ms=320)
    assert tr.passed is True
    assert tr.failed_cases == []


def test_test_result_failed():
    tr = TestResult(
        passed=False, total=5, passed_count=3,
        failed_cases=["weekday=invalid のとき例外", "境界値テスト失敗"],
    )
    assert tr.passed is False


# ── SolverOutput の暫定/確定 ────────────────────────────────────────

def test_solver_output_confirmed_default():
    output = SolverOutput(status="solved")
    assert output.shift_status == "confirmed"
    assert output.pending_constraints == []
    assert output.recalculation_needed is False


def test_solver_output_provisional():
    output = SolverOutput(
        status="solved",
        shift_status="provisional",
        pending_constraints=[
            UntranslatedConstraint(
                source_text="毎週水曜は習い事で休みです",
                reason="繰り返しパターンは対応中です",
            )
        ],
    )
    assert output.shift_status == "provisional"
    assert len(output.pending_constraints) == 1
