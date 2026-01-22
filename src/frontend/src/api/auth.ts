import { api } from './client'

export interface AuthUser {
  id: string
  email: string
  name: string
}

export interface AuthResponse {
  user: AuthUser
}

interface LoginPayload {
  email: string
  password: string
  remember?: boolean
}

export function loginUser(payload: LoginPayload): Promise<AuthResponse> {
  return api.post<AuthResponse>('/api/auth/login', payload)
}

export function logoutUser(): Promise<{ success: boolean }> {
  return api.post<{ success: boolean }>('/api/auth/logout')
}

export function getCurrentUser(): Promise<AuthResponse> {
  return api.get<AuthResponse>('/api/auth/me')
}
