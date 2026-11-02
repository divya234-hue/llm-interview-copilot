import { useState } from 'react'

export function useWorkspaceId(): string {
  const [workspaceId] = useState<string>(() => {
    const key = 'interview-copilot-workspace-id'
    const existing = localStorage.getItem(key)
    if (existing) {
      return existing
    }
    const fallback = 'local'
    localStorage.setItem(key, fallback)
    return fallback
  })

  return workspaceId
}
