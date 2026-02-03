// Admin page for batch workflow execution against clinical CSV data.
//
// Single-page dashboard layout: data/mapping on the left, results on the right.
// Raw clinical data is parsed client-side only — the server receives only
// structured {emis_number, input_values} dicts for execution.

import { useCallback, useEffect, useMemo, useState } from 'react'
import Papa from 'papaparse'
import { useAdminStore } from '../stores/adminStore'
import { listWorkflows } from '../api/workflows'
import { getWorkflow, batchExecute } from '../api/admin'
import type {
  ParsedRow,
  UploadedFile,
  CodeTermSummary,
  PatientRecord,
  VariableMapping,
  GapAnalysisItem,
} from '../types/admin'
import type { WorkflowVariable } from '../types'

// ============================================================================
// CSV PARSING HELPERS (client-side only)
// ============================================================================

/** Parse a date string like "24-Mar-17" or "08-Oct-15" into a Date */
function parseEMISDate(dateStr: string): Date {
  if (!dateStr) return new Date(0)
  const d = new Date(dateStr)
  if (!isNaN(d.getTime())) return d
  const parts = dateStr.split('-')
  if (parts.length === 3) {
    const [day, mon, year] = parts
    const fullYear = parseInt(year) < 50 ? `20${year}` : `19${year}`
    const d2 = new Date(`${day} ${mon} ${fullYear}`)
    if (!isNaN(d2.getTime())) return d2
  }
  return new Date(0)
}

/** Parse CSV text, auto-detecting header row by scanning for "EMIS Number".
 *  Detects whether column 3 is "Code Term" (clinical observations) or something
 *  else (e.g. "Date Drug Added" in Medication exports). Files without a Code Term
 *  column still contribute Age/Gender per patient but don't add Code Terms. */
function parseCSVText(text: string, fileName: string): { rows: ParsedRow[]; file: UploadedFile } {
  const result = Papa.parse<string[]>(text, { header: false, skipEmptyLines: 'greedy' })

  // Find the header row (contains "EMIS Number")
  let headerIndex = -1
  for (let i = 0; i < Math.min(result.data.length, 20); i++) {
    const firstCol = result.data[i][0]?.toString().toLowerCase().trim()
    if (firstCol === 'emis number' || firstCol === 'emis') {
      headerIndex = i
      break
    }
  }
  if (headerIndex === -1) headerIndex = 9 // fallback for standard EMIS export

  // Check if column 3 is actually "Code Term" — some EMIS exports have different
  // column layouts (e.g. Medication has "Date Drug Added" in column 3)
  const headerRow = result.data[headerIndex]
  const col3Header = headerRow?.[3]?.toString().toLowerCase().trim() ?? ''
  const hasCodeTermCol = col3Header === 'code term' || col3Header === 'codeterm'
    || col3Header === 'read code description' || col3Header === ''

  const dataRows = result.data.slice(headerIndex + 1)
  const rows: ParsedRow[] = []
  for (const cols of dataRows) {
    const emisNum = cols[0]?.toString().trim()
    if (!emisNum || cols.length < 3 || !/^\d+$/.test(emisNum)) continue
    rows.push({
      emis_number: emisNum,
      gender: cols[1]?.toString().trim() ?? '',
      age: parseInt(cols[2]?.toString().trim() ?? '0', 10) || 0,
      // Only read Code Term if the column header confirms it's a Code Term column
      code_term: hasCodeTermCol ? (cols[3]?.toString().trim() ?? '') : '',
      date: hasCodeTermCol ? (cols[4]?.toString().trim() ?? '') : '',
      value: hasCodeTermCol ? (cols[5]?.toString().trim() ?? '') : '',
      unit: hasCodeTermCol ? (cols[6]?.toString().trim() ?? '') : '',
      secondary_value: hasCodeTermCol ? (cols[7]?.toString().trim() ?? '') : '',
      secondary_unit: hasCodeTermCol ? (cols[8]?.toString().trim() ?? '') : '',
    })
  }
  return { rows, file: { name: fileName, rowCount: rows.length } }
}

