/**
 * Workflow-related WebSocket event handlers.
 * Handles: workflow_update, analysis_updated, workflow_created,
 *          workflow_saved, pending_question, plan_updated,
 *          subworkflow_created, subworkflow_building,
 *          build_error, subworkflow_ready
 */
import { useChatStore } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import { transformFlowchartFromBackend, transformNodeFromBackend } from '../../utils/canvas'
import type { WorkflowAnalysis } from '../../types'
import type { HandlerMap } from './index'


type WorkflowStateUpdate = {
  workflow_id?: string
  workflow?: { nodes?: unknown[]; edges?: unknown[] }
  analysis?: { variables?: unknown[]; outputs?: unknown[]; output_type?: string }
  task_id?: string
}


function applyWorkflowStateUpdate(data: WorkflowStateUpdate): void {
  const workflowStore = useWorkflowStore.getState()
  const eventWorkflowId = data.workflow_id
  const currentWorkflowId = workflowStore.currentWorkflow?.id
  if (eventWorkflowId && currentWorkflowId && eventWorkflowId !== currentWorkflowId) {
    return
  }

  if (data.workflow) {
    const flowchart = transformFlowchartFromBackend(data.workflow)
    workflowStore.setFlowchartSilent(flowchart)
  }

  if (data.analysis) {
    const currentAnalysis = workflowStore.currentAnalysis ?? { variables: [], outputs: [] }
    const updatedAnalysis: WorkflowAnalysis = {
      ...currentAnalysis,
      variables: (data.analysis.variables ?? currentAnalysis.variables) as WorkflowAnalysis['variables'],
      outputs: (data.analysis.outputs ?? currentAnalysis.outputs) as WorkflowAnalysis['outputs'],
      ...(data.analysis.output_type ? { output_type: data.analysis.output_type } : {}),
    }
    workflowStore.setAnalysis(updatedAnalysis)
  }
}

