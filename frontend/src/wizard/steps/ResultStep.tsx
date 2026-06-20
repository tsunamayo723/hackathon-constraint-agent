import { useEffect, useState } from "react"
import {
  answerManagerQuestion,
  clarifyNote,
  getDesiredShifts,
  getManagerQuestions,
  getPendingTypes,
  storeCompare,
} from "../../api"
import type { ManagerQuestion, StoreCompare } from "../../api"
import { datesInPeriod, mmdd, weekdayLabel } from "../../lib/shift"
import { personInfo } from "../../lib/people"
import { useWizard } from "../context"
import type { AssignmentDict, PendingType } from "../../types"

function timeStr(a: AssignmentDict) {
  return `${a.start.slice(0, 5)}–${a.end.slice(0, 5)}`
}

// 割当リストを person|date でまとめ、各キーの時間帯文字列を作る
function indexTimes(list: AssignmentDict[]): Map<string, string> {
  const groups = new Map<string, AssignmentDict[]>()
  for (const a of list) {
    const k = `${a.person_id}|${a.date}`
    const arr = groups.get(k) ?? []
    arr.push(a)
    groups.set(k, arr)
  }
  const out = new Map<string, string>()
  for (const [k, arr] of groups) {
    out.set(k, arr.sort((x, y) => x.start.localeCompare(y.start)).map(timeStr).join(", "))
  }
  return out
}

