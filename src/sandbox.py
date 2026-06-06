"""
サンドボックス（生成ハンドラの安全実行）

AIが生成したハンドラコードを **別プロセス＋タイムアウト** で実行し、
小さなシナリオで「エラーなく動くか／解けるか」をテストする。

設計（CLAUDE.md）: サンドボックス = Python subprocess + タイムアウト。
無限ループや暴走コードはタイムアウトで打ち切る。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# プロジェクトルート（src の1つ上）。subprocess の作業ディレクトリに使う。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIMEOUT_SEC = 8


def run_handler_test(handler_code: str, example_params: dict,
                     timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> dict:
    """
    生成ハンドラを別プロセスでテスト実行する。

    返り値: {"passed": bool, "message": str, ("traceback": str)}
    """
    with tempfile.TemporaryDirectory() as tmp:
        code_file = Path(tmp) / "handler_code.py"
        params_file = Path(tmp) / "params.json"
        code_file.write_text(handler_code, encoding="utf-8")
        params_file.write_text(json.dumps(example_params, ensure_ascii=False), encoding="utf-8")

        # 子プロセスの出力を必ずUTF-8にし、src を import できるようにする
        # （uvicorn から起動された場合に PYTHONPATH/エンコーディングが無い問題への対策）
        child_env = dict(os.environ)
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONPATH"] = str(_PROJECT_ROOT)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "src._sandbox_harness", str(code_file), str(params_file)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                cwd=str(_PROJECT_ROOT),
                env=child_env,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "message": f"タイムアウト（{timeout_sec}秒）。無限ループの可能性があります。",
            }

        out = (proc.stdout or "").strip()
        if not out:
            return {
                "passed": False,
                "message": f"出力がありませんでした。エラー: {(proc.stderr or '')[-400:]}",
            }

        # ハーネスは結果JSONを最終行に出す
        try:
            return json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            return {"passed": False, "message": f"結果の解析に失敗: {out[-400:]}"}
