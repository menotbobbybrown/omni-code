import axios from "axios"

// Create axios instance with default configuration
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
})

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    // Get token from cookie (set by NextAuth)
    const token = document.cookie
      .split("; ")
      .find((row) => row.startsWith("next-auth.session-token="))
      ?.split("=")[1]

    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }

    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized - redirect to login
      if (typeof window !== "undefined") {
        window.location.href = "/"
      }
    }
    return Promise.reject(error)
  }
)

export default api

// Helper functions for API calls
export async function getTasks(workspaceId?: number, status?: string) {
  const params = new URLSearchParams()
  if (workspaceId) params.append("workspace_id", workspaceId.toString())
  if (status) params.append("status", status)

  const response = await api.get(`/api/tasks?${params.toString()}`)
  return response.data
}

export async function getTask(taskId: number) {
  const response = await api.get(`/api/tasks/${taskId}`)
  return response.data
}

export async function createTask(workspaceId: number, taskType: string, payload: object) {
  const response = await api.post("/api/tasks", {
    workspace_id: workspaceId,
    task_type: taskType,
    payload,
  })
  return response.data
}

export async function resolveBlocker(taskId: number, resolution: string) {
  const response = await api.post(`/api/tasks/${taskId}/resolve`, { resolution })
  return response.data
}

export async function getThreadHistory(threadId: number) {
  const response = await api.get(`/api/threads/${threadId}/history`)
  return response.data
}

export async function rollbackAction(actionId: number) {
  const response = await api.post(`/api/rollback/${actionId}`)
  return response.data
}

export async function getModels() {
  const response = await api.get("/api/models")
  return response.data
}

export async function acceptChange(changeId: number) {
  const response = await api.post(`/api/pending-changes/${changeId}/accept`)
  return response.data
}

export async function rejectChange(changeId: number) {
  const response = await api.post(`/api/pending-changes/${changeId}/reject`)
  return response.data
}

export async function checkHealth() {
  const response = await api.get("/health")
  return response.data
}