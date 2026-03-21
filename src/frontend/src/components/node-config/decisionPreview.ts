import type { DecisionCondition, SimpleCondition, WorkflowVariable } from '../../types'
import { COMPARATOR_LABELS, isCompoundCondition } from '../../types'

function formatSimpleConditionPreview(condition: SimpleCondition, inputs: WorkflowVariable[]): string {
  if (!condition.input_id) return '(no input)'

  const input = inputs.find(inp => inp.id === condition.input_id)
  const inputName = input?.name ?? condition.input_id
  const compLabel = COMPARATOR_LABELS[condition.comparator] ?? condition.comparator

  if (condition.comparator === 'is_true' || condition.comparator === 'is_false') {
    return `${inputName} ${compLabel}`
  }
  if (condition.comparator === 'within_range' || condition.comparator === 'date_between') {
    return `${inputName} ${compLabel} [${condition.value ?? '?'}, ${condition.value2 ?? '?'}]`
  }

  const valueStr = typeof condition.value === 'string'
    ? `"${condition.value}"`
    : String(condition.value ?? '?')
  return `${inputName} ${compLabel} ${valueStr}`
}

export function formatConditionPreview(condition: DecisionCondition, inputs: WorkflowVariable[]): string {
  if (isCompoundCondition(condition)) {
    const joiner = ` ${condition.operator.toUpperCase()} `
    const parts = condition.conditions.map(sub => formatSimpleConditionPreview(sub, inputs))
    return parts.join(joiner) || '(empty compound)'
  }
  return formatSimpleConditionPreview(condition, inputs)
}
