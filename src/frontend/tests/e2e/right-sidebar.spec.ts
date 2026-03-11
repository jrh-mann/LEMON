/**
 * E2E tests for the right sidebar — variable cards, node properties,
 * source badges, and variable metadata display.
 *
 * The sidebar shows variables from the workflow analysis and switches
 * to node/edge properties when a node or edge is selected on the canvas.
 */
import { test, expect } from '@playwright/test'
import { mockAllAPIs, resetMsgCounter } from './helpers'

const WF_ID = 'wf_sidebar_0000000000000000000000'

test.describe('right sidebar — variables', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
  })

  test('renders variable cards from workflow data', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_age', name: 'Patient Age', type: 'number', source: 'input', range: { min: 0, max: 120 }, description: 'Age in years' },
          { id: 'var_flag', name: 'Is Emergency', type: 'bool', source: 'input' },
          { id: 'var_dept', name: 'Department', type: 'enum', source: 'input', enum_values: ['ER', 'ICU', 'General'] },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    // Should render 3 variable cards
    await expect(page.locator('.var-card')).toHaveCount(3)

    // Check variable names
    const names = await page.locator('.var-name').allTextContents()
    expect(names).toEqual(['Patient Age', 'Is Emergency', 'Department'])
  })

  test('variable type labels display correctly', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_a', name: 'Age', type: 'number', source: 'input' },
          { id: 'var_b', name: 'Flag', type: 'bool', source: 'input' },
          { id: 'var_c', name: 'Name', type: 'string', source: 'input' },
          { id: 'var_d', name: 'Dept', type: 'enum', source: 'input', enum_values: ['A', 'B'] },
          { id: 'var_e', name: 'DOB', type: 'date', source: 'input' },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    // Wait for variables to load from the API mock
    await expect(page.locator('.var-card')).toHaveCount(5)

    const typeLabels = await page.locator('.var-type-label').allTextContents()
    expect(typeLabels).toEqual(['Number', 'Boolean', 'String', 'Enum', 'Date'])
  })

  test('source badges show correct source type', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_a', name: 'Input Var', type: 'number', source: 'input' },
          { id: 'var_b', name: 'Sub Result', type: 'string', source: 'subprocess', source_node_id: 'n2' },
          { id: 'var_c', name: 'Calc Var', type: 'number', source: 'calculated', expression: 'a + b' },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    // Check source badge classes
    await expect(page.locator('.source-input')).toHaveCount(1)
    await expect(page.locator('.source-subprocess')).toHaveCount(1)
    await expect(page.locator('.source-calculated')).toHaveCount(1)
  })

  test('subprocess variable card has data-source attribute', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_sub', name: 'Triage Result', type: 'string', source: 'subprocess', source_node_id: 'n3' },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.var-card[data-source="subprocess"]')).toHaveCount(1)
  })

  test('number variable shows range hint', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_age', name: 'Age', type: 'number', source: 'input', range: { min: 0, max: 120 } },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.var-range-hint')).toContainText('0')
    await expect(page.locator('.var-range-hint')).toContainText('120')
  })

  test('enum variable shows enum values hint', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_dept', name: 'Dept', type: 'enum', source: 'input', enum_values: ['ER', 'ICU', 'General'] },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.var-enum-hint')).toContainText('ER')
    await expect(page.locator('.var-enum-hint')).toContainText('ICU')
    await expect(page.locator('.var-enum-hint')).toContainText('General')
  })

  test('variable description hint shows when present', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_age', name: 'Age', type: 'number', source: 'input', description: 'Patient age in years' },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.var-description-hint')).toContainText('Patient age in years')
  })

  test('empty state shows hint when no variables', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.sidebar-empty-hint')).toBeVisible()
  })

  test('add variable button is present', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.add-var-btn')).toBeVisible()
    await expect(page.locator('.add-var-btn')).toContainText('Add Variable')
  })

  test('variables survive page refresh', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [],
        variables: [
          { id: 'var_a', name: 'Alpha', type: 'number', source: 'input' },
          { id: 'var_b', name: 'Beta', type: 'bool', source: 'input' },
        ],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)
    await expect(page.locator('.var-card')).toHaveCount(2)

    await page.reload()
    await expect(page.locator('.var-card')).toHaveCount(2)
    const names = await page.locator('.var-name').allTextContents()
    expect(names).toEqual(['Alpha', 'Beta'])
  })
})