/** Build Code Term summaries from parsed rows */
function buildCodeTermSummaries(rows: ParsedRow[]): CodeTermSummary[] {
  const termMap = new Map<string, { count: number; values: Set<string>; nums: number[] }>()
  for (const row of rows) {
    if (!row.code_term) continue
    let entry = termMap.get(row.code_term)
    if (!entry) {
      entry = { count: 0, values: new Set(), nums: [] }
      termMap.set(row.code_term, entry)
    }
    entry.count++
    if (entry.values.size < 5) entry.values.add(row.value)
    const n = parseFloat(row.value)
    if (!isNaN(n)) entry.nums.push(n)
  }
  return Array.from(termMap.entries())
    .map(([codeTerm, info]) => ({
      codeTerm,
      count: info.count,
      sampleValues: Array.from(info.values),
      minValue: info.nums.length ? Math.min(...info.nums) : undefined,
      maxValue: info.nums.length ? Math.max(...info.nums) : undefined,
    }))
    .sort((a, b) => b.count - a.count)
}

/** Pivot long-format rows into one record per patient (latest value per Code Term) */
function pivotToPatients(rows: ParsedRow[]): PatientRecord[] {
  const patientMap = new Map<string, {
    age: number; gender: string
    codeTermLatest: Map<string, { date: Date; value: string }>
  }>()
  for (const row of rows) {
    if (!row.emis_number) continue
    let patient = patientMap.get(row.emis_number)
    if (!patient) {
      patient = { age: row.age, gender: row.gender, codeTermLatest: new Map() }
      patientMap.set(row.emis_number, patient)
    }
    if (row.code_term) {
      const date = parseEMISDate(row.date)
      const existing = patient.codeTermLatest.get(row.code_term)
      if (!existing || date > existing.date) {
        patient.codeTermLatest.set(row.code_term, { date, value: row.value })
      }
    }
  }
  return Array.from(patientMap.entries()).map(([emis, data]) => ({
    emis_number: emis,
    age: data.age,
    gender: data.gender,
    codeTermValues: Object.fromEntries(
      Array.from(data.codeTermLatest.entries()).map(([k, v]) => [k, v.value])
    ),
  }))
}

/** Coerce a string value to the type expected by a workflow variable */
function coerceValue(value: string, varType: string): unknown {
  switch (varType) {
    case 'int': return parseInt(value, 10)
    case 'float': return parseFloat(value)
    case 'bool': return ['true', 'yes', '1', 'y'].includes(value.toLowerCase())
    default: return value
  }
}

/** Fuzzy match: does `needle` appear as a substring (case-insensitive) in `haystack`? */
function fuzzyMatch(needle: string, haystack: string): boolean {
  const a = needle.toLowerCase()
  const b = haystack.toLowerCase()
  // Check if all significant words from needle appear in haystack
  const words = a.split(/\s+/).filter(w => w.length > 2)
  return words.length > 0 && words.every(w => b.includes(w))
}

/** Check if a Code Term name looks like a date (e.g. "01-Oct-2025", "22-Nov-2025") */
function looksLikeDate(codeTerm: string): boolean {
  return /^\d{1,2}-[A-Za-z]{3}-\d{2,4}$/.test(codeTerm.trim())
}

/** Check if a Code Term looks like it has numeric data */
function hasNumericData(ct: CodeTermSummary): boolean {
  return ct.minValue !== undefined && ct.maxValue !== undefined
}

/** Check if a Code Term looks boolean (small set of distinct values, text-like) */
function looksBoolish(ct: CodeTermSummary): boolean {
  if (ct.sampleValues.length === 0) return false
  const boolWords = ['yes', 'no', 'true', 'false', 'y', 'n', '1', '0']
  return ct.sampleValues.every(v => boolWords.includes(v.toLowerCase().trim()))
}

/**
 * Filter and rank Code Terms for a given workflow variable type.
 * Prevents the dropdown from showing hundreds of irrelevant items.
 * - numeric variables → only Code Terms with numeric values
 * - bool variables → only Code Terms with boolean-like values
 * - string variables → all Code Terms, but deprioritise purely numeric ones
 * Fuzzy matches are always sorted to the top.
 */
function relevantCodeTerms(
  allTerms: CodeTermSummary[],
  variableName: string,
  variableType: string
): CodeTermSummary[] {
  // Always exclude date-like Code Terms — they're never valid variable mappings
  const nonDates = allTerms.filter(ct => !looksLikeDate(ct.codeTerm))
  let filtered: CodeTermSummary[]

  switch (variableType) {
    case 'int':
    case 'float':
      // Only show Code Terms that contain numeric values
      filtered = nonDates.filter(hasNumericData)
      break
    case 'bool': {
      // Prefer Code Terms with boolean-like values, fall back to all non-date terms
      const boolish = nonDates.filter(ct => looksBoolish(ct))
      filtered = boolish.length > 0 ? boolish : nonDates
      break
    }
    default:
      // String — show all non-date terms
      filtered = nonDates
      break
  }

  // Sort: fuzzy matches first, then by observation count descending
  filtered.sort((a, b) => {
    const aMatch = fuzzyMatch(variableName, a.codeTerm) ? 1 : 0
    const bMatch = fuzzyMatch(variableName, b.codeTerm) ? 1 : 0
    if (aMatch !== bMatch) return bMatch - aMatch
    return b.count - a.count
  })

  // Cap at 30 to keep the dropdown usable
  return filtered.slice(0, 30)
}

