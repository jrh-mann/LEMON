import { api } from './client'
import type {
  Workflow,
  WorkflowDetailResponse,
  WorkflowSummary,
  SearchWorkflowsResponse,
  DomainsResponse,
  CreateWorkflowRequest,
  CreateWorkflowResponse,
  FlowNode,
  FlowEdge,
  WorkflowVariable,
  WorkflowOutput,
  ToolCall,
} from '../types'

// List all workflows (returns summaries, not full workflows)
export async function listWorkflows(): Promise<WorkflowSummary[]> {
  const response = await api.get<{ workflows: WorkflowSummary[]; count: number }>('/api/workflows')
  return response.workflows
}

// Get single workflow by ID (returns backend-shaped response, not frontend Workflow)
export async function getWorkflow(workflowId: string): Promise<WorkflowDetailResponse> {
  return api.get<WorkflowDetailResponse>(`/api/workflows/${workflowId}`)
}

// Create new workflow
export async function createWorkflow(
  data: CreateWorkflowRequest
): Promise<CreateWorkflowResponse> {
  return api.post<CreateWorkflowResponse>('/api/workflows', data)
}

// Update existing workflow
// Uses PUT to update an existing workflow by ID
export async function updateWorkflow(
  workflowId: string,
  data: CreateWorkflowRequest
): Promise<CreateWorkflowResponse> {
  return api.put<CreateWorkflowResponse>(`/api/workflows/${workflowId}`, data)
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

// Search workflows
export interface SearchParams {
  q?: string
  domain?: string
  validated?: boolean
  input?: string
  output?: string
}

export async function searchWorkflows(
  params: SearchParams = {}
): Promise<WorkflowSummary[]> {
  const searchParams = new URLSearchParams()

  if (params.q) searchParams.set('q', params.q)
  if (params.domain) searchParams.set('domain', params.domain)
  if (params.validated !== undefined)
    searchParams.set('validated', String(params.validated))
  if (params.input) searchParams.set('input', params.input)
  if (params.output) searchParams.set('output', params.output)

  const queryString = searchParams.toString()
  const endpoint = queryString ? `/api/search?${queryString}` : '/api/search'

  const response = await api.get<SearchWorkflowsResponse>(endpoint)
  return response.workflows
}

// Get available domains
export async function getDomains(): Promise<string[]> {
  const response = await api.get<DomainsResponse>('/api/domains')
  return response.domains
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

export async function compileToPython(
  payload: CompilePythonRequest
): Promise<CompilePythonResponse> {
  return api.post<CompilePythonResponse>('/api/workflows/compile', payload)
}

