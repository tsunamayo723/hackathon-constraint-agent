import type { Masters } from "../types"
import { personInfo } from "../lib/people"

type Props = {
  masters: Masters
  selected: string | null
  onSelect: (id: string) => void
}

// ①「あなたは誰ですか」— マスタからシフト提出者を選ぶ（役職・新人フラグも表示）
export function PersonPicker({ masters, selected, onSelect }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      {masters.persons.map((p) => {
        const active = p.id === selected
        const info = personInfo(masters, p)
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => onSelect(p.id)}
            className={
              "rounded-lg border px-3 py-2 text-left text-sm transition " +
              (active
                ? "border-blue-600 bg-blue-600 text-white shadow"
                : "border-gray-300 bg-white text-gray-700 hover:border-blue-400")
            }
          >
            <div className="flex items-center gap-1 font-medium">
              {p.name}
              {info.newbie && (
                <span className={"rounded px-1 text-[10px] " + (active ? "bg-white/25" : "bg-amber-100 text-amber-700")}>
                  🔰新人
                </span>
              )}
            </div>
            <div className={"text-[11px] " + (active ? "text-blue-100" : "text-gray-400")}>{info.roleName}</div>
          </button>
        )
      })}
    </div>
  )
}