/** Escape a value for CSV output */
function csvEscape(value: string): string {
  if (value.includes(',') || value.includes('\n') || value.includes('"')) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function AdminPage() {
  const store = useAdminStore()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listWorkflows()
      .then((wfs) => store.setWorkflows(wfs))
      .catch((err) => setError(`Failed to load workflows: ${err.message}`))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="admin-page">
      {/* Header */}
      <header className="admin-header">
        <div className="admin-header-left">
          <div className="logo">
            <span className="logo-mark">L</span>
          </div>
          <span className="admin-title">Batch Execute</span>
        </div>
        <button className="admin-back" onClick={() => { window.location.hash = '' }}>
          ← Back to workspace
        </button>
      </header>

      {error && (
        <div className="admin-error">
          {error}
          <button onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      {/* Two-column body */}
      <div className="admin-body">
        <LeftPanel onError={setError} />
        <RightPanel onError={setError} />
      </div>
    </div>
  )
}

// ============================================================================
// LEFT PANEL — Upload + Workflow + Mapping
// ============================================================================

function LeftPanel({ onError }: { onError: (msg: string) => void }) {
  const store = useAdminStore()

  return (
    <div className="admin-left">
      <UploadCard />
      {store.patients.length > 0 && <WorkflowCard onError={onError} />}
    </div>
  )
}

// -- Upload Card --

function UploadCard() {
  const store = useAdminStore()
  const [dragOver, setDragOver] = useState(false)
  const [processing, setProcessing] = useState<string | null>(null)

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return
    const batchRows: ParsedRow[][] = []
    const batchFiles: UploadedFile[] = []
    let doneCount = 0
    const totalFiles = files.length

    setProcessing(`0 / ${totalFiles}`)

    for (const file of Array.from(files)) {
      const reader = new FileReader()
      reader.onload = (e) => {
        try {
          const text = e.target?.result as string
          const { rows, file: fileMeta } = parseCSVText(text, file.name)
          batchRows.push(rows)
          batchFiles.push(fileMeta)
        } catch {
          batchRows.push([])
          batchFiles.push({ name: file.name + ' (error)', rowCount: 0 })
        }
        doneCount++
        setProcessing(`${doneCount} / ${totalFiles}`)

        if (doneCount === totalFiles) {
          const current = useAdminStore.getState()
          const allRows = [...current.parsedRows, ...batchRows.flat()]
          const allFiles = [...current.uploadedFiles, ...batchFiles]
          store.setParsedRows(allRows)
          store.setUploadedFiles(allFiles)
          store.setCodeTerms(buildCodeTermSummaries(allRows))
          store.setPatients(pivotToPatients(allRows))
          store.setStage('map')
          setProcessing(null)
        }
      }
      reader.onerror = () => {
        batchRows.push([])
        batchFiles.push({ name: file.name + ' (error)', rowCount: 0 })
        doneCount++
        if (doneCount === totalFiles) setProcessing(null)
      }
      reader.readAsText(file)
    }
  }, [store])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  return (
    <div>
      <div className="admin-eyebrow">Data</div>

      <div
        className={`admin-dropzone${dragOver ? ' drag-over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'
          input.multiple = true
          input.accept = '.csv'
          input.onchange = () => handleFiles(input.files)
          input.click()
        }}
      >
        <svg className="admin-dropzone-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        {processing
          ? <><span className="admin-spinner" /> Processing {processing}</>
          : 'Drop CSV files here or click to browse'}
      </div>

      {store.uploadedFiles.length > 0 && (
        <>
          <div className="admin-file-list">
            {store.uploadedFiles.map((f) => (
              <div key={f.name} className="admin-file-item">
                <span className="admin-file-check">✓</span>
                <span>{f.name}</span>
                <span className="admin-file-rows">{f.rowCount.toLocaleString()} rows</span>
              </div>
            ))}
          </div>
          <div className="admin-stats">
            <span><span className="admin-stat-value">{store.patients.length.toLocaleString()}</span> patients</span>
            <span><span className="admin-stat-value">{store.codeTerms.length}</span> code terms</span>
            <button className="admin-clear-btn" onClick={() => store.clearUploads()}>Clear all</button>
          </div>
        </>
      )}
    </div>
  )
}

// -- Mapping Dropdown (filtered + ranked by variable type) --

function MappingDropdown({
  allTerms, variableName, variableType, value, onChange,
}: {
  allTerms: CodeTermSummary[]
  variableName: string
  variableType: string
  value: string | null
  onChange: (ct: string | null) => void
}) {
  const options = useMemo(
    () => relevantCodeTerms(allTerms, variableName, variableType),
    [allTerms, variableName, variableType]
  )
  return (
    <select
      className="admin-mapping-select"
      value={value || ''}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">— select —</option>
      {options.map((ct) => (
        <option key={ct.codeTerm} value={ct.codeTerm}>
          {ct.codeTerm} ({ct.count.toLocaleString()})
        </option>
      ))}
    </select>
  )
}

// -- Workflow + Mapping Card --

function WorkflowCard({ onError }: { onError: (msg: string) => void }) {
  const store = useAdminStore()
  const [loading, setLoading] = useState(false)

  const handleWorkflowSelect = useCallback(async (workflowId: string) => {
    setLoading(true)
    try {
      const wf = await getWorkflow(workflowId)
      const variables: WorkflowVariable[] = (wf as any).inputs || []
      store.selectWorkflow(workflowId, variables)

      // Build mappings with fuzzy auto-mapping
      const mappings: VariableMapping[] = variables
        .filter((v) => v.source !== 'subprocess')
        .map((v) => {
          // Try exact match first, then fuzzy substring match
          const exactMatch = store.codeTerms.find(
            (ct) => ct.codeTerm.toLowerCase() === v.name.toLowerCase()
          )
          if (exactMatch) return { variableName: v.name, codeTerm: exactMatch.codeTerm }

          const fuzzy = store.codeTerms.find((ct) => fuzzyMatch(v.name, ct.codeTerm))
          if (fuzzy) return { variableName: v.name, codeTerm: fuzzy.codeTerm }

          return { variableName: v.name, codeTerm: null }
        })
      store.setMappings(mappings)
    } catch (err: any) {
      onError(`Failed to load workflow: ${err.message}`)
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.codeTerms])

  // Gap analysis
  const gapAnalysis: GapAnalysisItem[] = useMemo(() => {
    return store.selectedWorkflowVariables
      .filter((v) => v.source !== 'subprocess')
      .map((variable) => {
        const nameLower = variable.name.toLowerCase()
        const mapping = store.mappings.find((m) => m.variableName === variable.name)

        if (nameLower === 'age' || nameLower === 'gender' || nameLower === 'sex') {
          return { variable, status: 'direct_column' as const, mappedCodeTerm: null }
        }
        if (mapping?.codeTerm) {
          return { variable, status: 'mapped' as const, mappedCodeTerm: mapping.codeTerm }
        }
        return { variable, status: 'unmapped' as const, mappedCodeTerm: null }
      })
  }, [store.selectedWorkflowVariables, store.mappings])

  const mappedCount = gapAnalysis.filter((g) => g.status !== 'unmapped').length
  const totalVars = gapAnalysis.length
  const coveragePct = totalVars > 0 ? Math.round(100 * mappedCount / totalVars) : 0

  return (
    <div>
      <div className="admin-eyebrow">Workflow & Mapping</div>

      <select
        className="admin-select"
        value={store.selectedWorkflowId || ''}
        onChange={(e) => e.target.value && handleWorkflowSelect(e.target.value)}
      >
        <option value="">Select a workflow...</option>
        {store.workflows.map((wf) => (
          <option key={wf.id} value={wf.id}>{wf.name}</option>
        ))}
      </select>

      {loading && <div style={{ marginTop: 8, fontSize: '0.8rem', color: 'var(--muted)' }}><span className="admin-spinner" /> Loading workflow...</div>}

      {store.selectedWorkflowId && gapAnalysis.length > 0 && (
        <>
          {/* Coverage bar */}
          <div className="admin-coverage">
            <div className="admin-coverage-bar">
              <div className="admin-coverage-fill" style={{ width: `${coveragePct}%` }} />
            </div>
            <span>{mappedCount}/{totalVars} mapped</span>
          </div>

          {/* Mapping rows */}
          <div className="admin-mapping-list">
            {gapAnalysis.map((item) => (
              <div key={item.variable.id} className="admin-mapping-row">
                <div className={`admin-mapping-status ${item.status === 'unmapped' ? 'unmapped' : item.status === 'direct_column' ? 'mapped' : 'mapped'}`}>
                  {item.status === 'unmapped' ? '?' : '✓'}
                </div>
                <div className="admin-mapping-info">
                  <span className="admin-mapping-name">{item.variable.name}</span>
                  <span className="admin-mapping-type">{item.variable.type}</span>
                </div>
                {item.status === 'direct_column' ? (
                  <span className="admin-mapping-source">CSV column</span>
                ) : (
                  <MappingDropdown
                    allTerms={store.codeTerms}
                    variableName={item.variable.name}
                    variableType={item.variable.type}
                    value={item.mappedCodeTerm}
                    onChange={(ct) => store.updateMapping(item.variable.name, ct)}
                  />
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ============================================================================
// RIGHT PANEL — Preview, Execute, Results
// ============================================================================

function RightPanel({ onError }: { onError: (msg: string) => void }) {
  const store = useAdminStore()

  // Build mapped patient data for execution
  const mappedPatients = useMemo(() => {
    if (!store.selectedWorkflowId || store.mappings.length === 0) return []
    return store.patients.map((patient) => {
      const inputValues: Record<string, unknown> = {}
      for (const mapping of store.mappings) {
        const variable = store.selectedWorkflowVariables.find((v) => v.name === mapping.variableName)
        if (!variable) continue
        const nameLower = variable.name.toLowerCase()
        if (nameLower === 'age') {
          inputValues[variable.name] = patient.age
        } else if (nameLower === 'gender' || nameLower === 'sex') {
          inputValues[variable.name] = patient.gender
        } else if (mapping.codeTerm && patient.codeTermValues[mapping.codeTerm] !== undefined) {
          inputValues[variable.name] = coerceValue(patient.codeTermValues[mapping.codeTerm], variable.type)
        }
      }
      return { emis_number: patient.emis_number, input_values: inputValues }
    })
  }, [store.patients, store.mappings, store.selectedWorkflowVariables, store.selectedWorkflowId])

  const requiredVarNames = store.mappings.map((m) => m.variableName)
  const completeCount = mappedPatients.filter((p) =>
    requiredVarNames.every((name) => name in p.input_values)
  ).length

  const handleExecute = useCallback(async () => {
    if (!store.selectedWorkflowId) return
    store.setExecuting(true)
    try {
      const response = await batchExecute(store.selectedWorkflowId, mappedPatients)
      store.setResults(response.results, response.summary)
    } catch (err: any) {
      onError(`Batch execution failed: ${err.message}`)
    } finally {
      store.setExecuting(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.selectedWorkflowId, mappedPatients])

  const handleDownload = useCallback(() => {
    const header = 'EMIS Number,Outcome,Path,Status,Error,Missing Variables\n'
    const rows = store.results.map((r) =>
      [
        r.emis_number,
        csvEscape(r.output ?? ''),
        csvEscape(r.path?.join(' > ') ?? ''),
        r.status,
        csvEscape(r.error ?? ''),
        csvEscape(r.missing_variables.join(', ')),
      ].join(',')
    )
    const csv = header + rows.join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `batch-results-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [store.results])

  // Outcome distribution for bar chart
  const outcomeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of store.results) {
      if (r.status === 'SUCCESS' && r.output) {
        counts.set(r.output, (counts.get(r.output) || 0) + 1)
      }
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [store.results])

  const maxOutcome = outcomeCounts.length > 0 ? outcomeCounts[0][1] : 0
  const successCount = store.summary?.success ?? 0

  // No data yet — empty state
  if (store.patients.length === 0) {
    return (
      <div className="admin-right">
        <div className="admin-empty">
          <div className="admin-empty-icon">&#8593;</div>
          <h3>Upload clinical data</h3>
          <p>Drop EMIS CSV exports on the left to get started. Files are parsed in your browser — no data is sent to the server.</p>
        </div>
      </div>
    )
  }

  // Data loaded but no workflow selected
  if (!store.selectedWorkflowId) {
    return (
      <div className="admin-right">
        <div className="admin-empty">
          <div className="admin-empty-icon">&#8592;</div>
          <h3>Select a workflow</h3>
          <p>Pick a workflow from the library to see which variables need mapping and preview the batch execution.</p>
        </div>
      </div>
    )
  }

  // Workflow selected — show preview and/or results
  return (
    <div className="admin-right">
      {/* Results summary (if executed) */}
      {store.summary && (
        <>
          <div className="admin-eyebrow">Results</div>
          <div className="admin-summary">
            <div className="admin-summary-chip">
              <div className="admin-summary-value">{store.summary.total.toLocaleString()}</div>
              <div className="admin-summary-label">Total</div>
            </div>
            <div className="admin-summary-chip">
              <div className="admin-summary-value success">{store.summary.success.toLocaleString()}</div>
              <div className="admin-summary-label">Success</div>
            </div>
            <div className="admin-summary-chip">
              <div className="admin-summary-value skipped">{store.summary.skipped.toLocaleString()}</div>
              <div className="admin-summary-label">Skipped</div>
            </div>
            <div className="admin-summary-chip">
              <div className="admin-summary-value error">{store.summary.error.toLocaleString()}</div>
              <div className="admin-summary-label">Error</div>
            </div>
          </div>
        </>
      )}

      {/* Outcome distribution bar chart */}
      {outcomeCounts.length > 0 && (
        <>
          <div className="admin-eyebrow">Outcome Distribution</div>
          <div className="admin-outcomes">
            {outcomeCounts.map(([outcome, count]) => (
              <div key={outcome} className="admin-outcome-row">
                <div className="admin-outcome-bar-track">
                  <div
                    className="admin-outcome-bar-fill"
                    style={{ width: `${maxOutcome > 0 ? (count / maxOutcome) * 100 : 0}%` }}
                  >
                    <span className="admin-outcome-bar-label">{outcome}</span>
                  </div>
                </div>
                <span className="admin-outcome-pct">
                  {count.toLocaleString()} ({successCount > 0 ? (100 * count / successCount).toFixed(1) : 0}%)
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Results table or preview */}
      <div className="admin-eyebrow">
        {store.results.length > 0 ? 'Patient Results' : 'Preview'}
      </div>

      <div className="admin-results-scroll">
        <table className="admin-results-table">
          <thead>
            <tr>
              <th>EMIS</th>
              {store.results.length > 0 ? (
                <>
                  <th>Outcome</th>
                  <th>Status</th>
                  <th>Missing</th>
                </>
              ) : (
                store.mappings.map((m) => <th key={m.variableName}>{m.variableName}</th>)
              )}
            </tr>
          </thead>
          <tbody>
            {store.results.length > 0 ? (
              // Results mode
              store.results.slice(0, 500).map((r, i) => (
                <tr key={i}>
                  <td>{r.emis_number}</td>
                  <td>{r.output ?? '—'}</td>
                  <td>
                    <span className={`admin-status-badge ${r.status.toLowerCase()}`}>
                      {r.status === 'SUCCESS' ? '✓' : r.status}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                    {r.missing_variables.length > 0 ? r.missing_variables.join(', ') : ''}
                  </td>
                </tr>
              ))
            ) : (
              // Preview mode — first 10 patients
              mappedPatients.slice(0, 10).map((row) => (
                <tr key={row.emis_number}>
                  <td>{row.emis_number}</td>
                  {store.mappings.map((m) => (
                    <td key={m.variableName}>
                      {row.input_values[m.variableName] !== undefined
                        ? String(row.input_values[m.variableName])
                        : <span style={{ color: 'var(--muted)' }}>—</span>}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {store.results.length === 0 && (
        <div className="admin-preview-label">
          Showing 10 of {store.patients.length.toLocaleString()} patients
          &nbsp;·&nbsp; {completeCount.toLocaleString()} with complete data
        </div>
      )}

      {store.results.length > 500 && (
        <div className="admin-preview-label">
          Showing 500 of {store.results.length.toLocaleString()} results — download CSV for full data
        </div>
      )}

      {/* Action bar */}
      <div className="admin-actions">
        {store.results.length > 0 ? (
          <button className="primary" onClick={handleDownload}>
            ⬇ Download Results CSV
          </button>
        ) : (
          <button
            className="primary"
            onClick={handleExecute}
            disabled={store.isExecuting}
          >
            {store.isExecuting
              ? <><span className="admin-spinner" /> Executing...</>
              : `Execute ${store.patients.length.toLocaleString()} patients`}
          </button>
        )}

        {store.results.length > 0 && (
          <button className="ghost" onClick={() => store.setResults([], { total: 0, success: 0, skipped: 0, error: 0 } as any)}>
            Run again
          </button>
        )}
      </div>
    </div>
  )
}
