// LEMON TypeScript Types
// Matching backend Pydantic models

// ============ Enums ============

export type BlockType = 'input' | 'decision' | 'output' | 'workflow_ref'
export type InputType = 'int' | 'float' | 'bool' | 'string' | 'enum' | 'date' | 'number'
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

// Structured decision condition - references variables by ID
export interface DecisionCondition {
  input_id: string       // Which workflow variable to compare (e.g., "var_age_int")
  comparator: Comparator // The comparison operator to use
  value: unknown         // The value to compare against
  value2?: unknown       // Second value for range comparisons (within_range, date_between)
}

// Helper: Map input types to their valid comparators
export const COMPARATORS_BY_TYPE: Record<InputType, Comparator[]> = {
  int: ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'within_range'],
  float: ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'within_range'],
  number: ['eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'within_range'],  // Unified numeric type
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

// ============ Calculation Operators ============
// Frontend definitions mirroring backend operators.py

export type OperatorArity = 'unary' | 'binary' | 'variadic'

export interface OperatorDef {
  name: string           // Internal name, e.g., "add", "sqrt"
  displayName: string    // Human-readable name, e.g., "Add", "Square Root"
  symbol: string         // Mathematical symbol, e.g., "+", "sqrt"
  minArity: number       // Minimum operands required
  maxArity: number | null // Maximum operands (null = unlimited)
  description: string    // Explanation of what operator does
  category: OperatorArity // For grouping in UI
}

// All operators available for calculation nodes
// Mirrors backend src/backend/execution/operators.py
export const OPERATORS: OperatorDef[] = [
  // Unary operators (arity=1)
  { name: 'negate', displayName: 'Negate', symbol: '-x', minArity: 1, maxArity: 1, description: 'Returns the negation of the operand', category: 'unary' },
  { name: 'abs', displayName: 'Absolute Value', symbol: '|x|', minArity: 1, maxArity: 1, description: 'Returns the absolute value', category: 'unary' },
  { name: 'sqrt', displayName: 'Square Root', symbol: '√x', minArity: 1, maxArity: 1, description: 'Returns the square root (fails for negative)', category: 'unary' },
  { name: 'square', displayName: 'Square', symbol: 'x²', minArity: 1, maxArity: 1, description: 'Returns the operand squared', category: 'unary' },
  { name: 'cube', displayName: 'Cube', symbol: 'x³', minArity: 1, maxArity: 1, description: 'Returns the operand cubed', category: 'unary' },
  { name: 'reciprocal', displayName: 'Reciprocal', symbol: '1/x', minArity: 1, maxArity: 1, description: 'Returns 1 divided by operand (fails for zero)', category: 'unary' },
  { name: 'floor', displayName: 'Floor', symbol: '⌊x⌋', minArity: 1, maxArity: 1, description: 'Rounds down to nearest integer', category: 'unary' },
  { name: 'ceil', displayName: 'Ceiling', symbol: '⌈x⌉', minArity: 1, maxArity: 1, description: 'Rounds up to nearest integer', category: 'unary' },
  { name: 'round', displayName: 'Round', symbol: 'round', minArity: 1, maxArity: 1, description: 'Rounds to nearest integer', category: 'unary' },
  { name: 'sign', displayName: 'Sign', symbol: 'sign', minArity: 1, maxArity: 1, description: 'Returns -1, 0, or 1 based on sign', category: 'unary' },
  { name: 'ln', displayName: 'Natural Log', symbol: 'ln', minArity: 1, maxArity: 1, description: 'Natural logarithm (fails for non-positive)', category: 'unary' },
  { name: 'log10', displayName: 'Log Base 10', symbol: 'log₁₀', minArity: 1, maxArity: 1, description: 'Base-10 logarithm (fails for non-positive)', category: 'unary' },
  { name: 'exp', displayName: 'Exponential', symbol: 'eˣ', minArity: 1, maxArity: 1, description: 'Returns e raised to the power of x', category: 'unary' },
  { name: 'sin', displayName: 'Sine', symbol: 'sin', minArity: 1, maxArity: 1, description: 'Sine (radians)', category: 'unary' },
  { name: 'cos', displayName: 'Cosine', symbol: 'cos', minArity: 1, maxArity: 1, description: 'Cosine (radians)', category: 'unary' },
  { name: 'tan', displayName: 'Tangent', symbol: 'tan', minArity: 1, maxArity: 1, description: 'Tangent (radians)', category: 'unary' },
  { name: 'asin', displayName: 'Arc Sine', symbol: 'asin', minArity: 1, maxArity: 1, description: 'Arc sine (fails if |x| > 1)', category: 'unary' },
  { name: 'acos', displayName: 'Arc Cosine', symbol: 'acos', minArity: 1, maxArity: 1, description: 'Arc cosine (fails if |x| > 1)', category: 'unary' },
  { name: 'atan', displayName: 'Arc Tangent', symbol: 'atan', minArity: 1, maxArity: 1, description: 'Arc tangent', category: 'unary' },
  { name: 'degrees', displayName: 'Degrees', symbol: 'deg', minArity: 1, maxArity: 1, description: 'Converts radians to degrees', category: 'unary' },
  { name: 'radians', displayName: 'Radians', symbol: 'rad', minArity: 1, maxArity: 1, description: 'Converts degrees to radians', category: 'unary' },

  // Binary operators (arity=2)
  { name: 'subtract', displayName: 'Subtract', symbol: 'a - b', minArity: 2, maxArity: 2, description: 'Returns a minus b', category: 'binary' },
  { name: 'divide', displayName: 'Divide', symbol: 'a / b', minArity: 2, maxArity: 2, description: 'Returns a divided by b (fails for zero)', category: 'binary' },
  { name: 'floor_divide', displayName: 'Floor Divide', symbol: 'a // b', minArity: 2, maxArity: 2, description: 'Floor division (fails for zero)', category: 'binary' },
  { name: 'modulo', displayName: 'Modulo', symbol: 'a % b', minArity: 2, maxArity: 2, description: 'Remainder of a / b (fails for zero)', category: 'binary' },
  { name: 'power', displayName: 'Power', symbol: 'a ^ b', minArity: 2, maxArity: 2, description: 'Returns a raised to power b', category: 'binary' },
  { name: 'log', displayName: 'Logarithm', symbol: 'log_b(a)', minArity: 2, maxArity: 2, description: 'Logarithm of a with base b', category: 'binary' },
  { name: 'atan2', displayName: 'Arc Tangent 2', symbol: 'atan2', minArity: 2, maxArity: 2, description: 'Two-argument arc tangent', category: 'binary' },

  // Variadic operators (arity>=2, unlimited)
  { name: 'add', displayName: 'Add', symbol: '+', minArity: 2, maxArity: null, description: 'Sum of all operands', category: 'variadic' },
  { name: 'multiply', displayName: 'Multiply', symbol: '×', minArity: 2, maxArity: null, description: 'Product of all operands', category: 'variadic' },
  { name: 'min', displayName: 'Minimum', symbol: 'min', minArity: 2, maxArity: null, description: 'Minimum of all operands', category: 'variadic' },
  { name: 'max', displayName: 'Maximum', symbol: 'max', minArity: 2, maxArity: null, description: 'Maximum of all operands', category: 'variadic' },
  { name: 'sum', displayName: 'Sum', symbol: 'Σ', minArity: 2, maxArity: null, description: 'Sum of all operands (alias for add)', category: 'variadic' },
  { name: 'average', displayName: 'Average', symbol: 'avg', minArity: 2, maxArity: null, description: 'Arithmetic mean of all operands', category: 'variadic' },
  { name: 'hypot', displayName: 'Hypotenuse', symbol: 'hypot', minArity: 2, maxArity: null, description: 'Euclidean distance: √(x₁² + x₂² + ...)', category: 'variadic' },
  { name: 'geometric_mean', displayName: 'Geometric Mean', symbol: 'geomean', minArity: 2, maxArity: null, description: 'Geometric mean (fails for negative)', category: 'variadic' },
  { name: 'harmonic_mean', displayName: 'Harmonic Mean', symbol: 'harmean', minArity: 2, maxArity: null, description: 'Harmonic mean (fails for zero/negative)', category: 'variadic' },
  { name: 'variance', displayName: 'Variance', symbol: 'var', minArity: 2, maxArity: null, description: 'Sample variance (requires >= 2 values)', category: 'variadic' },
  { name: 'std_dev', displayName: 'Std Deviation', symbol: 'stdev', minArity: 2, maxArity: null, description: 'Sample standard deviation (requires >= 2)', category: 'variadic' },
  { name: 'range', displayName: 'Range', symbol: 'range', minArity: 2, maxArity: null, description: 'Returns max - min of all operands', category: 'variadic' },
]

// Helper to get operator by name
export const getOperator = (name: string): OperatorDef | undefined =>
  OPERATORS.find(op => op.name === name)

// Helper to get operators by category
export const getOperatorsByCategory = (category: OperatorArity): OperatorDef[] =>
  OPERATORS.filter(op => op.category === category)

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
  // Peer review fields (optional for private workflows)
  is_published?: boolean
  review_status?: 'unreviewed' | 'reviewed'
  net_votes?: number
  published_at?: string
  publisher_id?: string
  user_vote?: number | null  // Current user's vote: +1, -1, or null
}

