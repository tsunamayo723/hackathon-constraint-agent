import { useState } from "react"
import { clarifyNote } from "../../api"
import type { ChatMessage, ChatTurn } from "../../types"

const REJECT_LABEL: Record<string, string> = {
  negotiation_dependent: "他者の希望しだい（交渉が必要）",
  history_dependent: "過去の実績が必要",
  missing_data: "手元にないデータが必要",
  subjective: "数値にできない主観的な希望",
  advanced_logic: "他者に依存する高度な条件",
}

// ③ 店全体の要望（管理者）— ②と同じAIチャットで整理。新ルールは④の承認へ
export function PolicyStep() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [answer, setAnswer] = useState("")
  const [clarifying, setClarifying] = useState(false)
  const [err, setErr] = useState("")
  const [turn, setTurn] = useState<ChatTurn | null>(null)
  const [firstNote, setFirstNote] = useState("")

  async function send() {
    const text = answer.trim()
    if (!text) return
    const isFirst = !messages.some((m) => m.role === "user")
    const useNote = isFirst ? text : firstNote || text
    if (isFirst) setFirstNote(text)
    const history: ChatMessage[] = [...messages, { role: "user", text }]
    setMessages(history)
    setAnswer("")
    setClarifying(true)
    setErr("")
    try {
      const t = await clarifyNote(useNote, "store", null, history)
      setMessages([...history, { role: "ai", text: t.reply }])
      setTurn(t)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "会話に失敗しました")
    } finally {
      setClarifying(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-800">③ 店全体の要望（管理者）</h2>
        <p className="text-xs text-gray-400">
          店舗のルールをAIに相談します。新しい種類のルールは④の承認へ送られます。（任意・無ければ飛ばしてOK）
        </p>
      </div>

      {messages.length === 0 ? (
        <p className="text-sm text-gray-500">
          例：「新人だけの時間帯は作らないで」「朝の人数を増やしたい」「ディナーは各ポジション最低1人」
        </p>
      ) : (
        <div className="space-y-2 rounded-lg bg-gray-50 p-3">
          {messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
              <span
                className={
                  "inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
                  (m.role === "user" ? "bg-blue-600 text-white" : "bg-white text-gray-800 shadow-sm")
                }
              >
                {m.role === "ai" ? "🤖 " : ""}
                {m.text}
              </span>
            </div>
          ))}
          {clarifying && <p className="text-xs text-gray-400">AIが考えています…</p>}
        </div>
      )}

      {err && <p className="text-sm text-red-600">⚠️ {err}</p>}

      <div className="flex gap-2">
        <input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !clarifying && send()}
          placeholder={messages.length === 0 ? "店舗のルールを入力…" : "回答を入力…"}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={send}
          disabled={clarifying || !answer.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
        >
          {messages.length === 0 ? "AIに相談" : "送信"}
        </button>
      </div>

      {/* 整理できた要望 */}
      {turn && !turn.needs_clarification && turn.rules.length > 0 && (
        <div className="space-y-1.5">
          {turn.queued ? (
            <p className="text-xs font-medium text-violet-700">🆕 {turn.queued}件を④の承認へ送りました</p>
          ) : null}
          {turn.rules.map((r, i) => {
            if (r.decision === "queue") {
              return (
                <div key={i} className="rounded-lg border border-violet-200 bg-violet-50 p-2.5 text-sm text-violet-800">
                  🆕 {r.summary}
                  {r.suggested_type_name && (
                    <span className="ml-1 rounded bg-violet-200 px-1.5 py-0.5 text-xs">{r.suggested_type_name}</span>
                  )}
                  <span className="ml-1 text-xs">（→④の承認へ）</span>
                </div>
              )
            }
            if (r.decision === "memo") {
              return (
                <div key={i} className="rounded-lg border border-gray-300 bg-white p-2.5 text-sm text-gray-600">
                  📝 {r.summary}（申し送り）
                </div>
              )
            }
            return (
              <div key={i} className="rounded-lg border border-red-300 bg-red-50 p-2.5 text-sm text-red-700">
                ❌ {r.summary}
                <span className="ml-1 text-xs">（{REJECT_LABEL[r.reject_category] ?? "今の仕組みでは表現できません"}）</span>
              </div>
            )
          })}
          <p className="text-xs text-emerald-700">「次へ」で④の承認に進みます。</p>
        </div>
      )}
    </div>
  )
}
