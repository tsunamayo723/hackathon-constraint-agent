// FastAPI バックエンドへの薄いラッパ。
// 開発時は http://localhost:8001（Streamlit裏方と同じFastAPIを共有）。
// 本番(T6)では VITE_API_BASE で差し替える（FastAPI同梱なら "" ＝同一オリジンの相対パス）。

import type { ChatMessage, ChatTurn, DemoWishes, Frame, Masters, NoteResultItem, PreviewResult, SideResult } from "./types"

// 未指定(undefined)のときだけローカル既定にフォールバックする。
// 同梱配信では VITE_API_BASE="" を渡す＝同一オリジンの相対パス。"" を尊重するため || ではなく ?? を使う。
const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8001"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)
    } catch {
      // JSONでなければステータステキストのまま
    }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

export const getMasters = () => request<Masters>("/setup/masters")
export const getFrame = () => request<Frame>("/setup/frame")

// デモの希望（日ごとnote付き）＋overall_note をこの人ぶん取得（カレンダー自動入力用）
export const getDemoWishes = (personId: string) =>
  request<DemoWishes>(`/submit/demo-wishes?person_id=${encodeURIComponent(personId)}`)

// デモパターン一覧／一括投入（店舗のセットアップ）
export type DemoPattern = { key: string; label: string; description: string }
export const getDemoPatterns = () => request<{ patterns: DemoPattern[] }>("/setup/demo-patterns")
export const loadDemo = (pattern: string) =>
  request<{ 結果: string; 概要: Record<string, unknown> }>("/setup/load-demo", {
    method: "POST",
    body: JSON.stringify({ pattern }),
  })

export const clarifyNote = (
  requirements: string,
  scope: "person" | "store",
  personId: string | null,
  history: ChatMessage[],
) =>
  request<ChatTurn>("/chat/clarify-note", {
    method: "POST",
    body: JSON.stringify({ requirements, scope, person_id: personId, history }),
  })

export type PreviewBody = {
  person_id: string
  wishes: { date: string; start: string; end: string; note?: string }[]
  recipe: unknown | null
  type_name?: string
}
export const submitPreview = (body: PreviewBody) =>
  request<PreviewResult>("/submit/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })

// 個人の希望を店舗にマージ保存（最終計算の前段）
export const commitSubmission = (body: PreviewBody) =>
  request<{ recipe_applied: boolean; notes_adjusted: number }>("/submit/commit", {
    method: "POST",
    body: JSON.stringify(body),
  })

// 保存済みデータから全体シフトを計算
export const runStored = () =>
  request<import("./types").SolverResult>("/solver/run-stored", { method: "POST" })

// 保存済みの出勤希望（note付き）。シフト出力に備考を併記するため。
export type StoredAvailability = {
  items: { type: string; params: { person_id: string; date: string; start: string; end: string; note?: string | null } }[]
}
export const getDesiredShifts = () => request<StoredAvailability>("/setup/desired-shifts")

// 全体シフトを「note考慮あり/なし」で計算して比較（⑤用・非破壊）
export type StoreCompare = {
  before: SideResult
  after: SideResult
  note_results: NoteResultItem[]
  store: { before_ok: boolean; after_ok: boolean; before_coverage: number | null; after_coverage: number | null }
}
export const storeCompare = (body: PreviewBody) =>
  request<StoreCompare>("/submit/store-compare", { method: "POST", body: JSON.stringify(body) })

// ② 日ごとメモをAIで解釈して件数・分類を返す（フィードバック用・非破壊）
export type WishNotes = {
  counts: { applied: number; new_rules: number; unreflected: number }
  applied: { date: string; note: string; summary: string }[]
  new_rules: { date: string; note: string; suggested_type_name?: string | null }[]
  unreflected: { date: string; note: string }[]
}
export const interpretWishes = (person_id: string, wishes: PreviewBody["wishes"]) =>
  request<WishNotes>("/submit/interpret-wishes", {
    method: "POST",
    body: JSON.stringify({ person_id, wishes }),
  })

// ③ 店全体の要望（管理者NL）をParserで翻訳。既知→方針に反映 / 未知→承認キューへ。
export type ParseResult = {
  translated: { constraint: { type: string }; source_text?: string }[]
  untranslated: { source_text: string; suggested_type_name?: string | null; summary?: string | null }[]
}
export const parseInput = (input_text: string, person_id?: string) =>
  request<ParseResult>("/parser/parse", {
    method: "POST",
    body: JSON.stringify({ input_text, person_id }),
  })

// ④ 承認キュー（管理者）
export const getPendingTypes = (status = "pending") =>
  request<import("./types").PendingType[]>(`/admin/pending-types?status=${encodeURIComponent(status)}`)
export const getPendingType = (id: string) =>
  request<import("./types").PendingType>(`/admin/pending-types/${id}`)
export const generatePending = (id: string, feedback = "") =>
  request<Record<string, unknown>>(
    `/admin/pending-types/${id}/generate?feedback=${encodeURIComponent(feedback)}`,
    { method: "POST" },
  )
export const approvePending = (id: string) =>
  request<Record<string, unknown>>(`/admin/pending-types/${id}/approve`, { method: "POST" })
export const rejectPending = (id: string) =>
  request<Record<string, unknown>>(`/admin/pending-types/${id}/reject`, { method: "POST" })

// 責任者への確認（需要に依存する要望：混みそう？等）
export type ManagerQuestion = {
  id: string
  person_id: string | null
  question: string
  summary?: string | null
  status: string
  answer?: boolean | null
}
export const getManagerQuestions = (status = "open") =>
  request<{ questions: ManagerQuestion[] }>(`/chat/manager-questions?status=${encodeURIComponent(status)}`)
export const answerManagerQuestion = (qid: string, yes: boolean) =>
  request<{ applied: boolean }>(`/chat/manager-questions/${qid}/answer`, {
    method: "POST",
    body: JSON.stringify({ yes }),
  })
