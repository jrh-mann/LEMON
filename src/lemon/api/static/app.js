// LEMON Workflow Studio - Main Application

const API = '/api';

// =============================================================================
// State
// =============================================================================

const state = {
  // Multiple workspaces (tabs)
  workspaces: [],
  activeWorkspaceId: null,

  // Current workspace data (synced with active workspace)
  workflow: {
    id: null,
    name: 'Untitled workflow',
    nodes: [],
    edges: [],
  },
  selectedNode: null,
  selectedEdge: null,  // Index of selected edge
  connectMode: false,
  connectFrom: null,
  dragState: null,
  // Pan/zoom state
  viewBox: { x: 0, y: 0, w: 1200, h: 800 },
  isPanning: false,
  panStart: null,
  // Edge drawing state
  edgeDrawing: {
    active: false,
    fromNode: null,
    fromPort: null,  // 'top', 'right', 'bottom', 'left'
    tempLine: null,
  },
  // Image on canvas
  canvasImage: null,  // { dataUrl, x, y, width, height }
  isImageWorkspace: false,  // True if this workspace is for image analysis only
  validation: {
    sessionId: null,
    currentCase: null,
    progress: { current: 0, total: 0 },
  },
  conversationId: null,  // Per-workspace conversation ID
  // Browser state
  browser: {
    workflows: [],      // All workflows from API
    filtered: [],       // Currently displayed (filtered)
    selectedId: null,   // Currently selected workflow ID
  },
};

// Generate unique workspace ID
function generateWorkspaceId() {
  return 'ws_' + Date.now().toString(36) + Math.random().toString(36).substr(2, 5);
}

// Create a new workspace
function createWorkspace(name = 'Untitled workflow') {
  const workspace = {
    id: generateWorkspaceId(),
    workflow: {
      id: null,
      name: name,
      nodes: [],
      edges: [],
    },
    selectedNode: null,
    conversationId: null,  // Each workspace has its own conversation
    canvasImage: null,     // Each workspace can have an uploaded image
    isImageWorkspace: false,  // True for image analysis workspaces
    viewBox: { x: 0, y: 0, w: 1200, h: 800 },  // Pan/zoom state
  };
  state.workspaces.push(workspace);
  return workspace;
}

// Save current state to active workspace
function saveCurrentWorkspace() {
  if (!state.activeWorkspaceId) return;
  const workspace = state.workspaces.find(w => w.id === state.activeWorkspaceId);
  if (workspace) {
    workspace.workflow = JSON.parse(JSON.stringify(state.workflow));
    workspace.selectedNode = state.selectedNode;
    workspace.conversationId = state.conversationId;
    workspace.canvasImage = state.canvasImage;
    workspace.isImageWorkspace = state.isImageWorkspace;
    workspace.viewBox = { ...state.viewBox };
  }
}

// Load workspace into current state
function loadWorkspace(workspaceId) {
  const workspace = state.workspaces.find(w => w.id === workspaceId);
  if (!workspace) return;

  state.workflow = JSON.parse(JSON.stringify(workspace.workflow));
  state.selectedNode = workspace.selectedNode;
  state.conversationId = workspace.conversationId;
  state.canvasImage = workspace.canvasImage;
  state.isImageWorkspace = workspace.isImageWorkspace || false;
  state.viewBox = workspace.viewBox || { x: 0, y: 0, w: 1200, h: 800 };
  state.activeWorkspaceId = workspaceId;

  $('#workflowName').value = state.workflow.name || '';
  updatePaletteState();
  updateViewBox();
  renderCanvas();
  renderTabs();
  renderInputsPanel();
}

// Update palette visibility based on workspace type
function updatePaletteState() {
  const palette = $('.palette-sidebar');
  if (palette) {
    if (state.isImageWorkspace) {
      palette.classList.add('disabled');
    } else {
      palette.classList.remove('disabled');
    }
  }
}

// Update SVG viewBox for pan/zoom
function updateViewBox() {
  const { x, y, w, h } = state.viewBox;
  canvas.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
}

// Zoom the canvas (centered on a point)
function zoomCanvas(delta, centerX, centerY) {
  const zoomFactor = delta > 0 ? 1.1 : 0.9;
  const { x, y, w, h } = state.viewBox;

  // Calculate new dimensions
  const newW = Math.max(400, Math.min(4000, w * zoomFactor));
  const newH = Math.max(300, Math.min(3000, h * zoomFactor));

  // Adjust position to zoom toward the center point
  const scale = newW / w;
  const newX = centerX - (centerX - x) * scale;
  const newY = centerY - (centerY - y) * scale;

  state.viewBox = { x: newX, y: newY, w: newW, h: newH };
  updateViewBox();
}

// Reset zoom to default
function resetZoom() {
  state.viewBox = { x: 0, y: 0, w: 1200, h: 800 };
  updateViewBox();
  saveCurrentWorkspace();
}

// Switch to a workspace
function switchWorkspace(workspaceId) {
  if (workspaceId === state.activeWorkspaceId) return;
  saveCurrentWorkspace();
  loadWorkspace(workspaceId);

  // Clear browser selection when switching
  state.browser.selectedId = null;
  renderBrowserList();
}

// Close a workspace
function closeWorkspace(workspaceId) {
  const index = state.workspaces.findIndex(w => w.id === workspaceId);
  if (index === -1) return;

  // Don't close if it's the last tab
  if (state.workspaces.length === 1) {
    // Just clear it instead
    state.workspaces[0].workflow = { id: null, name: 'Untitled workflow', nodes: [], edges: [] };
    state.workspaces[0].selectedNode = null;
    loadWorkspace(state.workspaces[0].id);
    return;
  }

  state.workspaces.splice(index, 1);

  // If we closed the active workspace, switch to another
  if (workspaceId === state.activeWorkspaceId) {
    const newIndex = Math.min(index, state.workspaces.length - 1);
    loadWorkspace(state.workspaces[newIndex].id);
  } else {
    renderTabs();
  }
}

// Add a new workspace tab
function addNewWorkspace() {
  saveCurrentWorkspace();
  const workspace = createWorkspace();
  loadWorkspace(workspace.id);
}

