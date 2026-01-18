import { api } from './client'
import type {
  StartValidationRequest,
  StartValidationResponse,
  SubmitValidationRequest,
  SubmitValidationResponse,
  ValidationCase,
  ValidationScore,
  ValidationProgress,
} from '../types'

// Start a new validation session
export async function startValidation(
  request: StartValidationRequest
): Promise<StartValidationResponse> {
  return api.post<StartValidationResponse>('/api/validation/start', request)
}

// Submit an answer for current validation case
export async function submitValidationAnswer(
  request: SubmitValidationRequest
): Promise<SubmitValidationResponse> {
  return api.post<SubmitValidationResponse>('/api/validation/submit', request)
}

// Get validation session status
export interface ValidationStatusResponse {
  session: {
    id: string
    workflow_id: string
    strategy: string
    progress: ValidationProgress
  }
  current_case: ValidationCase | null
  score: ValidationScore
}

export async function getValidationStatus(
  sessionId: string
): Promise<ValidationStatusResponse> {
  return api.get<ValidationStatusResponse>(`/api/validation/${sessionId}`)
}
