import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { resolveWorkflowId, isForDifferentWorkflow, shouldIgnoreTask } from '../api/socket-handlers/utils'

beforeEach(() => {
  useChatStore.getState().reset()
  useWorkflowStore.getState().reset()
})

describe('resolveWorkflowId', () => {
  it('returns workflow_id from event data when present', () => {
    const id = resolveWorkflowId({ workflow_id: 'wf_abc' })
    expect(id).toBe('wf_abc')
  })

  it('falls back to chatStore activeWorkflowId', () => {
    useChatStore.getState().setActiveWorkflowId('wf_fallback')
    const id = resolveWorkflowId({})
    expect(id).toBe('wf_fallback')
  })

  it('returns null when no workflow_id and no active workflow', () => {
    const id = resolveWorkflowId({})
    expect(id).toBeNull()
  })

  it('prefers event workflow_id over activeWorkflowId', () => {
    useChatStore.getState().setActiveWorkflowId('wf_active')
    const id = resolveWorkflowId({ workflow_id: 'wf_event' })
    expect(id).toBe('wf_event')
  })
})

describe('isForDifferentWorkflow', () => {
  it('returns false when no event workflow_id', () => {
    expect(isForDifferentWorkflow(undefined)).toBe(false)
  })

  it('returns false when no current workflow set', () => {
    expect(isForDifferentWorkflow('wf_abc')).toBe(false)
  })

  it('returns false when IDs match', () => {
    useWorkflowStore.getState().setCurrentWorkflowId('wf_abc')
    expect(isForDifferentWorkflow('wf_abc')).toBe(false)
  })

  it('returns true when IDs differ', () => {
    useWorkflowStore.getState().setCurrentWorkflowId('wf_abc')
    expect(isForDifferentWorkflow('wf_xyz')).toBe(true)
  })
})

describe('shouldIgnoreTask', () => {
  it('returns false when no taskId', () => {
    expect(shouldIgnoreTask(undefined, 'wf_1')).toBe(false)
  })

  it('returns true when task is cancelled', () => {
    useChatStore.getState().markTaskCancelled('task_1')
    expect(shouldIgnoreTask('task_1', 'wf_1')).toBe(true)
  })

  it('returns false when task matches currentTaskId', () => {
    useChatStore.getState().setCurrentTaskId('wf_1', 'task_1')
    expect(shouldIgnoreTask('task_1', 'wf_1')).toBe(false)
  })

  it('returns true when task differs from currentTaskId', () => {
    useChatStore.getState().setCurrentTaskId('wf_1', 'task_current')
    expect(shouldIgnoreTask('task_stale', 'wf_1')).toBe(true)
  })

  it('returns false when no currentTaskId is set (first event)', () => {
    // No currentTaskId set — this is the first event, should not be ignored
    expect(shouldIgnoreTask('task_new', 'wf_1')).toBe(false)
  })
})
