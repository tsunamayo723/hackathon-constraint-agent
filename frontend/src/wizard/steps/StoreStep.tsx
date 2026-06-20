import { useEffect, useState } from "react"
import { getDemoPatterns, loadDemo } from "../../api"
import type { DemoPattern } from "../../api"
import { useWizard } from "../context"

// ② 店舗の準備（デモパターンを選んで、他スタッフ・必要人数・営業情報を一括投入）
export function StoreStep() {
  const { reloadStage, masters, frame } = useWizard()
  const [patterns, setPatterns] = useState<DemoPattern[]>([])
  const [sel, setSel] = useState("")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [err, setErr] = useState("")

  useEffect(() => {
    getDemoPatterns()
      .then((r) => {
        setPatterns(r.patterns)
        if (r.patterns[0]) setSel(r.patterns[0].key)
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "一覧の取得に失敗しました"))
  }, [])

  async function load() {
    if (!sel) return
    setBusy(true)
    setErr("")
    setMsg("")
    try {
      const r = await loadDemo(sel)
      await reloadStage()
      setMsg(typeof r.結果 === "string" ? r.結果 : "投入しました")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "投入に失敗しました")
    } finally {
      setBusy(false)
    }
  }

  const desc = patterns.find((p) => p.key === sel)?.description ?? ""

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-800">① 店舗を準備する</h2>
        <p className="text-xs text-gray-400">
          まずデモパターン（どんなお店か）を選びます。スタッフ・必要人数・営業情報をまとめて投入します（CSV不要）。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={sel}
          onChange={(e) => setSel(e.target.value)}
          className="rounded border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          {patterns.map((p) => (
            <option key={p.key} value={p.key}>{p.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={load}
          disabled={!sel || busy}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
        >
          {busy ? "投入中…" : "この店舗で進む"}
        </button>
      </div>
      {desc && <p className="text-xs text-gray-500">{desc}</p>}

      {msg && <p className="text-sm text-emerald-700">✅ {msg}</p>}
      {err && <p className="text-sm text-red-600">⚠️ {err}</p>}

      <div className="rounded-lg bg-gray-50 p-3 text-sm text-gray-600">
        現在の店舗：スタッフ {masters.persons.length}名 ／ 期間 {frame.period.start}〜{frame.period.end}
        <p className="mt-1 text-xs text-gray-400">
          ※ 店舗を投入すると承認キューや過去の方針はクリアされます。次の②で本人の希望を入れてください。
        </p>
      </div>
    </div>
  )
}
