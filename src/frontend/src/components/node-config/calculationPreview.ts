import type { CalculationConfig, Operand, WorkflowVariable } from '../../types'
import { getOperator } from '../../types'

/**
 * Format a calculation as a human-readable formula for preview.
 */
export function formatCalculationPreview(calc: CalculationConfig, inputs: WorkflowVariable[]): string {
  const op = getOperator(calc.operator)
  if (!op) return '(invalid operator)'

  const formatOperand = (operand: Operand): string => {
    if (operand.kind === 'literal') {
      return String(operand.value ?? '?')
    }
    const variable = inputs.find(v => v.id === operand.ref)
    return variable?.name ?? (operand.ref || '?')
  }

  const operandStrs = calc.operands.map(formatOperand)
  const outputName = calc.output.name || 'result'

  if (op.category === 'unary') {
    const arg = operandStrs[0] ?? '?'
    return `${outputName} = ${op.symbol.replace('x', arg)}`
  }

  if (op.category === 'binary') {
    const [a, b] = operandStrs
    const formula = op.symbol.replace('a', a ?? '?').replace('b', b ?? '?')
    return `${outputName} = ${formula}`
  }

  if (operandStrs.length === 0) {
    return `${outputName} = ${op.symbol}(?)`
  }

  if (['min', 'max', 'sum', 'average', 'hypot', 'variance', 'std_dev', 'range', 'geometric_mean', 'harmonic_mean'].includes(op.name)) {
    return `${outputName} = ${op.name}(${operandStrs.join(', ')})`
  }

  return `${outputName} = ${operandStrs.join(` ${op.symbol} `)}`
}
