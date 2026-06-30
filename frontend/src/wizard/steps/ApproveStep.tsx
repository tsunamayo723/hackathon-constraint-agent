import { useEffect, useState } from "react"
import {
  approvePending, generatePending, getPendingTypes, recipeChat, rejectPending,
} from "../../api"
import type { ChatMessage, PendingType } from "../../types"

const REJECT_LABEL: Record<string, string> = {
  negotiation_dependent: "他者の希望に依存（交渉が必要）",
  history_dependent: "過去の実績データが必要",
  missing_data: "手持ちに無いデータが必要",
  subjective: "主観的で数値化できない",
  advanced_logic: "高度な条件ロジックが必要（現在の部品で表現不可）",
}

// ④ 承認キュー（L2の山場）— Pro生成→テスト→承認。作り直しの相談は下部の「まとめチャット」1つで行う。
export function ApproveStep() {
  const [items, setItems] = useState<PendingType[]>([])
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState<string | null>(null)
  const [err, setErr] = useState("")
  const [msg, setMsg] = useState("")

  // 生成済みルールを「全部まとめて」仕上げる会話（履歴はクライアントが保持し毎回渡す）
  const [chat, setChat] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState("")
  const [chatBusy, setChatBusy] = useState(false)

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

  async function generate(id: string) {
    setWorking(id)
    setErr("")
    setMsg("")
    try {
      await generatePending(id, "")
      await fetchList()
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

  // まとめチャット送信：AIがどのルールの話かを判断して該当カードを作り直す
  async function sendChat() {
    const text = chatInput.trim()
    if (!text || chatBusy) return
    setChatBusy(true)
    setErr("")
    setMsg("")
    // 楽観的に自分の発言を出す
    setChat((c) => [...c, { role: "user", text }])
    setChatInput("")
    try {
      const res = await recipeChat(text, chat)
      setChat(res.history) // サーバが返した正の履歴（user＋ai）に置き換え
      await fetchList() // 作り直したレシピを一覧に反映
      if (res.updated_ids.length > 0) {
        setMsg(`🔄 ${res.updated_ids.length}件のルールを作り直しました`)
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "相談に失敗しました")
      setChat((c) => c.slice(0, -1)) // 失敗したら楽観表示を取り消す
      setChatInput(text)
    } finally {
      setChatBusy(false)
    }
  }

  const hasGenerated = items.some((it) => !!it.test_results)

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

      {/* 🤖 まとめチャット：生成済みルール全部を1つの会話で作り直す */}
      {items.length > 0 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm font-semibold text-blue-900">🤖 AIとまとめて相談（生成済みルール全部・履歴あり）</p>
          {!hasGenerated ? (
            <p className="mt-1 text-xs text-blue-700">
              先に上の「🤖 全部のレシピを生成」でレシピを作ると、ここでまとめて調整できます。
            </p>
          ) : (
            <>
              <p className="mt-0.5 mb-2 text-xs text-blue-700">
                例：「遅番の上限は月2回にして」「新人のは22時以降だけにして」。
                どのルールの話かはAIが判断して、その分だけ作り直します。
              </p>
              {chat.length > 0 && (
                <div className="mb-2 max-h-60 space-y-1.5 overflow-y-auto">
                  {chat.map((m, i) => (
                    <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                      <span
                        className={
                          "inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-2.5 py-1.5 text-xs " +
                          (m.role === "user"
                            ? "bg-blue-600 text-white"
                            : "border border-blue-200 bg-white text-gray-800")
                        }
                      >
                        {m.text}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendChat()}
                  disabled={chatBusy}
                  placeholder="直したい内容を入力（例：遅番は月2回まで）"
                  className="flex-1 rounded-lg border border-blue-300 bg-white px-3 py-1.5 text-xs"
                />
                <button
                  type="button"
                  onClick={sendChat}
                  disabled={chatBusy || !chatInput.trim()}
                  className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
                >
                  {chatBusy ? "相談中…" : "送信"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