// ⑤ シフト計算＋結果。note考慮「なし→あり」を1つの表に並べて見せる（スタッフごと・備考つき）
export function ResultStep() {
  const { masters, frame, personId, wishes, individualTurn } = useWizard()
  const [data, setData] = useState<StoreCompare | null>(null)
  const [noteMap, setNoteMap] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<PendingType[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [comment, setComment] = useState("")
  const [commentMsg, setCommentMsg] = useState("")
  const [sending, setSending] = useState(false)
  const [managerQs, setManagerQs] = useState<ManagerQuestion[]>([])

  async function loadQs() {
    try {
      setManagerQs((await getManagerQuestions("open")).questions)
    } catch {
      setManagerQs([])
    }
  }
  useEffect(() => { loadQs() }, [])

  async function answerQ(qid: string, yes: boolean) {
    try {
      await answerManagerQuestion(qid, yes)
      await loadQs()
    } catch {
      /* 無視（再読込で整合） */
    }
  }

  async function calc() {
    setBusy(true)
    setErr("")
    setData(null)
    setCommentMsg("")
    try {
      const wishRows = datesInPeriod(frame).flatMap((d) => {
        const dw = wishes[d]
        if (!dw || dw.status === "off") return []
        return [{ date: d, start: dw.start, end: dw.end, note: dw.note || "" }]
      })

      // 個人の毎週/期間ルールは④で承認済みのものがソルバーに効く（ここではレシピを渡さない）
      const res = await storeCompare({ person_id: personId ?? "", wishes: wishRows, recipe: null })

      // 備考マップ（保存済み＋本人の現在の入力で上書き）
      const ds = await getDesiredShifts()
      const map: Record<string, string> = {}
      for (const a of ds.items) {
        const n = (a.params.note || "").trim()
        if (n) map[`${a.params.person_id}|${a.params.date}`] = n
      }
      if (personId) {
        for (const k of Object.keys(map)) if (k.startsWith(personId + "|")) delete map[k]
        for (const [d, w] of Object.entries(wishes)) {
          const n = (w.note || "").trim()
          if (n) map[`${personId}|${d}`] = n
        }
      }
      setNoteMap(map)
      setData(res)
      try {
        setPending(await getPendingTypes("pending"))
      } catch {
        setPending([])
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "計算に失敗しました")
    } finally {
      setBusy(false)
    }
  }

  // 申し送りへのコメント → 店舗の要望として④へ送る（承認後に再計算で反映）
  async function sendComment() {
    const text = comment.trim()
    if (!text) return
    setSending(true)
    setCommentMsg("")
    try {
      const t = await clarifyNote(text, "store", null, [{ role: "user", text }])
      const q = t.queued ?? 0
      setCommentMsg(
        q > 0
          ? `🆕 ${q}件を④の承認へ送りました。④で承認してから「再計算」してください。`
          : "受け取りました（シフトのルールにはなりませんでした）。",
      )
      setComment("")
    } catch (e) {
      setCommentMsg(e instanceof Error ? e.message : "送信に失敗しました")
    } finally {
      setSending(false)
    }
  }

  const allDates = datesInPeriod(frame)
  const beforeTimes = data ? indexTimes(data.before.assignments) : new Map<string, string>()
  const afterTimes = data ? indexTimes(data.after.assignments) : new Map<string, string>()

  // どちらかで1コマでも入っている人だけ表示
  const shownPersons = masters.persons.filter((p) =>
    allDates.some((d) => beforeTimes.has(`${p.id}|${d}`) || afterTimes.has(`${p.id}|${d}`)),
  )

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-800">⑤ シフトを計算する</h2>
        <p className="text-xs text-gray-400">
          全スタッフの希望・備考と必要人数から計算し、**備考の考慮なし→あり**を並べて表示します。
        </p>
      </div>

      {/* 🙋 実行前に責任者へ確認（需要に依存する要望） */}
      {managerQs.length > 0 && (
        <div className="space-y-2 rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm font-semibold text-blue-900">🙋 実行前に責任者へ確認</p>
          {managerQs.map((q) => (
            <div key={q.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-gray-700">❓ {q.question}</span>
              <button
                type="button"
                onClick={() => answerQ(q.id, true)}
                className="rounded bg-emerald-600 px-2.5 py-0.5 text-xs font-medium text-white hover:bg-emerald-700"
              >
                はい
              </button>
              <button
                type="button"
                onClick={() => answerQ(q.id, false)}
                className="rounded border border-gray-300 px-2.5 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
              >
                いいえ
              </button>
            </div>
          ))}
          <p className="text-xs text-blue-700">回答後に「シフトを計算する」で反映されます。</p>
        </div>
      )}

      <button
        type="button"
        onClick={calc}
        disabled={busy}
        className="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
      >
        {busy ? "計算中…" : "シフトを計算する"}
      </button>
      {err && <p className="text-sm text-red-600">⚠️ {err}</p>}

      {data && (
        <div className="space-y-4">
          {/* サマリ（両方の充足を並べる） */}
          <div className="flex flex-wrap items-center gap-3 rounded-lg bg-gray-50 p-3 text-sm">
            <span className="text-gray-600">充足スコア</span>
            <span>考慮なし：<b>{data.store.before_coverage ?? "—"}</b></span>
            <span className="text-gray-300">→</span>
            <span className="text-emerald-700">考慮あり：<b>{data.store.after_coverage ?? "—"}</b></span>
            <span className={"ml-auto text-xs " + (data.store.after_ok ? "text-emerald-700" : "text-amber-700")}>
              {data.store.after_ok ? "✅ 必要人数を満たせています" : "⚠️ 一部で不足"}
            </span>
          </div>
          <p className="text-xs text-gray-400">
            黄色の行＝備考を考慮して変わったところ（例：水曜が休みに／時間が短く）。
          </p>

          {/* スタッフごとの表（考慮なし／あり を1表に） */}
          <div className="space-y-3">
            {shownPersons.map((p) => {
              const info = personInfo(masters, p)
              const rows = allDates
                .map((d) => ({
                  d,
                  before: beforeTimes.get(`${p.id}|${d}`) ?? "",
                  after: afterTimes.get(`${p.id}|${d}`) ?? "",
                  note: noteMap[`${p.id}|${d}`] ?? "",
                }))
                .filter((r) => r.before || r.after)
              return (
                <div key={p.id} className="overflow-hidden rounded-lg border border-gray-200">
                  <div className="flex flex-wrap items-center gap-1.5 bg-gray-50 px-3 py-2 text-sm">
                    <span className="font-medium text-gray-800">{p.name}</span>
                    <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[11px] text-gray-600">{info.roleName}</span>
                    {info.newbie && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-700">🔰新人</span>}
                    {info.skills.map((s) => (
                      <span key={s} className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-600">{s}</span>
                    ))}
                  </div>
                  <table className="w-full border-collapse text-xs">
                    <thead>
                      <tr className="bg-white text-gray-500">
                        <th className="border-b border-gray-100 p-1.5 text-left font-medium">日付</th>
                        <th className="border-b border-gray-100 p-1.5 text-left font-medium">考慮なし</th>
                        <th className="border-b border-gray-100 p-1.5 text-left font-medium">考慮あり</th>
                        <th className="border-b border-gray-100 p-1.5 text-left font-medium">備考</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => {
                        const changed = r.before !== r.after
                        return (
                          <tr key={r.d} className={changed ? "bg-yellow-50" : ""}>
                            <td className="border-b border-gray-50 p-1.5">{mmdd(r.d)}（{weekdayLabel(r.d)}）</td>
                            <td className="border-b border-gray-50 p-1.5 text-gray-500">{r.before || "—"}</td>
                            <td className="border-b border-gray-50 p-1.5 font-medium">
                              {r.after ? r.after : <span className="text-emerald-700">休み</span>}
                              {changed && <span className="ml-1 text-[10px] text-yellow-600">●</span>}
                            </td>
                            <td className="border-b border-gray-50 p-1.5 text-gray-500">
                              {r.note && <span>📝 {r.note}</span>}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )
            })}
          </div>

          {/* 🤖 AIからの申し送り（未反映・要確認・悩んだ点）＋ コメントで再実行 */}
          <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p className="text-sm font-semibold text-amber-900">🤖 AIからの申し送り</p>

            <div>
              <p className="text-xs font-medium text-gray-700">▼ 作成で悩んだ点</p>
              {(data.after.understaffed?.length ?? 0) === 0 && (data.after.soft_violations ?? 0) === 0 ? (
                <p className="text-xs text-emerald-700">特にありません（希望と必要人数をおおむね満たせました）。</p>
              ) : (
                <ul className="text-xs text-gray-600">
                  {(data.after.understaffed ?? []).map((u, i) => <li key={i}>・人数不足：{u}</li>)}
                  {(data.after.soft_violations ?? 0) > 0 && (
                    <li>・希望を満たしきれなかった箇所：{data.after.soft_violations}件</li>
                  )}
                </ul>
              )}
            </div>

            {pending.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-700">▼ 未反映（④で承認待ち）</p>
                <ul className="text-xs text-violet-700">
                  {pending.map((p) => (
                    <li key={p.id}>・{p.suggested_type_name}（{p.summary || ""}）</li>
                  ))}
                </ul>
              </div>
            )}

            {individualTurn && individualTurn.rules.some((r) => r.decision !== "queue") && (
              <div>
                <p className="text-xs font-medium text-gray-700">▼ スタッフに確認してほしいこと</p>
                <ul className="text-xs text-gray-600">
                  {individualTurn.rules.filter((r) => r.decision === "memo").map((r, i) => (
                    <li key={"m" + i}>・📝 {r.summary}</li>
                  ))}
                  {individualTurn.rules.filter((r) => r.decision === "reject").map((r, i) => (
                    <li key={"r" + i}>・❌ {r.summary}（今の仕組みでは未対応）</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="border-t border-amber-200 pt-2">
              <p className="mb-1 text-xs text-amber-800">
                この申し送りへのコメント（店舗ルールとして④へ送り、承認後に「再計算」で反映）
              </p>
              <div className="flex flex-wrap gap-2">
                <input
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !sending && sendComment()}
                  placeholder="例：11/4はもう1人増やして／新人だけにしない"
                  className="min-w-[200px] flex-1 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs"
                />
                <button
                  type="button"
                  onClick={sendComment}
                  disabled={sending || !comment.trim()}
                  className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-40"
                >
                  {sending ? "送信中…" : "送信"}
                </button>
                <button
                  type="button"
                  onClick={calc}
                  disabled={busy}
                  className="rounded-lg border border-emerald-300 px-3 py-1.5 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                >
                  🔄 再計算
                </button>
              </div>
              {commentMsg && <p className="mt-1 text-xs text-gray-700">{commentMsg}</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
