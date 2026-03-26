import { api, API_BASE, ApiError, getSessionId } from './client'
import type {
  WorkflowDetailResponse,
  WorkflowSummary,
  CreateWorkflowRequest,
  CreateWorkflowResponse,
  FlowNode,
  FlowEdge,
  WorkflowVariable,
  WorkflowOutput,
  ToolCall,
  WorkflowPackage,
} from '../types'

export async function listPackages(): Promise<WorkflowPackage[]> {
  const response = await api.get<{ packages: WorkflowPackage[] }>('/api/packages')
  return response.packages
}

export async function createPackage(data: { name?: string; description?: string }): Promise<WorkflowPackage> {
  return api.post<WorkflowPackage>('/api/packages', data)
}

export async function getPackage(packageId: string): Promise<WorkflowPackage> {
  return api.get<WorkflowPackage>(`/api/packages/${packageId}`)
}

export async function updatePackage(packageId: string, data: { name?: string; description?: string }): Promise<WorkflowPackage> {
  return api.patch<WorkflowPackage>(`/api/packages/${packageId}`, data)
}

export async function deletePackage(packageId: string): Promise<void> {
  await api.delete(`/api/packages/${packageId}`)
}

export async function addWorkflowToPackage(packageId: string, workflowId: string): Promise<WorkflowPackage> {
  return api.post<WorkflowPackage>(`/api/packages/${packageId}/members`, { workflow_id: workflowId })
}

export async function removeWorkflowFromPackage(packageId: string, workflowId: string): Promise<WorkflowPackage> {
  return api.delete<WorkflowPackage>(`/api/packages/${packageId}/members/${workflowId}`)
}

export async function setPackageHead(packageId: string, workflowId: string): Promise<WorkflowPackage> {
  return api.post<WorkflowPackage>(`/api/packages/${packageId}/head`, { workflow_id: workflowId })
}

export async function publishPackage(packageId: string): Promise<WorkflowPackage> {
  return api.post<WorkflowPackage>(`/api/packages/${packageId}/publish`, {})
}

// List all workflows (returns summaries, not full workflows)
export async function listWorkflows(): Promise<WorkflowSummary[]> {
  const response = await api.get<{ workflows: WorkflowSummary[]; count: number }>('/api/workflows')
  return response.workflows
}

// Get single workflow by ID (returns backend-shaped response, not frontend Workflow)
export async function getWorkflow(workflowId: string): Promise<WorkflowDetailResponse> {
  return api.get<WorkflowDetailResponse>(`/api/workflows/${workflowId}`)
}

export async function exportWorkflowJson(workflowId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/workflows/${workflowId}/export`, {
    credentials: 'include',
    headers: { 'X-Session-Id': getSessionId() },
  })
  if (!response.ok) throw new Error('Failed to export workflow')
  return await response.blob()
}

export async function exportWorkflowBundle(workflowId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/workflows/${workflowId}/export-bundle`, {
    credentials: 'include',
    headers: { 'X-Session-Id': getSessionId() },
  })
  if (!response.ok) throw new Error('Failed to export workflow bundle')
  return await response.blob()
}

export async function exportWorkflowBundleWithWarnings(
  workflowId: string
): Promise<{ blob: Blob; warnings: string[] }> {
  const response = await fetch(`${API_BASE}/api/workflows/${workflowId}/export-bundle`, {
    credentials: 'include',
    headers: { 'X-Session-Id': getSessionId() },
  })
  if (!response.ok) throw new Error('Failed to export workflow bundle')
  const warningsHeader = response.headers.get('X-LEMON-Export-Warnings')
  let warnings: string[] = []
  if (warningsHeader) {
    try {
      warnings = JSON.parse(warningsHeader)
    } catch {
      warnings = []
    }
  }
  return { blob: await response.blob(), warnings }
}

export interface WorkflowImportError extends Error {
  validation_errors?: ValidationError[]
}

export async function importWorkflowJson(
  payload: unknown,
  forceImport = false
): Promise<{ workflow_id: string }> {
  try {
    return await api.post<{ workflow_id: string }>(`/api/workflows/import?force_import=${forceImport}`, payload)
  } catch (error) {
    const importError = error as WorkflowImportError
    if (error instanceof ApiError && error.data && typeof error.data === 'object') {
      importError.validation_errors = (error.data as { validation_errors?: ValidationError[] }).validation_errors
      if ((error.data as { message?: string }).message) {
        importError.message = (error.data as { message: string }).message
      }
    }
    throw importError
  }
}

export async function importWorkflowBundle(
  file: File,
  forceImport = false
): Promise<{ workflow_id: string; imported_count: number }> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`/api/workflows/import-bundle?force_import=${forceImport}`, {
    method: 'POST',
    body: form,
    credentials: 'include',
    headers: { 'X-Session-Id': getSessionId() },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: 'Failed to import workflow bundle' }))
    const error = new Error(body.message || body.error || 'Failed to import workflow bundle') as WorkflowImportError
    error.validation_errors = body.validation_errors
    throw error
  }
  return await response.json()
}

