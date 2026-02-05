import type { FlowNode, FlowEdge } from '../types'

/**
 * Beautify/auto-layout a flowchart using hierarchical tree algorithm.
 * Extracted from Canvas.tsx for reuse in subflow visualization.
 * 
 * @param nodes - Array of flow nodes to layout
 * @param edges - Array of flow edges connecting nodes
 * @returns New arrays of nodes (with updated x,y) and edges
 */
export function beautifyNodes(
    nodes: FlowNode[],
    edges: FlowEdge[]
): { nodes: FlowNode[], edges: FlowEdge[] } {
    if (nodes.length === 0) {
        return { nodes: [], edges: [] }
    }

    // De-dupe nodes/edges to keep layout stable
    const nodeById = new Map(nodes.map((node) => [node.id, node]))
    const uniqueNodes = Array.from(nodeById.values())
    const edgeKeys = new Set<string>()
    const uniqueEdges = edges.filter((edge) => {
        const key = `${edge.from}->${edge.to}:${edge.label || ''}`
        if (edgeKeys.has(key)) return false
        edgeKeys.add(key)
        return nodeById.has(edge.from) && nodeById.has(edge.to)
    })

    // Build adjacency list
    const outgoing = new Map<string, { to: string; label: string }[]>()
    const incoming = new Map<string, string[]>()
    uniqueNodes.forEach(n => {
        outgoing.set(n.id, [])
        incoming.set(n.id, [])
    })
    uniqueEdges.forEach(e => {
        outgoing.get(e.from)?.push({ to: e.to, label: e.label })
        incoming.get(e.to)?.push(e.from)
    })

    // Find orphan nodes (no connections)
    const orphanNodeIds = new Set(
        uniqueNodes
            .filter(n => (incoming.get(n.id)?.length ?? 0) === 0 && (outgoing.get(n.id)?.length ?? 0) === 0)
            .map(n => n.id)
    )

    // Start nodes: no incoming edges but have outgoing, or type 'start'
    let startNodes = uniqueNodes.filter(n =>
        !orphanNodeIds.has(n.id) &&
        (((incoming.get(n.id)?.length ?? 0) === 0 && (outgoing.get(n.id)?.length ?? 0) > 0) ||
            n.type === 'start')
    )

    if (startNodes.length === 0) {
        const connectedNodes = uniqueNodes.filter(n => !orphanNodeIds.has(n.id))
        if (connectedNodes.length > 0) {
            startNodes = [connectedNodes[0]]
        } else {
            return { nodes, edges }
        }
    }

    // Tree structure for layout
    interface TreeNode {
        id: string
        originalId: string
        layer: number
        children: TreeNode[]
        parentId: string | null
        edgeLabel: string
    }

    const newNodes: FlowNode[] = []
    const newEdges: { from: string; to: string; label: string }[] = []
    const visited = new Set<string>()
    let dupCounter = 0

    // Layout constants
    const layerSpacing = 160
    const nodeSpacing = 220
    const startY = 100
    const siblingGap = 40

    // Skip orphans
    orphanNodeIds.forEach(id => visited.add(id))

    // Build tree via BFS
    const roots: TreeNode[] = []
    const queue: TreeNode[] = []

    startNodes.forEach(node => {
        if (visited.has(node.id)) return
        const treeNode: TreeNode = {
            id: node.id,
            originalId: node.id,
            layer: 0,
            children: [],
            parentId: null,
            edgeLabel: ''
        }
        roots.push(treeNode)
        queue.push(treeNode)
        visited.add(node.id)
    })

    while (queue.length > 0) {
        const current = queue.shift()!
        const children = outgoing.get(current.originalId) || []

        children.forEach(({ to, label }) => {
            let childId: string
            if (visited.has(to)) {
                dupCounter++
                childId = `${to}_dup${dupCounter}`
            } else {
                childId = to
                visited.add(to)
            }

            const childTreeNode: TreeNode = {
                id: childId,
                originalId: to,
                layer: current.layer + 1,
                children: [],
                parentId: current.id,
                edgeLabel: label
            }
            current.children.push(childTreeNode)
            queue.push(childTreeNode)
        })
    }

    // Handle remaining disconnected nodes
    uniqueNodes.forEach(n => {
        if (!visited.has(n.id)) {
            const treeNode: TreeNode = {
                id: n.id,
                originalId: n.id,
                layer: 0,
                children: [],
                parentId: null,
                edgeLabel: ''
            }
            roots.push(treeNode)
            visited.add(n.id)
        }
    })

    // Calculate subtree width
    const getSubtreeWidth = (node: TreeNode): number => {
        if (node.children.length === 0) return 1
        const childrenWidth = node.children.reduce((sum, child) => sum + getSubtreeWidth(child), 0)
        return Math.max(childrenWidth, node.children.length)
    }

    // Count descendants
    const getDescendantCount = (node: TreeNode): number => {
        if (node.children.length === 0) return 0
        return node.children.reduce((sum, child) => sum + 1 + getDescendantCount(child), 0)
    }

    // Order children: most descendants in center
    const orderNodeChildren = (node: TreeNode) => {
        if (node.children.length >= 2) {
            const childrenWithCounts = node.children.map(child => ({
                child,
                descendants: getDescendantCount(child)
            }))
            childrenWithCounts.sort((a, b) => b.descendants - a.descendants)

            if (node.children.length === 2) {
                const [larger, smaller] = childrenWithCounts.map(c => c.child)
                node.children = [smaller, larger]
            } else if (node.children.length === 3) {
                const [largest, second, third] = childrenWithCounts.map(c => c.child)
                node.children = [second, largest, third]
            } else {
                const sorted = childrenWithCounts.map(c => c.child)
                const middle = sorted[0]
                const others = sorted.slice(1)
                const left = others.filter((_, i) => i % 2 === 0)
                const right = others.filter((_, i) => i % 2 === 1)
                node.children = [...left, middle, ...right]
            }
        }
        node.children.forEach(orderNodeChildren)
    }

    roots.forEach(orderNodeChildren)

    // Assign positions recursively
    const assignPositions = (node: TreeNode, leftX: number): number => {
        const subtreeWidth = getSubtreeWidth(node)
        const numGaps = node.children.length > 1 ? node.children.length - 1 : 0
        const myWidth = subtreeWidth * nodeSpacing + numGaps * siblingGap

        if (node.children.length === 0) {
            const nodeX = leftX + myWidth / 2
            const originalNode = uniqueNodes.find(n => n.id === node.originalId)!
            newNodes.push({
                ...originalNode,
                id: node.id,
                x: nodeX,
                y: startY + node.layer * layerSpacing
            })
            if (node.parentId) {
                newEdges.push({ from: node.parentId, to: node.id, label: node.edgeLabel })
            }
            return myWidth
        }

        // Position children first
        let childX = leftX
        node.children.forEach((child, idx) => {
            const childWidth = assignPositions(child, childX)
            childX += childWidth
            if (idx < node.children.length - 1) {
                childX += siblingGap
            }
        })

        // Position node centered over children
        const firstChild = newNodes.find(n => n.id === node.children[0].id)!
        const lastChild = newNodes.find(n => n.id === node.children[node.children.length - 1].id)!
        const nodeX = (firstChild.x + lastChild.x) / 2

        const originalNode = uniqueNodes.find(n => n.id === node.originalId)
        if (originalNode) {
            newNodes.push({
                ...originalNode,
                id: node.id,
                x: nodeX,
                y: startY + node.layer * layerSpacing
            })
        }

        if (node.parentId) {
            newEdges.push({ from: node.parentId, to: node.id, label: node.edgeLabel })
        }

        return myWidth
    }

    // Assign positions for all roots
    let currentX = 0
    roots.forEach(root => {
        const width = assignPositions(root, currentX)
        currentX += width + nodeSpacing
    })

    // Center layout around x=400
    if (newNodes.length > 0) {
        const minX = Math.min(...newNodes.map(n => n.x))
        const maxX = Math.max(...newNodes.map(n => n.x))
        const centerOffset = 400 - (minX + maxX) / 2
        newNodes.forEach(n => { n.x += centerOffset })
    }

    // Auto-assign Yes/No labels to decision outputs
    const decisionNodes = newNodes.filter(n => n.type === 'decision')
    decisionNodes.forEach(decNode => {
        const outEdges = newEdges.filter(e => e.from === decNode.id)
        if (outEdges.length >= 2) {
            if (!outEdges[0].label) outEdges[0].label = 'Yes'
            if (!outEdges[1].label) outEdges[1].label = 'No'
        }
    })

    return { nodes: newNodes, edges: newEdges }
}
