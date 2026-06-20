import { createContext, useContext, useEffect, useState } from "react"
import type { ReactNode } from "react"
import { clarifyNote, getDemoWishes, getFrame, getMasters, loadDemo } from "../api"
import type { WishNotes } from "../api"
import { datesInPeriod, emptyWish } from "../lib/shift"
import type { ChatMessage, ChatTurn, DayWish, Frame, Masters, WishMap } from "../types"

export type Mode = "demo" | "manual"

// ウィザード全体で共有する状態。各ステップはこれを読み書きする。
type WizardCtx = {
  masters: Masters
  frame: Frame
  reloadStage: () => Promise<void> // 店舗（マスタ・営業情報）を読み直す（デモ投入後など）

  step: number
  setStep: (n: number) => void
  next: () => void
  back: () => void

  // ①：個人（本人・希望・備考・AIチャット）
  personId: string | null
  mode: Mode
  setMode: (m: Mode) => void
  selectPerson: (id: string, mode?: Mode) => Promise<void>
  loadingWishes: boolean

  wishes: WishMap
  setDay: (date: string, wish: DayWish) => void
  fillAllFull: () => void

  // ②：AIチャット主導（「AIに相談する」で起動→日ごとメモ反映→会話→全体要望）
  note: string
  setNote: (s: string) => void
  noteFeedback: WishNotes | null     // 日ごとメモの分類（✅時間補正/🆕新ルール/⚠️申し送り）
  consultStarted: boolean
  startConsult: () => Promise<void>  // 相談開始：日ごとメモを反映し、全体要望を聞く
  sendChat: () => Promise<void>      // chatAnswer をAIに送る
  chatMessages: ChatMessage[]
  chatAnswer: string
  setChatAnswer: (s: string) => void
  clarifying: boolean
  clarifyError: string
  individualTurn: ChatTurn | null
}

const Ctx = createContext<WizardCtx | null>(null)

export function useWizard(): WizardCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error("useWizard は WizardProvider の中で使ってください")
  return c
}

export const TOTAL_STEPS = 5