// Peer review status type
export type ReviewStatus = 'unreviewed' | 'reviewed'

// ============ Unified Variable System ============
// All workflow variables (user inputs, subprocess outputs, calculated values) are stored
// in a single list with a 'source' field indicating their origin.

// Variable source types - indicates where the variable value comes from
export type VariableSource = 'input' | 'subprocess' | 'calculated' | 'constant'

// Unified variable type - replaces the old WorkflowInput
export interface WorkflowVariable {
  id: string                          // e.g., "var_patient_age_int", "var_creditscore_float"
  name: string                        // Human-readable name, e.g., "Patient Age"
  type: InputType                     // "int", "float", "bool", "string", "enum", "date"
  source: VariableSource              // Where this variable comes from
  description?: string                // Optional description

  // For source='input' - user provides value at execution time
  enum_values?: string[]              // For enum type: allowed values
  range?: Range                       // For numeric types: min/max constraints

  // For source='subprocess' - value comes from executing another workflow
  source_node_id?: string             // Which subprocess node produces this variable
  subworkflow_id?: string             // Which subworkflow it comes from

  // For source='calculated' (future) - computed from other variables
  expression?: string                 // e.g., "Weight / (Height * Height)"
  depends_on?: string[]               // Variable IDs this depends on

  // For source='constant' (future) - fixed value
  value?: unknown                     // The constant value
}

