// API client with session handling and error management

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:5001'

// Session ID management
const SESSION_KEY = 'lemon_session_id'

export function getSessionId(): string {
  let sessionId = localStorage.getItem(SESSION_KEY)
  if (!sessionId) {
    sessionId = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
    localStorage.setItem(SESSION_KEY, sessionId)
  }
  return sessionId
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY)
}

// API error class
export class ApiError extends Error {
  status: number
  data?: unknown

  constructor(message: string, status: number, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

// Request options type
interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
}

// Generic fetch wrapper
export async function apiRequest<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const { body, headers: customHeaders, ...rest } = options

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    'X-Session-Id': getSessionId(),
    ...customHeaders,
  }

  const config: RequestInit = {
    ...rest,
    headers,
  }

  if (body !== undefined) {
    config.body = JSON.stringify(body)
  }

  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`

  const response = await fetch(url, config)

  if (!response.ok) {
    let errorData: unknown
    try {
      errorData = await response.json()
    } catch {
      errorData = { error: response.statusText }
    }

    const message =
      (errorData as { error?: string })?.error ||
      `HTTP ${response.status}: ${response.statusText}`

    throw new ApiError(message, response.status, errorData)
  }

  // Handle empty responses
  const contentType = response.headers.get('content-type')
  if (contentType?.includes('application/json')) {
    return response.json()
  }

  return {} as T
}

// Convenience methods
export const api = {
  get: <T>(endpoint: string, options?: RequestOptions) =>
    apiRequest<T>(endpoint, { ...options, method: 'GET' }),

  post: <T>(endpoint: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(endpoint, { ...options, method: 'POST', body }),

  put: <T>(endpoint: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(endpoint, { ...options, method: 'PUT', body }),

  delete: <T>(endpoint: string, options?: RequestOptions) =>
    apiRequest<T>(endpoint, { ...options, method: 'DELETE' }),
}

export { API_BASE }
