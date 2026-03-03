/**
 * API functions for MCP tool listing and execution.
 * Used by the DevTools panel for tool exploration and testing.
 */

import { api } from './client'

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
        }>
        required?: string[]
    }
}

/**
 * Fetch all available MCP tools with their schemas.
 */
export async function listMCPTools(): Promise<ToolDefinition[]> {
    const response = await api.get<{ tools: ToolDefinition[] }>('/api/tools')
    return response.tools || []
}

/**
 * Execute an MCP tool with the provided arguments.
 */
export async function executeMCPTool(
    toolName: string,
    args: Record<string, unknown>
): Promise<{ success: boolean; result?: unknown; error?: string }> {
    return api.post<{ success: boolean; result?: unknown; error?: string }>(
        `/api/tools/${encodeURIComponent(toolName)}/execute`,
        args
    )
}