// Legacy type alias for backwards compatibility during transition
export type WorkflowInput = WorkflowVariable

// Workflow output definition - now with required type for subprocess variable inference
export interface WorkflowOutput {
  name: string                        // Output name
  description?: string                // Optional description
  type: InputType                     // Output type (required for subprocess variable inference)
}

export interface WorkflowAnalysis {
  variables: WorkflowVariable[]       // Unified variable list (replaces inputs)
  outputs: WorkflowOutput[]           // Outputs with required type
  tree: Record<string, unknown>
  doubts: string[]
}

// ============ Flowchart Models (for canvas rendering) ============

export type FlowNodeType = 'start' | 'process' | 'decision' | 'subprocess' | 'calculation' | 'end'
export type FlowNodeColor = 'teal' | 'amber' | 'green' | 'slate' | 'rose' | 'sky' | 'purple'

// ============ Calculation Node Types ============
// Operand in a calculation - either a variable reference or a literal value

export type OperandKind = 'variable' | 'literal'

export interface VariableOperand {
  kind: 'variable'
  ref: string  // Variable ID, e.g., "var_weight_number"
}

export interface LiteralOperand {
  kind: 'literal'
  value: number  // Numeric literal value
}

export type Operand = VariableOperand | LiteralOperand

// Calculation output definition
export interface CalculationOutput {
  name: string         // Human-readable name, e.g., "BMI"
  description?: string // Optional description
}

// Full calculation configuration for a calculation node
export interface CalculationConfig {
  output: CalculationOutput  // The output variable to create
  operator: string           // Operator name, e.g., "divide", "add", "sqrt"
  operands: Operand[]        // The operands for the calculation
}

export interface FlowNode {
  id: string
  type: FlowNodeType
  label: string
  x: number
  y: number
  color: FlowNodeColor
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
  // Calculation-specific fields (for type='calculation')
  calculation?: CalculationConfig
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
  variables: WorkflowVariable[]       // Unified variable list (replaces inputs)
  outputs: WorkflowOutput[]           // Outputs with required type
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

export type SidebarTab = 'library' | 'variables' | 'properties'
