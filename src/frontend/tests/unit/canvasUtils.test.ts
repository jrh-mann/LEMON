import { describe, it, expect } from 'vitest'
import { wrapText } from '../../src/utils/canvas/textWrap'
import { hasCollision, resolveCollision } from '../../src/utils/canvas/collision'
import { resolveDecisionEdgeLabel } from '../../src/utils/canvas/edgeLabels'
import type { FlowNode } from '../../src/types'

describe('wrapText', () => {
  it('returns single line for short text', () => {
    expect(wrapText('Hello', 18)).toEqual(['Hello'])
  })

  it('wraps on word boundaries', () => {
    const lines = wrapText('Hello beautiful world', 10)
    expect(lines).toEqual(['Hello', 'beautiful', 'world'])
  })

  it('caps at 3 lines with ellipsis', () => {
    const lines = wrapText('one two three four five six seven', 8)
    expect(lines).toHaveLength(3)
    expect(lines[2]).toContain('\u2026')
  })

  it('handles single-word text longer than limit', () => {
    const lines = wrapText('Supercalifragilistic', 10)
    expect(lines).toHaveLength(1)
    expect(lines[0]).toBe('Supercalifragilistic')
  })
})

describe('hasCollision', () => {
  const makeNode = (id: string, x: number, y: number): FlowNode => ({
    id, x, y, type: 'process', label: 'Test', color: '#000',
  })

  it('returns false when no other nodes', () => {
    const nodes = [makeNode('n1', 100, 100)]
    expect(hasCollision(nodes, 'n1', 200, 200, 'process')).toBe(false)
  })

  it('returns true when overlapping another node', () => {
    const nodes = [
      makeNode('n1', 100, 100),
      makeNode('n2', 110, 110),
    ]
    // Moving n1 directly onto n2
    expect(hasCollision(nodes, 'n1', 110, 110, 'process')).toBe(true)
  })

  it('returns false when far from other nodes', () => {
    const nodes = [
      makeNode('n1', 100, 100),
      makeNode('n2', 500, 500),
    ]
    expect(hasCollision(nodes, 'n1', 200, 200, 'process')).toBe(false)
  })
})

describe('resolveCollision', () => {
  const makeNode = (id: string, x: number, y: number): FlowNode => ({
    id, x, y, type: 'process', label: 'Test', color: '#000',
  })

  it('returns target position when no collision', () => {
    const nodes = [makeNode('n1', 100, 100)]
    const result = resolveCollision(nodes, 'n1', 500, 500)
    expect(result).toEqual({ x: 500, y: 500 })
  })

  it('returns adjusted position when collision exists', () => {
    const nodes = [
      makeNode('n1', 100, 100),
      makeNode('n2', 200, 100),
    ]
    // Try to move n1 onto n2
    const result = resolveCollision(nodes, 'n1', 200, 100)
    // Should not be at 200,100 (that's where n2 is)
    expect(result.x).not.toBe(200)
  })
})

describe('resolveDecisionEdgeLabel', () => {
  it('returns null when node has no condition', () => {
    const node: FlowNode = { id: 'n1', x: 0, y: 0, type: 'decision', label: 'Test', color: '#000' }
    expect(resolveDecisionEdgeLabel(node, 'true', [])).toBeNull()
  })

  it('resolves simple numeric condition', () => {
    const node: FlowNode = {
      id: 'n1', x: 0, y: 0, type: 'decision', label: 'Test', color: '#000',
      condition: { input_id: 'var_age', comparator: 'gt', value: 18 },
    }
    const variables = [{ id: 'var_age', name: 'age', type: 'number' as const }]
    const trueLabel = resolveDecisionEdgeLabel(node, 'true', variables)
    const falseLabel = resolveDecisionEdgeLabel(node, 'false', variables)
    expect(trueLabel).toBe('age > 18')
    expect(falseLabel).toBe('age ≤ 18')
  })

  it('resolves "yes"/"no" as aliases for "true"/"false"', () => {
    const node: FlowNode = {
      id: 'n1', x: 0, y: 0, type: 'decision', label: 'Test', color: '#000',
      condition: { input_id: 'var_x', comparator: 'eq', value: 5 },
    }
    const variables = [{ id: 'var_x', name: 'x', type: 'number' as const }]
    expect(resolveDecisionEdgeLabel(node, 'Yes', variables)).toBe('x = 5')
    expect(resolveDecisionEdgeLabel(node, 'No', variables)).toBe('x ≠ 5')
  })

  it('returns null for non-boolean edge labels', () => {
    const node: FlowNode = {
      id: 'n1', x: 0, y: 0, type: 'decision', label: 'Test', color: '#000',
      condition: { input_id: 'var_x', comparator: 'eq', value: 5 },
    }
    expect(resolveDecisionEdgeLabel(node, 'maybe', [])).toBeNull()
  })

  it('resolves boolean condition', () => {
    const node: FlowNode = {
      id: 'n1', x: 0, y: 0, type: 'decision', label: 'Test', color: '#000',
      condition: { input_id: 'var_flag', comparator: 'is_true', value: null },
    }
    expect(resolveDecisionEdgeLabel(node, 'true', [])).toBe('True')
    expect(resolveDecisionEdgeLabel(node, 'false', [])).toBe('False')
  })

  it('resolves compound condition true branch with joiner', () => {
    const node: FlowNode = {
      id: 'n1', x: 0, y: 0, type: 'decision', label: 'Test', color: '#000',
      condition: {
        operator: 'and',
        conditions: [
          { input_id: 'var_a', comparator: 'gt', value: 10 },
          { input_id: 'var_b', comparator: 'lt', value: 100 },
        ],
      },
    }
    const vars = [
      { id: 'var_a', name: 'a', type: 'number' as const },
      { id: 'var_b', name: 'b', type: 'number' as const },
    ]
    expect(resolveDecisionEdgeLabel(node, 'true', vars)).toBe('a > 10 & b < 100')
    expect(resolveDecisionEdgeLabel(node, 'false', vars)).toBe('Else')
  })
})
