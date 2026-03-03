/**
 * Execution-related socket event handlers.
 * Handles: execution_started, execution_step, execution_paused, execution_resumed,
 *          execution_complete, execution_error, execution_log,
 *          subflow_start, subflow_step, subflow_complete
 */
import type { Socket } from 'socket.io-client'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import { beautifyNodes } from '../../utils/beautifyNodes'
import type { FlowNode, FlowEdge, ExecutionLogEntry } from '../../types'

/** Register all execution-related socket event handlers */
export function registerExecutionHandlers(socket: Socket): void {
  // Execution started - marks the beginning of a workflow execution session.
  // Skip if already started with same ID (optimistic update in socketActions already called startExecution).
  // Re-calling would reset executedNodeIds/executionLogs, causing a race condition in instant mode
  // where step/log events arrive before this event and get wiped.
  socket.on('execution_started', (data: { execution_id: string }) => {
    console.log('[Socket] execution_started:', data)
    const workflowStore = useWorkflowStore.getState()
    if (workflowStore.execution.executionId === data.execution_id) {
      return  // Already started optimistically, don't reset state
    }
    workflowStore.startExecution(data.execution_id)
  })

  // Execution step - fires when a node begins executing (highlight it)
  socket.on('execution_step', (data: {
    execution_id: string
    node_id: string
    node_type: string
    node_label: string
    step_index: number
  }) => {
    console.log('[Socket] execution_step:', data)
    const workflowStore = useWorkflowStore.getState()
    const execution = workflowStore.execution

    // Only process if this is our current execution
    if (execution.executionId !== data.execution_id) {
      console.warn('[Socket] Ignoring step from different execution')
      return
    }

    // Mark the previous executing node as executed (trail effect)
    if (execution.executingNodeId) {
      workflowStore.markNodeExecuted(execution.executingNodeId)
    }

    // Set the new executing node
    workflowStore.setExecutingNode(data.node_id)
  })

  // Execution paused - user requested pause
  socket.on('execution_paused', (data: { execution_id: string; current_node_id: string }) => {
    console.log('[Socket] execution_paused:', data)
    const workflowStore = useWorkflowStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      workflowStore.pauseExecution()
    }
  })

  // Execution resumed - user requested resume
  socket.on('execution_resumed', (data: { execution_id: string }) => {
    console.log('[Socket] execution_resumed:', data)
    const workflowStore = useWorkflowStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      workflowStore.resumeExecution()
    }
  })

  // Execution complete - workflow finished executing (success or failure)
  // Reopens the execute modal to show results to user
  socket.on('execution_complete', (data: {
    execution_id: string
    success: boolean
    output?: unknown
    path?: string[]
    error?: string
  }) => {
    console.log('[Socket] execution_complete:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()
    const execution = workflowStore.execution

    if (execution.executionId !== data.execution_id) {
      console.warn('[Socket] Ignoring completion from different execution')
      return
    }

    // Mark the last executing node as executed
    if (execution.executingNodeId) {
      workflowStore.markNodeExecuted(execution.executingNodeId)
    }

    // Clear executing node and set output
    workflowStore.setExecutingNode(null)
    workflowStore.stopExecution()

    if (data.success) {
      workflowStore.setExecutionOutput(data.output)
    } else {
      workflowStore.setExecutionError(data.error || 'Execution failed')
    }

    // Reopen the execute modal to show results/error to user
    uiStore.openModal('execute')
  })

  // Execution error - something went wrong during execution
  // Reopens the execute modal to show error to user
  socket.on('execution_error', (data: { execution_id: string; error: string }) => {
    console.error('[Socket] execution_error:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      workflowStore.setExecutionError(data.error)
      workflowStore.stopExecution()
      // Reopen the execute modal to show error to user
      uiStore.openModal('execute')
    }
  })

  // ============ Execution Log Events (Dev Tools) ============
  // Detailed logging for decision evaluations, calculations, etc.

  socket.on('execution_log', (data: {
    execution_id: string
    log_type: 'decision' | 'calculation' | 'subflow_start' | 'subflow_step' | 'subflow_complete' | 'start' | 'end'
    node_id: string
    node_label: string
    // Decision-specific fields
    condition_expression?: string
    input_name?: string
    input_value?: unknown
    comparator?: string
    compare_value?: unknown
    compare_value2?: unknown
    result?: boolean | unknown
    branch_taken?: 'true' | 'false'
    // Calculation-specific fields
    output_name?: string
    operator?: string
    operands?: Array<{ name: string; kind: string; value: number }>
    formula?: string
    // Subflow-specific fields (can be on any log type if inside subflow)
    subworkflow_id?: string
    subworkflow_name?: string
    parent_node_id?: string
    node_type?: string
    // Subflow complete fields
    success?: boolean
    output?: unknown
    error?: string
    // Start/End specific fields
    inputs?: Record<string, unknown>
    output_value?: unknown
  }) => {
    console.log('[Socket] execution_log:', data)
    const workflowStore = useWorkflowStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      // Create log entry with unique ID and timestamp
      const logEntry = {
        id: `log_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        timestamp: Date.now(),
        execution_id: data.execution_id,
        node_id: data.node_id,
        node_label: data.node_label,
        log_type: data.log_type,
        // Subworkflow info (can be on any log type if node is in subflow)
        subworkflow_id: data.subworkflow_id,
        subworkflow_name: data.subworkflow_name,
        // Include all fields directly based on log type
        ...(data.log_type === 'decision' && {
          condition_expression: data.condition_expression,
          input_name: data.input_name,
          input_value: data.input_value,
          comparator: data.comparator,
          compare_value: data.compare_value,
          compare_value2: data.compare_value2,
          result: data.result,
          branch_taken: data.branch_taken,
        }),
        ...(data.log_type === 'calculation' && {
          output_name: data.output_name,
          operator: data.operator,
          operands: data.operands,
          result: data.result,
          formula: data.formula,
        }),
        ...(data.log_type === 'subflow_step' && {
          parent_node_id: data.parent_node_id,
          node_type: data.node_type,
        }),
        ...(data.log_type === 'subflow_complete' && {
          success: data.success,
          output: data.output,
          error: data.error,
        }),
        ...(data.log_type === 'start' && {
          inputs: data.inputs,
        }),
        ...(data.log_type === 'end' && {
          output_value: data.output,
        }),
      }
      workflowStore.addExecutionLog(logEntry as ExecutionLogEntry)
    }
  })

  // ============ Subflow Visualization Events ============
  // These events enable the popup modal for visualizing subflow execution

  // Subflow start - opens popup modal with subflow canvas
  socket.on('subflow_start', (data: {
    execution_id: string
    parent_node_id: string
    subworkflow_id: string
    subworkflow_name: string
    nodes: FlowNode[]
    edges: FlowEdge[]
  }) => {
    console.log('[Socket] subflow_start:', data)
    const workflowStore = useWorkflowStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      // Beautify nodes before displaying for better layout
      const beautified = beautifyNodes(data.nodes, data.edges)

      workflowStore.startSubflowExecution(
        data.parent_node_id,
        data.subworkflow_id,
        data.subworkflow_name,
        beautified.nodes,
        beautified.edges
      )
    }
  })

  // Subflow step - highlights node in subflow popup modal
  socket.on('subflow_step', (data: {
    execution_id: string
    parent_node_id: string
    subworkflow_id: string
    node_id: string
    node_type: string
    node_label: string
    step_index: number
  }) => {
    console.log('[Socket] subflow_step:', data)
    const workflowStore = useWorkflowStore.getState()
    const { subflowStack } = workflowStore

    // Get top subflow from stack
    const topSubflow = subflowStack.length > 0 ? subflowStack[subflowStack.length - 1] : null

    // Only process if this is our current execution and matches top subflow
    if (workflowStore.execution.executionId !== data.execution_id) return
    if (!topSubflow || topSubflow.subworkflowId !== data.subworkflow_id) return

    // Mark previous node as executed
    if (topSubflow.executingNodeId) {
      workflowStore.markSubflowNodeExecuted(topSubflow.executingNodeId)
    }

    // Set new executing node
    workflowStore.setSubflowExecutingNode(data.node_id)
  })

  // Subflow complete - closes popup modal
  socket.on('subflow_complete', (data: {
    execution_id: string
    parent_node_id: string
    subworkflow_id: string
    subworkflow_name: string
    success: boolean
    output?: unknown
    error?: string
  }) => {
    console.log('[Socket] subflow_complete:', data)
    const workflowStore = useWorkflowStore.getState()
    const { subflowStack } = workflowStore
    const topSubflow = subflowStack.length > 0 ? subflowStack[subflowStack.length - 1] : null

    if (workflowStore.execution.executionId === data.execution_id && topSubflow) {
      // Mark final subflow node as executed before closing
      if (topSubflow.executingNodeId) {
        workflowStore.markSubflowNodeExecuted(topSubflow.executingNodeId)
      }
      // Delay so user can see final state before modal closes (skip in instant mode)
      const closeDelay = workflowStore.execution.executionSpeed === 0 ? 0 : 500
      setTimeout(() => {
        workflowStore.endSubflowExecution()
      }, closeDelay)
    }
  })
}
