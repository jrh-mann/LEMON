# Proposed Feature Additions

This document explores potential new features and enhancements to expand the capability of the LEMON workflow engine.

## 1. Historical Versioning for Workflows
- **Use Case**: As users create more complex workflows, they often need the ability to revert to previous working states.
- **Implementation**: Introduce a history table that snapshots workflow `tree`, `nodes`, and `edges` on every major save. The frontend can provide a basic "time-travel" diff UI.

## 2. CI/CD Bulk Testing (Node Validation)
- **Use Case**: Ensuring a workflow remains correct when refactoring structure / calculations.
- **Implementation**: Allow users to upload a `.csv` defining input values and expected output variables. The backend spins up an isolated interpreter pool to bulk traverse the trees and display regression diffs.

## 3. Webhook Nodes / Cloud Integrations
- **Use Case**: Currently, execution occurs in an isolated sandbox. Workflows would be incredibly powerful if they could request external APIs.
- **Implementation**: Add an `HTTP Request` node type where users can configure REST endpoints, passing down context variables as JSON payloads. This would pair well with a top-level Webhook listener so external SaaS apps can trigger a LEMON workflow.

## 4. Code Snippet Plugin Nodes
- **Use Case**: In scenarios where complex data structures need modification, the `calculation` node UI might be too restrictive.
- **Implementation**: Allow creating `script` nodes that support raw JavaScript/Python environments (via restricted sandboxes). Variables go in, run through code string, variables come out.

## 5. Subflow Auto-Beautification (Enhanced Visualization)
- **Use Case**: Subflows viewed inside modals often scramble or hide important structures because the visualizer isn't fully self-centering on entry nodes or dynamically re-rendering the bounding box.
- **Implementation**: Implement an on-render event in the modal that triggers the equivalent of the `beautify` action to evenly space child workflow nodes before presenting them.

## 6. Real-time Collaboration
- **Use Case**: Multiple team members building a decision matrix together.
- **Implementation**: Use WebSockets and CRDTs / operational-transform to stream live node movements, similar to Figma.
