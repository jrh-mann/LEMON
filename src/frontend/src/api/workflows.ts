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