// Render workspace tabs
function renderTabs() {
  const tabsContainer = $('#workspaceTabs');
  tabsContainer.innerHTML = '';

  state.workspaces.forEach(workspace => {
    const tab = document.createElement('div');
    tab.className = 'workspace-tab' + (workspace.id === state.activeWorkspaceId ? ' active' : '');
    if (workspace.isImageWorkspace) {
      tab.classList.add('image-tab');
    }
    tab.dataset.id = workspace.id;

    // Add image icon for image workspaces
    if (workspace.isImageWorkspace) {
      const icon = document.createElement('span');
      icon.className = 'workspace-tab-icon';
      icon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
      </svg>`;
      tab.appendChild(icon);
    }

    const name = document.createElement('span');
    name.className = 'workspace-tab-name';
    name.textContent = workspace.workflow.name || 'Untitled';
    tab.appendChild(name);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'workspace-tab-close';
    closeBtn.innerHTML = '×';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeWorkspace(workspace.id);
    });
    tab.appendChild(closeBtn);

    tab.addEventListener('click', () => switchWorkspace(workspace.id));
    tabsContainer.appendChild(tab);
  });

  // Add "+" button
  const addBtn = document.createElement('button');
  addBtn.className = 'workspace-tab-add';
  addBtn.innerHTML = '+';
  addBtn.addEventListener('click', addNewWorkspace);
  tabsContainer.appendChild(addBtn);
}

// Node sizes by type
const NODE_SIZES = {
  start: { w: 100, h: 50 },
  input: { w: 140, h: 60 },  // Kept for backwards compat, but not shown on canvas
  decision: { w: 140, h: 90 },
  output: { w: 160, h: 50 },
  subflow: { w: 160, h: 70 },
};

// Colors by type
const NODE_COLORS = {
  start: { fill: 'rgba(31, 110, 104, 0.2)', stroke: '#1f6e68' },
  input: { fill: 'rgba(31, 110, 104, 0.15)', stroke: '#1f6e68' },
  decision: { fill: 'rgba(201, 138, 44, 0.15)', stroke: '#c98a2c' },
  output: { fill: 'rgba(62, 124, 77, 0.2)', stroke: '#3e7c4d' },
  subflow: { fill: 'rgba(180, 83, 61, 0.15)', stroke: '#b4533d' },
};

// =============================================================================
// DOM Elements
// =============================================================================

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const canvas = $('#flowchartCanvas');
const nodeLayer = $('#nodeLayer');
const edgeLayer = $('#edgeLayer');
const imageLayer = $('#imageLayer');
const canvasEmpty = $('#canvasEmpty');
const chatThread = $('#chatThread');
const chatInput = $('#chatInput');
const blockCount = $('#blockCount');
const browserList = $('#browserList');
const browserFilter = $('#browserFilter');
const browserEmpty = $('#browserEmpty');
const imageUpload = $('#imageUpload');

// Semantic search elements
const semanticStatus = $('#semanticStatus');

// Sidebar elements
const sidebarTabs = $$('.sidebar-tab');
const libraryPanel = $('#libraryPanel');
const inputsPanel = $('#inputsPanel');
const inputsList = $('#inputsList');
const inputsEmpty = $('#inputsEmpty');

// =============================================================================
// Canvas Rendering
// =============================================================================

function renderCanvas() {
  nodeLayer.innerHTML = '';
  edgeLayer.innerHTML = '';
  imageLayer.innerHTML = '';

  // Render canvas image if present
  if (state.canvasImage) {
    renderCanvasImage();
  }

  // Update empty state
  if (state.workflow.nodes.length === 0 && !state.canvasImage) {
    canvasEmpty.classList.remove('hidden');
  } else {
    canvasEmpty.classList.add('hidden');
  }

  // Update block count
  blockCount.textContent = `${state.workflow.nodes.length} blocks`;

  // Enable/disable buttons
  const hasNodes = state.workflow.nodes.length > 0;
  $('#exportBtn').disabled = !hasNodes;

  // Render edges first (behind nodes) - layout algorithm minimizes crossings
  state.workflow.edges.forEach((edge, index) => renderEdge(edge, index));

  // Render nodes with connection ports
  state.workflow.nodes.forEach(renderNode);

  // Update inputs panel
  renderInputsPanel();
}

// Render uploaded image on canvas
function renderCanvasImage() {
  if (!state.canvasImage) return;

  const img = document.createElementNS('http://www.w3.org/2000/svg', 'image');
  img.setAttribute('href', state.canvasImage.dataUrl);
  img.setAttribute('x', state.canvasImage.x);
  img.setAttribute('y', state.canvasImage.y);
  img.setAttribute('width', state.canvasImage.width);
  img.setAttribute('height', state.canvasImage.height);
  img.setAttribute('opacity', '0.9');
  img.classList.add('canvas-image');
  imageLayer.appendChild(img);

  // Add a border around the image
  const border = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  border.setAttribute('x', state.canvasImage.x);
  border.setAttribute('y', state.canvasImage.y);
  border.setAttribute('width', state.canvasImage.width);
  border.setAttribute('height', state.canvasImage.height);
  border.setAttribute('fill', 'none');
  border.setAttribute('stroke', 'var(--teal)');
  border.setAttribute('stroke-width', '2');
  border.setAttribute('stroke-dasharray', '8,4');
  border.setAttribute('rx', '4');
  imageLayer.appendChild(border);

  // Only show delete button for non-image workspaces (for image workspaces, close the tab)
  if (!state.isImageWorkspace) {
    const deleteBtn = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    deleteBtn.classList.add('image-delete-btn');
    deleteBtn.setAttribute('transform', `translate(${state.canvasImage.x + state.canvasImage.width - 12}, ${state.canvasImage.y - 12})`);
    deleteBtn.innerHTML = `
      <circle cx="12" cy="12" r="12" fill="var(--rose)" />
      <path d="M8 8 L16 16 M16 8 L8 16" stroke="white" stroke-width="2" stroke-linecap="round" />
    `;
    deleteBtn.style.cursor = 'pointer';
    deleteBtn.addEventListener('click', () => {
      state.canvasImage = null;
      saveCurrentWorkspace();
      renderCanvas();
    });
    imageLayer.appendChild(deleteBtn);
  }
}

// Get port positions for a node type
function getPortPositions(nodeType, size) {
  if (nodeType === 'decision') {
    // Diamond has ports at vertices plus bottom-left/bottom-right for Yes/No branches
    return [
      { name: 'top', x: size.w / 2, y: 0 },
      { name: 'right', x: size.w, y: size.h / 2 },
      { name: 'bottom', x: size.w / 2, y: size.h },
      { name: 'left', x: 0, y: size.h / 2 },
      // Yes/No ports on the bottom edges of the diamond
      { name: 'bottom-left', x: size.w * 0.25, y: size.h * 0.75 },
      { name: 'bottom-right', x: size.w * 0.75, y: size.h * 0.75 },
    ];
  } else {
    // Rectangle has ports at edge centers
    return [
      { name: 'top', x: size.w / 2, y: 0 },
      { name: 'right', x: size.w, y: size.h / 2 },
      { name: 'bottom', x: size.w / 2, y: size.h },
      { name: 'left', x: 0, y: size.h / 2 },
    ];
  }
}

function renderNode(node) {
  // Skip input nodes - they're shown in the sidebar, not on canvas
  if (node.type === 'input') return;

  const size = NODE_SIZES[node.type] || NODE_SIZES.decision;
  const colors = NODE_COLORS[node.type] || NODE_COLORS.decision;

  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.classList.add('flow-node');
  g.dataset.id = node.id;
  g.setAttribute('transform', `translate(${node.x}, ${node.y})`);

  if (state.selectedNode === node.id) {
    g.classList.add('selected');
  }

  // Shape based on type
  let shape;
  if (node.type === 'start') {
    // Ellipse (oval) for start node
    shape = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
    shape.setAttribute('cx', size.w / 2);
    shape.setAttribute('cy', size.h / 2);
    shape.setAttribute('rx', size.w / 2);
    shape.setAttribute('ry', size.h / 2);
  } else if (node.type === 'decision') {
    // Diamond
    shape = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    const points = [
      `${size.w / 2},0`,
      `${size.w},${size.h / 2}`,
      `${size.w / 2},${size.h}`,
      `0,${size.h / 2}`,
    ].join(' ');
    shape.setAttribute('points', points);
  } else if (node.type === 'output') {
    // Pill shape (fully rounded rectangle)
    shape = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    shape.setAttribute('width', size.w);
    shape.setAttribute('height', size.h);
    shape.setAttribute('rx', size.h / 2);
  } else {
    // Regular rounded rectangle (subflow, etc)
    shape = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    shape.setAttribute('width', size.w);
    shape.setAttribute('height', size.h);
    shape.setAttribute('rx', 10);
  }

  shape.setAttribute('fill', colors.fill);
  shape.setAttribute('stroke', colors.stroke);
  shape.setAttribute('stroke-width', '2');
  g.appendChild(shape);

  // Add connection ports (small circles on edges)
  const portPositions = getPortPositions(node.type, size);
  portPositions.forEach(port => {
    const portEl = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    portEl.classList.add('connection-port');
    portEl.dataset.port = port.name;
    portEl.setAttribute('cx', port.x);
    portEl.setAttribute('cy', port.y);
    portEl.setAttribute('r', 6);
    portEl.setAttribute('fill', 'white');
    portEl.setAttribute('stroke', colors.stroke);
    portEl.setAttribute('stroke-width', '2');
    g.appendChild(portEl);
  });

  // For subflow nodes, add input/output port indicators
  if (node.type === 'subflow' && (node.subflowInputs?.length || node.subflowOutputs?.length)) {
    const inputs = node.subflowInputs || [];
    const outputs = node.subflowOutputs || [];

    // Input ports on left side
    inputs.forEach((inp, i) => {
      const portY = (size.h / (inputs.length + 1)) * (i + 1);
      const port = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      port.setAttribute('cx', 0);
      port.setAttribute('cy', portY);
      port.setAttribute('r', 5);
      port.setAttribute('fill', '#1f6e68');
      port.setAttribute('stroke', 'white');
      port.setAttribute('stroke-width', '1.5');
      g.appendChild(port);

      // Port label
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.textContent = inp.name;
      label.setAttribute('x', 8);
      label.setAttribute('y', portY + 3);
      label.setAttribute('font-size', '8');
      label.setAttribute('fill', '#6d6b64');
      g.appendChild(label);
    });

    // Output ports on right side
    outputs.forEach((out, i) => {
      const portY = (size.h / (outputs.length + 1)) * (i + 1);
      const port = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      port.setAttribute('cx', size.w);
      port.setAttribute('cy', portY);
      port.setAttribute('r', 5);
      port.setAttribute('fill', '#3e7c4d');
      port.setAttribute('stroke', 'white');
      port.setAttribute('stroke-width', '1.5');
      g.appendChild(port);
    });

    // Inner border to show it's a composite
    const inner = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    inner.setAttribute('x', 4);
    inner.setAttribute('y', 4);
    inner.setAttribute('width', size.w - 8);
    inner.setAttribute('height', size.h - 8);
    inner.setAttribute('rx', 6);
    inner.setAttribute('fill', 'none');
    inner.setAttribute('stroke', colors.stroke);
    inner.setAttribute('stroke-width', '1');
    inner.setAttribute('stroke-dasharray', '3,2');
    g.appendChild(inner);
  }

  // Label with text wrapping using foreignObject
  const fo = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
  const padding = node.type === 'decision' ? 15 : (node.type === 'subflow' ? 20 : 8);
  fo.setAttribute('x', padding);
  fo.setAttribute('y', 0);
  fo.setAttribute('width', size.w - padding * 2);
  fo.setAttribute('height', size.h);

  const div = document.createElement('div');
  div.className = 'node-label';
  div.textContent = node.label || node.type;
  fo.appendChild(div);
  g.appendChild(fo);

  nodeLayer.appendChild(g);
}

// Get connection point on the edge of a shape
function getEdgePoint(node, targetX, targetY) {
  const size = NODE_SIZES[node.type] || NODE_SIZES.input;
  const cx = node.x + size.w / 2;
  const cy = node.y + size.h / 2;

  // Direction from center to target
  const dx = targetX - cx;
  const dy = targetY - cy;

  const len = Math.sqrt(dx * dx + dy * dy);
  if (len === 0) return { x: cx, y: cy };

  if (node.type === 'decision') {
    // Diamond shape: |x - cx|/hw + |y - cy|/hh = 1
    // For ray from center: x = cx + t*dx, y = cy + t*dy
    // Substituting: t*(|dx|/hw + |dy|/hh) = 1
    const hw = size.w / 2;
    const hh = size.h / 2;

    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);

    // Avoid division by zero
    if (absDx < 0.001 && absDy < 0.001) return { x: cx, y: cy };

    const t = 1 / (absDx / hw + absDy / hh);
    return { x: cx + dx * t, y: cy + dy * t };
  } else {
    // Rectangle or rounded rectangle
    const hw = size.w / 2;
    const hh = size.h / 2;

    // Find intersection with rectangle boundary
    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);

    let scale;
    if (absDx * hh > absDy * hw) {
      // Intersects left or right side
      scale = hw / absDx;
    } else {
      // Intersects top or bottom side
      scale = hh / absDy;
    }

    return { x: cx + dx * scale, y: cy + dy * scale };
  }
}

// =============================================================================
// Layered Graph Layout Algorithm (Sugiyama-style)
// =============================================================================

function autoLayoutWorkflow() {
  const allNodes = state.workflow.nodes;
  const edges = state.workflow.edges;

  if (allNodes.length === 0) return;

  // Filter out input nodes - they're hidden from canvas, shown in sidebar
  const nodes = allNodes.filter(n => n.type !== 'input');

  if (nodes.length === 0) return;

  // Build adjacency lists
  const outgoing = {};  // nodeId -> [targetIds]
  const incoming = {};  // nodeId -> [sourceIds]

  nodes.forEach(n => {
    outgoing[n.id] = [];
    incoming[n.id] = [];
  });

  edges.forEach(e => {
    if (outgoing[e.from]) outgoing[e.from].push(e.to);
    if (incoming[e.to]) incoming[e.to].push(e.from);
  });

  // Step 1: Assign layers using BFS (topological order)
  const layers = {};  // nodeId -> layer number
  const layerNodes = [];  // layer index -> [nodeIds]

  // Find root nodes (no incoming edges, or start type)
  const roots = nodes.filter(n => incoming[n.id].length === 0 || n.type === 'start');

  // BFS to assign layers
  const queue = roots.map(n => ({ id: n.id, layer: 0 }));
  const visited = new Set();

  while (queue.length > 0) {
    const { id, layer } = queue.shift();

    if (visited.has(id)) {
      // Already visited - update layer if this path is longer
      if (layer > layers[id]) {
        layers[id] = layer;
      }
      continue;
    }

    visited.add(id);
    layers[id] = layer;

    // Add children to queue
    outgoing[id].forEach(childId => {
      queue.push({ id: childId, layer: layer + 1 });
    });
  }

  // Handle any unvisited nodes (disconnected)
  nodes.forEach(n => {
    if (!visited.has(n.id)) {
      layers[n.id] = 0;
    }
  });

  // Group nodes by layer
  const maxLayer = Math.max(...Object.values(layers), 0);
  for (let i = 0; i <= maxLayer; i++) {
    layerNodes[i] = [];
  }
  nodes.forEach(n => {
    layerNodes[layers[n.id]].push(n.id);
  });

  // Step 2: Order nodes within layers to minimize crossings (barycenter heuristic)
  // Do multiple passes - alternating down and up - for better results
  const numPasses = 4;

  for (let pass = 0; pass < numPasses; pass++) {
    if (pass % 2 === 0) {
      // Down pass: order based on parents
      for (let i = 1; i <= maxLayer; i++) {
        const layer = layerNodes[i];
        const barycenters = {};

        layer.forEach(nodeId => {
          const parents = incoming[nodeId];
          if (parents.length > 0) {
            const parentPositions = parents.map(pId => {
              const pLayer = layerNodes[layers[pId]];
              return pLayer.indexOf(pId);
            });
            barycenters[nodeId] = parentPositions.reduce((a, b) => a + b, 0) / parentPositions.length;
          } else {
            barycenters[nodeId] = layer.indexOf(nodeId);
          }
        });

        layer.sort((a, b) => barycenters[a] - barycenters[b]);
      }
    } else {
      // Up pass: order based on children
      for (let i = maxLayer - 1; i >= 0; i--) {
        const layer = layerNodes[i];
        const barycenters = {};

        layer.forEach(nodeId => {
          const children = outgoing[nodeId];
          if (children.length > 0) {
            const childPositions = children.map(cId => {
              const cLayer = layerNodes[layers[cId]];
              return cLayer ? cLayer.indexOf(cId) : 0;
            });
            barycenters[nodeId] = childPositions.reduce((a, b) => a + b, 0) / childPositions.length;
          } else {
            barycenters[nodeId] = layer.indexOf(nodeId);
          }
        });

        layer.sort((a, b) => barycenters[a] - barycenters[b]);
      }
    }
  }

  // Step 3: Assign X and Y positions
  const layerSpacing = 140;  // Vertical space between layers
  const nodeSpacing = 180;   // Horizontal space between nodes
  const startY = 60;
  const canvasWidth = 1000;

  nodes.forEach(n => {
    const layer = layers[n.id];
    const layerArray = layerNodes[layer];
    const indexInLayer = layerArray.indexOf(n.id);
    const layerWidth = layerArray.length * nodeSpacing;

    // Center the layer
    const startX = (canvasWidth - layerWidth) / 2 + nodeSpacing / 2;

    n.x = startX + indexInLayer * nodeSpacing;
    n.y = startY + layer * layerSpacing;
  });
}

// Pre-calculate edge routing to avoid overlaps
function calculateEdgeOffsets(edges) {
  const offsets = {};

  // Group edges by source node and port
  const bySourcePort = {};
  edges.forEach((edge, i) => {
    const key = `${edge.from}-${edge.fromPort || 'default'}`;
    if (!bySourcePort[key]) bySourcePort[key] = [];
    bySourcePort[key].push(i);
  });

  // Assign offsets to edges sharing the same source port
  Object.values(bySourcePort).forEach(indices => {
    if (indices.length > 1) {
      indices.forEach((idx, i) => {
        offsets[idx] = (i - (indices.length - 1) / 2) * 15;
      });
    }
  });

  // Also check for edges going to the same target
  const byTarget = {};
  edges.forEach((edge, i) => {
    const key = `${edge.to}-${edge.toPort || 'default'}`;
    if (!byTarget[key]) byTarget[key] = [];
    byTarget[key].push(i);
  });

  Object.values(byTarget).forEach(indices => {
    if (indices.length > 1) {
      indices.forEach((idx, i) => {
        // Add to existing offset or create new
        const existingOffset = offsets[idx] || 0;
        offsets[idx] = existingOffset + (i - (indices.length - 1) / 2) * 10;
      });
    }
  });

  return offsets;
}

function renderEdge(edge, index) {
  const fromNode = state.workflow.nodes.find(n => n.id === edge.from);
  const toNode = state.workflow.nodes.find(n => n.id === edge.to);
  if (!fromNode || !toNode) return;

  const fromSize = NODE_SIZES[fromNode.type] || NODE_SIZES.input;
  const toSize = NODE_SIZES[toNode.type] || NODE_SIZES.input;

  // Get port positions
  const fromPorts = getPortPositions(fromNode.type, fromSize);
  const toPorts = getPortPositions(toNode.type, toSize);

  let fromPoint, toPoint;

  // For decision nodes with Yes/No labels, use bottom-left/bottom-right ports
  if (fromNode.type === 'decision' && (edge.label === 'Yes' || edge.label === 'No')) {
    const portName = edge.label === 'Yes' ? 'bottom-left' : 'bottom-right';
    const fromPortData = fromPorts.find(p => p.name === portName);
    const toPortData = toPorts.find(p => p.name === 'top');
    if (fromPortData && toPortData) {
      fromPoint = { x: fromNode.x + fromPortData.x, y: fromNode.y + fromPortData.y };
      toPoint = { x: toNode.x + toPortData.x, y: toNode.y + toPortData.y };
      edge.fromPort = portName;
      edge.toPort = 'top';
    }
  }

  // Use stored ports if available, otherwise calculate best ports
  if (!fromPoint && edge.fromPort && edge.toPort) {
    const fromPortData = fromPorts.find(p => p.name === edge.fromPort);
    const toPortData = toPorts.find(p => p.name === edge.toPort);
    if (fromPortData && toPortData) {
      fromPoint = { x: fromNode.x + fromPortData.x, y: fromNode.y + fromPortData.y };
      toPoint = { x: toNode.x + toPortData.x, y: toNode.y + toPortData.y };
    }
  }

  // Fallback: calculate best ports based on relative positions
  if (!fromPoint || !toPoint) {
    const bestPorts = getBestPorts(fromNode, toNode);
    fromPoint = bestPorts.from;
    toPoint = bestPorts.to;
    // Store the calculated ports for consistency
    edge.fromPort = bestPorts.fromPort;
    edge.toPort = bestPorts.toPort;
  }

  // Create edge group for easier selection
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.classList.add('flow-edge');
  g.dataset.index = index;
  if (state.selectedEdge === index) {
    g.classList.add('selected');
  }

  // Always use straight lines - layout algorithm minimizes crossings
  const pathD = `M ${fromPoint.x} ${fromPoint.y} L ${toPoint.x} ${toPoint.y}`;

  // Invisible wider path for easier clicking
  const hitArea = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  hitArea.setAttribute('d', pathD);
  hitArea.setAttribute('stroke', 'transparent');
  hitArea.setAttribute('stroke-width', '12');
  hitArea.setAttribute('fill', 'none');
  hitArea.classList.add('edge-hit-area');
  g.appendChild(hitArea);

  // Visible curved path
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', pathD);
  path.setAttribute('stroke', state.selectedEdge === index ? 'var(--teal)' : '#1f2422');
  path.setAttribute('stroke-width', state.selectedEdge === index ? '3' : '2');
  path.setAttribute('fill', 'none');
  path.setAttribute('marker-end', 'url(#arrowhead)');
  g.appendChild(path);

  edgeLayer.appendChild(g);

  // Edge label - position at midpoint
  if (edge.label) {
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.textContent = edge.label;

    const midX = (fromPoint.x + toPoint.x) / 2;
    const midY = (fromPoint.y + toPoint.y) / 2;
    const edgeDx = toPoint.x - fromPoint.x;
    const edgeDy = toPoint.y - fromPoint.y;

    const isVertical = Math.abs(edgeDy) > Math.abs(edgeDx) * 1.5;

    if (isVertical) {
      text.setAttribute('x', midX + 10);
      text.setAttribute('y', midY + 4);
      text.setAttribute('text-anchor', 'start');
    } else {
      text.setAttribute('x', midX);
      text.setAttribute('y', midY - 8);
      text.setAttribute('text-anchor', 'middle');
    }

    text.setAttribute('font-size', '11');
    text.setAttribute('fill', '#6d6b64');
    edgeLayer.appendChild(text);
  }
}

// Calculate best ports for connecting two nodes based on their positions
function getBestPorts(fromNode, toNode) {
  const fromSize = NODE_SIZES[fromNode.type] || NODE_SIZES.input;
  const toSize = NODE_SIZES[toNode.type] || NODE_SIZES.input;

  const fromCenter = { x: fromNode.x + fromSize.w / 2, y: fromNode.y + fromSize.h / 2 };
  const toCenter = { x: toNode.x + toSize.w / 2, y: toNode.y + toSize.h / 2 };

  const dx = toCenter.x - fromCenter.x;
  const dy = toCenter.y - fromCenter.y;

  let fromPort, toPort;

  // Determine best ports based on direction
  if (Math.abs(dx) > Math.abs(dy)) {
    // Horizontal connection
    if (dx > 0) {
      fromPort = 'right';
      toPort = 'left';
    } else {
      fromPort = 'left';
      toPort = 'right';
    }
  } else {
    // Vertical connection
    if (dy > 0) {
      fromPort = 'bottom';
      toPort = 'top';
    } else {
      fromPort = 'top';
      toPort = 'bottom';
    }
  }

  const fromPorts = getPortPositions(fromNode.type, fromSize);
  const toPorts = getPortPositions(toNode.type, toSize);

  const fromPortData = fromPorts.find(p => p.name === fromPort);
  const toPortData = toPorts.find(p => p.name === toPort);

  return {
    from: { x: fromNode.x + fromPortData.x, y: fromNode.y + fromPortData.y },
    to: { x: toNode.x + toPortData.x, y: toNode.y + toPortData.y },
    fromPort,
    toPort,
  };
}

// =============================================================================
// Node Operations
// =============================================================================

function addNode(type, x, y) {
  const id = `${type}_${Date.now().toString(36)}`;
  const size = NODE_SIZES[type] || NODE_SIZES.input;

  // Default position if not specified - use center of current viewBox
  if (x === undefined) {
    x = state.viewBox.x + state.viewBox.w / 2 + (Math.random() - 0.5) * 100;
    y = state.viewBox.y + state.viewBox.h / 2 + (Math.random() - 0.5) * 100;
  }

  const node = {
    id,
    type,
    label: type.charAt(0).toUpperCase() + type.slice(1),
    x: x - size.w / 2,
    y: y - size.h / 2,
    // Type-specific defaults
    ...(type === 'input' && { inputType: 'float', range: { min: 0, max: 100 } }),
    ...(type === 'decision' && { condition: '' }),
    ...(type === 'output' && { value: '' }),
  };

  state.workflow.nodes.push(node);
  selectNode(id);
  renderCanvas();
}

function deleteNode(id) {
  state.workflow.nodes = state.workflow.nodes.filter(n => n.id !== id);
  state.workflow.edges = state.workflow.edges.filter(e => e.from !== id && e.to !== id);
  if (state.selectedNode === id) {
    selectNode(null);
  }
  renderCanvas();
}

// Add a subflow node (workflow as a block)
function addSubflowNode(workflowId, workflowData, x, y) {
  const id = `subflow_${Date.now().toString(36)}`;
  const size = NODE_SIZES.subflow;

  // Extract inputs and outputs from workflow blocks
  const blocks = workflowData.blocks || [];
  const inputs = blocks.filter(b => b.input_type || b.name).map(b => ({
    id: b.id,
    name: b.name || b.id,
    type: b.input_type || 'any',
  }));
  const outputs = blocks.filter(b => b.value !== undefined).map(b => ({
    id: b.id,
    value: b.value,
  }));

  const node = {
    id,
    type: 'subflow',
    label: workflowData.metadata?.name || workflowId,
    x: x - size.w / 2,
    y: y - size.h / 2,
    // Subflow-specific data
    subflowId: workflowId,
    subflowInputs: inputs,
    subflowOutputs: outputs,
  };

  state.workflow.nodes.push(node);
  selectNode(id);
  renderCanvas();
  saveCurrentWorkspace();
}

function selectNode(id) {
  state.selectedNode = id;
  state.selectedEdge = null;  // Deselect edge when selecting node
  renderCanvas();
}

// =============================================================================
// Canvas Interaction
// =============================================================================

// Convert client coordinates to SVG coordinates
function clientToSvg(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const { x, y, w, h } = state.viewBox;
  return {
    x: x + ((clientX - rect.left) / rect.width) * w,
    y: y + ((clientY - rect.top) / rect.height) * h,
  };
}

// Wheel event for zooming
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const svgCoords = clientToSvg(e.clientX, e.clientY);
  zoomCanvas(e.deltaY, svgCoords.x, svgCoords.y);
}, { passive: false });

canvas.addEventListener('pointerdown', (e) => {
  const portEl = e.target.closest('.connection-port');
  const nodeEl = e.target.closest('.flow-node');

  // If already drawing an edge, second click completes it
  if (state.edgeDrawing.active) {
    e.stopPropagation();
    const svgCoords = clientToSvg(e.clientX, e.clientY);
    const snapTarget = findSnapTarget(svgCoords.x, svgCoords.y, state.edgeDrawing.fromNode);

    // Remove temp line
    const tempLine = edgeLayer.querySelector('.temp-edge');
    if (tempLine) tempLine.remove();
    highlightSnapTarget(null);

    if (snapTarget) {
      // Create edge with port information
      const edgeExists = state.workflow.edges.some(
        edge => edge.from === state.edgeDrawing.fromNode && edge.to === snapTarget.nodeId
      );

      if (!edgeExists) {
        state.workflow.edges.push({
          from: state.edgeDrawing.fromNode,
          to: snapTarget.nodeId,
          fromPort: state.edgeDrawing.fromPort,
          toPort: snapTarget.port,
          label: '',
        });
        saveCurrentWorkspace();
      }
    }

    // Reset and re-render
    state.edgeDrawing = { active: false, fromNode: null, fromPort: null };
    canvas.classList.remove('edge-drawing');
    renderCanvas();
    return;
  }

  // Check if clicking on a connection port (start edge drawing)
  if (portEl && nodeEl) {
    e.stopPropagation();
    const nodeId = nodeEl.dataset.id;
    const portName = portEl.dataset.port;
    const node = state.workflow.nodes.find(n => n.id === nodeId);

    if (node) {
      const size = NODE_SIZES[node.type] || NODE_SIZES.input;
      const ports = getPortPositions(node.type, size);
      const port = ports.find(p => p.name === portName);

      if (port) {
        const startX = node.x + port.x;
        const startY = node.y + port.y;

        state.edgeDrawing = {
          active: true,
          fromNode: nodeId,
          fromPort: portName,
          startX: startX,
          startY: startY,
        };

        // Create temp line immediately (starts at port, ends at mouse)
        const svgCoords = clientToSvg(e.clientX, e.clientY);
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.classList.add('temp-edge');
        line.setAttribute('x1', startX);
        line.setAttribute('y1', startY);
        line.setAttribute('x2', svgCoords.x);
        line.setAttribute('y2', svgCoords.y);
        line.setAttribute('stroke', '#1f6e68');
        line.setAttribute('stroke-width', '2');
        line.setAttribute('stroke-dasharray', '5,5');
        edgeLayer.appendChild(line);

        // Visual cue: crosshair cursor
        canvas.classList.add('edge-drawing');
      }
    }
    return;
  }

  if (nodeEl) {
    const id = nodeEl.dataset.id;
    selectNode(id);

    // Start drag
    const node = state.workflow.nodes.find(n => n.id === id);
    if (node) {
      state.dragState = {
        nodeId: id,
        startX: e.clientX,
        startY: e.clientY,
        origX: node.x,
        origY: node.y,
      };
      canvas.setPointerCapture(e.pointerId);
    }
  } else {
    // Clicking on empty canvas - start potential pan (will deselect if no drag)
    state.isPanning = true;
    state.panStart = {
      x: e.clientX,
      y: e.clientY,
      vbX: state.viewBox.x,
      vbY: state.viewBox.y,
      didMove: false  // Track if we actually panned
    };
    canvas.setPointerCapture(e.pointerId);
  }
});

// Use mousemove for edge drawing (works without button held)
canvas.addEventListener('mousemove', (e) => {
  if (!state.edgeDrawing.active) return;

  const svgCoords = clientToSvg(e.clientX, e.clientY);

  // Check for snap target (nearby port)
  const snapTarget = findSnapTarget(svgCoords.x, svgCoords.y, state.edgeDrawing.fromNode);
  highlightSnapTarget(snapTarget);

  // Update temp line - snap to port if near one, otherwise follow mouse
  const tempLine = edgeLayer.querySelector('.temp-edge');
  if (tempLine) {
    if (snapTarget) {
      // Snap to the port position
      tempLine.setAttribute('x2', snapTarget.x);
      tempLine.setAttribute('y2', snapTarget.y);
    } else {
      // Follow mouse
      tempLine.setAttribute('x2', svgCoords.x);
      tempLine.setAttribute('y2', svgCoords.y);
    }
  }
});

canvas.addEventListener('pointermove', (e) => {
  // Handle panning
  if (state.isPanning && state.panStart) {
    const dx = e.clientX - state.panStart.x;
    const dy = e.clientY - state.panStart.y;

    // Only start panning if moved more than 5 pixels (to distinguish from click)
    if (!state.panStart.didMove && (Math.abs(dx) > 5 || Math.abs(dy) > 5)) {
      state.panStart.didMove = true;
      canvas.style.cursor = 'grabbing';
    }

    if (state.panStart.didMove) {
      const rect = canvas.getBoundingClientRect();
      const scaledDx = dx * (state.viewBox.w / rect.width);
      const scaledDy = dy * (state.viewBox.h / rect.height);

      state.viewBox.x = state.panStart.vbX - scaledDx;
      state.viewBox.y = state.panStart.vbY - scaledDy;
      updateViewBox();
    }
    return;
  }

  // Handle node drag (still requires button held)
  if (!state.dragState) return;

  const node = state.workflow.nodes.find(n => n.id === state.dragState.nodeId);
  if (!node) return;

  // Scale drag by viewBox ratio
  const rect = canvas.getBoundingClientRect();
  const scaleX = state.viewBox.w / rect.width;
  const scaleY = state.viewBox.h / rect.height;

  const dx = (e.clientX - state.dragState.startX) * scaleX;
  const dy = (e.clientY - state.dragState.startY) * scaleY;

  node.x = state.dragState.origX + dx;
  node.y = state.dragState.origY + dy;

  renderCanvas();
});

canvas.addEventListener('pointerup', (e) => {
  // End panning
  if (state.isPanning) {
    const didMove = state.panStart?.didMove;
    canvas.releasePointerCapture(e.pointerId);
    state.isPanning = false;
    state.panStart = null;
    canvas.style.cursor = '';

    if (didMove) {
      // Actually panned - save the new position
      saveCurrentWorkspace();
    } else {
      // Just a click - deselect
      selectNode(null);
    }
    return;
  }

  // Node drag complete
  if (state.dragState) {
    canvas.releasePointerCapture(e.pointerId);
    state.dragState = null;
    saveCurrentWorkspace();
  }
});

// Keyboard shortcuts for canvas
document.addEventListener('keydown', (e) => {
  // Escape cancels edge drawing
  if (e.key === 'Escape' && state.edgeDrawing.active) {
    const tempLine = edgeLayer.querySelector('.temp-edge');
    if (tempLine) tempLine.remove();
    highlightSnapTarget(null);
    state.edgeDrawing = { active: false, fromNode: null, fromPort: null };
    canvas.classList.remove('edge-drawing');
    return;
  }

  // Delete/Backspace deletes selected node or edge
  if ((e.key === 'Delete' || e.key === 'Backspace') && !e.target.matches('input, textarea')) {
    if (state.selectedEdge !== null) {
      state.workflow.edges.splice(state.selectedEdge, 1);
      state.selectedEdge = null;
      renderCanvas();
      saveCurrentWorkspace();
    } else if (state.selectedNode) {
      deleteNode(state.selectedNode);
      saveCurrentWorkspace();
    }
  }

  // Reset zoom with '0' key
  if (e.key === '0' && !e.target.matches('input, textarea')) {
    resetZoom();
  }

  // Zoom in/out with +/-
  if ((e.key === '=' || e.key === '+') && !e.target.matches('input, textarea')) {
    zoomCanvas(-100, state.viewBox.x + state.viewBox.w / 2, state.viewBox.y + state.viewBox.h / 2);
  }
  if (e.key === '-' && !e.target.matches('input, textarea')) {
    zoomCanvas(100, state.viewBox.x + state.viewBox.w / 2, state.viewBox.y + state.viewBox.h / 2);
  }
});

// Find the closest snap target (port on another node) near the given coordinates
function findSnapTarget(x, y, excludeNodeId) {
  const snapRadius = 30;
  let closest = null;
  let closestDist = Infinity;

  for (const node of state.workflow.nodes) {
    if (node.id === excludeNodeId) continue;

    const size = NODE_SIZES[node.type] || NODE_SIZES.input;
    const ports = getPortPositions(node.type, size);

    for (const port of ports) {
      const portX = node.x + port.x;
      const portY = node.y + port.y;
      const dist = Math.sqrt((x - portX) ** 2 + (y - portY) ** 2);

      if (dist < snapRadius && dist < closestDist) {
        closestDist = dist;
        closest = { nodeId: node.id, port: port.name, x: portX, y: portY };
      }
    }
  }
  return closest;
}

// Highlight the snap target port
function highlightSnapTarget(snapTarget) {
  // Remove existing highlights
  $$('.connection-port.snap-highlight').forEach(el => {
    el.classList.remove('snap-highlight');
  });

  if (snapTarget) {
    const nodeEl = nodeLayer.querySelector(`.flow-node[data-id="${snapTarget.nodeId}"]`);
    if (nodeEl) {
      const portEl = nodeEl.querySelector(`.connection-port[data-port="${snapTarget.port}"]`);
      if (portEl) {
        portEl.classList.add('snap-highlight');
      }
    }
  }
}

// =============================================================================
// Context Menus (Right-click on nodes/edges)
// =============================================================================

const nodeContextMenu = $('#nodeContextMenu');
const edgeContextMenu = $('#edgeContextMenu');
let contextMenuNodeId = null;
let contextMenuEdgeIndex = null;

// Helper to find parent element by class
function findParentByClass(el, className) {
  let current = el;
  while (current && current !== canvas) {
    if (current.classList && current.classList.contains(className)) {
      return current;
    }
    current = current.parentElement || current.parentNode;
  }
  return null;
}

function hideAllContextMenus() {
  nodeContextMenu.classList.remove('visible');
  edgeContextMenu.classList.remove('visible');
  contextMenuNodeId = null;
  contextMenuEdgeIndex = null;
}

function showNodeContextMenu(e, nodeId) {
  e.preventDefault();
  e.stopPropagation();
  hideAllContextMenus();
  contextMenuNodeId = nodeId;

  nodeContextMenu.style.left = `${e.clientX}px`;
  nodeContextMenu.style.top = `${e.clientY}px`;
  nodeContextMenu.classList.add('visible');
}

function showEdgeContextMenu(e, edgeIndex) {
  e.preventDefault();
  e.stopPropagation();
  hideAllContextMenus();
  contextMenuEdgeIndex = edgeIndex;

  edgeContextMenu.style.left = `${e.clientX}px`;
  edgeContextMenu.style.top = `${e.clientY}px`;
  edgeContextMenu.classList.add('visible');
}

// Right-click on canvas (works for SVG)
canvas.addEventListener('contextmenu', (e) => {
  const nodeEl = findParentByClass(e.target, 'flow-node');
  const edgeEl = findParentByClass(e.target, 'flow-edge');

  if (nodeEl) {
    showNodeContextMenu(e, nodeEl.dataset.id);
  } else if (edgeEl) {
    showEdgeContextMenu(e, parseInt(edgeEl.dataset.index));
  } else {
    hideAllContextMenus();
  }
});

// Ctrl+click for Mac trackpad users
canvas.addEventListener('click', (e) => {
  if (e.ctrlKey) {
    const nodeEl = findParentByClass(e.target, 'flow-node');
    const edgeEl = findParentByClass(e.target, 'flow-edge');

    if (nodeEl) {
      showNodeContextMenu(e, nodeEl.dataset.id);
    } else if (edgeEl) {
      showEdgeContextMenu(e, parseInt(edgeEl.dataset.index));
    }
  }
});

// Click on edge to select it
canvas.addEventListener('click', (e) => {
  if (e.ctrlKey) return; // Handled above

  const edgeEl = findParentByClass(e.target, 'flow-edge');
  if (edgeEl) {
    e.stopPropagation();
    state.selectedEdge = parseInt(edgeEl.dataset.index);
    state.selectedNode = null;
    renderCanvas();
    return;
  }

  // If clicking elsewhere (not on node), deselect edge
  const nodeEl = findParentByClass(e.target, 'flow-node');
  if (!nodeEl && state.selectedEdge !== null) {
    state.selectedEdge = null;
    renderCanvas();
  }
});

// Hide context menus when clicking elsewhere
document.addEventListener('click', (e) => {
  if (!nodeContextMenu.contains(e.target) && !edgeContextMenu.contains(e.target)) {
    hideAllContextMenus();
  }
});

// Handle node context menu actions
nodeContextMenu.addEventListener('click', (e) => {
  const item = e.target.closest('.context-menu-item');
  if (!item || contextMenuNodeId === null) return;

  const action = item.dataset.action;
  const node = state.workflow.nodes.find(n => n.id === contextMenuNodeId);

  if (action === 'delete' && node) {
    deleteNode(contextMenuNodeId);
    saveCurrentWorkspace();
  } else if (action === 'edit' && node) {
    editNodeViaPrompt(node);
  }

  hideAllContextMenus();
});

// Handle edge context menu actions
edgeContextMenu.addEventListener('click', (e) => {
  const item = e.target.closest('.context-menu-item');
  if (!item || contextMenuEdgeIndex === null) return;

  const action = item.dataset.action;
  const edge = state.workflow.edges[contextMenuEdgeIndex];

  if (!edge) {
    hideAllContextMenus();
    return;
  }

  if (action === 'delete') {
    state.workflow.edges.splice(contextMenuEdgeIndex, 1);
    state.selectedEdge = null;
    renderCanvas();
    saveCurrentWorkspace();
  } else if (action === 'flip') {
    // Swap from/to and ports
    const temp = edge.from;
    edge.from = edge.to;
    edge.to = temp;
    const tempPort = edge.fromPort;
    edge.fromPort = edge.toPort;
    edge.toPort = tempPort;
    renderCanvas();
    saveCurrentWorkspace();
  } else if (action === 'editLabel') {
    const newLabel = prompt('Edge label:', edge.label || '');
    if (newLabel !== null) {
      edge.label = newLabel;
      renderCanvas();
      saveCurrentWorkspace();
    }
  }

  hideAllContextMenus();
});

// Edit node via prompt
function editNodeViaPrompt(node) {
  const newLabel = prompt('Edit label:', node.label || '');
  if (newLabel !== null && newLabel !== node.label) {
    node.label = newLabel;
    renderCanvas();
    saveCurrentWorkspace();
  }
}

// Double-click to open subflow in new tab (or edit regular nodes)
canvas.addEventListener('dblclick', (e) => {
  const nodeEl = findParentByClass(e.target, 'flow-node');

  if (!nodeEl) return;

  const id = nodeEl.dataset.id;
  const node = state.workflow.nodes.find(n => n.id === id);

  if (node && node.type === 'subflow' && node.subflowId) {
    openSubflowInNewTab(node.subflowId, node.label);
  } else if (node) {
    // Double-click on regular node opens edit
    editNodeViaPrompt(node);
  }
});

// Open a subflow workflow in a new tab
async function openSubflowInNewTab(workflowId, workflowName) {
  // Save current workspace first
  saveCurrentWorkspace();

  // Check if this workflow is already open in a tab
  const existingWorkspace = state.workspaces.find(w => w.workflow.id === workflowId);
  if (existingWorkspace) {
    // Switch to existing tab
    loadWorkspace(existingWorkspace.id);
    return;
  }

  // Create new workspace and load the workflow
  const workspace = createWorkspace(workflowName || 'Subflow');
  state.activeWorkspaceId = workspace.id;

  // Load the workflow into the new workspace
  try {
    const res = await fetch(`${API}/workflows/${workflowId}`);
    if (res.ok) {
      const wf = await res.json();
      loadWorkflowToCanvas(wf);
    }
  } catch (err) {
    console.error('Failed to load subflow:', err);
    addAssistantMessage(`Error loading subflow: ${err.message}`);
  }
}

// =============================================================================
// Drag & Drop from Palette
// =============================================================================

$$('.palette-block').forEach(block => {
  block.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('blockType', block.dataset.type);
  });
});

$('#canvasContainer').addEventListener('dragover', (e) => {
  e.preventDefault();
});

$('#canvasContainer').addEventListener('drop', (e) => {
  e.preventDefault();

  // Don't allow drops on image workspaces
  if (state.isImageWorkspace) return;

  // Convert to SVG coordinates (accounting for pan/zoom)
  const svgCoords = clientToSvg(e.clientX, e.clientY);
  const svgX = svgCoords.x;
  const svgY = svgCoords.y;

  // Check if dropping a workflow as subflow
  const subflowId = e.dataTransfer.getData('subflowId');
  if (subflowId) {
    const subflowData = JSON.parse(e.dataTransfer.getData('subflowData') || '{}');
    addSubflowNode(subflowId, subflowData, svgX, svgY);
    return;
  }

  // Otherwise, dropping a palette block
  const type = e.dataTransfer.getData('blockType');
  if (type) {
    addNode(type, svgX, svgY);
  }
});

// Palette click to add
$$('.palette-block').forEach(block => {
  block.addEventListener('click', () => {
    // Don't allow adding blocks on image workspaces
    if (state.isImageWorkspace) return;
    addNode(block.dataset.type);
  });
});

// =============================================================================
// Workflow Browser
// =============================================================================

async function loadBrowserWorkflows() {
  try {
    const res = await fetch(`${API}/workflows`);
    const data = await res.json();
    state.browser.workflows = data.workflows || [];
    state.browser.filtered = [...state.browser.workflows];
    renderBrowserList();
  } catch (err) {
    console.error('Failed to load workflows:', err);
    browserList.innerHTML = '<p class="muted">Failed to load workflows</p>';
  }
}

function filterBrowserWorkflows(query) {
  const q = query.toLowerCase().trim();

  if (!q) {
    state.browser.filtered = [...state.browser.workflows];
    // Hide semantic status when search is cleared
    if (semanticStatus) {
      semanticStatus.style.display = 'none';
    }
  } else {
    state.browser.filtered = state.browser.workflows.filter(wf => {
      const name = (wf.metadata?.name || wf.id || '').toLowerCase();
      const desc = (wf.metadata?.description || '').toLowerCase();
      const domain = (wf.metadata?.domain || '').toLowerCase();
      const tags = (wf.metadata?.tags || []).join(' ').toLowerCase();
      return name.includes(q) || desc.includes(q) || domain.includes(q) || tags.includes(q);
    });
  }

  renderBrowserList();
}

function renderBrowserList() {
  browserList.innerHTML = '';

  if (state.browser.filtered.length === 0) {
    browserList.style.display = 'none';
    browserEmpty.style.display = 'block';
    return;
  }

  browserList.style.display = 'flex';
  browserEmpty.style.display = 'none';

  state.browser.filtered.forEach(wf => {
    const card = document.createElement('div');
    card.className = 'browser-card';
    card.dataset.id = wf.id;
    card.draggable = true;

    if (state.browser.selectedId === wf.id) {
      card.classList.add('selected');
    }

    const name = wf.metadata?.name || wf.id;
    const desc = wf.metadata?.description || '';
    const domain = wf.metadata?.domain || '';
    const score = wf.metadata?.validation_score || 0;

    card.innerHTML = `
      <div class="browser-card-name">${escapeHtml(name)}</div>
      ${desc ? `<div class="browser-card-desc">${escapeHtml(desc)}</div>` : ''}
      <div class="browser-card-meta">
        ${domain ? `<span class="browser-card-domain">${escapeHtml(domain)}</span>` : ''}
        ${score > 0 ? `<span class="browser-card-score">${score.toFixed(0)}%</span>` : ''}
      </div>
    `;

    // Click to load workflow
    card.addEventListener('click', () => selectBrowserWorkflow(wf));

    // Drag to create subflow block
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('subflowId', wf.id);
      e.dataTransfer.setData('subflowData', JSON.stringify(wf));
      e.dataTransfer.effectAllowed = 'copy';
    });

    browserList.appendChild(card);
  });
}

async function selectBrowserWorkflow(wf) {
  // Open workflow in a NEW tab (don't replace current canvas)
  saveCurrentWorkspace();

  // Check if this workflow is already open in a tab
  const existingWorkspace = state.workspaces.find(w => w.workflow.id === wf.id);
  if (existingWorkspace) {
    // Switch to existing tab
    loadWorkspace(existingWorkspace.id);
    state.browser.selectedId = wf.id;
    renderBrowserList();
    return;
  }

  // Create new tab and load workflow
  const workspace = createWorkspace(wf.metadata?.name || wf.id);
  state.activeWorkspaceId = workspace.id;
  state.browser.selectedId = wf.id;

  await loadWorkflowById(wf.id);
  renderBrowserList();
}

// Browser filter input
browserFilter.addEventListener('input', (e) => {
  filterBrowserWorkflows(e.target.value);
});

// Semantic search trigger (appears when no regex matches)
// Use event delegation since element may not exist initially
document.addEventListener('click', (e) => {
  const trigger = e.target.closest('.semantic-search-trigger');
  if (trigger) {
    console.log('Semantic search button clicked');
    e.preventDefault();
    e.stopPropagation();
    runSemanticSearch();
  }
}, true); // Use capture phase to ensure we catch it first

// Run semantic search using the API
async function runSemanticSearch() {
  const query = browserFilter.value.trim();
  if (!query) return;

  console.log('Running semantic search for:', query);

  // Show loading state
  if (semanticStatus) {
    semanticStatus.style.display = 'block';
    semanticStatus.innerHTML = `
      <div class="semantic-thinking">
        <div class="spinner-small"></div>
        <span>Searching for "${escapeHtml(query)}"...</span>
      </div>
    `;
  }

  // Hide both lists during search
  browserList.style.display = 'none';
  browserEmpty.style.display = 'none';

  try {
    const res = await fetch(`${API}/search?q=${encodeURIComponent(query)}`);
    const results = await res.json();

    // Extract workflows array from API response
    const workflows = results.workflows || [];

    console.log('Semantic search results:', workflows.length);

    // Update status with results count
    if (semanticStatus) {
      if (workflows.length > 0) {
        semanticStatus.innerHTML = `
          <div class="semantic-thinking">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <span>Found ${workflows.length} result${workflows.length !== 1 ? 's' : ''}</span>
          </div>
          <div class="semantic-query">Query: "${escapeHtml(query)}"</div>
        `;
      } else {
        semanticStatus.innerHTML = `
          <div class="semantic-thinking">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <span>No results found</span>
          </div>
          <div class="semantic-query">Query: "${escapeHtml(query)}"</div>
        `;
      }
    }

    // Update the filtered list with search results
    state.browser.filtered = workflows;
    renderBrowserList();

    // Auto-hide status after a few seconds if we have results
    if (workflows.length > 0) {
      setTimeout(() => {
        if (semanticStatus) semanticStatus.style.display = 'none';
      }, 3000);
    }

  } catch (err) {
    console.error('Semantic search failed:', err);
    if (semanticStatus) {
      semanticStatus.innerHTML = `
        <div class="semantic-thinking">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--rose)" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>Search failed: ${err.message}</span>
        </div>
      `;
    }
    // Show empty state on error
    browserEmpty.style.display = 'block';
  }
}

// =============================================================================
// Sidebar Tabs & Inputs Panel
// =============================================================================

// Switch sidebar tab
function switchSidebarTab(tabName) {
  // Update tab buttons
  sidebarTabs.forEach(tab => {
    if (tab.dataset.tab === tabName) {
      tab.classList.add('active');
    } else {
      tab.classList.remove('active');
    }
  });

  // Update panels
  if (libraryPanel) {
    libraryPanel.classList.toggle('hidden', tabName !== 'library');
  }
  if (inputsPanel) {
    inputsPanel.classList.toggle('hidden', tabName !== 'inputs');
  }
}

// Render inputs panel based on current workflow
function renderInputsPanel() {
  if (!inputsList || !inputsEmpty) return;

  // Get input nodes from current workflow
  const inputNodes = state.workflow.nodes.filter(n => n.type === 'input');

  inputsList.innerHTML = '';

  if (inputNodes.length === 0) {
    inputsEmpty.classList.remove('hidden');
    inputsList.style.display = 'none';
    return;
  }

  inputsEmpty.classList.add('hidden');
  inputsList.style.display = 'flex';

  inputNodes.forEach(node => {
    const card = document.createElement('div');
    card.className = 'input-card';
    card.dataset.id = node.id;

    const name = node.label || node.name || 'Unnamed input';
    const dataType = node.dataType || node.type || 'any';
    const desc = node.description || '';
    const range = node.range || (node.min !== undefined && node.max !== undefined ? { min: node.min, max: node.max } : null);

    let rangeHtml = '';
    if (range && (range.min !== undefined || range.max !== undefined)) {
      rangeHtml = `<span class="input-card-range">Range: ${range.min ?? '...'} - ${range.max ?? '...'}</span>`;
    }

    card.innerHTML = `
      <div class="input-card-name">${escapeHtml(name)}</div>
      <div class="input-card-type">${escapeHtml(dataType)}</div>
      ${desc ? `<div class="input-card-desc">${escapeHtml(desc)}</div>` : ''}
      ${rangeHtml}
    `;

    inputsList.appendChild(card);
  });
}

// Add sidebar tab event listeners
sidebarTabs.forEach(tab => {
  tab.addEventListener('click', () => {
    switchSidebarTab(tab.dataset.tab);
  });
});

// =============================================================================
// Chat
// =============================================================================

function addUserMessage(text) {
  const msg = document.createElement('div');
  msg.className = 'message user';
  msg.innerHTML = `<div class="message-content"><p>${escapeHtml(text)}</p></div>`;
  chatThread.appendChild(msg);
  chatThread.scrollTop = chatThread.scrollHeight;
}

function addAssistantMessage(text, choices = []) {
  const msg = document.createElement('div');
  msg.className = 'message assistant';

  // Render Markdown (using marked.js)
  const renderedText = typeof marked !== 'undefined' ? marked.parse(text) : escapeHtml(text);

  let html = `<div class="message-content">${renderedText}`;
  if (choices.length > 0) {
    html += `<div class="chat-choices">`;
    choices.forEach(choice => {
      html += `<button class="chat-choice" data-choice="${escapeHtml(choice)}">${escapeHtml(choice)}</button>`;
    });
    html += `</div>`;
  }
  html += `</div>`;

  msg.innerHTML = html;
  chatThread.appendChild(msg);
  chatThread.scrollTop = chatThread.scrollHeight;

  // Wire up choice buttons
  msg.querySelectorAll('.chat-choice').forEach(btn => {
    btn.addEventListener('click', () => {
      handleChatChoice(btn.dataset.choice);
    });
  });
}

function handleChatChoice(choice) {
  addUserMessage(choice);
  processMessage(choice);
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  addUserMessage(text);

  // Automatically include image if present on canvas
  const includeImage = !!state.canvasImage;
  await processMessage(text, includeImage);
}

async function processMessage(text, includeImage = false) {
  // Show typing indicator
  const typingMsg = document.createElement('div');
  typingMsg.className = 'message assistant typing';
  typingMsg.innerHTML = '<div class="message-content"><div class="typing-indicator"><span></span><span></span><span></span></div></div>';
  chatThread.appendChild(typingMsg);
  chatThread.scrollTop = chatThread.scrollHeight;

  try {
    // Build request body
    const requestBody = {
      message: text,
      conversation_id: state.conversationId,
    };

    // Include image if requested and available
    if (includeImage && state.canvasImage) {
      requestBody.image = state.canvasImage.dataUrl;
    }

    // Call the orchestrator API
    const res = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    // Remove typing indicator
    typingMsg.remove();

    const data = await res.json();
    state.conversationId = data.conversation_id;

    // Process any tool calls that affect the canvas
    if (data.tool_calls && data.tool_calls.length > 0) {
      for (const tc of data.tool_calls) {
        handleToolCall(tc);
      }
    }

    // Show the response
    addAssistantMessage(data.response);
  } catch (err) {
    typingMsg.remove();
    addAssistantMessage(`I encountered an error: ${err.message}`);
  }
}

// Handle tool call results from the orchestrator
function handleToolCall(toolCall) {
  const { tool, result } = toolCall;
  console.log('handleToolCall:', tool, result);

  if (tool === 'create_workflow' && result?.workflow_id) {
    // Refresh browser to show new workflow
    loadBrowserWorkflows();

    // If nodes and edges are provided, render the workflow in a new tab
    if (result.nodes && result.edges) {
      openCreatedWorkflowInNewTab(result);
    }
  } else if (tool === 'search_library' && result?.workflows?.length > 0) {
    // Show search results as horizontal carousel in chat
    addSearchResultsCarousel(result.workflows);
  } else if (tool === 'execute_workflow' && result) {
    // Show execution result
    console.log('Execution result:', result);
  } else if (tool === 'start_validation' && result?.session_id) {
    // Open validation modal with this session
    state.validation.sessionId = result.session_id;
    state.validation.progress = result.progress || { current: 0, total: 10 };
    $('#validationModal').classList.add('active');
    $('#validationTitle').textContent = state.workflow.name || 'Workflow';
    renderValidationCase(result);
  }
}

// Add search results as horizontal carousel in chat
function addSearchResultsCarousel(workflows) {
  const container = document.createElement('div');
  container.className = 'message assistant';

  let carouselHtml = '<div class="message-content"><div class="chat-carousel">';

  workflows.forEach(wf => {
    const name = wf.name || wf.id;
    const desc = wf.description || '';
    const domain = wf.domain || '';
    const score = wf.validation_score || 0;

    carouselHtml += `
      <div class="chat-carousel-card" data-workflow-id="${escapeHtml(wf.id)}">
        <h4>${escapeHtml(name)}</h4>
        <p>${escapeHtml(desc)}</p>
        <div class="card-meta">
          ${domain ? `<span class="domain-tag">${escapeHtml(domain)}</span>` : ''}
          ${score > 0 ? `<span class="score-tag">${score.toFixed(0)}%</span>` : ''}
        </div>
      </div>
    `;
  });

  carouselHtml += '</div>';

  if (workflows.length > 3) {
    carouselHtml += '<span class="chat-carousel-hint">Scroll to see more →</span>';
  }

  carouselHtml += '</div>';
  container.innerHTML = carouselHtml;

  // Add click handlers to carousel cards
  container.querySelectorAll('.chat-carousel-card').forEach(card => {
    card.addEventListener('click', () => {
      const wfId = card.dataset.workflowId;
      const wf = workflows.find(w => w.id === wfId);
      if (wf) {
        selectChatCarouselCard(card, wf);
      }
    });
  });

  chatThread.appendChild(container);
  chatThread.scrollTop = chatThread.scrollHeight;
}

async function selectChatCarouselCard(card, wf) {
  // Toggle selection
  const wasSelected = card.classList.contains('selected');

  // Deselect all cards in this carousel
  card.closest('.chat-carousel').querySelectorAll('.chat-carousel-card').forEach(c => {
    c.classList.remove('selected');
  });

  if (wasSelected) {
    // Already selected - do nothing
    return;
  }

  // Select - open in NEW tab
  card.classList.add('selected');
  saveCurrentWorkspace();

  // Check if this workflow is already open in a tab
  const existingWorkspace = state.workspaces.find(w => w.workflow.id === wf.id);
  if (existingWorkspace) {
    loadWorkspace(existingWorkspace.id);
    state.browser.selectedId = wf.id;
    renderBrowserList();
    return;
  }

  // Create new tab and load workflow
  const workspace = createWorkspace(wf.name || wf.id);
  state.activeWorkspaceId = workspace.id;
  state.browser.selectedId = wf.id;

  await loadWorkflowById(wf.id);
  renderBrowserList();
}

// =============================================================================
// Workflow Loading
// =============================================================================

// Open a newly created workflow in a new tab (from image analysis)
function openCreatedWorkflowInNewTab(workflowData) {
  // Save current workspace first
  saveCurrentWorkspace();

  // Create a new workspace for the created workflow
  const workspace = createWorkspace(workflowData.name || 'New Workflow');
  workspace.workflow = {
    id: workflowData.workflow_id,
    name: workflowData.name || 'New Workflow',
    nodes: workflowData.nodes || [],
    edges: workflowData.edges || [],
  };
  workspace.isImageWorkspace = false;  // This is a proper workflow, not image
  workspace.canvasImage = null;  // No image in this workspace
  workspace.viewBox = { x: 0, y: 0, w: 1200, h: 800 };  // Reset zoom

  // Switch to the new workspace
  loadWorkspace(workspace.id);

  // Apply proper layout algorithm
  autoLayoutWorkflow();
  saveCurrentWorkspace();
  renderCanvas();

  // Show success message (the orchestrator also sends a message, so this is supplementary)
  console.log('Created workflow opened in new tab:', workflowData.name);
}

async function loadWorkflowById(id) {
  try {
    const res = await fetch(`${API}/workflows/${id}`);
    if (res.ok) {
      const wf = await res.json();
      loadWorkflowToCanvas(wf);
    }
  } catch (err) {
    console.error('Failed to load workflow:', err);
  }
}

// Load a workflow from the API into the canvas
function loadWorkflowToCanvas(wf) {
  state.workflow.id = wf.id;
  state.workflow.name = wf.metadata?.name || wf.id;
  $('#workflowName').value = state.workflow.name;

  // Categorize blocks
  const blocksByType = { input: [], decision: [], output: [] };
  (wf.blocks || []).forEach(block => {
    const type = block.input_type ? 'input' : block.condition ? 'decision' : 'output';
    blocksByType[type].push(block);
  });

  const nodes = [];
  const inputIds = new Set(blocksByType.input.map(b => b.id));

  // 1. Start node (visual entry point)
  nodes.push({
    id: 'start',
    type: 'start',
    label: 'Start',
    x: 0, y: 0,  // Will be positioned by autoLayoutWorkflow
  });

  // 2. Input nodes (hidden from canvas, shown in sidebar)
  blocksByType.input.forEach(block => {
    nodes.push({
      id: block.id,
      type: 'input',
      label: block.name || block.id,
      x: 0, y: 0,
      dataType: block.input_type?.toLowerCase() || 'float',
      range: block.range,
      description: block.description || '',
    });
  });

  // 3. Decision nodes
  blocksByType.decision.forEach(block => {
    nodes.push({
      id: block.id,
      type: 'decision',
      label: block.description || block.condition || block.id,
      x: 0, y: 0,
      condition: block.condition,
    });
  });

  // Build edges first to know which outputs need duplication
  const inputTargets = new Set();
  const outputEdges = [];  // edges going to output nodes
  const otherEdges = [];   // edges between non-output nodes

  (wf.connections || []).forEach(conn => {
    if (inputIds.has(conn.from_block)) {
      inputTargets.add(conn.to_block);
      return;
    }

    const port = (conn.from_port || '').toLowerCase();
    const edge = {
      from: conn.from_block,
      to: conn.to_block,
      label: port === 'true' ? 'Yes' : port === 'false' ? 'No' : '',
    };

    // Check if target is an output
    const isOutputTarget = blocksByType.output.some(b => b.id === conn.to_block);
    if (isOutputTarget) {
      outputEdges.push(edge);
    } else {
      otherEdges.push(edge);
    }
  });

  // 4. Output nodes - duplicate if multiple edges point to same output
  const outputUsageCount = {};
  outputEdges.forEach(e => {
    outputUsageCount[e.to] = (outputUsageCount[e.to] || 0) + 1;
  });

  // Create output nodes, duplicating as needed
  const outputIdMapping = {};  // original edge -> new node id
  blocksByType.output.forEach(block => {
    const usageCount = outputUsageCount[block.id] || 1;

    if (usageCount <= 1) {
      // Single use - just create the node
      nodes.push({
        id: block.id,
        type: 'output',
        label: block.value || block.id,
        x: 0, y: 0,
        value: block.value,
      });
    } else {
      // Multiple uses - create duplicates
      let dupIndex = 0;
      outputEdges.forEach((e, edgeIdx) => {
        if (e.to === block.id) {
          const dupId = `${block.id}_${dupIndex}`;
          nodes.push({
            id: dupId,
            type: 'output',
            label: block.value || block.id,
            x: 0, y: 0,
            value: block.value,
          });
          outputIdMapping[edgeIdx] = dupId;
          dupIndex++;
        }
      });
    }
  });

  // Build final edges
  const edges = [];

  // Start connects to whatever inputs connected to
  inputTargets.forEach(targetId => {
    edges.push({ from: 'start', to: targetId });
  });

  // Add non-output edges
  otherEdges.forEach(e => edges.push(e));

  // Add output edges (with remapped IDs for duplicates)
  outputEdges.forEach((e, idx) => {
    edges.push({
      from: e.from,
      to: outputIdMapping[idx] || e.to,
      label: e.label,
    });
  });

  state.workflow.nodes = nodes;
  state.workflow.edges = edges;

  // Let the layout algorithm position everything properly
  autoLayoutWorkflow();
  renderCanvas();
  saveCurrentWorkspace();
  renderTabs();
}

$('#sendBtn').addEventListener('click', sendMessage);

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// =============================================================================
// Voice Input (Web Speech API + Web Audio API for visualization)
// =============================================================================

const voiceBtn = $('#voiceBtn');
const voiceWaves = voiceBtn ? voiceBtn.querySelector('.voice-waves') : null;
const waveBars = voiceWaves ? voiceWaves.querySelectorAll('span') : [];

let recognition = null;
let isRecording = false;
let audioContext = null;
let analyser = null;
let microphone = null;
let animationId = null;

// Check for Web Speech API support
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-GB';

  let finalTranscript = '';
  let interimTranscript = '';

  recognition.onresult = (event) => {
    interimTranscript = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += transcript + ' ';
      } else {
        interimTranscript += transcript;
      }
    }
    // Show live transcription in textarea
    chatInput.value = finalTranscript + interimTranscript;
  };

  recognition.onend = () => {
    if (isRecording) {
      // Stopped unexpectedly, restart
      recognition.start();
    } else {
      // User stopped, finalize
      voiceBtn.classList.remove('recording');
      chatInput.value = finalTranscript.trim();
      finalTranscript = '';
      interimTranscript = '';
    }
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    stopRecording();
    if (event.error === 'not-allowed') {
      addAssistantMessage('Microphone access denied. Please allow microphone access to use voice input.');
    }
  };

  voiceBtn.addEventListener('click', () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });
} else {
  // No support - hide the button
  voiceBtn.style.display = 'none';
}

async function startRecording() {
  if (!recognition) return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.4;
    analyser.minDecibels = -90;
    analyser.maxDecibels = -10;

    microphone = audioContext.createMediaStreamSource(stream);
    microphone.connect(analyser);

    isRecording = true;
    voiceBtn.classList.add('recording');
    chatInput.value = '';
    chatInput.placeholder = 'Listening...';
    recognition.start();
    visualizeAudio();

  } catch (err) {
    console.error('Failed to access microphone:', err);
    addAssistantMessage('Could not access microphone. Please check permissions.');
  }
}

function visualizeAudio() {
  if (!analyser || !isRecording) return;

  const dataArray = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(dataArray);

  // Focus on speech frequencies (first ~25 bins)
  const speechBins = dataArray.slice(0, 25);

  waveBars.forEach((bar, i) => {
    // Sample different frequency bins for each bar
    const binIndex = Math.floor((i / waveBars.length) * speechBins.length);
    const value = speechBins[binIndex] || 0;

    // Scale for good visual response
    const normalized = value / 255;
    const boosted = Math.pow(normalized, 0.7) * 1.1;  // Slight curve + subtle boost
    const clamped = Math.min(1, boosted);

    // Map to height (min 3px, max 20px)
    const height = 3 + (clamped * 17);
    bar.style.height = `${height}px`;
  });

  animationId = requestAnimationFrame(visualizeAudio);
}

function stopRecording() {
  if (!recognition) return;
  isRecording = false;
  recognition.stop();
  chatInput.placeholder = 'Describe your workflow or ask a question...';

  // Stop visualization
  if (animationId) {
    cancelAnimationFrame(animationId);
    animationId = null;
  }

  // Clean up audio
  if (audioContext) {
    audioContext.close();
    audioContext = null;
    analyser = null;
    microphone = null;
  }

  // Reset bar heights
  waveBars.forEach(bar => {
    bar.style.height = '3px';
  });
}

// =============================================================================
// Canvas Operations
// =============================================================================

function clearCanvas() {
  state.workflow.nodes = [];
  state.workflow.edges = [];
  state.workflow.id = null;
  state.workflow.name = 'Untitled workflow';
  state.selectedNode = null;
  state.browser.selectedId = null;
  $('#workflowName').value = '';
  renderCanvas();
  renderBrowserList();
  saveCurrentWorkspace();
  renderTabs();
}

// =============================================================================
// Image Upload
// =============================================================================

imageUpload.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  // Read the file as data URL
  const reader = new FileReader();
  reader.onload = (event) => {
    const img = new Image();
    img.onload = () => {
      // Scale to fit in canvas (max 800x600 for better visibility)
      const maxW = 800;
      const maxH = 600;
      let w = img.width;
      let h = img.height;

      if (w > maxW) {
        h = h * (maxW / w);
        w = maxW;
      }
      if (h > maxH) {
        w = w * (maxH / h);
        h = maxH;
      }

      // Save current workspace first
      saveCurrentWorkspace();

      // Create a new workspace for the image
      const imageName = file.name.replace(/\.[^/.]+$/, '') || 'Uploaded Image';
      const workspace = createWorkspace(imageName);
      workspace.isImageWorkspace = true;  // Mark as image-only workspace
      workspace.canvasImage = {
        dataUrl: event.target.result,
        x: (1200 - w) / 2,
        y: (800 - h) / 2,
        width: w,
        height: h,
      };

      // Switch to the new workspace
      loadWorkspace(workspace.id);
    };
    img.src = event.target.result;
  };
  reader.readAsDataURL(file);

  // Reset file input so same file can be selected again
  e.target.value = '';
});

// Sync workflow name with tab
$('#workflowName').addEventListener('input', (e) => {
  state.workflow.name = e.target.value || 'Untitled workflow';
  saveCurrentWorkspace();
  renderTabs();
});

// =============================================================================
// Library Modal
// =============================================================================

$('#browseLibrary').addEventListener('click', openLibrary);
$('#closeLibrary').addEventListener('click', closeLibrary);
$('#libraryModal .modal-backdrop').addEventListener('click', closeLibrary);

async function openLibrary() {
  $('#libraryModal').classList.add('active');
  await loadLibrary();
}

function closeLibrary() {
  $('#libraryModal').classList.remove('active');
}

async function loadLibrary() {
  const grid = $('#libraryGrid');
  grid.innerHTML = '<div class="loading"><div class="spinner"></div>Loading...</div>';

  try {
    const res = await fetch(`${API}/workflows`);
    const data = await res.json();

    if (!data.workflows?.length) {
      grid.innerHTML = '<p class="muted">No workflows in library</p>';
      return;
    }

    grid.innerHTML = data.workflows.map(wf => `
      <div class="library-item" data-id="${wf.id}">
        <h4>${escapeHtml(wf.metadata?.name || wf.id)}</h4>
        <p>${escapeHtml(wf.metadata?.description || 'No description')}</p>
        <div class="library-item-meta">
          <span class="library-tag">${escapeHtml(wf.metadata?.domain || 'general')}</span>
          ${wf.metadata?.validation_score ? `<span class="library-score">${wf.metadata.validation_score.toFixed(0)}% validated</span>` : ''}
        </div>
      </div>
    `).join('');

    // Wire up click handlers
    grid.querySelectorAll('.library-item').forEach(item => {
      item.addEventListener('click', () => loadFromLibrary(item.dataset.id));
    });
  } catch (err) {
    grid.innerHTML = `<p class="muted">Error loading library: ${err.message}</p>`;
  }
}

async function loadFromLibrary(id) {
  try {
    const res = await fetch(`${API}/workflows/${id}`);
    const wf = await res.json();

    // Convert to canvas format
    state.workflow.id = wf.id;
    state.workflow.name = wf.metadata?.name || wf.id;
    $('#workflowName').value = state.workflow.name;

    // Map blocks to nodes (with auto-layout if no positions)
    state.workflow.nodes = (wf.blocks || []).map((block, i) => ({
      id: block.id,
      type: block.id?.includes('input') || block.name ? 'input' :
            block.condition ? 'decision' :
            block.value !== undefined ? 'output' : 'input',
      label: block.name || block.value || block.id,
      x: 100 + (i % 3) * 200,
      y: 100 + Math.floor(i / 3) * 120,
      ...(block.input_type && { inputType: block.input_type.toLowerCase() }),
      ...(block.range && { range: block.range }),
      ...(block.condition && { condition: block.condition }),
      ...(block.value !== undefined && { value: block.value }),
    }));

    state.workflow.edges = (wf.connections || []).map(conn => ({
      from: conn.from_block,
      to: conn.to_block,
      label: conn.from_port === 'TRUE' ? 'Yes' : conn.from_port === 'FALSE' ? 'No' : '',
    }));

    closeLibrary();
    renderCanvas();
    saveCurrentWorkspace();
    renderTabs();
  } catch (err) {
    console.error('Error loading workflow:', err);
  }
}

// =============================================================================
// Validation Modal
// =============================================================================

$('#closeValidation').addEventListener('click', closeValidation);
$('#validationModal .modal-backdrop').addEventListener('click', closeValidation);

async function openValidation() {
  if (state.workflow.nodes.length === 0) return;

  $('#validationModal').classList.add('active');
  $('#validationTitle').textContent = state.workflow.name || 'Workflow';

  // For demo, we'll use the library workflow if it exists, otherwise show placeholder
  if (state.workflow.id) {
    await startValidationSession(state.workflow.id);
  } else {
    $('#validationCase').innerHTML = `
      <p class="muted">Save this workflow to the library first to enable validation.</p>
      <button class="primary" onclick="closeValidation()">Close</button>
    `;
  }
}

function closeValidation() {
  $('#validationModal').classList.remove('active');
}

async function startValidationSession(workflowId) {
  const caseDiv = $('#validationCase');
  caseDiv.innerHTML = '<div class="loading"><div class="spinner"></div>Starting session...</div>';

  try {
    const res = await fetch(`${API}/validation/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_id: workflowId, case_count: 10 }),
    });

    const data = await res.json();
    state.validation.sessionId = data.session_id;
    state.validation.progress = data.progress || { current: 0, total: 10 };

    renderValidationCase(data);
  } catch (err) {
    caseDiv.innerHTML = `<p class="muted">Error: ${err.message}</p>`;
  }
}

