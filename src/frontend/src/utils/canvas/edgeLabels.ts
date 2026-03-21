// Decision edge label resolver
// Converts "true"/"false" edge labels into human-readable descriptions
// based on the decision node's structured condition and workflow variables.

import type { FlowNode, SimpleCondition, WorkflowVariable } from '../../types'
import { isCompoundCondition } from '../../types'

/** Comparator symbols for concise edge labels */
const COMPARATOR_SYMBOL: Record<string, { true: string; false: string }> = {
  // Numeric
  eq:    { true: '=',  false: '≠' },
  neq:   { true: '≠',  false: '=' },
  lt:    { true: '<',  false: '≥' },
  lte:   { true: '≤',  false: '>' },
  gt:    { true: '>',  false: '≤' },
  gte:   { true: '≥',  false: '<' },
  // Boolean — just show True / False
  is_true:  { true: 'True',  false: 'False' },
  is_false: { true: 'False', false: 'True' },
  // String
  str_eq:          { true: '=',  false: '≠' },
  str_neq:         { true: '≠',  false: '=' },
  str_contains:    { true: 'contains',      false: '!contains' },
  str_starts_with: { true: 'starts with',   false: '!starts with' },
  str_ends_with:   { true: 'ends with',     false: '!ends with' },
  // Enum
  enum_eq:  { true: '=',  false: '≠' },
  enum_neq: { true: '≠',  false: '=' },
  // Date
  date_eq:      { true: '=',      false: '≠' },
  date_before:  { true: 'before', false: 'on/after' },
  date_after:   { true: 'after',  false: 'on/before' },
  date_between: { true: 'in',     false: 'outside' },
}

/** Build a label string for one simple condition on a given branch. */
function formatSimpleCondition(
  cond: SimpleCondition,
  branch: 'true' | 'false',
  variables: WorkflowVariable[],
): string {
  const variable = variables.find(v => v.id === cond.input_id)
  const varName = variable?.name ?? cond.input_id
  const symbols = COMPARATOR_SYMBOL[cond.comparator]
  if (!symbols) return branch === 'true' ? 'Yes' : 'No'
  const sym = symbols[branch]

  // Range comparators show both bounds
  if (cond.comparator === 'within_range' || cond.comparator === 'date_between') {
    const lo = cond.value ?? '?'
    const hi = cond.value2 ?? '?'
    return branch === 'true'
      ? `${varName} ${lo}–${hi}`
      : `${varName} outside ${lo}–${hi}`
  }

  // Boolean comparators — just show True / False
  if (cond.comparator === 'is_true' || cond.comparator === 'is_false') {
    return sym
  }

  // Enum comparators — show the matching value on the match branch,
  // and the other enum value(s) on the non-match branch.
  if (cond.comparator === 'enum_eq' || cond.comparator === 'enum_neq') {
    const val = cond.value ?? '?'
    const isMatch = (cond.comparator === 'enum_eq') === (branch === 'true')
    if (isMatch) return String(val)
    // Show the other enum value(s) instead of "Not {val}"
    const others = (variable?.enum_values ?? []).filter(v => v !== val)
    return others.length ? others.join(' | ') : `Not ${val}`
  }

  const val = cond.value ?? '?'
  return `${varName} ${sym} ${val}`
}

/** Resolve a decision edge label from its condition. Returns null to keep
 *  the original label when no condition is available. */
export function resolveDecisionEdgeLabel(
  node: FlowNode,
  edgeLabel: string,
  variables: WorkflowVariable[],
): string | null {
  if (!node.condition) return null
  const lower = edgeLabel.toLowerCase()
  // Map yes/no and true/false to the canonical branch names
  const branch: 'true' | 'false' | null =
    lower === 'true' || lower === 'yes' ? 'true' :
    lower === 'false' || lower === 'no' ? 'false' : null
  if (!branch) return null

  if (isCompoundCondition(node.condition)) {
    // Compound: true branch shows concise conditions joined with & / |,
    // false branch just shows "Else" since negating a compound is confusing.
    if (branch === 'false') return 'Else'
    const parts = node.condition.conditions.map(c =>
      formatSimpleCondition(c, branch, variables),
    )
    const joiner = node.condition.operator === 'and' ? ' & ' : ' | '
    return parts.join(joiner)
  }

  return formatSimpleCondition(node.condition, branch, variables)
}
