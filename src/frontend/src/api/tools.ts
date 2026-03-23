/**
 * API functions for tool listing and execution.
 * Used by the DevTools panel for tool exploration and testing.
 */

import { api } from './client'
import type { Flowchart, WorkflowAnalysis } from '../types'

/**
 * Tool definition as returned by the API
 */
export interface ToolDefinition {
    name: string
    description: string
    inputSchema: {
        type?: string
        properties?: Record<string, {
            type?: string
            description?: string
            required?: boolean
            enum?: string[]
            oneOf?: Array<Record<string, unknown>>
            anyOf?: Array<Record<string, unknown>>
        }>
        required?: string[]
    }
}

export interface DevToolOpenTab {
    workflow_id: string
    title: string
    node_count: number
    edge_count: number
    is_active: boolean
}

export interface DevToolExecutionContext {
    current_workflow_id?: string
    workflow?: Flowchart & {
        variables?: WorkflowAnalysis['variables']
        outputs?: WorkflowAnalysis['outputs']
        output_type?: string
    }
    analysis?: WorkflowAnalysis | null
    open_tabs?: DevToolOpenTab[]
}

/**
 * Fetch all available tools with their schemas.
 */
export async function listTools(): Promise<ToolDefinition[]> {
    const response = await api.get<{ tools: ToolDefinition[] }>('/api/tools')
    return response.tools || []
}

/**
 * Execute a tool with the provided arguments.
 */
export async function executeTool(
    toolName: string,
    args: Record<string, unknown>,
    context?: DevToolExecutionContext
): Promise<{ success: boolean; result?: unknown; error?: string }> {
    return api.post<{ success: boolean; result?: unknown; error?: string }>(
        `/api/tools/${encodeURIComponent(toolName)}/execute`,
        {
            args,
            context,
        }
    )
}
