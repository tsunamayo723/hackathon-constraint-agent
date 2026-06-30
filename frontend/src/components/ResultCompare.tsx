import type { AssignmentDict, Frame, NoteResultItem, PreviewResult } from "../types"
import { datesInPeriod, mmdd, weekdayLabel } from "../lib/shift"

// その日の割当時刻を「11:00–17:00」形式で（複数ブロックはカンマ区切り）
function timesFor(list: AssignmentDict[], date: string): string {
  return list
    .filter((a) => a.date === date)
    .map((a) => `${a.start.slice(0, 5)}–${a.end.slice(0, 5)}`)
    .join(", ")
}

type Props = {
  frame: Frame
  result: PreviewResult
}

// 日ごとnoteの分類の見た目（結果画面 ResultStep でも再利用）
export const NOTE_STYLE: Record<NoteResultItem["status"], { icon: string; cls: string; label: string }> = {
  applied: { icon: "✅", cls: "border-emerald-200 bg-emerald-50 text-emerald-800", label: "時間を補正" },
  pending: { icon: "🆕", cls: "border-violet-200 bg-violet-50 text-violet-800", label: "新ルール候補 → 管理者の承認待ちへ" },
  unreflected: { icon: "⚠️", cls: "border-amber-200 bg-amber-50 text-amber-800", label: "申し送り（シフトには未反映）" },
}

// ⑤ note考慮あり/なしの比較。「自分の要望」と「店舗の要望」が両立しているのを見せる
export function ResultCompare({ frame, result }: Props) {
  const dates = datesInPeriod(frame)
  const removed = result.personal.diff.removed // 備考のおかげで休めた日
  const added = result.personal.diff.added // 備考のおかげで入った日
  const storeOk = result.store.after_ok
  const cover = result.store.after_coverage
  const notes = result.note_results ?? []

  return (
    <div className="space-y-5">
      {/* まとめ（自分／店舗） */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <p className="mb-1 text-sm font-semibold text-blue-900">🙋 あなたの要望</p>
          {!result.note_applied ? (
            <p className="text-sm text-blue-800">備考の反映は無し（希望どおりのシフトです）</p>
          ) : removed.length > 0 ? (
            <ul className="text-sm text-blue-800">
              {removed.map((a) => (
                <li key={a.date}>
                  ✅ {mmdd(a.date)}（{weekdayLabel(a.date)}）はお休みになりました
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-blue-800">備考を反映しました（割当の変化はありませんでした）</p>
          )}
          {added.length > 0 && (
            <ul className="mt-1 text-sm text-blue-700">
              {added.map((a) => (
                <li key={a.date}>＋ {mmdd(a.date)}（{weekdayLabel(a.date)}）に入りました</li>
              ))}
            </ul>
          )}
        </div>

        <div
          className={
            "rounded-lg border p-4 " +
            (storeOk ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50")
          }
        >
          <p className="mb-1 text-sm font-semibold text-gray-900">🏪 店舗の要望（必要人数）</p>
          {storeOk ? (
            <p className="text-sm text-emerald-800">✅ 必要人数を満たせています（充足 {cover}%）</p>
          ) : (
            <p className="text-sm text-amber-800">
              ⚠️ 一部の時間帯で人数が不足しています（充足 {cover}%）
            </p>
          )}
        </div>
      </div>

      {/* 日ごとnoteのAI翻訳結果 */}
      {notes.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium text-gray-700">🤖 AIが備考をどう解釈したか</p>
          <ul className="space-y-1.5">
            {notes.map((n, i) => {
              const s = NOTE_STYLE[n.status]
              return (
                <li key={i} className={"rounded-lg border p-2.5 text-sm " + s.cls}>
                  <span className="mr-1">{s.icon}</span>
                  <span className="font-medium">{mmdd(n.date)}</span>
                  <span className="ml-1 text-xs opacity-70">[{s.label}]</span>
                  <div className="mt-0.5 text-xs opacity-90">
                    「{n.note}」
                    {n.suggested_type_name && (
                      <span className="ml-1 rounded bg-white/60 px-1.5 py-0.5">{n.suggested_type_name}</span>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* 日ごとの before/after（変わった日をハイライト） */}
      <div>
        <p className="mb-2 text-sm font-medium text-gray-700">あなたのシフト（備考 考慮なし → あり）</p>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-100 text-gray-600">
                <th className="border-b p-2 text-left">日付</th>
                <th className="border-b p-2 text-center">考慮なし</th>
                <th className="border-b p-2 text-center">考慮あり</th>
              </tr>
            </thead>
            <tbody>
              {dates.map((d) => {
                const bt = timesFor(result.personal.before, d)
                const at = timesFor(result.personal.after, d)
                const changed = bt !== at
                return (
                  <tr key={d} className={changed ? "bg-yellow-50" : ""}>
                    <td className="border-b p-2">
                      {mmdd(d)}（{weekdayLabel(d)}）
                    </td>
                    <td className="border-b p-2 text-center text-gray-600">{bt || "—"}</td>
                    <td className="border-b p-2 text-center font-medium">
                      {at ? at : <span className="text-emerald-700">休み</span>}
                      {changed && <span className="ml-1 text-xs text-yellow-600">●</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
