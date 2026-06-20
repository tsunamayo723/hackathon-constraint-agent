// バックエンド（FastAPI）とやり取りする型の定義

export type Person = { id: string; name: string; role_id?: string | null; skill_ids?: string[] }
export type Position = { id: string; name: string }
export type Role = { id: string; name: string }
export type Skill = { id: string; name: string }
export type Masters = { persons: Person[]; positions: Position[]; roles: Role[]; skills: Skill[] }

export type Frame = {
  period: { start: string; end: string }
  operating_window: { open: string; close: string; slot_minutes: number }
  policy_mode: string
}

// 1日分の希望：出勤可なら時間帯（30分刻み）、休みなら枠なし。＋その日のメモ（AIが翻訳）
export type DayWish = {
  status: "available" | "off"
  start: string // "HH:MM"（status="available" のとき有効）
  end: string // "HH:MM"
  note: string // その日のメモ
}
export type WishMap = Record<string, DayWish> // date -> DayWish

// クイック入力プリセット（終日/早番/遅番/休み）
export type WishPreset = "full" | "early" | "late" | "off"

// /submit/demo-wishes の返り（デモの希望をカレンダーに自動入力）
export type DemoWishes = {
  person_id: string
  wishes: { date: string; start: string; end: string; note: string }[]
  overall_note: string
}

// /chat/clarify-note の返り（複数ルール対応）
export type ChatRule = {
  source_text: string
  summary: string
  decision: "queue" | "memo" | "reject"
  suggested_type_name: string
  recipe_json: string
  reject_category: string
}
export type ChatTurn = {
  reply: string
  needs_clarification: boolean
  rules: ChatRule[]
  queued?: number // ④の承認キューに登録した件数（エンドポイントが付与）
}

export type ChatMessage = { role: "user" | "ai"; text: string }

// 日ごとnoteのAI翻訳結果（✅時間補正 / 🆕新ルール候補 / ⚠️申し送り）
export type NoteResultItem = {
  person_id: string
  date: string
  note: string
  status: "applied" | "pending" | "unreflected"
  summary: string
  suggested_type_name?: string
}

// /submit/preview の返り
export type AssignmentDict = {
  person_id: string; date: string; position_id: string; start: string; end: string
}
export type SideResult = {
  status: string
  assignments: AssignmentDict[]
  coverage_score: number | null
  shortage_units: number | null
  understaffed?: string[]
  soft_violations?: number
}
export type PreviewResult = {
  person_id: string
  note_applied: boolean
  recipe_applied: boolean
  notes_adjusted: number
  note_message: string
  note_recipe: unknown
  note_results: NoteResultItem[]
  before: SideResult
  after: SideResult
  personal: {
    before: AssignmentDict[]
    after: AssignmentDict[]
    diff: { removed: AssignmentDict[]; added: AssignmentDict[] }
  }
  store: {
    before_ok: boolean
    after_ok: boolean
    before_coverage: number | null
    after_coverage: number | null
  }
}

// 承認キュー（管理者）
export type TestResult = {
  passed: boolean
  total: number
  passed_count: number
  failed_cases: string[]
  detail: string
}
export type PendingType = {
  id: string
  suggested_type_name: string
  source_texts: string[]
  occurrence_count: number
  summary?: string | null
  ai_assessment?: string | null
  review_points?: string[]
  suggested_recipe?: Record<string, unknown> | null
  tested_params?: Record<string, unknown> | null
  expressible?: boolean
  reject_category?: string | null
  test_results?: TestResult | null
  confidence: number
  concerns?: string[]
  status: string
}

// /solver/run-stored の返り（必要な部分だけ）
export type SolverWarning = {
  type: string
  affected_date?: string | null
  affected_time?: string | null
  shortage?: number | null
}
export type SolverResult = {
  status: string
  shift_status: string // "confirmed" | "provisional"
  meta: { coverage_score: number | null; shortage_units: number | null } | null
  assignments: AssignmentDict[]
  warnings: SolverWarning[]
}
