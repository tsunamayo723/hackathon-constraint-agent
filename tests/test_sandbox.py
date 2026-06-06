"""
サンドボックス（生成ハンドラの安全実行）のテスト

Geminiは使わない（生成済みコード文字列を渡して subprocess 実行を確認するだけ）。
- 正しいハンドラ → 合格
- 無限ループ → タイムアウトで打ち切り
- 例外を投げるコード → 失敗として捕捉
- handle未定義 → 失敗
"""

from src.sandbox import run_handler_test

GOOD_HANDLER = """
def handle(params, ctx):
    weekday_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
                   "friday":4,"saturday":5,"sunday":6}
    pid = params.get("person_id")
    wd = weekday_map.get(str(params.get("weekday","")).lower())
    if pid not in ctx.person_ids or wd is None:
        return
    for di, day in enumerate(ctx.days):
        if day.weekday() == wd:
            for slot in ctx.slots:
                ctx.model.Add(ctx.present[(pid, di, slot.index)] == 0)
"""


def test_good_handler_passes():
    res = run_handler_test(GOOD_HANDLER, {"person_id": "p1", "weekday": "wednesday"})
    assert res["passed"] is True


def test_infinite_loop_times_out():
    code = "def handle(params, ctx):\n    while True:\n        pass\n"
    res = run_handler_test(code, {}, timeout_sec=3)
    assert res["passed"] is False
    assert "タイムアウト" in res["message"]


def test_raising_handler_is_caught():
    code = "def handle(params, ctx):\n    raise ValueError('boom')\n"
    res = run_handler_test(code, {})
    assert res["passed"] is False
    assert "実行エラー" in res["message"]


def test_missing_handle_function():
    code = "x = 1  # handle が無い\n"
    res = run_handler_test(code, {})
    assert res["passed"] is False
