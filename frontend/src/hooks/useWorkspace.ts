import { useCallback, useState } from 'react'
import { loadWorkspaceData } from '../services/interviewService'
import type { DashboardStats, InterviewItem } from '../types'

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

export function useWorkspace(onError: (message: string) => void) {
  const workspaceId = useWorkspaceId()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [history, setHistory] = useState<InterviewItem[]>([])

  const refresh = useCallback(async () => {
    try {
      const [dashboard, items] = await loadWorkspaceData(workspaceId)
      setStats(dashboard)
      setHistory(items)
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : 'Could not load dashboard data.')
    }
  }, [onError, workspaceId])

  return { workspaceId, stats, history, refresh }
}
