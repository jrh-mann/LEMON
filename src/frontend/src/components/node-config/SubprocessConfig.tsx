/**
 * SubprocessConfig - Configuration panel for subprocess nodes.
 * Allows selecting a subworkflow, mapping parent inputs to subworkflow inputs,
 * and naming the output variable for use in subsequent nodes.
 */

import { useState } from 'react'
import type { FlowNode, WorkflowVariable, WorkflowSummary } from '../../types'

export function SubprocessConfig({
  node,
  workflows,
  analysisInputs,
  currentWorkflowId,
  onUpdate,
}: {
  node: FlowNode
  workflows: WorkflowSummary[]
  analysisInputs: WorkflowVariable[]
  currentWorkflowId?: string
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  // Local state for new mapping entry
  const [newMappingParent, setNewMappingParent] = useState('')
  const [newMappingSubflow, setNewMappingSubflow] = useState('')

  // Get the selected subworkflow's input names for the mapping dropdown
  const selectedWorkflow = workflows.find(w => w.id === node.subworkflow_id)
  const subflowInputNames = selectedWorkflow?.input_names ?? []

  // Current input mapping (parent input name -> subflow input name)
  const inputMapping = node.input_mapping ?? {}

  // Handle subworkflow selection change
  const handleWorkflowChange = (workflowId: string) => {
    onUpdate({
      subworkflow_id: workflowId || undefined,
      // Clear mappings when workflow changes since inputs may differ
      input_mapping: {},
    })
  }

  // Add a new input mapping entry
  const handleAddMapping = () => {
    if (!newMappingParent || !newMappingSubflow) return
    // Prevent duplicate mappings for the same parent input
    if (inputMapping[newMappingParent]) return

    onUpdate({
      input_mapping: {
        ...inputMapping,
        [newMappingParent]: newMappingSubflow,
      },
    })
    setNewMappingParent('')
    setNewMappingSubflow('')
  }

  // Remove a mapping entry by parent input name
  const handleRemoveMapping = (parentKey: string) => {
    const { [parentKey]: _, ...remaining } = inputMapping
    onUpdate({ input_mapping: remaining })
  }

  // Filter out parent inputs already used in mappings
  const availableParentInputs = analysisInputs.filter(
    input => !inputMapping[input.name]
  )

  return (
    <>
      <div className="form-divider" />
      <h5>Subprocess Configuration</h5>

      {/* Subworkflow selector */}
      <div className="form-group">
        <label>Target Workflow</label>
        <select
          value={node.subworkflow_id || ''}
          onChange={(e) => handleWorkflowChange(e.target.value)}
        >
          <option value="">Select a workflow...</option>
          {workflows
            .filter(w => w.id !== currentWorkflowId) // Prevent self-reference
            .map(w => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
        </select>
        <p className="muted small">The workflow to execute as a subprocess.</p>
      </div>

      {/* Show subflow details if selected */}
      {selectedWorkflow && (
        <div className="subprocess-info">
          <p className="muted small">
            <strong>Inputs:</strong> {subflowInputNames.length > 0 ? subflowInputNames.join(', ') : 'None'}
          </p>
          <p className="muted small">
            <strong>Outputs:</strong> {selectedWorkflow.output_values?.join(', ') || 'None'}
          </p>
        </div>
      )}

      {/* Input mapping section */}
      {node.subworkflow_id && (
        <>
          <div className="form-divider" />
          <h5>Input Mapping</h5>
          <p className="muted small">Map this workflow's inputs to the subprocess inputs.</p>

          {/* Existing mappings */}
          {Object.entries(inputMapping).length > 0 && (
            <div className="mapping-list">
              {Object.entries(inputMapping).map(([parentInput, subflowInput]) => (
                <div className="mapping-row" key={parentInput}>
                  <span className="mapping-parent">{parentInput}</span>
                  <span className="mapping-arrow">&rarr;</span>
                  <span className="mapping-subflow">{subflowInput}</span>
                  <button
                    className="mapping-remove ghost"
                    onClick={() => handleRemoveMapping(parentInput)}
                    title="Remove mapping"
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Add new mapping */}
          {availableParentInputs.length > 0 && subflowInputNames.length > 0 && (
            <div className="mapping-add">
              <select
                value={newMappingParent}
                onChange={(e) => setNewMappingParent(e.target.value)}
              >
                <option value="">Parent input...</option>
                {availableParentInputs.map(input => (
                  <option key={input.id} value={input.name}>
                    {input.name}
                  </option>
                ))}
              </select>
              <span className="mapping-arrow">&rarr;</span>
              <select
                value={newMappingSubflow}
                onChange={(e) => setNewMappingSubflow(e.target.value)}
              >
                <option value="">Subflow input...</option>
                {subflowInputNames.map(name => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                className="ghost"
                onClick={handleAddMapping}
                disabled={!newMappingParent || !newMappingSubflow}
              >
                Add
              </button>
            </div>
          )}

          {availableParentInputs.length === 0 && Object.keys(inputMapping).length > 0 && (
            <p className="muted small">All parent inputs are mapped.</p>
          )}

          {analysisInputs.length === 0 && (
            <p className="muted small warning">
              No variables defined for this workflow. Add variables in the Variables panel.
            </p>
          )}
        </>
      )}

      {/* Output variable name */}
      {node.subworkflow_id && (
        <>
          <div className="form-divider" />
          <h5>Output Variable</h5>
          <div className="form-group">
            <label>Variable Name</label>
            <input
              type="text"
              value={node.output_variable || ''}
              onChange={(e) => onUpdate({ output_variable: e.target.value })}
              placeholder="e.g. subprocess_result"
            />
            <p className="muted small">
              Name for the subprocess output. Use this variable in subsequent decision nodes.
            </p>
          </div>
        </>
      )}
    </>
  )
}