export function WizardProvider({ children }: { children: ReactNode }) {
  const [masters, setMasters] = useState<Masters | null>(null)
  const [frame, setFrame] = useState<Frame | null>(null)
  const [bootError, setBootError] = useState("")

  const [step, setStep] = useState(1)
  const [personId, setPersonId] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>("demo")
  const [wishes, setWishes] = useState<WishMap>({})
  const [loadingWishes, setLoadingWishes] = useState(false)

  // ②：AIチャット
  const [note, setNote] = useState("")
  const [noteFeedback, setNoteFeedback] = useState<WishNotes | null>(null)
  const [consultStarted, setConsultStarted] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatAnswer, setChatAnswer] = useState("")
  const [clarifying, setClarifying] = useState(false)
  const [clarifyError, setClarifyError] = useState("")
  const [individualTurn, setIndividualTurn] = useState<ChatTurn | null>(null)

  async function reloadStage() {
    const [m, f] = await Promise.all([getMasters(), getFrame()])
    setMasters(m)
    setFrame(f)
  }

  // 起動時：データがあれば尊重、無ければデモ(cafe_easy)を自動投入してから読む
  useEffect(() => {
    (async () => {
      try {
        await reloadStage()
      } catch {
        try {
          await loadDemo("cafe_easy")
          await reloadStage()
        } catch (e) {
          setBootError(e instanceof Error ? e.message : "初期化に失敗しました")
        }
      }
    })()
  }, [])

  function allOff(f: Frame): WishMap {
    const w: WishMap = {}
    for (const d of datesInPeriod(f)) w[d] = emptyWish()
    return w
  }

  function resetChat() {
    setChatMessages([])
    setChatAnswer("")
    setClarifyError("")
    setIndividualTurn(null)
    setNoteFeedback(null)
    setConsultStarted(false)
  }

  async function selectPerson(id: string, nextMode: Mode = mode) {
    setPersonId(id)
    resetChat()
    if (!frame) return
    if (nextMode === "manual") {
      setWishes(allOff(frame))
      setNote("")
      return
    }
    setLoadingWishes(true)
    try {
      const dw = await getDemoWishes(id)
      const w = allOff(frame)
      for (const x of dw.wishes) {
        w[x.date] = { status: "available", start: x.start, end: x.end, note: x.note || "" }
      }
      setWishes(w)
      setNote(dw.overall_note || "")
    } catch {
      setWishes(allOff(frame))
      setNote("")
    } finally {
      setLoadingWishes(false)
    }
  }

  function setDay(date: string, wish: DayWish) {
    setWishes((w) => ({ ...w, [date]: wish }))
  }
  function fillAllFull() {
    if (!frame) return
    const open = frame.operating_window.open
    const close = frame.operating_window.close
    setWishes((w) => {
      const next: WishMap = {}
      for (const d of datesInPeriod(frame)) {
        next[d] = { status: "available", start: open, end: close, note: w[d]?.note ?? "" }
      }
      return next
    })
  }

  // 「AIに相談する」押下：カレンダーの日ごとメモ＋全体希望を1つの要望にまとめ、
  // 同じ会話AI（一人のエージェント）に渡す。AIが曖昧点を聞き返し、要望ごとに整理する。
  async function startConsult() {
    if (!personId || !frame) return
    setConsultStarted(true)
    setClarifyError("")
    setNoteFeedback(null)
    const dayNotes = datesInPeriod(frame)
      .filter((d) => (wishes[d]?.note || "").trim())
      .map((d) => `${d}: ${wishes[d]!.note.trim()}`)
    const parts = [...dayNotes]
    if (note.trim()) parts.push(note.trim())
    const requirements = parts.join("\n")

    if (!requirements) {
      setChatMessages([{ role: "ai", text: "毎週/期間のご希望やメモがあればどうぞ。無ければ「次へ」で進めます。" }])
      return
    }
    setNote(requirements) // 以降の聞き返しでも使う固定の要望
    const history: ChatMessage[] = [{ role: "user", text: requirements }]
    setChatMessages(history)
    setClarifying(true)
    try {
      const t = await clarifyNote(requirements, "person", personId, history)
      setChatMessages([...history, { role: "ai", text: t.reply }])
      setIndividualTurn(t)
    } catch (e) {
      setClarifyError(e instanceof Error ? e.message : "AIとの通信に失敗しました")
    } finally {
      setClarifying(false)
    }
  }

  // チャット送信：chatAnswer をAIに送る（要望本文は note 固定・履歴を積む）
  async function sendChat() {
    const text = chatAnswer.trim()
    if (!text) return
    const useNote = note.trim() || text
    if (!note.trim()) setNote(text)
    const history: ChatMessage[] = [...chatMessages, { role: "user", text }]
    setChatMessages(history)
    setChatAnswer("")
    setClarifying(true)
    setClarifyError("")
    try {
      const t = await clarifyNote(useNote, "person", personId, history)
      setChatMessages([...history, { role: "ai", text: t.reply }])
      setIndividualTurn(t)
    } catch (e) {
      setClarifyError(e instanceof Error ? e.message : "AIとの通信に失敗しました")
    } finally {
      setClarifying(false)
    }
  }

  if (bootError) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-6 text-amber-800">
          <p className="font-semibold">⚠️ 初期化に失敗しました</p>
          <p className="mt-2 text-sm">{bootError}</p>
          <p className="mt-3 text-sm">FastAPI（:8001）が起動しているか確認してください。</p>
        </div>
      </div>
    )
  }
  if (!masters || !frame) {
    return <div className="p-8 text-gray-500">準備中…（店舗データを読み込んでいます）</div>
  }

  const value: WizardCtx = {
    masters, frame, reloadStage,
    step, setStep,
    next: () => setStep((s) => Math.min(TOTAL_STEPS, s + 1)),
    back: () => setStep((s) => Math.max(1, s - 1)),
    personId, mode, setMode, selectPerson, loadingWishes,
    wishes, setDay, fillAllFull,
    note, setNote, noteFeedback, consultStarted, startConsult, sendChat,
    chatMessages, chatAnswer, setChatAnswer,
    clarifying, clarifyError, individualTurn,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
