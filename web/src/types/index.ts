// LEMON TypeScript Types
// Matching backend Pydantic models

// ============ Enums ============

export type BlockType = 'input' | 'decision' | 'output' | 'workflow_ref'
export type InputType = 'int' | 'float' | 'bool' | 'string' | 'enum' | 'date'
export type PortType = 'default' | 'true' | 'false'
export type ValidationConfidence = 'none' | 'low' | 'medium' | 'high'
export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

// ============ Core Workflow Models ============

export interface Position {
  x: number
  y: number
}

export interface Range {
  min?: number
  max?: number
}

export interface BlockBase {
  id: string
  type: BlockType
  position: Position
}

export interface InputBlock extends BlockBase {
  type: 'input'
  name: string
  input_type: InputType
  range?: Range
  enum_values?: string[]
  description: string
  required: boolean
}

export interface DecisionBlock extends BlockBase {
  type: 'decision'
  condition: string
  description: string
}

export interface OutputBlock extends BlockBase {
  type: 'output'
  value: string
  description: string
}

export interface WorkflowRefBlock extends BlockBase {
  type: 'workflow_ref'
  ref_id: string
  ref_name: string
  input_mapping: Record<string, string>
  output_name: string
}

export type Block = InputBlock | DecisionBlock | OutputBlock | WorkflowRefBlock

export interface Connection {
  id: string
  from_block: string
  from_port: PortType
  to_block: string
  to_port: PortType
}

export interface WorkflowMetadata {
  name: string
  description: string
  domain?: string
  tags: string[]
  creator_id?: string
  created_at: string
  updated_at: string
  validation_score: number
  validation_count: number
  confidence: ValidationConfidence
  is_validated: boolean
}

export interface Workflow {
  id: string
  metadata: WorkflowMetadata
  blocks: Block[]
  connections: Connection[]
}

export interface WorkflowSummary {
  id: string
  name: string
  description: string
  domain?: string
  tags: string[]
  validation_score: number
  validation_count: number
  confidence: ValidationConfidence
  is_validated: boolean
  input_names: string[]
  output_values: string[]
  created_at: string
  updated_at: string
}

// ============ Flowchart Models (for canvas rendering) ============

export type FlowNodeType = 'start' | 'process' | 'decision' | 'subprocess' | 'end'
export type FlowNodeColor = 'teal' | 'amber' | 'green' | 'slate' | 'rose' | 'sky'

export interface FlowNode {
  id: string
  type: FlowNodeType
  label: string
  x: number
  y: number
  color: FlowNodeColor
}

export interface FlowEdge {
  from: string
  to: string
  label: string
}

export interface Flowchart {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

// ============ Execution Models ============

export interface ExecutionStep {
  step: number
  block_id: string
  block_type: string
  state_before: Record<string, unknown>
  action: 'output' | 'decision' | 'workflow_ref' | 'input' | 'unknown'
  [key: string]: unknown
}

export interface ExecutionResult {
  output?: string
  path: string[]
  error?: string
  context: Record<string, unknown>
  success: boolean
}

export interface ExecutionTrace {
  result: ExecutionResult
  steps: ExecutionStep[]
  state_history: Record<string, unknown>[]
}

// ============ Validation Models ============

export interface ValidationCase {
  case_id: string
  inputs: Record<string, unknown>
  workflow_output: string
}

export interface ValidationAnswer {
  case_id: string
  user_answer: string
  workflow_output: string
  matched: boolean
  timestamp: string
}

export interface ValidationProgress {
  total: number
  current: number
  remaining?: number
}

export interface ValidationScore {
  matches: number
  total: number
  score: number
  confidence?: ValidationConfidence
  is_validated?: boolean
}

export interface ValidationSession {
  id: string
  workflow_id: string
  strategy: string
  cases: ValidationCase[]
  answers: ValidationAnswer[]
  current_index: number
  status: 'in_progress' | 'completed' | 'abandoned'
  created_at: string
  is_complete: boolean
  progress: ValidationProgress
}

// ============ Chat/Conversation Models ============

export interface ToolCall {
  tool: string
  arguments?: Record<string, unknown>
  result?: Record<string, unknown>
}

export interface Message {
  id: string
  role: MessageRole
  content: string
  timestamp: string
  tool_calls: ToolCall[]
}

export interface WorkingContext {
  current_workflow_id?: string
  current_workflow_name?: string
  validation_session_id?: string
  last_execution_result?: Record<string, unknown>
  draft_workflow?: Record<string, unknown>
  has_draft?: boolean
}

export interface ConversationContext {
  id: string
  messages: Message[]
  working: WorkingContext
  user_id?: string
  created_at: string
  updated_at: string
}

// ============ API Request/Response Types ============

export interface ListWorkflowsResponse {
  workflows: Workflow[]
  count: number
}

export interface SearchWorkflowsResponse {
  workflows: WorkflowSummary[]
}

export interface DomainsResponse {
  domains: string[]
}

export interface CreateWorkflowRequest {
  name: string
  description: string
  domain?: string
  tags?: string[]
  inputs: Array<{
    name: string
    type: InputType
    range?: Range
    enum_values?: string[]
    description?: string
  }>
  decisions: Array<{
    id: string
    condition: string
    description?: string
  }>
  outputs: string[]
  connections: Array<{
    from_block: string
    to_block: string
    from_port: PortType
  }>
}

export interface CreateWorkflowResponse {
  workflow_id: string
  name: string
  description: string
  domain?: string
  tags: string[]
  nodes: FlowNode[]
  edges: FlowEdge[]
  message: string
}

export interface ExecuteWorkflowRequest {
  [inputName: string]: unknown
}

export interface StartValidationRequest {
  workflow_id: string
  case_count?: number
  strategy?: 'random' | 'boundary' | 'comprehensive'
}

export interface StartValidationResponse {
  session_id: string
  progress: ValidationProgress
  current_case: ValidationCase
}

export interface SubmitValidationRequest {
  session_id: string
  answer: string
}

export interface SubmitValidationResponse {
  matched: boolean
  user_answer: string
  workflow_output: string
  progress: ValidationProgress
  current_score: ValidationScore
  next_case: ValidationCase | null
  session_complete: boolean
}

export interface ChatRequest {
  message: string
  conversation_id?: string
  image?: string
}

export interface ChatResponse {
  conversation_id: string
  response: string
  tool_calls: ToolCall[]
}

export interface ApiInfo {
  name: string
  version: string
  endpoints: Record<string, string>
}

export interface ApiError {
  error: string
}

// ============ WebSocket Event Types ============

export interface SocketConnectEvent {
  session_id: string
}

export interface SocketChatEvent {
  session_id: string
  message: string
  conversation_id?: string
  image?: string
}

export interface SocketChatResponse {
  response: string
  conversation_id: string
  tool_calls: ToolCall[]
  task_id?: string
}

export interface SocketAgentQuestion {
  task_id: string
  question: string
}

export interface SocketAgentComplete {
  task_id: string
  message: string
  result?: {
    workflow_id: string
    name: string
    nodes: FlowNode[]
    edges: FlowEdge[]
  }
}

export interface SocketAgentError {
  task_id: string
  error: string
}

// ============ UI State Types ============

export type Stage = 'idle' | 'analyzing' | 'awaiting_approval' | 'tests_running' | 'code_refining' | 'done'

export type ModalType = 'library' | 'validation' | 'none'

export type SidebarTab = 'library' | 'inputs'
