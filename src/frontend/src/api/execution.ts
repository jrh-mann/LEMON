import { api } from './client'
import type { ExecutionResult, ExecuteWorkflowRequest } from '../types'

// Execute a workflow with given inputs
export async function executeWorkflow(
  workflowId: string,
  inputs: ExecuteWorkflowRequest
): Promise<ExecutionResult> {
  return api.post<ExecutionResult>(`/api/execute/${workflowId}`, inputs)
}
