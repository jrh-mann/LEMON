/**
 * E2E tests for the canvas — node rendering, node types, decision diamonds,
 * edge labels, and visual differentiation between node types.
 */
import { test, expect } from '@playwright/test'
import { mockAllAPIs, resetMsgCounter, type NodePayload, type EdgePayload } from './helpers'

const WF_ID = 'wf_canvas_00000000000000000000000000'

// Comprehensive set of nodes covering every type
const ALL_TYPE_NODES: NodePayload[] = [
  { id: 'n1', type: 'start',       label: 'Begin',           x: 100, y: 200, color: 'green' },
  { id: 'n2', type: 'process',     label: 'Gather Data',     x: 300, y: 200, color: 'teal' },
  { id: 'n3', type: 'decision',    label: 'Age Check',       x: 500, y: 200, color: 'amber',
    condition: { input_id: 'var_age', comparator: 'gte', value: 18 } },
  { id: 'n4', type: 'calculation', label: 'Compute BMI',     x: 700, y: 100, color: 'purple' },
  { id: 'n5', type: 'subprocess',  label: 'Run Sub-Protocol', x: 700, y: 300, color: 'rose',
    subworkflow_id: 'wf_sub_1' },
  { id: 'n6', type: 'end',         label: 'Output Result',   x: 900, y: 200, color: 'amber' },
]

const ALL_TYPE_EDGES: EdgePayload[] = [
  { from: 'n1', to: 'n2', label: '' },
  { from: 'n2', to: 'n3', label: '' },
  { from: 'n3', to: 'n4', label: 'true' },   // Decision true branch
  { from: 'n3', to: 'n5', label: 'false' },   // Decision false branch
  { from: 'n4', to: 'n6', label: '' },
  { from: 'n5', to: 'n6', label: '' },
]