/** Register all workflow-related event handlers into the handler map */
export function registerWorkflowHandlers(handlers: HandlerMap): void {
  // Workflow update events (from orchestrator manipulation tools)
  handlers['workflow_update'] = (data: { action: string; data: Record<string, unknown> }) => {
    // Guard against malformed payloads — backend bugs shouldn't crash the WS loop
    if (!data?.data) {
      console.error('[WS] workflow_update missing data payload:', data)
      return
    }

    console.log('[WS] workflow_update:', data.action, 'workflow_id:', data.data.workflow_id)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    // Filter by workflow_id: background subworkflow builders emit events
    // for their own workflow — ignore them unless the user is viewing that workflow
    const eventWorkflowId = data.data.workflow_id as string | undefined
    const currentWorkflowId = workflowStore.currentWorkflow?.id
    if (eventWorkflowId && currentWorkflowId && eventWorkflowId !== currentWorkflowId) {
      console.log('[WS] Ignoring workflow_update for different workflow:', eventWorkflowId)
      return
    }

    try {
      switch (data.action) {
        case 'add_node':
          // Single node added by orchestrator
          if (data.data.node) {
            const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
            workflowStore.addNode(node)
            // Switch to workflow tab to show the change
            uiStore.setCanvasTab('workflow')
            console.log('[WS] Added node:', node.id)
          }
          break

        case 'modify_node':
          // Node updated by orchestrator
          if (data.data.node) {
            const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
            const exists = workflowStore.flowchart.nodes.find(n => n.id === node.id)
            if (!exists) {
              console.error('[WS] Cannot modify non-existent node:', node.id)
              break
            }
            workflowStore.updateNode(node.id, node)
            console.log('[WS] Modified node:', node.id)
          }
          break

        case 'delete_node':
          // Node deleted by orchestrator
          if (data.data.node_id) {
            const nodeId = data.data.node_id as string
            const exists = workflowStore.flowchart.nodes.find(n => n.id === nodeId)
            if (!exists) {
              console.error('[WS] Cannot delete non-existent node:', nodeId)
              break
            }
            workflowStore.deleteNode(nodeId)
            console.log('[WS] Deleted node:', nodeId)
            // Note: deleteNode() automatically removes connected edges
          }
          break

        case 'add_connection':
          // Edge added by orchestrator
          if (data.data.edge) {
            const edge = data.data.edge as {
              from: string
              to: string
              label?: string
              id?: string
            }
            workflowStore.addEdge({
              from: edge.from,
              to: edge.to,
              label: edge.label || '',
              id: edge.id,
            })
            console.log('[WS] Added connection:', edge.from, '->', edge.to)
          }
          break

        case 'delete_connection':
          // Edge removed by orchestrator
          if (data.data.from_node_id && data.data.to_node_id) {
            const fromId = data.data.from_node_id as string
            const toId = data.data.to_node_id as string
            workflowStore.deleteEdge(fromId, toId)
            console.log('[WS] Deleted connection:', fromId, '->', toId)
          }
          break

        case 'batch_edit':
          // Multiple operations applied atomically — use setFlowchartSilent
          // to avoid polluting the undo stack with server-driven changes
          if (data.data.workflow) {
            const flowchart = transformFlowchartFromBackend(
              data.data.workflow as { nodes: unknown[]; edges: unknown[] }
            )
            workflowStore.setFlowchartSilent(flowchart)
            // Switch to workflow tab to show the changes
            uiStore.setCanvasTab('workflow')
            console.log('[WS] Applied batch edit:', data.data.operation_count, 'operations')
          }
          break

        case 'highlight_node':
          // Pulse a node to draw user's attention
          if (data.data.node_id) {
            workflowStore.highlightNode(data.data.node_id as string)
            uiStore.setCanvasTab('workflow')
            console.log('[WS] Highlighting node:', data.data.node_id)
          }
          break

        default:
          console.warn('[WS] Unknown workflow_update action:', data.action)
      }
    } catch (err) {
      console.error('[WS] workflow_update handler error:', data.action, err)
    }
  }

  // Analysis updates (from input management tools)
  // Only apply if task_id matches current task (prevents updates from inactive tabs)
  handlers['analysis_updated'] = (data: { variables: unknown[]; outputs: unknown[]; task_id?: string }) => {
    console.log('[WS] analysis_updated:', data)
    const chatStore = useChatStore.getState()
    const workflowStore = useWorkflowStore.getState()
    const taskId = data.task_id

    // Filter out updates from stale/different tasks to prevent tab cross-contamination
    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[WS] Ignoring cancelled analysis_updated:', taskId)
        return
      }
      // Check currentTaskId from the active workflow's conversation
      const activeWfId = chatStore.activeWorkflowId
      const conv = activeWfId ? chatStore.conversations[activeWfId] : undefined
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) {
        console.log('[WS] Ignoring stale analysis_updated:', taskId, 'current:', conv.currentTaskId)
        return
      }
    }

    // Update the analysis with new variables/outputs
    const currentAnalysis = workflowStore.currentAnalysis ?? {
      variables: [],
      outputs: [],
    }

    const updatedAnalysis: WorkflowAnalysis = {
      ...currentAnalysis,
      variables: data.variables as WorkflowAnalysis['variables'],
      outputs: data.outputs as WorkflowAnalysis['outputs'],
    }

    workflowStore.setAnalysis(updatedAnalysis)
    console.log('[WS] Updated analysis with', data.variables.length, 'variables and', data.outputs.length, 'outputs')
  }

  handlers['workflow_state_updated'] = (data: WorkflowStateUpdate) => {
    console.log('[WS] workflow_state_updated:', data)
    const chatStore = useChatStore.getState()
    const taskId = data.task_id
    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        return
      }
      const activeWfId = chatStore.activeWorkflowId
      const conv = activeWfId ? chatStore.conversations[activeWfId] : undefined
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) {
        return
      }
    }
    applyWorkflowStateUpdate(data)
  }

  // ===== Workflow Library Events =====
  // These events handle workflow creation and saving by the LLM

  // Workflow created - LLM called create_workflow, track the workflow_id for this tab.
  // Uses a single atomic state update to avoid race conditions from multiple getState() calls.
  handlers['workflow_created'] = (data: {
    workflow_id: string
    name: string
    output_type: string
    is_draft: boolean
  }) => {
    console.log('[WS] workflow_created:', data)
    const store = useWorkflowStore.getState()
    const currentId = store.currentWorkflow?.id

    // Sync workflow ID if backend generated a different one
    if (!currentId || currentId !== data.workflow_id) {
      store.setCurrentWorkflowId(data.workflow_id)
    }

    // Ensure the chatStore tracks this workflow so the Chat component renders
    // events (thinking, progress, response) that arrive with this workflow_id.
    const chatStore = useChatStore.getState()
    if (!chatStore.activeWorkflowId || chatStore.activeWorkflowId !== data.workflow_id) {
      chatStore.setActiveWorkflowId(data.workflow_id)
    }

    // Apply name and output_type in a single atomic update
    const wf = useWorkflowStore.getState().currentWorkflow
    if (wf) {
      useWorkflowStore.getState().setCurrentWorkflow({
        ...wf,
        ...(data.name ? { metadata: { ...wf.metadata, name: data.name } } : {}),
        ...(data.output_type ? { output_type: data.output_type } : {}),
      })
    }

    console.log('[WS] workflow_created complete - ID:', data.workflow_id, 'name:', data.name, 'output_type:', data.output_type)
  }

  // Workflow saved - LLM called save_workflow_to_library, update draft status
  handlers['workflow_saved'] = (data: {
    workflow_id: string
    name: string
    is_draft: boolean
    already_saved: boolean
  }) => {
    console.log('[WS] workflow_saved:', data)
    const workflowStore = useWorkflowStore.getState()

    // Update the workflow in the current tab to mark it as saved
    // This could update a UI indicator showing the workflow is now in the user's library
    if (!data.already_saved) {
      // Only update name if it wasn't already saved
      const currentWf = workflowStore.currentWorkflow
      if (currentWf && data.name) {
        workflowStore.setCurrentWorkflow({
          ...currentWf,
          metadata: { ...currentWf.metadata, name: data.name }
        })
      }
      console.log('[WS] Workflow saved to library:', data.workflow_id, 'name:', data.name)
    } else {
      console.log('[WS] Workflow was already saved:', data.workflow_id)
    }
  }

  // Inline question from ask_question tool — enqueue so multiple questions
  // are shown one at a time (answering one reveals the next).
  handlers['pending_question'] = (data: { question: string; options: { label: string; value: string }[] }) => {
    console.log('[WS] pending_question:', data)
    const chatStore = useChatStore.getState()
    chatStore.enqueuePendingQuestion(data)
  }

  // Plan updates (from update_plan tool — extraction progress checklist)
  handlers['plan_updated'] = (data: { items: Array<{ text: string; done: boolean }> }) => {
    console.log('[WS] plan_updated:', data)
    const workflowStore = useWorkflowStore.getState()
    workflowStore.setPlan(data.items)
  }

  // ===== Background Subworkflow Build Events =====
  // These events handle library auto-refresh for subworkflows being built
  // by background orchestrators. Chat streaming events (chat_stream, chat_thinking,
  // chat_response, build_user_message) are handled by chatHandlers.

  // New subworkflow created — trigger library refresh so it appears
  // with a "Building..." badge without manual page reload
  handlers['subworkflow_created'] = (data: { workflow_id: string; name: string; building: boolean }) => {
    console.log('[WS] subworkflow_created:', data.workflow_id, data.name)
    useWorkflowStore.getState().incrementLibraryRefresh()
  }

  // Existing subworkflow is being rebuilt by update_subworkflow tool
  handlers['subworkflow_building'] = (data: { workflow_id: string; name: string; building: boolean }) => {
    console.log('[WS] subworkflow_building:', data.workflow_id, data.name)
    useWorkflowStore.getState().incrementLibraryRefresh()
  }

  // Subworkflow build failed — refresh library to clear "Building..." badge
  handlers['build_error'] = (data: { workflow_id: string; error: string }) => {
    console.error('[WS] build_error:', data.workflow_id, data.error)
    useWorkflowStore.getState().incrementLibraryRefresh()
  }

  // Subworkflow build complete — refresh library badge.
  // Chat conversation state is managed by chatStore, no cleanup needed here.
  handlers['subworkflow_ready'] = (data: { workflow_id: string }) => {
    console.log('[WS] subworkflow_ready:', data.workflow_id)
    useWorkflowStore.getState().incrementLibraryRefresh()
  }
}
