import { useState } from "react"
import type { DayWish, Frame, WishMap } from "../types"
import { WEEKDAY_JP, datesInPeriod, mmdd, monFirstCol, slotOptions, weekdayLabel } from "../lib/shift"

type Props = {
  frame: Frame
  wishes: WishMap
  onChangeDay: (date: string, wish: DayWish) => void
  onFillAll: () => void // すべて「終日OK」
}

// セルに出す短いラベル（"11:00"→"11" / "16:30"はそのまま）
function cellLabel(w?: DayWish): string {
  if (!w || w.status === "off") return "休み"
  const c = (t: string) => (t.endsWith(":00") ? t.slice(0, 2) : t)
  return `${c(w.start)}–${c(w.end)}`
}

// ② カレンダー月表示で日ごとの希望（出勤できる/休み・時間30分刻み・メモ）を入力する
export function WishCalendar({ frame, wishes, onChangeDay, onFillAll }: Props) {
  const dates = datesInPeriod(frame)
  const [selected, setSelected] = useState<string | null>(dates[0] ?? null)
  const options = slotOptions(frame)

  // 月曜始まりのグリッドに並べる（先頭の空白＋末尾の空白で7列に揃える）
  const lead = dates.length ? monFirstCol(dates[0]) : 0
  const cells: (string | null)[] = [...Array(lead).fill(null), ...dates]
  while (cells.length % 7 !== 0) cells.push(null)

  const cur = selected ? wishes[selected] : undefined

  // 出勤できる/休み の切替（出勤可の初期時間は営業時間まるごと＝終日OK）
  function setStatus(date: string, status: DayWish["status"]) {
    const base = wishes[date]
    const note = base?.note ?? ""
    if (status === "off") {
      onChangeDay(date, { status: "off", start: "", end: "", note })
    } else {
      const start = base?.status === "available" ? base.start : frame.operating_window.open
      const end = base?.status === "available" ? base.end : frame.operating_window.close
      onChangeDay(date, { status: "available", start, end, note })
    }
  }

  function setTime(date: string, part: "start" | "end", v: string) {
    const base = wishes[date]
    let start = base?.start || frame.operating_window.open
    let end = base?.end || frame.operating_window.close
    if (part === "start") {
      start = v
      if (end <= start) end = options.find((t) => t > start) ?? frame.operating_window.close
    } else {
      end = v
    }
    onChangeDay(date, { status: "available", start, end, note: base?.note ?? "" })
  }

  function setNote(date: string, note: string) {
    const base = wishes[date] ?? { status: "off", start: "", end: "", note: "" }
    onChangeDay(date, { ...base, note })
  }

  return (
    <div className="space-y-4">
      {/* 説明＋クイック */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-gray-500">
          日付をクリックして、出勤できる時間（30分刻み）とその日のメモを入力します。
        </p>
        <button
          type="button"
          onClick={onFillAll}
          className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1 text-xs text-emerald-700 hover:bg-emerald-100"
        >
          すべて「終日OK」にする
        </button>
      </div>

      {/* 曜日ヘッダ */}
      <div className="grid grid-cols-7 gap-1 text-center text-xs font-medium text-gray-500">
        {WEEKDAY_JP.map((wd) => (
          <div key={wd} className={wd === "日" ? "text-red-400" : wd === "土" ? "text-blue-400" : ""}>
            {wd}
          </div>
        ))}
      </div>

      {/* 日付セル */}
      <div className="grid grid-cols-7 gap-1">
        {cells.map((d, i) => {
          if (!d) return <div key={i} />
          const w = wishes[d]
          const off = !w || w.status === "off"
          const isSel = d === selected
          const hasNote = !!(w && w.note.trim())
          return (
            <button
              key={d}
              type="button"
              onClick={() => setSelected(d)}
              className={
                "relative flex h-16 flex-col items-center justify-center rounded border text-sm transition " +
                (off
                  ? "border-gray-200 bg-gray-100 text-gray-400"
                  : "border-emerald-300 bg-emerald-100 text-emerald-800") +
                (isSel ? " ring-2 ring-blue-500" : " hover:ring-1 hover:ring-blue-300")
              }
            >
              <span className="font-semibold">{mmdd(d).split("/")[1]}</span>
              <span className="text-[10px] leading-tight">{cellLabel(w)}</span>
              {hasNote && <span className="absolute right-1 top-1 text-[10px]">📝</span>}
            </button>
          )
        })}
      </div>

      {/* 選択中の日の編集 */}
      {selected && (
        <div className="space-y-3 rounded-lg bg-blue-50 p-3">
          <p className="text-sm font-medium text-blue-900">
            {mmdd(selected)}（{weekdayLabel(selected)}）の希望
          </p>

          {/* 出勤できる / 休み のトグル */}
          <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 text-sm">
            {([["available", "出勤できる"], ["off", "休み"]] as [DayWish["status"], string][]).map(([s, label]) => {
              const active = (cur?.status ?? "off") === s
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(selected, s)}
                  className={
                    "rounded-md px-3 py-1.5 transition " +
                    (active ? "bg-blue-600 font-medium text-white" : "text-gray-600 hover:text-gray-800")
                  }
                >
                  {label}
                </button>
              )
            })}
          </div>

          {/* 時間指定（出勤できるのとき・30分刻み） */}
          {cur?.status === "available" && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-600">出勤できる時間</span>
              <select
                value={cur.start}
                onChange={(e) => setTime(selected, "start", e.target.value)}
                className="rounded border border-gray-300 bg-white px-2 py-1"
              >
                {options.slice(0, -1).map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <span className="text-gray-500">〜</span>
              <select
                value={cur.end}
                onChange={(e) => setTime(selected, "end", e.target.value)}
                className="rounded border border-gray-300 bg-white px-2 py-1"
              >
                {options.filter((t) => t > cur.start).map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          )}

          {/* その日のメモ（AIが翻訳） */}
          <div>
            <label className="mb-1 block text-xs text-gray-500">
              この日のメモ（AIが解釈します。例：お迎えで17時まで／通院で午後から）
            </label>
            <input
              value={cur?.note ?? ""}
              onChange={(e) => setNote(selected, e.target.value)}
              placeholder="（任意）"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
        </div>
      )}
    </div>
  )
}
