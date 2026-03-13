import { useState, useCallback } from 'react'
import type { WorkflowVariable, InputType, VariableSource } from '../types'

/* ── Constants ───────────────────────────────────────────── */

/** All available variable types */
const INPUT_TYPES: { value: InputType; label: string }[] = [
  { value: 'string', label: 'String' },
  { value: 'number', label: 'Number' },
  { value: 'bool', label: 'Boolean' },
  { value: 'date', label: 'Date' },
  { value: 'enum', label: 'Enum' },
]

/** All available variable sources */
const VARIABLE_SOURCES: { value: VariableSource; label: string }[] = [
  { value: 'input', label: 'Input' },
  { value: 'subprocess', label: 'Subprocess' },
  { value: 'calculated', label: 'Calculated' },
  { value: 'constant', label: 'Constant' },
]

/**
 * Slugify a variable name into a safe identifier fragment.
 * e.g. "Patient Age" -> "patient_age"
 */
const slugify = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')

/**
 * Build a deterministic variable ID from name + type.
 * Format: var_{slug}_{type}
 */
const buildVariableId = (name: string, type: InputType): string => {
  const slug = slugify(name) || 'var'
  return `var_${slug}_${type}`
}

/* ── Props ───────────────────────────────────────────────── */

interface VariableModalProps {
  /** The variable to edit, or null when creating a new variable */
  variable: WorkflowVariable | null
  /** Called with the finished variable (new or updated) */
  onSave: (variable: WorkflowVariable) => void
  /** Called when the modal is dismissed without saving */
  onClose: () => void
}

/* ── Default factory ─────────────────────────────────────── */

/** Blank variable template used when creating a new variable */
const makeDefault = (): WorkflowVariable => ({
  id: '',
  name: '',
  type: 'string',
  source: 'input',
})

/* ── Component ───────────────────────────────────────────── */

/**
 * Modal for creating or editing a single workflow variable.
 * Shows all editable fields: name, type, source, description,
 * and type-specific fields (enum values, number range, constant value).
 */
export default function VariableModal(props: VariableModalProps) {
  const modalKey = props.variable?.id ?? 'new'
  return <VariableModalContent key={modalKey} {...props} />
}

