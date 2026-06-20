import { useEffect, useState } from "react"
import { approvePending, generatePending, getPendingType, getPendingTypes, rejectPending } from "../../api"
import type { PendingType } from "../../types"

const REJECT_LABEL: Record<string, string> = {
  negotiation_dependent: "他者の希望に依存（交渉が必要）",
  history_dependent: "過去の実績データが必要",
  missing_data: "手持ちに無いデータが必要",
  subjective: "主観的で数値化できない",
  advanced_logic: "高度な条件ロジックが必要（現在の部品で表現不可）",
}

// ④ 承認キュー（L2の山場）— Pro生成→テスト→承認
export function ApproveStep() {
  const [items, setItems] = useState<PendingType[]>([])
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState<string | null>(null)
  const [err, setErr] = useState("")
  const [msg, setMsg] = useState("")
  const [feedbacks, setFeedbacks] = useState<Record<string, string>>({})

  async function fetchList() {
    setLoading(true)
    setErr("")
    try {
      setItems(await getPendingTypes("pending"))
    } catch (e) {
      setErr(e instanceof Error ? e.message : "一覧の取得に失敗しました")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchList() }, [])

  function replaceItem(updated: PendingType) {
    setItems((list) => list.map((it) => (it.id === updated.id ? updated : it)))
  }

  async function generate(id: string) {
    setWorking(id)
    setErr("")
    setMsg("")
    try {
      await generatePending(id, feedbacks[id] || "")
      replaceItem(await getPendingType(id))
    } catch (e) {
      setErr(e instanceof Error ? e.message : "生成に失敗しました")
    } finally {
      setWorking(null)
    }
  }

  async function generateAll() {
    setWorking("__all__")
    setErr("")
    setMsg("")
    try {
      const targets = items.filter((it) => !it.test_results)
      for (const it of targets) {
        try {
          await generatePending(it.id, "")
        } catch {
          /* 1件失敗しても続ける */
        }
      }
      await fetchList()
      setMsg(`${targets.length}件のレシピを生成しました`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "一括生成に失敗しました")
    } finally {
      setWorking(null)
    }
  }

  async function decide(id: string, approve: boolean) {
    setWorking(id)
    setErr("")
    setMsg("")
    try {
      if (approve) await approvePending(id)
      else await rejectPending(id)
      setMsg(approve ? "✅ 承認しました（以降ソルバーで使われます）" : "却下しました")
      await fetchList()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "処理に失敗しました")
    } finally {
      setWorking(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-800">④ 承認（自律エージェントの山場）</h2>
          <p className="text-xs text-gray-400">
            未知ルールに対しAIがレシピを生成→テスト→人間が承認。承認後はソルバーで自動利用されます。
          </p>
        </div>
        <div className="flex gap-2">
          {items.some((it) => !it.test_results) && (
            <button
              type="button"
              onClick={generateAll}
              disabled={working === "__all__"}
              className="rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              {working === "__all__" ? "生成中…" : "🤖 全部のレシピを生成"}
            </button>
          )}
          <button
            type="button"
            onClick={fetchList}
            className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
          >
            {loading ? "更新中…" : "更新"}
          </button>
        </div>
      </div>

      {err && <p className="text-sm text-red-600">⚠️ {err}</p>}
      {msg && <p className="text-sm text-emerald-700">{msg}</p>}

      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-500">
          承認待ちはありません。③で店舗の要望（未知ルール）を入れると、ここに届きます。
        </p>
      ) : (
        <div className="space-y-3">
          {items.map((it) => {
            const busy = working === it.id
            const generated = !!it.test_results
            const passed = it.test_results?.passed
            return (
              <div key={it.id} className="rounded-lg border border-gray-200 p-3">
                {/* 見出し */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-violet-100 px-2 py-0.5 text-sm font-medium text-violet-800">
                    🆕 {it.suggested_type_name}
                  </span>
                  <span className="text-xs text-gray-400">{it.occurrence_count}件の要望</span>
                </div>
                {it.summary && <p className="mt-1 text-sm text-gray-700">{it.summary}</p>}
                {it.ai_assessment && <p className="mt-0.5 text-xs text-gray-500">AIの見解：{it.ai_assessment}</p>}

                {/* 元の要望 */}
                <ul className="mt-2 space-y-0.5 text-xs text-gray-500">
                  {it.source_texts.map((s, i) => (
                    <li key={i}>・「{s}」</li>
                  ))}
                </ul>

                {/* 生成前 → 生成ボタン */}
                {!generated && (
                  <button
                    type="button"
                    onClick={() => generate(it.id)}
                    disabled={busy}
                    className="mt-3 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
                  >
                    {busy ? "生成中…（Pro）" : "🤖 AIにレシピを生成（Pro）"}
                  </button>
                )}

                {/* 生成後 */}
                {generated && (
                  <div className="mt-3 space-y-2 border-t border-gray-100 pt-3">
                    {it.expressible === false ? (
                      <div className="rounded-lg border border-red-300 bg-red-50 p-2.5 text-sm text-red-700">
                        ❌ この要望は今の部品では表現できません
                        {it.reject_category && <span className="ml-1">（{REJECT_LABEL[it.reject_category] ?? it.reject_category}）</span>}
                        {it.test_results?.detail && <p className="mt-1 text-xs text-red-600">{it.test_results.detail}</p>}
                      </div>
                    ) : (
                      <>
                        {/* レシピ */}
                        <div>
                          <p className="text-xs font-medium text-gray-600">生成されたレシピ（操作×選択子）</p>
                          <pre className="mt-1 overflow-x-auto rounded bg-gray-900 p-2 text-[11px] text-gray-100">
                            {JSON.stringify(it.suggested_recipe, null, 2)}
                          </pre>
                        </div>
                        {/* テスト結果 */}
                        <p className={"text-sm " + (passed ? "text-emerald-700" : "text-amber-700")}>
                          {passed ? "✅ テスト合格" : "❌ テスト不合格"}
                          {!passed && it.test_results?.failed_cases?.length ? (
                            <span className="ml-1 text-xs">（{it.test_results.failed_cases.join(" / ")}）</span>
                          ) : null}
                        </p>
                        <p className="text-xs text-gray-500">
                          自信度：{Math.round(it.confidence * 100)}%
                          {it.concerns && it.concerns.length > 0 && <span className="ml-2">懸念：{it.concerns.join(" / ")}</span>}
                        </p>
                      </>
                    )}

                    {/* 回答して再生成（却下や懸念・テスト不合格に応えて作り直す） */}
                    <div className="rounded-lg border border-blue-200 bg-blue-50 p-2.5">
                      <p className="mb-1.5 text-xs font-medium text-blue-800">
                        🤖 AIに追加で伝えて作り直す（却下・懸念・テスト不合格があればここで回答）
                      </p>
                      <div className="flex gap-2">
                        <input
                          value={feedbacks[it.id] ?? ""}
                          onChange={(e) => setFeedbacks((f) => ({ ...f, [it.id]: e.target.value }))}
                          onKeyDown={(e) => e.key === "Enter" && !busy && generate(it.id)}
                          placeholder="例：遅番は18時以降／月曜だけ／新人はキッチン"
                          className="flex-1 rounded-lg border border-blue-300 bg-white px-3 py-1.5 text-xs"
                        />
                        <button
                          type="button"
                          onClick={() => generate(it.id)}
                          disabled={busy}
                          className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
                        >
                          {busy ? "再生成中…" : "🔄 再生成"}
                        </button>
                      </div>
                    </div>

                    {/* 承認 / 却下 */}
                    <div className="flex gap-2 pt-1">
                      {it.expressible !== false && passed && (
                        <button
                          type="button"
                          onClick={() => decide(it.id, true)}
                          disabled={busy}
                          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
                        >
                          {busy ? "処理中…" : "承認する"}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => decide(it.id, false)}
                        disabled={busy}
                        className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                      >
                        却下
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
