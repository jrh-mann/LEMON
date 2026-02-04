import { api } from './client'
import type {
  Workflow,
  WorkflowSummary,
  SearchWorkflowsResponse,
  DomainsResponse,
  CreateWorkflowRequest,
  CreateWorkflowResponse,
} from '../types'

// List all workflows (returns summaries, not full workflows)
export async function listWorkflows(): Promise<WorkflowSummary[]> {
  const response = await api.get<{ workflows: WorkflowSummary[]; count: number }>('/api/workflows')
  return response.workflows
}

// Get single workflow by ID
export async function getWorkflow(workflowId: string): Promise<Workflow> {
  return api.get<Workflow>(`/api/workflows/${workflowId}`)
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
  nodes?: any[]
  edges?: any[]
  variables?: any[]
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
  nodes: any[]
  edges: any[]
  variables: any[]  // Workflow variables for template validation
}): Promise<ValidationResponse> {
  return api.post<ValidationResponse>('/api/validate', payload)
}

// Compile workflow to Python code
export interface CompilePythonResponse {
  success: boolean
  code: string | null
  error?: string
  warnings: string[]
}

export interface CompilePythonRequest {
  nodes: any[]
  edges: any[]
  variables: any[]
  outputs?: any[]
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
export async function getPublicWorkflow(workflowId: string): Promise<Workflow> {
  return api.get<Workflow>(`/api/workflows/public/${workflowId}`)
}

// Vote on a published workflow
// vote: +1 for upvote, -1 for downvote, 0 to remove vote
export async function voteOnWorkflow(
  workflowId: string,
  vote: number
): Promise<VoteResponse> {
  return api.post<VoteResponse>(`/api/workflows/public/${workflowId}/vote`, { vote })
}
