// Admin page for batch workflow execution against clinical CSV data.
//
// Flow: Upload CSVs → inspect data → pick workflow → map Code Terms
//       to variables → preview → execute → download results CSV.
//
// Raw clinical data is parsed client-side only. The server receives
// only structured {emis_number, input_values} dicts for execution.

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
  BatchResultRow,
} from '../types/admin'
import type { WorkflowVariable } from '../types'

// Auto-detect header row by looking for "EMIS Number" in first column

// ============================================================================
// CSV PARSING HELPERS
// ============================================================================

/** Parse a date string like "24-Mar-17" or "08-Oct-15" into a Date */
function parseEMISDate(dateStr: string): Date {
  if (!dateStr) return new Date(0)
  // Try native parsing first (handles ISO and many formats)
  const d = new Date(dateStr)
  if (!isNaN(d.getTime())) return d
  // Fallback: DD-Mon-YY format
  const parts = dateStr.split('-')
  if (parts.length === 3) {
    const [day, mon, year] = parts
    // Two-digit year: 00-49 → 2000s, 50-99 → 1900s
    const fullYear = parseInt(year) < 50 ? `20${year}` : `19${year}`
    const rebuilt = `${day} ${mon} ${fullYear}`
    const d2 = new Date(rebuilt)
    if (!isNaN(d2.getTime())) return d2
  }
  return new Date(0)
}

