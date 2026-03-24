import type { FlowNode, FlowEdge } from '../types'

/**
 * Compute a clean hierarchical layout for a flowchart.
 *
 * IMPORTANT: This function NEVER modifies the graph topology.
 * Same node IDs in, same node IDs out. Same edges in, same edges out.
 * Only x,y positions are updated.
 *
 * Supports DAGs (nodes with multiple parents). Each node is positioned
 * exactly once at its deepest reachable layer.
 *
 * Algorithm:
 * 1. Assign layers via topological sort (Kahn's). Each node's layer =
 *    max(parent layers) + 1, so it sits below ALL parents.
 * 2. Build a spanning tree (BFS, first-parent wins) for width calculation
 *    and child ordering — this is purely for layout, not stored anywhere.
 * 3. Position nodes using the spanning tree: subtree widths prevent overlap,
 *    parents are centered over their children.
 * 4. Return the original nodes with updated x,y and the original edges untouched.
 */
export function beautifyNodes(
    nodes: FlowNode[],
    edges: FlowEdge[]
): { nodes: FlowNode[], edges: FlowEdge[] } {
    if (nodes.length === 0) {
        return { nodes: [], edges: [] }
    }

    // De-dupe nodes/edges to keep layout stable across repeated runs
    const nodeById = new Map(nodes.map((node) => [node.id, node]))
    const uniqueNodes = Array.from(nodeById.values())
    const edgeKeys = new Set<string>()
    const uniqueEdges = edges.filter((edge) => {
        const key = `${edge.from}->${edge.to}:${edge.label || ''}`
        if (edgeKeys.has(key)) return false
        edgeKeys.add(key)
        return nodeById.has(edge.from) && nodeById.has(edge.to)
    })

    // Build adjacency lists
    const outgoing = new Map<string, string[]>()
    const incoming = new Map<string, string[]>()
    uniqueNodes.forEach(n => {
        outgoing.set(n.id, [])
        incoming.set(n.id, [])
    })
    uniqueEdges.forEach(e => {
        outgoing.get(e.from)?.push(e.to)
        incoming.get(e.to)?.push(e.from)
    })

    // Identify orphan nodes (no connections at all)
    const orphanNodeIds = new Set(
        uniqueNodes
            .filter(n =>
                (incoming.get(n.id)?.length ?? 0) === 0 &&
                (outgoing.get(n.id)?.length ?? 0) === 0
            )
            .map(n => n.id)
    )

    // Start nodes: no incoming edges but have outgoing, or type 'start'
    const startNodeIds = uniqueNodes
        .filter(n =>
            !orphanNodeIds.has(n.id) &&
            (((incoming.get(n.id)?.length ?? 0) === 0 &&
              (outgoing.get(n.id)?.length ?? 0) > 0) ||
             n.type === 'start')
        )
        .map(n => n.id)

    if (startNodeIds.length === 0) {
        const connectedNodes = uniqueNodes.filter(n => !orphanNodeIds.has(n.id))
        if (connectedNodes.length > 0) {
            startNodeIds.push(connectedNodes[0].id)
        } else {
            // All orphans — nothing meaningful to layout
            return { nodes, edges }
        }
    }

    // ── Phase 1: Assign layers via topological sort (Kahn's algorithm) ──
    // Each node's layer = max(parent layers) + 1, so it sits below ALL parents.
    const inDegree = new Map<string, number>()
    const connectedNodes = uniqueNodes.filter(n => !orphanNodeIds.has(n.id))
    connectedNodes.forEach(n => {
        inDegree.set(n.id, (incoming.get(n.id) ?? []).length)
    })

    const topoQueue: string[] = []
    for (const [id, deg] of inDegree) {
        if (deg === 0) topoQueue.push(id)
    }

    const layerOf = new Map<string, number>()
    for (const id of topoQueue) {
        layerOf.set(id, 0)
    }

    while (topoQueue.length > 0) {
        const id = topoQueue.shift()!
        const myLayer = layerOf.get(id)!

        for (const child of (outgoing.get(id) ?? [])) {
            // Push child to at least one layer below this parent
            const current = layerOf.get(child) ?? 0
            layerOf.set(child, Math.max(current, myLayer + 1))

            const remaining = (inDegree.get(child) ?? 1) - 1
            inDegree.set(child, remaining)
            if (remaining === 0) {
                topoQueue.push(child)
            }
        }
    }

    // Safety: any connected node not reached by topo sort (shouldn't happen
    // for acyclic graphs but handles degenerate cases)
    connectedNodes.forEach(n => {
        if (!layerOf.has(n.id)) layerOf.set(n.id, 0)
    })

    // ── Phase 2: Build spanning tree for layout (BFS, first-parent wins) ──
    // This tree is used only for subtree-width calculations and child ordering.
    // Cross-links (DAG edges not in the tree) are drawn but don't affect layout.
    interface LayoutNode {
        id: string
        layer: number
        children: LayoutNode[]
    }

    const visited = new Set<string>()
    const layoutMap = new Map<string, LayoutNode>()
    const roots: LayoutNode[] = []
    const bfsQueue: string[] = []

    // Skip orphans from tree construction
    orphanNodeIds.forEach(id => visited.add(id))

    for (const id of startNodeIds) {
        if (visited.has(id)) continue
        const node: LayoutNode = { id, layer: layerOf.get(id) ?? 0, children: [] }
        roots.push(node)
        layoutMap.set(id, node)
        bfsQueue.push(id)
        visited.add(id)
    }

    while (bfsQueue.length > 0) {
        const parentId = bfsQueue.shift()!
        const parent = layoutMap.get(parentId)!

        for (const childId of (outgoing.get(parentId) ?? [])) {
            if (visited.has(childId)) continue // Already in tree — DAG cross-link
            visited.add(childId)

            const child: LayoutNode = {
                id: childId,
                layer: layerOf.get(childId) ?? (parent.layer + 1),
                children: [],
            }
            parent.children.push(child)
            layoutMap.set(childId, child)
            bfsQueue.push(childId)
        }
    }

    // Handle remaining disconnected-but-not-orphan nodes
    connectedNodes.forEach(n => {
        if (!visited.has(n.id)) {
            const node: LayoutNode = { id: n.id, layer: layerOf.get(n.id) ?? 0, children: [] }
            roots.push(node)
            layoutMap.set(n.id, node)
            visited.add(n.id)
        }
    })

    // ── Phase 3: Position nodes using the spanning tree ──
    const layerSpacing = 160
    const nodeSpacing = 220
    const siblingGap = 40
    const startY = 100

    // Subtree width for spacing calculations
    const getSubtreeWidth = (node: LayoutNode): number => {
        if (node.children.length === 0) return 1
        const childrenWidth = node.children.reduce(
            (sum, child) => sum + getSubtreeWidth(child), 0
        )
        return Math.max(childrenWidth, node.children.length)
    }

    // Descendant count for ordering children (most descendants in center)
    const getDescendantCount = (node: LayoutNode): number => {
        if (node.children.length === 0) return 0
        return node.children.reduce(
            (sum, child) => sum + 1 + getDescendantCount(child), 0
        )
    }

    // Order children: largest subtree in center for a balanced visual
    const orderChildren = (node: LayoutNode) => {
        if (node.children.length >= 2) {
            const withCounts = node.children.map(c => ({
                child: c,
                desc: getDescendantCount(c),
            }))
            withCounts.sort((a, b) => b.desc - a.desc)

            if (node.children.length === 2) {
                // Smaller left, larger right
                node.children = [withCounts[1].child, withCounts[0].child]
            } else if (node.children.length === 3) {
                // Largest in middle
                node.children = [withCounts[1].child, withCounts[0].child, withCounts[2].child]
            } else {
                const sorted = withCounts.map(c => c.child)
                const middle = sorted[0]
                const others = sorted.slice(1)
                const left = others.filter((_, i) => i % 2 === 0)
                const right = others.filter((_, i) => i % 2 === 1)
                node.children = [...left, middle, ...right]
            }
        }
        node.children.forEach(orderChildren)
    }
    roots.forEach(orderChildren)

    // Recursively assign positions: children first, then center parent above them
    const positions = new Map<string, { x: number; y: number }>()

    const assignPositions = (node: LayoutNode, leftX: number): number => {
        const subtreeWidth = getSubtreeWidth(node)
        const numGaps = node.children.length > 1 ? node.children.length - 1 : 0
        const myWidth = subtreeWidth * nodeSpacing + numGaps * siblingGap

        if (node.children.length === 0) {
            positions.set(node.id, {
                x: leftX + myWidth / 2,
                y: startY + node.layer * layerSpacing,
            })
            return myWidth
        }

        // Position children first
        let childX = leftX
        node.children.forEach((child, idx) => {
            const childWidth = assignPositions(child, childX)
            childX += childWidth
            if (idx < node.children.length - 1) childX += siblingGap
        })

        // Center parent over its children
        const firstPos = positions.get(node.children[0].id)!
        const lastPos = positions.get(node.children[node.children.length - 1].id)!
        positions.set(node.id, {
            x: (firstPos.x + lastPos.x) / 2,
            y: startY + node.layer * layerSpacing,
        })

        return myWidth
    }

    let currentX = 0
    roots.forEach(root => {
        const width = assignPositions(root, currentX)
        currentX += width + nodeSpacing
    })

    // Place orphan nodes in a row below the deepest layer
    const maxLayer = Math.max(0, ...Array.from(layerOf.values()))
    const orphanList = uniqueNodes.filter(n => orphanNodeIds.has(n.id))
    if (orphanList.length > 0) {
        const orphanY = startY + (maxLayer + 2) * layerSpacing
        const totalWidth = (orphanList.length - 1) * nodeSpacing
        const orphanStartX = 400 - totalWidth / 2
        orphanList.forEach((n, idx) => {
            positions.set(n.id, { x: orphanStartX + idx * nodeSpacing, y: orphanY })
        })
    }

    // Center entire layout around x=400
    const allPos = Array.from(positions.values())
    if (allPos.length > 0) {
        const minX = Math.min(...allPos.map(p => p.x))
        const maxX = Math.max(...allPos.map(p => p.x))
        const offset = 400 - (minX + maxX) / 2
        allPos.forEach(p => { p.x += offset })
    }

    // Build result: same nodes with updated positions, same edges unchanged
    const resultNodes = uniqueNodes.map(n => {
        const pos = positions.get(n.id)
        return pos ? { ...n, x: pos.x, y: pos.y } : { ...n }
    })

    return { nodes: resultNodes, edges: uniqueEdges }
}
