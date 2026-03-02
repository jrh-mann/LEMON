/**
 * Workflow-related socket event handlers.
 * Handles: workflow_modified, workflow_update, analysis_updated,
 *          workflow_created, workflow_saved, annotations_update
 */
import type { Socket } from 'socket.io-client'
import { useChatStore } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import { transformFlowchartFromBackend, transformNodeFromBackend } from '../../utils/canvas'
import { syncWorkflow } from '../socketActions'
import type { WorkflowAnalysis } from '../../types'

/** Register all workflow-related socket event handlers */
export function registerWorkflowHandlers(socket: Socket): void {
  // Workflow modification events (from orchestrator editing tools)
  socket.on('workflow_modified', (data: { action: string; data: Record<string, unknown> }) => {
    console.log('[Socket] workflow_modified:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    switch (data.action) {
      case 'create_workflow':
        // Full workflow created - load it
        {
          const payload = data.data as {
            flowchart?: { nodes?: unknown[]; edges?: unknown[] }
            analysis?: WorkflowAnalysis
            nodes?: unknown[]
            edges?: unknown[]
          }
          if (payload.analysis) {
            workflowStore.setAnalysis(payload.analysis)
          }
          const flowchartData = payload.flowchart?.nodes ? payload.flowchart : payload
          if (flowchartData.nodes && flowchartData.edges) {
            // Transform backend data (top-left coords, BlockType) to frontend format
            const flowchart = transformFlowchartFromBackend(flowchartData as { nodes: unknown[]; edges: unknown[] })
            workflowStore.setFlowchart(flowchart)
            // Switch canvas to workflow tab to show the new workflow
            uiStore.setCanvasTab('workflow')
            // Sync workflow to backend session (establish backend as source of truth)
            syncWorkflow('upload')
          }
        }
        break

      case 'add_block':
        // Single block added - transform from backend format
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          workflowStore.addNode(node)
        }
        break

      case 'update_block':
        // Block updated - transform from backend format
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          workflowStore.updateNode(node.id, node)
        }
        break

      case 'delete_block':
        // Block deleted
        if (data.data.deleted_block_id) {
          workflowStore.deleteNode(data.data.deleted_block_id as string)
        }
        break

      case 'connect_blocks':
        // Edge added
        if (data.data.edge) {
          const edge = data.data.edge as typeof workflowStore.flowchart.edges[0]
          workflowStore.addEdge(edge)
        }
        break

      case 'disconnect_blocks':
        // Edge removed
        if (data.data.removed_connection_id) {
          workflowStore.deleteEdgeById(data.data.removed_connection_id as string)
        }
        break

      default:
        console.warn('[Socket] Unknown workflow action:', data.action)
    }
  })

  // Workflow update events (from orchestrator manipulation tools)
  socket.on('workflow_update', (data: { action: string; data: Record<string, unknown> }) => {
    console.log('[Socket] workflow_update:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    // Filter updates for different workflows to prevent cross-tab contamination
    const currentId = workflowStore.currentWorkflow?.id
    const updatedId = data.data.workflow_id as string | undefined

    if (updatedId && currentId && updatedId !== currentId) {
      console.log('[Socket] Ignoring update for different workflow:', updatedId, 'current:', currentId)
      return
    }

    switch (data.action) {
      case 'add_node':
        // Single node added by orchestrator
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          workflowStore.addNode(node)
          // Switch to workflow tab to show the change
          uiStore.setCanvasTab('workflow')
          console.log('[Socket] Added node:', node.id)
        }
        break

      case 'modify_node':
        // Node updated by orchestrator
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          const exists = workflowStore.flowchart.nodes.find(n => n.id === node.id)
          if (!exists) {
            console.error('[Socket] Cannot modify non-existent node:', node.id)
            break
          }
          workflowStore.updateNode(node.id, node)
          console.log('[Socket] Modified node:', node.id)
        }
        break

      case 'delete_node':
        // Node deleted by orchestrator
        if (data.data.node_id) {
          const nodeId = data.data.node_id as string
          const exists = workflowStore.flowchart.nodes.find(n => n.id === nodeId)
          if (!exists) {
            console.error('[Socket] Cannot delete non-existent node:', nodeId)
            break
          }
          workflowStore.deleteNode(nodeId)
          console.log('[Socket] Deleted node:', nodeId)
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
          console.log('[Socket] Added connection:', edge.from, '->', edge.to)
        }
        break

      case 'delete_connection':
        // Edge removed by orchestrator
        if (data.data.from_node_id && data.data.to_node_id) {
          const fromId = data.data.from_node_id as string
          const toId = data.data.to_node_id as string
          workflowStore.deleteEdge(fromId, toId)
          console.log('[Socket] Deleted connection:', fromId, '->', toId)
        }
        break

      case 'batch_edit':
        // Multiple operations applied atomically
        if (data.data.workflow) {
          const flowchart = transformFlowchartFromBackend(
            data.data.workflow as { nodes: unknown[]; edges: unknown[] }
          )
          workflowStore.setFlowchart(flowchart)
          // Switch to workflow tab to show the changes
          uiStore.setCanvasTab('workflow')
          console.log('[Socket] Applied batch edit:', data.data.operations_applied, 'operations')
        }
        break

      default:
        console.warn('[Socket] Unknown workflow_update action:', data.action)
    }
  })

  // Analysis updates (from input management tools)
  // Only apply if task_id matches current task (prevents updates from inactive tabs)
  socket.on('analysis_updated', (data: { variables: unknown[]; outputs: unknown[]; task_id?: string }) => {
    console.log('[Socket] analysis_updated:', data)
    const chatStore = useChatStore.getState()
    const workflowStore = useWorkflowStore.getState()
    const taskId = data.task_id

    // Filter out updates from stale/different tasks to prevent tab cross-contamination
    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[Socket] Ignoring cancelled analysis_updated:', taskId)
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        console.log('[Socket] Ignoring stale analysis_updated:', taskId, 'current:', chatStore.currentTaskId)
        return
      }
    }

    // Update the analysis with new variables/outputs
    const currentAnalysis = workflowStore.currentAnalysis ?? {
      variables: [],
      outputs: [],
      tree: {},
      doubts: [],
    }

    const updatedAnalysis: WorkflowAnalysis = {
      ...currentAnalysis,
      variables: data.variables as WorkflowAnalysis['variables'],
      outputs: data.outputs as WorkflowAnalysis['outputs'],
    }

    workflowStore.setAnalysis(updatedAnalysis)
    console.log('[Socket] Updated analysis with', data.variables.length, 'variables and', data.outputs.length, 'outputs')
  })

  // ===== Workflow Library Events =====
  // These events handle workflow creation and saving by the LLM

  // Workflow created - LLM called create_workflow, track the workflow_id for this tab
  socket.on('workflow_created', (data: {
    workflow_id: string
    name: string
    output_type: string
    is_draft: boolean
  }) => {
    console.log('[Socket] workflow_created:', data)
    const workflowStore = useWorkflowStore.getState()
    const currentId = workflowStore.currentWorkflow?.id

    // Only update workflow ID if frontend didn't already have one
    // Frontend generates ID on tab creation, backend should use that same ID
    // If IDs match (expected case), no need to update
    // If IDs differ, it means backend generated a new ID (legacy behavior) - update to sync
    if (!currentId || currentId !== data.workflow_id) {
      workflowStore.setCurrentWorkflowId(data.workflow_id)
      console.log('[Socket] Updated workflow ID:', currentId, '->', data.workflow_id)
    } else {
      console.log('[Socket] Workflow ID already matches:', data.workflow_id)
    }

    // Update the workflow name
    const currentWf = workflowStore.currentWorkflow
    if (currentWf && data.name) {
      workflowStore.setCurrentWorkflow({
        ...currentWf,
        metadata: { ...currentWf.metadata, name: data.name }
      })
    }

    // Store workflow-level output_type from backend
    if (data.output_type) {
      const currentWf2 = workflowStore.currentWorkflow
      if (currentWf2) {
        workflowStore.setCurrentWorkflow({ ...currentWf2, output_type: data.output_type })
      }
    }

    console.log('[Socket] workflow_created complete - ID:', data.workflow_id, 'name:', data.name, 'output_type:', data.output_type)
  })

  // Workflow saved - LLM called save_workflow_to_library, update draft status
  socket.on('workflow_saved', (data: {
    workflow_id: string
    name: string
    is_draft: boolean
    already_saved: boolean
  }) => {
    console.log('[Socket] workflow_saved:', data)
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
      console.log('[Socket] Workflow saved to library:', data.workflow_id, 'name:', data.name)
    } else {
      console.log('[Socket] Workflow was already saved:', data.workflow_id)
    }
  })

  // Annotations update (from orchestrator image questions)
  socket.on('annotations_update', (data: { annotations: unknown[] }) => {
    console.log('[Socket] annotations_update:', data)
    const workflowStore = useWorkflowStore.getState()
    workflowStore.setPendingAnnotations(data.annotations as any)
  })
}