test.describe('canvas — node rendering', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Canvas Test Workflow',
        nodes: ALL_TYPE_NODES, edges: ALL_TYPE_EDGES,
        variables: [
          { id: 'var_age', name: 'age', type: 'number', source: 'input' },
        ],
      },
    })
  })

  test('all 6 node types render on canvas', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)
    await expect(page.locator('#flowchartCanvas')).toBeVisible()

    // Total nodes
    await expect(page.locator('.flow-node')).toHaveCount(6)

    // One of each type
    await expect(page.locator('.flow-node.start')).toHaveCount(1)
    await expect(page.locator('.flow-node.process')).toHaveCount(1)
    await expect(page.locator('.flow-node.decision')).toHaveCount(1)
    await expect(page.locator('.flow-node.calculation')).toHaveCount(1)
    await expect(page.locator('.flow-node.subprocess')).toHaveCount(1)
    await expect(page.locator('.flow-node.end')).toHaveCount(1)
  })

  test('decision node uses diamond path (SVG)', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    // Decision node should be present and contain a diamond shape.
    // SVG path elements inside <g> can be checked via evaluate.
    const decisionNode = page.locator('.flow-node.decision')
    await expect(decisionNode).toHaveCount(1)

    // Verify it has a <path> element (diamond) via JS evaluation
    const hasPath = await decisionNode.evaluate(
      (el) => el.querySelectorAll('path').length > 0,
    )
    expect(hasPath).toBe(true)
  })

  test('subprocess node has inner border rect', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    const subNode = page.locator('.flow-node.subprocess')
    await expect(subNode).toHaveCount(1)

    // Subprocess has extra inner rect (double border). Count rects via JS.
    // Hit area + outer shape + inner border = at least 3 rects
    const rectCount = await subNode.evaluate(
      (el) => el.querySelectorAll('rect').length,
    )
    expect(rectCount).toBeGreaterThanOrEqual(3)
  })

  test('node labels match the data', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)
    await expect(page.locator('.flow-node')).toHaveCount(6)

    // SVG text elements use namespaces, so use getElementById + getElementsByTagName
    const nodeTexts = await page.evaluate(() => {
      const nodeLayer = document.getElementById('nodeLayer')
      if (!nodeLayer) return []
      const texts: string[] = []
      nodeLayer.querySelectorAll('text').forEach(el => {
        const t = el.textContent?.trim()
        if (t) texts.push(t)
      })
      return texts
    })
    expect(nodeTexts).toContain('Begin')
    expect(nodeTexts).toContain('Gather Data')
    expect(nodeTexts).toContain('Age Check')
    expect(nodeTexts).toContain('Compute BMI')
    expect(nodeTexts).toContain('Run Sub-Protocol')
    expect(nodeTexts).toContain('Output Result')
  })

  test('correct number of edges render', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    // 6 edges in the test data
    await expect(page.locator('.flow-edge')).toHaveCount(6)
  })

  test('decision edge labels resolve from condition and variables', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    // The decision node has condition: age >= 18
    // Edge labels are SVG <text> elements inside #edgeLayer
    const edgeLayer = page.locator('#edgeLayer')
    await expect(edgeLayer).toBeVisible()

    const edgeTexts = await page.evaluate(() => {
      const layer = document.getElementById('edgeLayer')
      if (!layer) return []
      const texts: string[] = []
      layer.querySelectorAll('text').forEach(el => {
        const t = el.textContent?.trim()
        if (t) texts.push(t)
      })
      return texts
    })

    // At least the decision edge labels should be resolved to human-readable form
    const hasResolvedLabel = edgeTexts.some(t =>
      t.includes('age') && (t.includes('≥') || t.includes('<') || t.includes('18')),
    )
    expect(hasResolvedLabel).toBe(true)
  })

  test('clicking a node selects it (dashed selection ring)', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    // Initially no node should be selected
    await expect(page.locator('.flow-node.selected')).toHaveCount(0)

    // Click the "Gather Data" process node
    // SVG nodes receive clicks on their hit area rect
    const processNode = page.locator('.flow-node.process')
    await processNode.click()

    // Now it should have the selected class
    await expect(page.locator('.flow-node.selected')).toHaveCount(1)
    await expect(processNode).toHaveClass(/selected/)
  })

  test('clicking empty canvas deselects node', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    // Select a node first
    await page.locator('.flow-node.start').click()
    await expect(page.locator('.flow-node.selected')).toHaveCount(1)

    // Click on empty area of the canvas (far from any node)
    await page.locator('#flowchartCanvas').click({ position: { x: 50, y: 50 } })

    // Selection should be cleared
    await expect(page.locator('.flow-node.selected')).toHaveCount(0)
  })

  test('selecting a node shows node properties in sidebar', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    // Before selection — sidebar shows VARIABLES section
    await expect(page.locator('.eyebrow', { hasText: 'VARIABLES' })).toBeVisible()

    // Click a node
    await page.locator('.flow-node.process').click()

    // Sidebar should now show NODE PROPERTIES
    await expect(page.locator('.eyebrow', { hasText: 'NODE PROPERTIES' })).toBeVisible()
  })

  test('nodes and edges survive page refresh', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.flow-node')).toHaveCount(6)
    await expect(page.locator('.flow-edge')).toHaveCount(6)

    await page.reload()

    await expect(page.locator('.flow-node')).toHaveCount(6)
    await expect(page.locator('.flow-edge')).toHaveCount(6)
  })
})

test.describe('canvas — minimal workflows', () => {
  test('empty workflow shows just the canvas with no nodes', async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Empty Workflow',
        nodes: [], edges: [], variables: [],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('#flowchartCanvas')).toBeVisible()
    await expect(page.locator('.flow-node')).toHaveCount(0)
    await expect(page.locator('.flow-edge')).toHaveCount(0)
  })

  test('single start node renders correctly', async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Single Node',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 200, y: 200, color: 'green' }],
        edges: [],
        variables: [],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.flow-node')).toHaveCount(1)
    await expect(page.locator('.flow-node.start')).toHaveCount(1)
    await expect(page.locator('.flow-node text')).toContainText('Start')
  })
})
