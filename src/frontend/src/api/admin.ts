// API client for admin batch execution

import { api } from './client'
import type { BatchResponse } from '../types/admin'
import type { WorkflowVariable } from '../types'

/** Fetch full workflow details (including variables/inputs) by ID */
export async function getWorkflow(workflowId: string): Promise<{
  id: string
  inputs: WorkflowVariable[]
  tree: Record<string, unknown>
}> {
  return api.get(`/api/workflows/${workflowId}`)
}

/** Execute a workflow against a batch of patients */
export async function batchExecute(
  workflowId: string,
  patients: Array<{ emis_number: string; input_values: Record<string, unknown> }>
): Promise<BatchResponse> {
  return api.post('/api/admin/batch-execute', {
    workflow_id: workflowId,
    patients,
  })
}
