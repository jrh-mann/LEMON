// Zustand store for admin batch execution page state

import { create } from 'zustand'
import type { WorkflowSummary, WorkflowVariable } from '../types'
import type {
  ParsedRow,
  UploadedFile,
  CodeTermSummary,
  PatientRecord,
  VariableMapping,
  BatchResultRow,
  BatchSummary,
  AdminStage,
} from '../types/admin'

interface AdminState {
  // Upload stage
  uploadedFiles: UploadedFile[]
  parsedRows: ParsedRow[]
  codeTerms: CodeTermSummary[]
  patients: PatientRecord[]

  // Map stage
  workflows: WorkflowSummary[]
  selectedWorkflowId: string | null
  selectedWorkflowVariables: WorkflowVariable[]
  mappings: VariableMapping[]

  // Execution
  isExecuting: boolean
  results: BatchResultRow[]
  summary: BatchSummary | null

  // UI
  stage: AdminStage

  // Actions
  setUploadedFiles: (files: UploadedFile[]) => void
  setParsedRows: (rows: ParsedRow[]) => void
  setCodeTerms: (terms: CodeTermSummary[]) => void
  setPatients: (patients: PatientRecord[]) => void
  setWorkflows: (workflows: WorkflowSummary[]) => void
  selectWorkflow: (id: string | null, variables: WorkflowVariable[]) => void
  setMappings: (mappings: VariableMapping[]) => void
  updateMapping: (variableName: string, codeTerm: string | null) => void
  setExecuting: (executing: boolean) => void
  setResults: (results: BatchResultRow[], summary: BatchSummary) => void
  setStage: (stage: AdminStage) => void
  reset: () => void
}

const initialState = {
  uploadedFiles: [] as UploadedFile[],
  parsedRows: [] as ParsedRow[],
  codeTerms: [] as CodeTermSummary[],
  patients: [] as PatientRecord[],
  workflows: [] as WorkflowSummary[],
  selectedWorkflowId: null as string | null,
  selectedWorkflowVariables: [] as WorkflowVariable[],
  mappings: [] as VariableMapping[],
  isExecuting: false,
  results: [] as BatchResultRow[],
  summary: null as BatchSummary | null,
  stage: 'upload' as AdminStage,
}

export const useAdminStore = create<AdminState>((set) => ({
  ...initialState,

  setUploadedFiles: (files) => set({ uploadedFiles: files }),
  setParsedRows: (rows) => set({ parsedRows: rows }),
  setCodeTerms: (terms) => set({ codeTerms: terms }),
  setPatients: (patients) => set({ patients }),
  setWorkflows: (workflows) => set({ workflows }),

  selectWorkflow: (id, variables) =>
    set({ selectedWorkflowId: id, selectedWorkflowVariables: variables }),

  setMappings: (mappings) => set({ mappings }),

  updateMapping: (variableName, codeTerm) =>
    set((state) => ({
      mappings: state.mappings.map((m) =>
        m.variableName === variableName ? { ...m, codeTerm } : m
      ),
    })),

  setExecuting: (executing) => set({ isExecuting: executing }),

  setResults: (results, summary) =>
    set({ results, summary, stage: 'results' }),

  setStage: (stage) => set({ stage }),

  reset: () => set(initialState),
}))
