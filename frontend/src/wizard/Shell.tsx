import { TOTAL_STEPS, useWizard } from "./context"
import { IndividualStep } from "./steps/IndividualStep"
import { StoreStep } from "./steps/StoreStep"
import { PolicyStep } from "./steps/PolicyStep"
import { ApproveStep } from "./steps/ApproveStep"
import { ResultStep } from "./steps/ResultStep"

const STEPS = [
  { n: 1, title: "店舗の準備" },
  { n: 2, title: "個人の希望" },
  { n: 3, title: "全体の要望" },
  { n: 4, title: "承認" },
  { n: 5, title: "シフト計算" },
]

export function Shell() {
  const { step, setStep, next, back, frame } = useWizard()

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 sm:p-8">
      <header>
        <h1 className="text-xl font-bold text-gray-900">🗓️ シフト作成ウィザード</h1>
        <p className="text-sm text-gray-500">
          対象期間 {frame.period.start} 〜 {frame.period.end} ／ 営業 {frame.operating_window.open}〜{frame.operating_window.close}
        </p>
      </header>

      {/* ステッパー */}
      <ol className="flex flex-wrap gap-1">
        {STEPS.map((s) => {
          const state = s.n === step ? "active" : s.n < step ? "done" : "todo"
          return (
            <li key={s.n} className="flex-1">
              <button
                type="button"
                onClick={() => setStep(s.n)}
                className={
                  "w-full rounded-lg border px-2 py-1.5 text-left text-xs transition " +
                  (state === "active"
                    ? "border-blue-600 bg-blue-600 text-white shadow"
                    : state === "done"
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border-gray-200 bg-white text-gray-400")
                }
              >
                <span className="font-bold">{s.n}</span>
                <span className="ml-1">{s.title}</span>
              </button>
            </li>
          )
        })}
      </ol>

      {/* 現在のステップ */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        {step === 1 && <StoreStep />}
        {step === 2 && <IndividualStep />}
        {step === 3 && <PolicyStep />}
        {step === 4 && <ApproveStep />}
        {step === 5 && <ResultStep />}
      </div>

      {/* 前後ナビ */}
      <div className="flex justify-between">
        <button
          type="button"
          onClick={back}
          disabled={step === 1}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-30"
        >
          ← 戻る
        </button>
        <button
          type="button"
          onClick={next}
          disabled={step === TOTAL_STEPS}
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-30"
        >
          次へ →
        </button>
      </div>
    </div>
  )
}
