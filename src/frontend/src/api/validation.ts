import { api } from './client'
import type {
  StartValidationRequest,
  StartValidationResponse,
  SubmitValidationRequest,
  SubmitValidationResponse,
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
