// LEMON TypeScript Types
// Matching backend Pydantic models

// ============ Enums ============

export type BlockType = 'input' | 'decision' | 'output' | 'workflow_ref'
export type InputType = 'int' | 'float' | 'bool' | 'string' | 'enum' | 'date'
export type PortType = 'default' | 'true' | 'false'

// ============ Decision Condition Types ============
// Comparators for structured decision node conditions

// Numeric comparators (for int, float types)
export type NumericComparator = 'eq' | 'neq' | 'lt' | 'lte' | 'gt' | 'gte' | 'within_range'

// Boolean comparators
export type BooleanComparator = 'is_true' | 'is_false'

// String comparators (case-insensitive)
export type StringComparator = 'str_eq' | 'str_neq' | 'str_contains' | 'str_starts_with' | 'str_ends_with'

// Date comparators (ISO format: "YYYY-MM-DD")
export type DateComparator = 'date_eq' | 'date_before' | 'date_after' | 'date_between'

// Enum comparators (same as string but uses dropdown in UI)
export type EnumComparator = 'enum_eq' | 'enum_neq'

// Union of all comparators
export type Comparator =
  | NumericComparator
  | BooleanComparator
  | StringComparator
  | DateComparator
  | EnumComparator

// Structured decision condition - replaces label-based condition parsing
export interface DecisionCondition {
  input_id: string       // Which workflow input to compare (e.g., "input_age_int")
  comparator: Comparator // The comparison operator to use
  value: unknown         // The value to compare against
  value2?: unknown       // Second value for range comparisons (within_range, date_between)
}

// Helper: Map input types to their valid comparators
export const COMPARATORS_BY_TYPE: Record<InputType, Comparator[]> = {
  int: ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'within_range'],
  float: ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'within_range'],
  bool: ['is_true', 'is_false'],
  string: ['str_eq', 'str_neq', 'str_contains', 'str_starts_with', 'str_ends_with'],
  date: ['date_eq', 'date_before', 'date_after', 'date_between'],
  enum: ['enum_eq', 'enum_neq'],
}

// Helper: Human-readable labels for comparators
export const COMPARATOR_LABELS: Record<Comparator, string> = {
  // Numeric
  eq: 'equals (=)',
  neq: 'not equals (≠)',
  lt: 'less than (<)',
  lte: 'less than or equal (≤)',
  gt: 'greater than (>)',
  gte: 'greater than or equal (≥)',
  within_range: 'within range',
  // Boolean
  is_true: 'is true',
  is_false: 'is false',
  // String
  str_eq: 'equals',
  str_neq: 'not equals',
  str_contains: 'contains',
  str_starts_with: 'starts with',
  str_ends_with: 'ends with',
  // Date
  date_eq: 'equals',
  date_before: 'before',
  date_after: 'after',
  date_between: 'between',
  // Enum
  enum_eq: 'equals',
  enum_neq: 'not equals',
}
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
  output_type?: string
  output_template?: string
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

export interface WorkflowInput {
  id: string
  name: string
  type: InputType
  description?: string
  enum?: string[]
  enum_values?: string[]
  range?: Range
}

export interface WorkflowAnalysis {
  inputs: WorkflowInput[]
  outputs: Array<{ name: string; description?: string }>
  tree: Record<string, unknown>
  doubts: string[]
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
  input_ref?: string
  output_type?: string
  output_template?: string
  output_value?: unknown
  // Decision node condition (for type='decision')
  // Structured condition that replaces label-based condition parsing
  condition?: DecisionCondition
  // Subprocess-specific fields (for type='subprocess')
  subworkflow_id?: string
  input_mapping?: Record<string, string>
  output_variable?: string
}

export interface FlowEdge {
  id?: string
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
  nodes: FlowNode[]
  edges: FlowEdge[]
  inputs: WorkflowInput[]
  outputs: Array<{ name: string; description?: string }>
  tree: Record<string, unknown>
  doubts: string[]
  validation_score?: number
  validation_count?: number
  is_validated?: boolean
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
  task_id?: string
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
  task_id?: string
  error: string
}

// ============ UI State Types ============

export type Stage = 'idle' | 'analyzing' | 'awaiting_approval' | 'tests_running' | 'code_refining' | 'done'

export type ModalType = 'library' | 'validation' | 'save' | 'execute' | 'none'

export type SidebarTab = 'library' | 'inputs' | 'properties'