/** Parse CSV text, auto-detecting header row by looking for "EMIS Number" */
function parseCSVText(text: string, fileName: string): { rows: ParsedRow[]; file: UploadedFile } {
  const result = Papa.parse<string[]>(text, { header: false, skipEmptyLines: 'greedy' })

  // Find the header row (contains "EMIS Number" or "EMIS")
  let headerIndex = -1
  for (let i = 0; i < Math.min(result.data.length, 20); i++) {
    const firstCol = result.data[i][0]?.toString().toLowerCase().trim()
    if (firstCol === 'emis number' || firstCol === 'emis') {
      headerIndex = i
      break
    }
  }

  if (headerIndex === -1) {
    console.warn(`[parseCSVText] Could not find header row in ${fileName}, trying row 9`)
    headerIndex = 9 // fallback
  }

  // Data starts after header row
  const dataRows = result.data.slice(headerIndex + 1)
  console.log(`[parseCSVText] ${fileName}: header at row ${headerIndex}, ${dataRows.length} data rows`)

  const rows: ParsedRow[] = []
  for (const cols of dataRows) {
    // Skip rows without EMIS number or with too few columns
    const emisNum = cols[0]?.toString().trim()
    if (!emisNum || cols.length < 3) continue

    // Skip if first column looks like metadata (contains letters other than just the number)
    if (!/^\d+$/.test(emisNum)) continue

    rows.push({
      emis_number: emisNum,
      gender: cols[1]?.toString().trim() ?? '',
      age: parseInt(cols[2]?.toString().trim() ?? '0', 10) || 0,
      code_term: cols[3]?.toString().trim() ?? '',
      date: cols[4]?.toString().trim() ?? '',
      value: cols[5]?.toString().trim() ?? '',
      unit: cols[6]?.toString().trim() ?? '',
      secondary_value: cols[7]?.toString().trim() ?? '',
      secondary_unit: cols[8]?.toString().trim() ?? '',
    })
  }

  console.log(`[parseCSVText] ${fileName}: parsed ${rows.length} valid patient rows`)
  return {
    rows,
    file: { name: fileName, rowCount: rows.length },
  }
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

/** Pivot long-format rows into one record per patient (latest values) */
function pivotToPatients(rows: ParsedRow[]): PatientRecord[] {
  // Group by EMIS number
  const patientMap = new Map<string, {
    age: number
    gender: string
    codeTermLatest: Map<string, { date: Date; value: string }>
  }>()

  for (const row of rows) {
    if (!row.emis_number) continue
    let patient = patientMap.get(row.emis_number)
    if (!patient) {
      patient = { age: row.age, gender: row.gender, codeTermLatest: new Map() }
      patientMap.set(row.emis_number, patient)
    }
    // Keep latest value per Code Term (by date)
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

/** Coerce a string value to the appropriate JS type for a workflow variable */
function coerceValue(value: string, varType: string): unknown {
  switch (varType) {
    case 'int':
      return parseInt(value, 10)
    case 'float':
      return parseFloat(value)
    case 'bool':
      return ['true', 'yes', '1', 'y'].includes(value.toLowerCase())
    default:
      return value
  }
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function AdminPage() {
  const store = useAdminStore()
  const [error, setError] = useState<string | null>(null)

  // Load workflow list on mount
  useEffect(() => {
    listWorkflows()
      .then((wfs) => store.setWorkflows(wfs))
      .catch((err) => setError(`Failed to load workflows: ${err.message}`))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      overflowY: 'auto',
      background: 'var(--bg, #1a1a1a)',
      zIndex: 10,
    }}>
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '24px 16px', paddingBottom: 100 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24, gap: 16 }}>
        <button
          onClick={() => { window.location.hash = '' }}
          style={linkBtnStyle}
        >
          ← Back to Workspace
        </button>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>LEMON Admin — Batch Execute</h1>
      </div>

      {error && (
        <div style={errorBannerStyle}>
          {error}
          <button onClick={() => setError(null)} style={linkBtnStyle}>dismiss</button>
        </div>
      )}

      <UploadSection />
      {store.parsedRows.length > 0 && <MapSection onError={setError} />}
      {store.mappings.length > 0 && store.selectedWorkflowId && <PreviewSection onError={setError} />}
      {store.results.length > 0 && <ResultsSection />}
    </div>
    </div>
  )
}

// ============================================================================
// SECTION 1: UPLOAD
// ============================================================================

function UploadSection() {
  const store = useAdminStore()
  const [dragOver, setDragOver] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<{ total: number; done: number } | null>(null)

  const handleFiles = useCallback((files: FileList | null) => {
    console.log('[AdminPage] handleFiles called with', files?.length, 'files')
    if (!files || files.length === 0) return

    // Use getState() to always get fresh state, avoiding stale closure issues
    const getLatestState = () => useAdminStore.getState()

    // Track parsed results for this batch
    const batchRows: ParsedRow[][] = []
    const batchFiles: UploadedFile[] = []
    const totalFiles = files.length
    let doneCount = 0

    setUploadProgress({ total: totalFiles, done: 0 })

    for (const file of Array.from(files)) {
      console.log('[AdminPage] Starting to read file:', file.name)
      const reader = new FileReader()
      reader.onload = (e) => {
        try {
          const text = e.target?.result as string
          console.log('[AdminPage] File loaded:', file.name, 'size:', (text?.length / 1024 / 1024).toFixed(2), 'MB')
          const { rows, file: fileMeta } = parseCSVText(text, file.name)
          console.log('[AdminPage] Parsed', rows.length, 'rows from', file.name)
          batchRows.push(rows)
          batchFiles.push(fileMeta)
        } catch (err) {
          console.error('[AdminPage] Parse error for', file.name, err)
          // Still count as done but with empty data
          batchRows.push([])
          batchFiles.push({ name: file.name + ' (ERROR)', rowCount: 0 })
        }

        doneCount++
        setUploadProgress({ total: totalFiles, done: doneCount })

        if (doneCount === totalFiles) {
          // All files in this batch parsed — merge with current store state
          try {
            const currentState = getLatestState()
            const allRows = [...currentState.parsedRows, ...batchRows.flat()]
            const allFiles = [...currentState.uploadedFiles, ...batchFiles]
            console.log('[AdminPage] All files parsed. Total rows:', allRows.length, 'Total files:', allFiles.length)

            const patients = pivotToPatients(allRows)
            const codeTerms = buildCodeTermSummaries(allRows)
            console.log('[AdminPage] Pivoted to', patients.length, 'patients,', codeTerms.length, 'code terms')

            store.setParsedRows(allRows)
            store.setUploadedFiles(allFiles)
            store.setCodeTerms(codeTerms)
            store.setPatients(patients)
            store.setStage('map')
          } catch (err) {
            console.error('[AdminPage] Error finalizing upload:', err)
          }
          setUploadProgress(null)
        }
      }
      reader.onerror = (err) => {
        console.error('[AdminPage] FileReader error for', file.name, err)
        batchRows.push([])
        batchFiles.push({ name: file.name + ' (ERROR)', rowCount: 0 })
        doneCount++
        setUploadProgress({ total: totalFiles, done: doneCount })

        if (doneCount === totalFiles) {
          setUploadProgress(null)
        }
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
    <section style={sectionStyle}>
      <h2 style={sectionHeadingStyle}>1. Upload Data</h2>

      {/* Drop zone */}
      <div
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
        style={{
          ...dropZoneStyle,
          borderColor: dragOver ? '#3b82f6' : '#555',
          background: dragOver ? 'rgba(59,130,246,0.08)' : 'rgba(255,255,255,0.03)',
        }}
      >
        {uploadProgress
          ? `Processing ${uploadProgress.done}/${uploadProgress.total} files...`
          : 'Drop CSV files here or click to browse'}
      </div>

      {/* File list */}
      {store.uploadedFiles.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {store.uploadedFiles.map((f) => (
            <div key={f.name} style={{ fontSize: 13, color: '#aaa', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>✓ {f.name} — {f.rowCount.toLocaleString()} rows</span>
            </div>
          ))}
          <div style={{ marginTop: 8, fontSize: 14, color: '#ccc', display: 'flex', alignItems: 'center', gap: 16 }}>
            <span>
              Patients: <strong>{store.patients.length.toLocaleString()}</strong>
              {' | '}
              Code Terms: <strong>{store.codeTerms.length}</strong>
            </span>
            <button
              onClick={() => store.clearUploads()}
              style={{ ...linkBtnStyle, color: '#f87171' }}
              title="Clear all uploaded files"
            >
              Clear All
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

// ============================================================================
// SECTION 2: SELECT WORKFLOW + MAP
// ============================================================================

function MapSection({ onError }: { onError: (msg: string) => void }) {
  const store = useAdminStore()
  const [loadingWorkflow, setLoadingWorkflow] = useState(false)

  // When user picks a workflow, load its full details and build gap analysis
  const handleWorkflowSelect = useCallback(async (workflowId: string) => {
    setLoadingWorkflow(true)
    try {
      const wf = await getWorkflow(workflowId)
      // The full workflow response has 'inputs' as the variable list
      const variables: WorkflowVariable[] = (wf as any).inputs || []
      store.selectWorkflow(workflowId, variables)

      // Build initial mappings — auto-map Age/Gender from direct columns
      const codeTermNames = new Set(store.codeTerms.map((ct) => ct.codeTerm))
      const mappings: VariableMapping[] = variables
        .filter((v) => v.source !== 'subprocess')
        .map((v) => {
          // Try exact-match auto-mapping: if a Code Term matches the variable name
          const autoMatch = store.codeTerms.find(
            (ct) => ct.codeTerm.toLowerCase() === v.name.toLowerCase()
          )
          return {
            variableName: v.name,
            codeTerm: autoMatch ? autoMatch.codeTerm : null,
          }
        })
      store.setMappings(mappings)
    } catch (err: any) {
      onError(`Failed to load workflow: ${err.message}`)
    } finally {
      setLoadingWorkflow(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.codeTerms])

  // Build gap analysis items for display
  const gapAnalysis: GapAnalysisItem[] = useMemo(() => {
    return store.selectedWorkflowVariables
      .filter((v) => v.source !== 'subprocess')
      .map((variable) => {
        const nameLower = variable.name.toLowerCase()
        const mapping = store.mappings.find((m) => m.variableName === variable.name)

        // Age and Gender come from direct CSV columns
        if (nameLower === 'age' || nameLower === 'gender' || nameLower === 'sex') {
          return { variable, status: 'direct_column' as const, mappedCodeTerm: null }
        }

        if (mapping?.codeTerm) {
          return { variable, status: 'mapped' as const, mappedCodeTerm: mapping.codeTerm }
        }

        // Check if any Code Term could be mapped
        const hasCandidate = store.codeTerms.length > 0
        return {
          variable,
          status: hasCandidate ? 'unmapped' as const : 'not_in_data' as const,
          mappedCodeTerm: null,
        }
      })
  }, [store.selectedWorkflowVariables, store.mappings, store.codeTerms])

  const mappedCount = gapAnalysis.filter((g) => g.status === 'direct_column' || g.status === 'mapped').length
  const totalVars = gapAnalysis.length

  return (
    <section style={sectionStyle}>
      <h2 style={sectionHeadingStyle}>2. Select Workflow & Map Variables</h2>

      {/* Workflow picker */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 13, color: '#999', display: 'block', marginBottom: 4 }}>
          Workflow:
        </label>
        <select
          value={store.selectedWorkflowId || ''}
          onChange={(e) => e.target.value && handleWorkflowSelect(e.target.value)}
          style={selectStyle}
        >
          <option value="">Select a workflow...</option>
          {store.workflows.map((wf) => (
            <option key={wf.id} value={wf.id}>{wf.name}</option>
          ))}
        </select>
        {loadingWorkflow && <span style={{ marginLeft: 8, color: '#999', fontSize: 13 }}>Loading...</span>}
      </div>

      {/* Gap analysis */}
      {store.selectedWorkflowId && gapAnalysis.length > 0 && (
        <div>
          <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>
            Coverage: {mappedCount}/{totalVars} variables mappable ({totalVars > 0 ? Math.round(100 * mappedCount / totalVars) : 0}%)
          </div>

          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Variable</th>
                <th style={thStyle}>Type</th>
                <th style={thStyle}>Source / Mapping</th>
              </tr>
            </thead>
            <tbody>
              {gapAnalysis.map((item) => (
                <tr key={item.variable.id}>
                  <td style={tdStyle}>{statusIcon(item.status)}</td>
                  <td style={tdStyle}>{item.variable.name}</td>
                  <td style={{ ...tdStyle, color: '#999', fontSize: 12 }}>{item.variable.type}</td>
                  <td style={tdStyle}>
                    {item.status === 'direct_column' ? (
                      <span style={{ color: '#6ee7b7' }}>← CSV column</span>
                    ) : (
                      <select
                        value={item.mappedCodeTerm || ''}
                        onChange={(e) => store.updateMapping(
                          item.variable.name,
                          e.target.value || null
                        )}
                        style={{ ...selectStyle, minWidth: 200 }}
                      >
                        <option value="">— not mapped —</option>
                        {store.codeTerms.map((ct) => (
                          <option key={ct.codeTerm} value={ct.codeTerm}>
                            {ct.codeTerm} ({ct.count.toLocaleString()} rows)
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function statusIcon(status: GapAnalysisItem['status']): string {
  switch (status) {
    case 'direct_column': return '✅'
    case 'mapped': return '✅'
    case 'unmapped': return '⚠️'
    case 'not_in_data': return '❌'
  }
}

// ============================================================================
// SECTION 3: PREVIEW & EXECUTE
// ============================================================================

function PreviewSection({ onError }: { onError: (msg: string) => void }) {
  const store = useAdminStore()

  // Build mapped patient data for preview and execution
  const mappedPatients = useMemo(() => {
    return store.patients.map((patient) => {
      const inputValues: Record<string, unknown> = {}
      for (const mapping of store.mappings) {
        const variable = store.selectedWorkflowVariables.find(
          (v) => v.name === mapping.variableName
        )
        if (!variable) continue

        const nameLower = variable.name.toLowerCase()
        // Direct column mappings
        if (nameLower === 'age') {
          inputValues[variable.name] = patient.age
        } else if (nameLower === 'gender' || nameLower === 'sex') {
          inputValues[variable.name] = patient.gender
        } else if (mapping.codeTerm && patient.codeTermValues[mapping.codeTerm] !== undefined) {
          // Coerce the string value to the right type
          inputValues[variable.name] = coerceValue(
            patient.codeTermValues[mapping.codeTerm],
            variable.type
          )
        }
        // If no mapping or no value: leave it out (will be SKIPPED on execute)
      }
      return {
        emis_number: patient.emis_number,
        input_values: inputValues,
      }
    })
  }, [store.patients, store.mappings, store.selectedWorkflowVariables])

  // Count patients with complete data
  const requiredVarNames = store.mappings.map((m) => m.variableName)
  const completeCount = mappedPatients.filter((p) =>
    requiredVarNames.every((name) => name in p.input_values)
  ).length

  // Preview table: first 10 patients
  const previewRows = mappedPatients.slice(0, 10)
  // Column names for preview
  const previewColumns = ['EMIS', ...store.mappings.map((m) => m.variableName)]

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

  return (
    <section style={sectionStyle}>
      <h2 style={sectionHeadingStyle}>3. Preview & Execute</h2>

      <div style={{ fontSize: 13, color: '#999', marginBottom: 12 }}>
        Patients with complete data: <strong>{completeCount.toLocaleString()}</strong> / {store.patients.length.toLocaleString()}
      </div>

      {/* Preview table */}
      <div style={{ overflowX: 'auto', marginBottom: 16 }}>
        <table style={tableStyle}>
          <thead>
            <tr>
              {previewColumns.map((col) => (
                <th key={col} style={thStyle}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {previewRows.map((row) => (
              <tr key={row.emis_number}>
                <td style={tdStyle}>{row.emis_number}</td>
                {store.mappings.map((m) => (
                  <td key={m.variableName} style={tdStyle}>
                    {row.input_values[m.variableName] !== undefined
                      ? String(row.input_values[m.variableName])
                      : <span style={{ color: '#666' }}>—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
          Showing {previewRows.length} of {store.patients.length.toLocaleString()} patients
        </div>
      </div>

      <button
        onClick={handleExecute}
        disabled={store.isExecuting}
        style={{
          ...primaryBtnStyle,
          opacity: store.isExecuting ? 0.6 : 1,
          cursor: store.isExecuting ? 'wait' : 'pointer',
        }}
      >
        {store.isExecuting
          ? 'Executing...'
          : `▶ Execute ${store.patients.length.toLocaleString()} patients`}
      </button>
    </section>
  )
}

// ============================================================================
// SECTION 4: RESULTS
// ============================================================================

function ResultsSection() {
  const { results, summary } = useAdminStore()

  // Outcome distribution
  const outcomeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of results) {
      if (r.status === 'SUCCESS' && r.output) {
        counts.set(r.output, (counts.get(r.output) || 0) + 1)
      }
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
  }, [results])

  const successCount = summary?.success ?? 0

  // Build CSV for download
  const handleDownload = useCallback(() => {
    const header = 'EMIS Number,Outcome,Path,Status,Error,Missing Variables\n'
    const rows = results.map((r) =>
      [
        r.emis_number,
        csvEscape(r.output ?? ''),
        csvEscape(r.path?.join(' → ') ?? ''),
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
  }, [results])

  return (
    <section style={sectionStyle}>
      <h2 style={sectionHeadingStyle}>4. Results</h2>

      {/* Summary */}
      {summary && (
        <div style={{ display: 'flex', gap: 24, marginBottom: 16, flexWrap: 'wrap' }}>
          <SummaryChip label="Total" value={summary.total} color="#ccc" />
          <SummaryChip label="Success" value={summary.success} color="#6ee7b7" />
          <SummaryChip label="Skipped" value={summary.skipped} color="#fbbf24" />
          <SummaryChip label="Error" value={summary.error} color="#f87171" />
        </div>
      )}

      {/* Outcome distribution */}
      {outcomeCounts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 14, color: '#999', margin: '0 0 8px' }}>Outcome Distribution:</h3>
          {outcomeCounts.map(([outcome, count]) => (
            <div key={outcome} style={{ fontSize: 13, color: '#ccc', marginBottom: 2 }}>
              {outcome} — {count.toLocaleString()} ({successCount > 0 ? (100 * count / successCount).toFixed(1) : 0}%)
            </div>
          ))}
        </div>
      )}

      {/* Results table */}
      <div style={{ overflowX: 'auto', marginBottom: 16, maxHeight: 400, overflowY: 'auto' }}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>EMIS</th>
              <th style={thStyle}>Outcome</th>
              <th style={thStyle}>Path</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Missing</th>
            </tr>
          </thead>
          <tbody>
            {results.slice(0, 200).map((r, i) => (
              <tr key={i}>
                <td style={tdStyle}>{r.emis_number}</td>
                <td style={tdStyle}>{r.output ?? '—'}</td>
                <td style={{ ...tdStyle, fontSize: 11, color: '#888' }}>
                  {r.path?.join(' → ') ?? '—'}
                </td>
                <td style={tdStyle}>
                  <span style={{ color: statusColor(r.status) }}>
                    {r.status === 'SUCCESS' ? '✓' : r.status}
                  </span>
                </td>
                <td style={{ ...tdStyle, fontSize: 12, color: '#999' }}>
                  {r.missing_variables.length > 0 ? r.missing_variables.join(', ') : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {results.length > 200 && (
          <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
            Showing 200 of {results.length.toLocaleString()} results. Download CSV for full data.
          </div>
        )}
      </div>

      <button onClick={handleDownload} style={primaryBtnStyle}>
        ⬇ Download Results CSV
      </button>
    </section>
  )
}

// ============================================================================
// SMALL HELPERS
// ============================================================================

function SummaryChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value.toLocaleString()}</div>
      <div style={{ fontSize: 12, color: '#999' }}>{label}</div>
    </div>
  )
}

function statusColor(status: BatchResultRow['status']): string {
  switch (status) {
    case 'SUCCESS': return '#6ee7b7'
    case 'SKIPPED': return '#fbbf24'
    case 'ERROR': return '#f87171'
  }
}

/** Escape a value for CSV (wrap in quotes if it contains comma/newline/quote) */
function csvEscape(value: string): string {
  if (value.includes(',') || value.includes('\n') || value.includes('"')) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

// ============================================================================
// INLINE STYLES (keeping it self-contained — no separate CSS file)
// ============================================================================

const sectionStyle: React.CSSProperties = {
  border: '1px solid #333',
  borderRadius: 8,
  padding: 20,
  marginBottom: 20,
  background: 'rgba(255,255,255,0.02)',
}

const sectionHeadingStyle: React.CSSProperties = {
  margin: '0 0 16px',
  fontSize: 16,
  fontWeight: 600,
  color: '#e2e8f0',
}

const dropZoneStyle: React.CSSProperties = {
  border: '2px dashed #555',
  borderRadius: 8,
  padding: '32px 16px',
  textAlign: 'center',
  cursor: 'pointer',
  color: '#999',
  fontSize: 14,
  transition: 'border-color 0.15s, background 0.15s',
}

const selectStyle: React.CSSProperties = {
  background: '#1e1e1e',
  color: '#e2e8f0',
  border: '1px solid #444',
  borderRadius: 4,
  padding: '6px 8px',
  fontSize: 13,
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 10px',
  borderBottom: '1px solid #444',
  color: '#999',
  fontSize: 12,
  fontWeight: 600,
}

const tdStyle: React.CSSProperties = {
  padding: '6px 10px',
  borderBottom: '1px solid #2a2a2a',
  color: '#ccc',
}

const primaryBtnStyle: React.CSSProperties = {
  background: '#3b82f6',
  color: '#fff',
  border: 'none',
  borderRadius: 6,
  padding: '10px 20px',
  fontSize: 14,
  fontWeight: 600,
  cursor: 'pointer',
}

const linkBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#3b82f6',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}

const errorBannerStyle: React.CSSProperties = {
  background: '#7f1d1d',
  color: '#fca5a5',
  padding: '10px 16px',
  borderRadius: 6,
  marginBottom: 16,
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  fontSize: 13,
}
