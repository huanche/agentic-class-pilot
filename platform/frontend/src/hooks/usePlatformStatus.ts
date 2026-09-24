import { useQuery } from "@tanstack/react-query"

export type PlatformStatus = {
  teacherReady?: boolean
  studentAgentReady?: boolean
  teacherUrl?: string
}

async function fetchPlatformStatus(): Promise<PlatformStatus> {
  const response = await fetch("/api/v1/platform/status", { credentials: "include" })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

/** Shared platform-status query; all teacher-service entries derive from it. */
export function usePlatformStatus() {
  return useQuery({
    queryKey: ["platform-status"],
    queryFn: fetchPlatformStatus,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })
}

/** Absolute URL of a teacher-workspace page, or undefined while the teacher service is unknown. */
export function teacherServiceUrl(teacherUrl: string | undefined, path: string): string | undefined {
  return teacherUrl ? `${teacherUrl.replace(/\/+$/, "")}${path}` : undefined
}
