// Types for the Admin batch execution page

import type { WorkflowVariable, WorkflowSummary } from './index'

/** A single row parsed from a clinical CSV file */
export interface ParsedRow {
  emis_number: string
  gender: string
  age: number
  code_term: string
  date: string      // raw date string from CSV, e.g. "24-Mar-17"
  value: string
  unit: string
  secondary_value: string
  secondary_unit: string
}

/** Metadata about an uploaded CSV file */
export interface UploadedFile {
  name: string
  rowCount: number  // data rows (excluding header)
}

/** Summary of a Code Term found in the data */
export interface CodeTermSummary {
  codeTerm: string
  count: number
  sampleValues: string[]   // first few unique values
  minValue?: number
  maxValue?: number
}

/** Patient data pivoted to one row per patient with latest values */
export interface PatientRecord {
  emis_number: string
  age: number
  gender: string
  /** Code Term → latest value (already picked most recent by date) */
  codeTermValues: Record<string, string>
}

/** Mapping from a Code Term to a workflow variable name */
export interface VariableMapping {
  variableName: string       // workflow variable name, e.g. "Total Cholesterol"
  codeTerm: string | null    // which Code Term maps to it, or null if unmapped
}

/** Gap analysis for a single workflow variable */
export interface GapAnalysisItem {
  variable: WorkflowVariable
  /** How this variable can be filled */
  status: 'direct_column' | 'mapped' | 'unmapped' | 'not_in_data'
  /** Which Code Term is mapped to it (if status is 'mapped') */
  mappedCodeTerm: string | null
}

/** Result of executing a workflow for one patient (from backend) */
export interface BatchResultRow {
  emis_number: string
  success: boolean
  output: string | null
  path: string[] | null
  status: 'SUCCESS' | 'SKIPPED' | 'ERROR'
  error: string | null
  missing_variables: string[]
}

/** Summary counts from batch execution */
export interface BatchSummary {
  total: number
  success: number
  skipped: number
  error: number
}

/** Full batch execution response from backend */
export interface BatchResponse {
  results: BatchResultRow[]
  summary: BatchSummary
}

/** Stage of the admin page workflow */
export type AdminStage = 'upload' | 'map' | 'preview' | 'results'

/** Store for selected workflow with its full details */
export interface SelectedWorkflow {
  summary: WorkflowSummary
  variables: WorkflowVariable[]
}
