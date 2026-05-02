import { OmniCodeClient } from "@omnicode/sdk"

const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function getToken() {
  if (typeof document === "undefined") return undefined
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith("next-auth.session-token="))
    ?.split("=")[1]
}

export const client = new OmniCodeClient(baseUrl, getToken())

export async function getTasks(workspaceId?: number, status?: string) {
  return client.tasks.list({ workspace_id: workspaceId, status })
}

export async function getTask(taskId: number) {
  return client.tasks.get(taskId)
}

export async function createTask(workspaceId: number, taskType: string, payload: object) {
  return client.tasks.create({
    workspace_id: workspaceId,
    task_type: taskType,
    payload,
  })
}

export async function resolveBlocker(taskId: number, resolution: string) {
  return client.tasks.resolve(taskId, resolution)
}

export async function getThreadHistory(threadId: number) {
  return client.threads.getHistory(threadId)
}

export async function rollbackAction(actionId: number) {
  return client.rollback(actionId)
}

export async function getModels() {
  return client.models.list()
}

export async function acceptChange(changeId: number) {
  return client.changes.accept(changeId)
}

export async function rejectChange(changeId: number) {
  return client.changes.reject(changeId)
}

export async function checkHealth() {
  return client.health.check()
}

export async function getSkills(workspaceId?: number, category?: string) {
  return client.skills.list({ workspace_id: workspaceId, category })
}

export async function getSkill(skillId: number) {
  return client.skills.get(skillId)
}

export async function createSkill(skill: any) {
  return client.skills.create(skill)
}

export async function updateSkill(skillId: number, skill: any) {
  return client.skills.update(skillId, skill)
}

export async function deleteSkill(skillId: number) {
  return client.skills.delete(skillId)
}

export async function searchSkills(query: string, workspaceId?: number) {
  return client.skills.search(query, workspaceId)
}

export async function getSkillCategories(workspaceId?: number) {
  return client.skills.getCategories(workspaceId)
}

export async function generateWorkspaceSkill(workspaceId: number) {
  return client.workspaces.generateSkill(workspaceId)
}

export async function analyzeWorkspace(workspaceId: number) {
  return client.workspaces.analyze(workspaceId)
}

export default client;