function renderValidationCase(data) {
  const caseDiv = $('#validationCase');
  const caseData = data.current_case;

  $('#validationProgress').textContent = `${data.progress?.current || 0} / ${data.progress?.total || 0}`;

  if (!caseData) {
    // Complete
    const score = data.score?.agreement_rate || 0;
    caseDiv.innerHTML = `
      <div class="validation-complete">
        <div class="validation-score-display">${(score * 100).toFixed(0)}%</div>
        <p class="validation-score-label">Agreement Rate</p>
        <p class="muted">${data.score?.total || 0} cases reviewed</p>
        <button class="primary" onclick="closeValidation()" style="margin-top: 20px;">Done</button>
      </div>
    `;
    return;
  }

  const percent = data.progress?.total > 0 ? (data.progress.current / data.progress.total * 100) : 0;

  caseDiv.innerHTML = `
    <div class="progress-bar">
      <div class="progress-fill" style="width: ${percent}%"></div>
    </div>
    <div class="case-inputs">
      ${Object.entries(caseData.inputs || {}).map(([k, v]) => `
        <div class="case-input-row">
          <span class="case-input-label">${escapeHtml(k)}</span>
          <span class="case-input-value">${escapeHtml(String(v))}</span>
        </div>
      `).join('')}
    </div>
    <div class="case-output">
      <p class="case-output-label">WORKFLOW OUTPUT</p>
      <div class="case-output-value">${escapeHtml(caseData.expected_output || 'Unknown')}</div>
    </div>
    <p class="validation-question">Is this output correct?</p>
    <div class="validation-buttons">
      <button class="primary btn-agree" onclick="submitValidation('${escapeHtml(caseData.expected_output)}')">Correct</button>
      <button class="primary btn-disagree" onclick="submitValidation('DISAGREE')">Incorrect</button>
    </div>
  `;
}

