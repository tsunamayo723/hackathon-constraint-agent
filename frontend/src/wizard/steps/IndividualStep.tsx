import { PersonPicker } from "../../components/PersonPicker"
import { WishCalendar } from "../../components/WishCalendar"
import { personById, personInfo } from "../../lib/people"
import { useWizard } from "../context"
import type { Mode } from "../context"

const REJECT_LABEL: Record<string, string> = {
  negotiation_dependent: "他の人の希望しだい（交渉が必要）",
  history_dependent: "過去の実績が必要",
  missing_data: "手元にないデータが必要",
  subjective: "数値にできない主観的な希望",
  advanced_logic: "他者に依存する高度な条件",
}

// ② 個人の希望（本人・カレンダー）＋ AIチャット主導で備考を整える
export function IndividualStep() {
  const {
    masters, frame, personId, mode, setMode, selectPerson, loadingWishes,
    wishes, setDay, fillAllFull,
    consultStarted, startConsult, sendChat, noteFeedback,
    chatMessages, chatAnswer, setChatAnswer, clarifying, clarifyError, individualTurn,
  } = useWizard()

  function changeMode(m: Mode) {
    setMode(m)
    if (personId) selectPerson(personId, m)
  }

  const turn = individualTurn

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-800">② あなたの希望を出す</h2>
        <p className="text-xs text-gray-400">
          本人を選び、出勤できる日時を入力。仕上げに「AIに相談」でメモと全体の希望を整えます。
        </p>
      </div>

      {/* デモ / 手動 トグル */}
      <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5 text-sm">
        {([["demo", "デモの希望を読み込む"], ["manual", "自分で記入"]] as [Mode, string][]).map(([m, label]) => (
          <button
            key={m}
            type="button"
            onClick={() => changeMode(m)}
            className={
              "rounded-md px-3 py-1.5 transition " +
              (mode === m ? "bg-white font-medium text-blue-700 shadow-sm" : "text-gray-500 hover:text-gray-700")
            }
          >
            {label}
          </button>
        ))}
      </div>

      <PersonPicker masters={masters} selected={personId} onSelect={(id) => selectPerson(id)} />
      {loadingWishes && <p className="text-xs text-gray-400">デモの希望を読み込み中…</p>}

      {personId && (() => {
        const info = personInfo(masters, personById(masters, personId))
        return (
          <div className="rounded-lg bg-gray-50 p-2.5 text-xs text-gray-600">
            役職：<b className="text-gray-800">{info.roleName}</b>
            {info.newbie && <span className="ml-1 rounded bg-amber-100 px-1 text-amber-700">🔰新人</span>}
            {info.skills.length > 0 && <span className="ml-2">スキル：{info.skills.join("・")}</span>}
          </div>
        )
      })()}

      {!personId ? (
        <p className="text-sm text-gray-400">先に本人を選んでください。</p>
      ) : (
        <>
          <WishCalendar frame={frame} wishes={wishes} onChangeDay={setDay} onFillAll={fillAllFull} />

          {/* AIに相談（日ごとメモ反映 → 全体要望） */}
          <div className="space-y-3 border-t border-gray-100 pt-4">
            {!consultStarted ? (
              <div>
                <button
                  type="button"
                  onClick={startConsult}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                >
                  🤖 AIに相談する
                </button>
                <p className="mt-1 text-xs text-gray-400">
                  日ごとメモをAIが反映し、最後に「毎週・期間の希望」を確認します。モデル: Flash
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {/* 日ごとメモの反映結果 */}
                {noteFeedback && (
                  <div className="rounded-lg bg-emerald-50 p-3 text-sm">
                    <p className="font-medium text-emerald-900">
                      📝 メモを反映しました：✅時間補正 {noteFeedback.counts.applied}件 ／
                      🆕新ルール候補 {noteFeedback.counts.new_rules}件
                      {noteFeedback.counts.new_rules > 0 && <span className="text-violet-700">（→④の承認へ）</span>} ／
                      ⚠️申し送り {noteFeedback.counts.unreflected}件
                    </p>
                    {noteFeedback.applied.map((n, i) => (
                      <p key={"a" + i} className="text-xs text-emerald-700">✅ {n.summary}</p>
                    ))}
                    {noteFeedback.new_rules.map((n, i) => (
                      <p key={"r" + i} className="text-xs text-violet-700">🆕 「{n.note}」</p>
                    ))}
                    {noteFeedback.unreflected.map((n, i) => (
                      <p key={"u" + i} className="text-xs text-amber-700">⚠️ 「{n.note}」</p>
                    ))}
                  </div>
                )}

                {/* 会話ログ */}
                <div className="space-y-2 rounded-lg bg-gray-50 p-3">
                  {chatMessages.map((m, i) => (
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

                {clarifyError && <p className="text-sm text-red-600">⚠️ {clarifyError}</p>}

                {/* 入力欄（送信で続行） */}
                <div className="flex gap-2">
                  <input
                    value={chatAnswer}
                    onChange={(e) => setChatAnswer(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !clarifying && sendChat()}
                    placeholder="例：毎週水曜は休み／前日が遅番なら翌日休み／特になし"
                    className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
                  />
                  <button
                    type="button"
                    onClick={sendChat}
                    disabled={clarifying || !chatAnswer.trim()}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
                  >
                    送信
                  </button>
                </div>

                {/* 整理できた要望（複数）の表示 */}
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
                    <p className="text-xs text-emerald-700">「次へ」で店舗の準備に進めます。</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