// Create new workflow
export async function createWorkflow(
  data: CreateWorkflowRequest
): Promise<CreateWorkflowResponse> {
  return api.post<CreateWorkflowResponse>('/api/workflows', data)
}

// Incrementally patch a workflow without changing draft status
// Use this for UI-triggered changes (edge labels, node positions, etc.)
export interface PatchWorkflowRequest {
  nodes?: FlowNode[]
  edges?: FlowEdge[]
  variables?: WorkflowVariable[]
  outputs?: WorkflowOutput[]
  output_type?: string
}

export interface PatchWorkflowResponse {
  workflow_id: string
  message: string
  updated_fields: string[]
}

export async function patchWorkflow(
  workflowId: string,
  data: PatchWorkflowRequest
): Promise<PatchWorkflowResponse> {
  return api.patch<PatchWorkflowResponse>(`/api/workflows/${workflowId}`, data)
}

// Delete workflow
export async function deleteWorkflow(workflowId: string): Promise<void> {
  await api.delete(`/api/workflows/${workflowId}`)
}

// Validate workflow structure
export interface ValidationError {
  code: string
  message: string
  node_id?: string
}

export interface ValidationResponse {
  success: boolean
  valid: boolean
  message: string
  errors?: ValidationError[]
}

export async function validateWorkflow(payload: {
  nodes: FlowNode[]
  edges: FlowEdge[]
  variables: WorkflowVariable[]  // Workflow variables for template validation
}): Promise<ValidationResponse> {
  return api.post<ValidationResponse>('/api/validate', payload)
}

// Fetch conversation history from the backend's in-memory ConversationStore.
// Returns messages if the conversation is still alive in memory, 404 otherwise.
export interface ConversationHistoryResponse {
  id: string
  messages: Array<{
    id: string
    role: 'user' | 'assistant'
    content: string
    timestamp: string
    tool_calls: ToolCall[]
  }>
}

export async function getConversationHistory(
  conversationId: string
): Promise<ConversationHistoryResponse | null> {
  try {
    return await api.get<ConversationHistoryResponse>(`/api/chat/${conversationId}`)
  } catch {
    // 404 = conversation evicted or server restarted — not an error
    return null
  }
}

// Compile workflow to Python code
export interface CompilePythonResponse {
  success: boolean
  code: string | null
  error?: string
  warnings: string[]
  partial_failure?: boolean
}

export interface CompilePythonRequest {
  nodes: FlowNode[]
  edges: FlowEdge[]
  variables: WorkflowVariable[]
  outputs?: WorkflowOutput[]
  name?: string
  include_imports?: boolean
  include_docstring?: boolean
  include_main?: boolean
}

export interface CompileStoredWorkflowRequest {
  workflow_id: string
  include_imports?: boolean
  include_docstring?: boolean
  include_main?: boolean
}

export async function compileToPython(
  payload: CompilePythonRequest
): Promise<CompilePythonResponse> {
  return api.post<CompilePythonResponse>('/api/workflows/compile', payload)
}

export async function compileStoredWorkflowToPython(
  payload: CompileStoredWorkflowRequest
): Promise<CompilePythonResponse> {
  return api.post<CompilePythonResponse>('/api/workflows/compile-stored', payload)
}

// ============ Peer Review / Public Workflows ============

// Response type for public workflow list
export interface PublicWorkflowsResponse {
  workflows: WorkflowSummary[]
  count: number
  publish_threshold: number  // Votes needed for "reviewed" status
}

// Response type for voting
export interface VoteResponse {
  success: boolean
  net_votes: number
  review_status: 'unreviewed' | 'reviewed'
  user_vote: number | null  // +1, -1, or null if vote removed
}

// List published workflows for peer review
// Can filter by review_status: 'unreviewed', 'reviewed', or all (no filter)
// Returns workflows and the publish threshold
export async function listPublicWorkflows(
  reviewStatus?: 'unreviewed' | 'reviewed'
): Promise<{ workflows: WorkflowSummary[], publishThreshold: number }> {
  const params = new URLSearchParams()
  if (reviewStatus) {
    params.set('review_status', reviewStatus)
  }
  const query = params.toString()
  const endpoint = query ? `/api/workflows/public?${query}` : '/api/workflows/public'

  const response = await api.get<PublicWorkflowsResponse>(endpoint)
  return {
    workflows: response.workflows || [],
    publishThreshold: response.publish_threshold ?? 1,  // Default to 1 if not provided
  }
}

// Get a specific published workflow by ID
export async function getPublicWorkflow(workflowId: string): Promise<WorkflowDetailResponse> {
  return api.get<WorkflowDetailResponse>(`/api/workflows/public/${workflowId}`)
}

// Vote on a published workflow
// vote: +1 for upvote, -1 for downvote, 0 to remove vote
export async function voteOnWorkflow(
  workflowId: string,
  vote: number
): Promise<VoteResponse> {
  return api.post<VoteResponse>(`/api/workflows/public/${workflowId}/vote`, { vote })
}