async function submitValidation(answer) {
  const caseDiv = $('#validationCase');
  caseDiv.innerHTML = '<div class="loading"><div class="spinner"></div>Submitting...</div>';

  try {
    const res = await fetch(`${API}/validation/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.validation.sessionId,
        answer: answer,
      }),
    });

    const data = await res.json();
    renderValidationCase(data);
  } catch (err) {
    caseDiv.innerHTML = `<p class="muted">Error: ${err.message}</p>`;
  }
}

// Make submitValidation global for onclick
window.submitValidation = submitValidation;
window.closeValidation = closeValidation;

// =============================================================================
// Utilities
// =============================================================================

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

// =============================================================================
// Chat Dock Resize
// =============================================================================

const chatDock = $('#chatDock');
const chatResizeHandle = $('#chatResizeHandle');

if (chatResizeHandle && chatDock) {
  let isResizing = false;
  let startY = 0;
  let startHeight = 0;

  chatResizeHandle.addEventListener('mousedown', (e) => {
    isResizing = true;
    startY = e.clientY;
    startHeight = chatDock.offsetHeight;
    chatResizeHandle.classList.add('dragging');
    document.body.style.cursor = 'ns-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;

    // Dragging up increases height, dragging down decreases
    const delta = startY - e.clientY;
    const newHeight = Math.max(80, Math.min(window.innerHeight * 0.8, startHeight + delta));
    chatDock.style.height = `${newHeight}px`;

    // Keep chat scrolled to bottom (most recent messages)
    chatThread.scrollTop = chatThread.scrollHeight;
  });

  document.addEventListener('mouseup', () => {
    if (isResizing) {
      isResizing = false;
      chatResizeHandle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
  });
}

// =============================================================================
// Auto-Arrange Button
// =============================================================================

const autoArrangeBtn = $('#autoArrangeBtn');
if (autoArrangeBtn) {
  autoArrangeBtn.addEventListener('click', () => {
    if (state.workflow.nodes.length > 0) {
      autoLayoutWorkflow();
      saveCurrentWorkspace();
      renderCanvas();
    }
  });
}

// =============================================================================
// Zoom Controls
// =============================================================================

const zoomInBtn = $('#zoomIn');
const zoomOutBtn = $('#zoomOut');
const zoomResetBtn = $('#zoomReset');

if (zoomInBtn) {
  zoomInBtn.addEventListener('click', () => {
    zoomCanvas(-100, state.viewBox.x + state.viewBox.w / 2, state.viewBox.y + state.viewBox.h / 2);
  });
}

if (zoomOutBtn) {
  zoomOutBtn.addEventListener('click', () => {
    zoomCanvas(100, state.viewBox.x + state.viewBox.w / 2, state.viewBox.y + state.viewBox.h / 2);
  });
}

if (zoomResetBtn) {
  zoomResetBtn.addEventListener('click', resetZoom);
}

// =============================================================================
// WebSocket Connection
// =============================================================================

let socket = null;
let sessionId = null;
let typingIndicator = null;

function initWebSocket() {
  sessionId = 'session_' + Math.random().toString(36).substr(2, 9);
  socket = io({
    query: { session_id: sessionId }
  });

  socket.on('connect', () => {
    console.log('WebSocket connected');
  });

  socket.on('connected', (data) => {
    sessionId = data.session_id;
    console.log('Session ID:', sessionId);
  });

  socket.on('chat_response', (data) => {
    // Remove typing indicator if present
    if (typingIndicator) {
      typingIndicator.remove();
      typingIndicator = null;
    }

    state.conversationId = data.conversation_id;

    // Handle tool calls
    if (data.tool_calls && data.tool_calls.length > 0) {
      for (const tc of data.tool_calls) {
        handleToolCall(tc);
      }
    }

    // Show response
    addAssistantMessage(data.response);
  });

  socket.on('agent_question', (data) => {
    // Remove typing indicator
    if (typingIndicator) {
      typingIndicator.remove();
      typingIndicator = null;
    }

    // Show the question from the background agent
    addAssistantMessage(data.question);

    // Optionally highlight that we're waiting for input
    console.log('Agent waiting for input:', data.task_id);
  });

  socket.on('agent_complete', (data) => {
    // Background task completed
    console.log('Agent complete:', data);

    // Show completion message
    addAssistantMessage(data.message);

    // If workflow was created, open it
    if (data.result && data.result.workflow_id) {
      loadBrowserWorkflows();
      if (data.result.nodes && data.result.edges) {
        openCreatedWorkflowInNewTab(data.result);
      }
    }
  });

  socket.on('agent_error', (data) => {
    if (typingIndicator) {
      typingIndicator.remove();
      typingIndicator = null;
    }
    addAssistantMessage(`Error: ${data.error}`);
  });

  socket.on('disconnect', () => {
    console.log('WebSocket disconnected');
  });
}

// Send message via WebSocket
function sendMessageWs(text, includeImage = false) {
  if (!socket || !socket.connected) {
    // Fallback to HTTP
    return false;
  }

  const payload = {
    session_id: sessionId,
    message: text,
    conversation_id: state.conversationId,
  };

  if (includeImage && state.canvasImage) {
    payload.image = state.canvasImage.dataUrl;
  }

  // Show typing indicator
  typingIndicator = document.createElement('div');
  typingIndicator.className = 'message assistant typing';
  typingIndicator.innerHTML = '<div class="message-content"><div class="typing-indicator"><span></span><span></span><span></span></div></div>';
  chatThread.appendChild(typingIndicator);
  chatThread.scrollTop = chatThread.scrollHeight;

  socket.emit('chat', payload);
  return true;
}

// Override processMessage to use WebSocket when available
const originalProcessMessage = processMessage;
async function processMessage(text, includeImage = false) {
  // Try WebSocket first
  if (sendMessageWs(text, includeImage)) {
    return;
  }
  // Fallback to HTTP
  return originalProcessMessage(text, includeImage);
}

// =============================================================================
// Initialize
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
  // Create initial workspace
  const initialWorkspace = createWorkspace();
  state.activeWorkspaceId = initialWorkspace.id;

  renderTabs();
  renderCanvas();
  loadBrowserWorkflows();

  // Initialize WebSocket connection
  initWebSocket();
});