function VariableModalContent({ variable, onSave, onClose }: VariableModalProps) {
  const isNew = variable === null
  const [draft, setDraft] = useState<WorkflowVariable>(variable ?? makeDefault())

  /** Merge partial updates into the draft */
  const update = useCallback((patch: Partial<WorkflowVariable>) => {
    setDraft(prev => ({ ...prev, ...patch }))
  }, [])

  /** Validate and save */
  const handleSave = useCallback(() => {
    const trimmedName = draft.name.trim()
    if (!trimmedName) return // name is required

    const finalVar: WorkflowVariable = {
      ...draft,
      name: trimmedName,
      id: buildVariableId(trimmedName, draft.type),
    }
    onSave(finalVar)
  }, [draft, onSave])

  /* ── Enum values management ────────────────────────────── */

  /** Raw comma-separated string for the enum editor */
  const enumText = (draft.enum_values ?? []).join(', ')

  const handleEnumChange = useCallback((raw: string) => {
    const values = raw
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
    update({ enum_values: values })
  }, [update])

  /* ── Render ────────────────────────────────────────────── */

  return (
    <div className="modal">
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-content variable-modal-content">
        <div className="modal-header">
          <h2>{isNew ? 'New Variable' : 'Edit Variable'}</h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {/* Name */}
          <div className="form-group">
            <label htmlFor="var-name">
              Name <span className="required">*</span>
            </label>
            <input
              id="var-name"
              type="text"
              value={draft.name}
              placeholder="e.g. Patient Age"
              onChange={e => update({ name: e.target.value })}
              autoFocus
            />
          </div>

          {/* Type */}
          <div className="form-group">
            <label htmlFor="var-type">Type</label>
            <select
              id="var-type"
              value={draft.type}
              onChange={e => update({ type: e.target.value as InputType })}
            >
              {INPUT_TYPES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* Source — read-only display. Source is a structural property
              determined by how the variable was created (user input, subprocess
              output, calculation result, or constant). It should not be changed
              after creation. */}
          <div className="form-group">
            <label>Source</label>
            <span className={`var-source-badge source-${draft.source}`}>
              {VARIABLE_SOURCES.find(s => s.value === draft.source)?.label ?? draft.source}
            </span>
          </div>

          {/* Description */}
          <div className="form-group">
            <label htmlFor="var-desc">Description</label>
            <textarea
              id="var-desc"
              value={draft.description ?? ''}
              placeholder="Optional description of this variable"
              onChange={e => update({ description: e.target.value || undefined })}
            />
          </div>

          {/* ── Type-specific fields ─────────────────────── */}

          {/* Number: range (min / max) */}
          {draft.type === 'number' && (
            <fieldset className="var-modal-fieldset">
              <legend>Number Range</legend>
              <div className="var-modal-range-row">
                <div className="form-group">
                  <label htmlFor="var-range-min">Min</label>
                  <input
                    id="var-range-min"
                    type="number"
                    step="any"
                    value={draft.range?.min ?? ''}
                    placeholder="No minimum"
                    onChange={e => {
                      const val = e.target.value === '' ? undefined : parseFloat(e.target.value)
                      update({
                        range: {
                          ...draft.range,
                          min: val !== undefined && !isNaN(val) ? val : undefined,
                          max: draft.range?.max,
                        },
                      })
                    }}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="var-range-max">Max</label>
                  <input
                    id="var-range-max"
                    type="number"
                    step="any"
                    value={draft.range?.max ?? ''}
                    placeholder="No maximum"
                    onChange={e => {
                      const val = e.target.value === '' ? undefined : parseFloat(e.target.value)
                      update({
                        range: {
                          min: draft.range?.min,
                          ...draft.range,
                          max: val !== undefined && !isNaN(val) ? val : undefined,
                        },
                      })
                    }}
                  />
                </div>
              </div>
            </fieldset>
          )}

          {/* Enum: allowed values */}
          {draft.type === 'enum' && (
            <fieldset className="var-modal-fieldset">
              <legend>Enum Values</legend>
              <div className="form-group">
                <label htmlFor="var-enum-values">Values (comma-separated)</label>
                <input
                  id="var-enum-values"
                  type="text"
                  value={enumText}
                  placeholder="e.g. low, medium, high"
                  onChange={e => handleEnumChange(e.target.value)}
                />
                {(draft.enum_values?.length ?? 0) > 0 && (
                  <small>{draft.enum_values!.length} value{draft.enum_values!.length !== 1 ? 's' : ''}</small>
                )}
              </div>
            </fieldset>
          )}

          {/* Constant: value */}
          {draft.source === 'constant' && (
            <fieldset className="var-modal-fieldset">
              <legend>Constant Value</legend>
              <div className="form-group">
                <label htmlFor="var-const-value">Value</label>
                <input
                  id="var-const-value"
                  type={draft.type === 'number' ? 'number' : 'text'}
                  value={draft.value !== undefined ? String(draft.value) : ''}
                  placeholder="Fixed value for this variable"
                  onChange={e => {
                    const raw = e.target.value
                    if (draft.type === 'number') {
                      const num = parseFloat(raw)
                      update({ value: isNaN(num) ? undefined : num })
                    } else if (draft.type === 'bool') {
                      update({ value: raw === 'true' })
                    } else {
                      update({ value: raw || undefined })
                    }
                  }}
                />
              </div>
            </fieldset>
          )}
        </div>

        {/* Footer actions */}
        <div className="var-modal-footer">
          <button className="ghost" onClick={onClose}>Cancel</button>
          <button
            className="run-btn"
            onClick={handleSave}
            disabled={!draft.name.trim()}
          >
            {isNew ? 'Add Variable' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
