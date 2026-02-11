/**
 * Miro integration API client
 *
 * Handles Miro token management and board imports.
 */

import { api } from './client'

// ============ Types ============

export interface MiroBoard {
  id: string
  name: string
  description: string
  modified_at: string
}

export interface MiroBoardsResponse {
  boards: MiroBoard[]
  count: number
}

export interface MiroWarning {
  code: string
  message: string
  fix?: string
}

export interface MiroInference {
  id: string
  type: string
  original_text: string
  inferred: Record<string, unknown>
  confidence: 'high' | 'medium' | 'low'
}

export interface MiroImportResponse {
  success: boolean
  workflow?: {
    name: string
    description: string
    nodes: any[]
    edges: any[]
    variables: any[]
    output_type: string
    miro_board_id: string
  }
  board?: {
    id: string
    name: string
  }
  stats?: {
    nodes: number
    edges: number
    variables: number
  }
  warnings: MiroWarning[]
  inferences: MiroInference[]
  error?: string
}

export interface MiroConfirmResponse {
  success: boolean
  workflow_id: string
  name: string
  miro_board_id?: string
  message: string
  validation_warnings: Array<{ code: string; message: string }>
}

// ============ OAuth & Token Management ============

export interface MiroStatusResponse {
  connected: boolean
  service: string
  connected_at?: string
  needs_refresh?: boolean
}

/**
 * Check if user has a Miro connection configured
 */
export async function getMiroStatus(): Promise<MiroStatusResponse> {
  return api.get<MiroStatusResponse>('/api/auth/miro/status')
}

/**
 * Start OAuth flow - redirects to Miro authorization
 * Call this when user clicks "Connect to Miro"
 */
export function startMiroOAuth(): void {
  // Redirect to backend OAuth endpoint, which redirects to Miro
  // Use full URL because window.location.href bypasses Vite's proxy
  const backendUrl = import.meta.env.VITE_API_URL || 'http://localhost:5001'
  window.location.href = `${backendUrl}/api/auth/miro`
}

/**
 * Refresh an expired Miro token
 */
export async function refreshMiroToken(): Promise<{ success: boolean; message: string }> {
  return api.post('/api/auth/miro/refresh')
}

/**
 * Disconnect Miro - removes stored tokens
 */
export async function disconnectMiro(): Promise<{ success: boolean; message: string }> {
  return api.delete('/api/auth/miro/token')
}

// ============ Board Import ============

/**
 * List Miro boards accessible to the user
 */
export async function listMiroBoards(): Promise<MiroBoard[]> {
  const response = await api.get<MiroBoardsResponse>('/api/import/miro/boards')
  return response.boards
}

/**
 * Import a Miro board as a draft workflow
 *
 * @param boardUrlOrId - Full Miro URL or board ID
 * @returns Draft workflow with warnings for review
 */
export async function importMiroBoard(boardUrlOrId: string): Promise<MiroImportResponse> {
  // Determine if it's a URL or ID
  const isUrl = boardUrlOrId.startsWith('http')
  const payload = isUrl ? { board_url: boardUrlOrId } : { board_id: boardUrlOrId }

  return api.post<MiroImportResponse>('/api/import/miro', payload)
}

/**
 * Confirm and save an imported workflow
 *
 * @param workflow - The draft workflow from importMiroBoard
 * @param acceptedInferences - IDs of inferences to accept
 */
export async function confirmMiroImport(
  workflow: MiroImportResponse['workflow'],
  acceptedInferences: string[] = []
): Promise<MiroConfirmResponse> {
  return api.post<MiroConfirmResponse>('/api/import/miro/confirm', {
    workflow,
    accepted_inferences: acceptedInferences,
  })
}
