import { Navigate, Route, Routes } from "react-router-dom"

import { Shell } from "./components/Shell.tsx"
import { ChatPage } from "./pages/ChatPage.tsx"
import { DocumentsPage } from "./pages/DocumentsPage.tsx"
import { EvaluationsPage } from "./pages/EvaluationsPage.tsx"
import { IntegrationsPage } from "./pages/IntegrationsPage.tsx"
import { TracesPage } from "./pages/TracesPage.tsx"

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentsPage />} />
        <Route path="/integrations" element={<IntegrationsPage />} />
        <Route path="/evaluations" element={<EvaluationsPage />} />
        <Route path="/traces" element={<TracesPage />} />
        <Route path="/traces/:messageId" element={<TracesPage />} />
      </Route>
    </Routes>
  )
}
