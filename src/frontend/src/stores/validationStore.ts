import { create } from 'zustand'
import type {
  ValidationSession,
  ValidationCase,
  ValidationScore,
  ValidationProgress,
} from '../types'

interface ValidationState {
  // Session
  session: ValidationSession | null
  sessionId: string | null

  // Current case
  currentCase: ValidationCase | null

  // Progress and score
  progress: ValidationProgress | null
  score: ValidationScore | null

  // State
  isSubmitting: boolean
  lastResult: {
    matched: boolean
    userAnswer: string
    workflowOutput: string
  } | null

  // Actions
  setSession: (session: ValidationSession | null) => void
  setSessionId: (id: string | null) => void
  setCurrentCase: (testCase: ValidationCase | null) => void
  setProgress: (progress: ValidationProgress | null) => void
  setScore: (score: ValidationScore | null) => void
  setSubmitting: (submitting: boolean) => void
  setLastResult: (result: ValidationState['lastResult']) => void

  // Start new session
  startSession: (sessionId: string, firstCase: ValidationCase, progress: ValidationProgress) => void

  // Handle answer result
  handleAnswerResult: (
    matched: boolean,
    userAnswer: string,
    workflowOutput: string,
    nextCase: ValidationCase | null,
    progress: ValidationProgress,
    score: ValidationScore
  ) => void

  // Reset
  reset: () => void
}

export const useValidationStore = create<ValidationState>((set) => ({
  // Initial state
  session: null,
  sessionId: null,
  currentCase: null,
  progress: null,
  score: null,
  isSubmitting: false,
  lastResult: null,

  // Actions
  setSession: (session) => set({ session }),
  setSessionId: (id) => set({ sessionId: id }),
  setCurrentCase: (testCase) => set({ currentCase: testCase }),
  setProgress: (progress) => set({ progress }),
  setScore: (score) => set({ score }),
  setSubmitting: (submitting) => set({ isSubmitting: submitting }),
  setLastResult: (result) => set({ lastResult: result }),

  // Start new session
  startSession: (sessionId, firstCase, progress) =>
    set({
      sessionId,
      currentCase: firstCase,
      progress,
      score: null,
      lastResult: null,
      isSubmitting: false,
    }),

  // Handle answer result
  handleAnswerResult: (matched, userAnswer, workflowOutput, nextCase, progress, score) =>
    set({
      lastResult: { matched, userAnswer, workflowOutput },
      currentCase: nextCase,
      progress,
      score,
      isSubmitting: false,
    }),

  // Reset
  reset: () =>
    set({
      session: null,
      sessionId: null,
      currentCase: null,
      progress: null,
      score: null,
      isSubmitting: false,
      lastResult: null,
    }),
}))
