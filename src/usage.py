"""
Gemini 利用量・概算料金トラッカー

Gemini APIのレスポンスに含まれる usage_metadata（入力/出力トークン数）から、
- 1回ごとの消費トークン・概算料金
- セッション内（プロセス起動中）の累計
を計算する。DBは不要（後でSupabaseに貯めれば日次/月次ダッシュボードにできる）。

※ 単価は「概算」。公式の料金ページで確認して PRICING_USD_PER_1M を更新すること。
"""

import os

# モデル別の単価（USD / 100万トークン）。★概算★ 公式pricingで要確認・更新。
PRICING_USD_PER_1M = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}
# 未知モデルはFlash相当で概算
_DEFAULT_PRICE = {"input": 0.30, "output": 2.50}

USD_TO_JPY = float(os.environ.get("USD_TO_JPY", "150"))


def _price_for(model: str) -> dict:
    for name, price in PRICING_USD_PER_1M.items():
        if name in model:
            return price
    return _DEFAULT_PRICE


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    """トークン数から概算料金（USD/JPY）を計算する。"""
    p = _price_for(model)
    usd = input_tokens / 1_000_000 * p["input"] + output_tokens / 1_000_000 * p["output"]
    return {"usd": round(usd, 6), "jpy": round(usd * USD_TO_JPY, 4)}


# ── セッション内の累計（インメモリ。再起動で消える） ──────────────────

# model -> {"calls", "input_tokens", "output_tokens", "total_tokens", "usd", "jpy"}
_totals: dict[str, dict] = {}


def record(model: str, input_tokens: int, output_tokens: int) -> dict:
    """1回分の利用を記録し、その回の概算（トークン・料金）を返す。"""
    total_tokens = input_tokens + output_tokens
    cost = estimate_cost(model, input_tokens, output_tokens)

    t = _totals.setdefault(model, {
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "total_tokens": 0, "usd": 0.0, "jpy": 0.0,
    })
    t["calls"] += 1
    t["input_tokens"] += input_tokens
    t["output_tokens"] += output_tokens
    t["total_tokens"] += total_tokens
    t["usd"] = round(t["usd"] + cost["usd"], 6)
    t["jpy"] = round(t["jpy"] + cost["jpy"], 4)

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "usd": cost["usd"],
        "jpy": cost["jpy"],
    }


def session_summary() -> dict:
    """セッション内の累計（モデル別＋合計）を返す。"""
    grand = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
             "total_tokens": 0, "usd": 0.0, "jpy": 0.0}
    for t in _totals.values():
        for k in grand:
            grand[k] = round(grand[k] + t[k], 6)
    return {
        "為替レート(USD→JPY)": USD_TO_JPY,
        "注記": "単価は概算です。公式pricingで PRICING_USD_PER_1M を更新してください。",
        "モデル別": _totals,
        "合計": grand,
    }
