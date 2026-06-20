import { WizardProvider } from "./wizard/context"
import { Shell } from "./wizard/Shell"

// 提出者〜管理者までを1本のページ遷移ウィザードにまとめる
export default function App() {
  return (
    <WizardProvider>
      <Shell />
    </WizardProvider>
  )
}
