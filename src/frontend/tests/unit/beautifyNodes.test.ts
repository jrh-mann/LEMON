import { describe, it, expect } from 'vitest'
import { beautifyNodes } from '../../src/utils/beautifyNodes'
import type { FlowNode, FlowEdge } from '../../src/types'

/** Helper: create a minimal FlowNode at origin. */
function makeNode(id: string, type: FlowNode['type'] = 'process', label?: string): FlowNode {
  return { id, type, label: label ?? id, x: 0, y: 0, color: 'teal' }
}

/** Helper: create a FlowEdge. */
function makeEdge(from: string, to: string, label = ''): FlowEdge {
  return { id: `${from}->${to}`, from, to, label }
}

describe('beautifyNodes', () => {
  it('returns empty arrays for empty input', () => {
    const result = beautifyNodes([], [])
    expect(result.nodes).toHaveLength(0)
    expect(result.edges).toHaveLength(0)
  })

  it('preserves node count and IDs for a simple chain', () => {
    const nodes = [makeNode('s', 'start'), makeNode('a'), makeNode('e', 'end')]
    const edges = [makeEdge('s', 'a'), makeEdge('a', 'e')]

    const result = beautifyNodes(nodes, edges)

    expect(result.nodes).toHaveLength(3)
    const ids = new Set(result.nodes.map(n => n.id))
    expect(ids).toEqual(new Set(['s', 'a', 'e']))
  })

  it('preserves edge count and references for a simple chain', () => {
    const nodes = [makeNode('s', 'start'), makeNode('a'), makeNode('e', 'end')]
    const edges = [makeEdge('s', 'a'), makeEdge('a', 'e')]

    const result = beautifyNodes(nodes, edges)

    expect(result.edges).toHaveLength(2)
    expect(result.edges.map(e => `${e.from}->${e.to}`)).toEqual(
      expect.arrayContaining(['s->a', 'a->e'])
    )
  })

  it('assigns positions to all nodes', () => {
    const nodes = [makeNode('s', 'start'), makeNode('a'), makeNode('e', 'end')]
    const edges = [makeEdge('s', 'a'), makeEdge('a', 'e')]

    const result = beautifyNodes(nodes, edges)

    for (const node of result.nodes) {
      expect(typeof node.x).toBe('number')
      expect(typeof node.y).toBe('number')
      expect(Number.isFinite(node.x)).toBe(true)
      expect(Number.isFinite(node.y)).toBe(true)
    }
  })

  it('does NOT duplicate nodes for a DAG with convergent connections', () => {
    // Diamond DAG: S -> A, S -> B, A -> C, B -> C (C has two parents)
    const nodes = [
      makeNode('s', 'start'),
      makeNode('a'),
      makeNode('b'),
      makeNode('c', 'end'),
    ]
    const edges = [
      makeEdge('s', 'a'),
      makeEdge('s', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'c'),
    ]

    const result = beautifyNodes(nodes, edges)

    // Must have exactly 4 nodes — no _dup copies
    expect(result.nodes).toHaveLength(4)
    const ids = result.nodes.map(n => n.id)
    expect(ids).not.toEqual(expect.arrayContaining([expect.stringContaining('_dup')]))
    expect(new Set(ids)).toEqual(new Set(['s', 'a', 'b', 'c']))

    // Must have exactly 4 edges — same as input
    expect(result.edges).toHaveLength(4)
  })

  it('handles a complex DAG with multiple convergence points', () => {
    // S -> D1 (decision)
    // D1 -true-> A, D1 -false-> B
    // A -> M (mandatory), B -> M (both branches converge)
    // M -> E (end)
    const nodes = [
      makeNode('s', 'start'),
      makeNode('d1', 'decision'),
      makeNode('a'),
      makeNode('b'),
      makeNode('m'),
      makeNode('e', 'end'),
    ]
    const edges = [
      makeEdge('s', 'd1'),
      makeEdge('d1', 'a', 'true'),
      makeEdge('d1', 'b', 'false'),
      makeEdge('a', 'm'),
      makeEdge('b', 'm'),
      makeEdge('m', 'e'),
    ]

    const result = beautifyNodes(nodes, edges)

    expect(result.nodes).toHaveLength(6)
    expect(result.edges).toHaveLength(6)
    // No _dup node IDs
    for (const n of result.nodes) {
      expect(n.id).not.toContain('_dup')
    }
  })

  it('preserves all node properties except x and y', () => {
    const nodes = [
      { ...makeNode('s', 'start'), label: 'Start Here', color: 'green' as const },
      { ...makeNode('e', 'end'), label: 'Done', color: 'rose' as const },
    ]
    const edges = [makeEdge('s', 'e')]

    const result = beautifyNodes(nodes, edges)

    const startNode = result.nodes.find(n => n.id === 's')!
    expect(startNode.label).toBe('Start Here')
    expect(startNode.color).toBe('green')
    expect(startNode.type).toBe('start')

    const endNode = result.nodes.find(n => n.id === 'e')!
    expect(endNode.label).toBe('Done')
    expect(endNode.color).toBe('rose')
  })

  it('preserves edge labels', () => {
    const nodes = [
      makeNode('s', 'start'),
      makeNode('d', 'decision'),
      makeNode('a'),
      makeNode('b'),
    ]
    const edges = [
      makeEdge('s', 'd'),
      makeEdge('d', 'a', 'true'),
      makeEdge('d', 'b', 'false'),
    ]

    const result = beautifyNodes(nodes, edges)

    const trueEdge = result.edges.find(e => e.from === 'd' && e.to === 'a')
    const falseEdge = result.edges.find(e => e.from === 'd' && e.to === 'b')
    expect(trueEdge?.label).toBe('true')
    expect(falseEdge?.label).toBe('false')
  })

  it('handles orphan nodes (no connections)', () => {
    const nodes = [
      makeNode('s', 'start'),
      makeNode('a'),
      makeNode('orphan'),  // No edges to/from this
    ]
    const edges = [makeEdge('s', 'a')]

    const result = beautifyNodes(nodes, edges)

    // All 3 nodes present, none duplicated
    expect(result.nodes).toHaveLength(3)
    const orphan = result.nodes.find(n => n.id === 'orphan')!
    expect(orphan).toBeDefined()
    expect(Number.isFinite(orphan.x)).toBe(true)
  })

  it('layers convergent node below ALL its parents', () => {
    // S -> A -> C, S -> B -> C
    // C should be at layer 2 (below both A and B at layer 1)
    const nodes = [
      makeNode('s', 'start'),
      makeNode('a'),
      makeNode('b'),
      makeNode('c', 'end'),
    ]
    const edges = [
      makeEdge('s', 'a'),
      makeEdge('s', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'c'),
    ]

    const result = beautifyNodes(nodes, edges)

    const yOf = (id: string) => result.nodes.find(n => n.id === id)!.y
    // C must be below both A and B
    expect(yOf('c')).toBeGreaterThan(yOf('a'))
    expect(yOf('c')).toBeGreaterThan(yOf('b'))
    // A and B should be at the same layer
    expect(yOf('a')).toBe(yOf('b'))
  })

  it('is idempotent — running twice produces the same result', () => {
    const nodes = [
      makeNode('s', 'start'),
      makeNode('a'),
      makeNode('b'),
      makeNode('c', 'end'),
    ]
    const edges = [
      makeEdge('s', 'a'),
      makeEdge('s', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'c'),
    ]

    const first = beautifyNodes(nodes, edges)
    const second = beautifyNodes(first.nodes, first.edges)

    expect(second.nodes).toHaveLength(first.nodes.length)
    for (const node of second.nodes) {
      const firstNode = first.nodes.find(n => n.id === node.id)!
      expect(node.x).toBe(firstNode.x)
      expect(node.y).toBe(firstNode.y)
    }
  })
})
