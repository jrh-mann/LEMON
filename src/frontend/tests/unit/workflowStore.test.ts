import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkflowStore } from '../../src/stores/workflowStore'

beforeEach(() => {
  useWorkflowStore.getState().reset()
})

describe('workflowStore', () => {
  it('reset clears workflow-specific UI state', () => {
    const store = useWorkflowStore.getState()

    store.selectEdge({ from: 'n1', to: 'n2' })
    store.highlightNode('n1')
    store.startSubflowExecution('parent', 'subflow', 'Subflow', [], [])

    store.reset()

    const next = useWorkflowStore.getState()
    expect(next.selectedEdge).toBeNull()
    expect(next.highlightedNodeId).toBeNull()
    expect(next.subflowStack).toEqual([])
  })
})
