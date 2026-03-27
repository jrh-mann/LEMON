# Individual Report Draft (Extended Version)

## 1. Project Information

### 1.1 Project Title
LEMON - Conversational Workflow Engineering Platform

### 1.2 Team Number
[Fill in team number]

### 1.3 Student Name and ID
[Fill in your full name]

[Fill in your student ID]

### 1.4 Purpose of This Draft
This is a deliberately long, detailed draft of my individual report based on a full review of the repository history and my authored changes. I have written this version at greater depth than a final 4-5 page submission so I can cut it down later while preserving key technical detail and reflection.

---

## 2. My Overall Contribution Scope

I worked across the full software stack of the project, with most of my contribution concentrated in system artefacts: backend architecture, workflow tools, runtime execution, state synchronization, frontend workflow UX, import/export infrastructure, package/public-library features, and test coverage.

Across the project history, my authored work represents a substantial share of the development effort:

- I authored 251 commits in this repository.
- I contributed continuously from the early architecture phase through the final stabilization and submission phase.
- I touched over 500 relevant source/test/documentation files (excluding generated local artifacts).
- My highest concentration was in `src/frontend/src/components`, `src/backend/api`, `src/backend/tools`, and `tests`.

The best way to summarize my role is: I was one of the primary integrators and stabilizers of the workflow engine and user-facing editing/runtime experience, especially during the high-pressure final phase where features had to be hardened, unified, and production-ready.

### 2.1 History-Derived Contribution Table (System Artefacts)

I derived the table below from my authored git history (`author = axelcbw`) using line-churn analysis (`insertions + deletions`) and category mapping.

Notes on methodology:

- Included: source, tests, scripts, docs, non-generated eval code.
- Excluded generated/local artifacts (e.g., `.chrome-profile*`, `.lemon/*`, `node_modules/*`, `.vite/*`, `evals/results/*`).
- This is an engineering-effort estimate, not an exact time log.

| Work Package | Churn-Weighted Effort | Approx % |
| --- | ---: | ---: |
| Research and experiments / technical docs | 3,983 | 4.68% |
| UI design / UX implementation | 25,372 | 29.79% |
| Coding / architecture (backend + integration) | 38,022 | 44.64% |
| Testing / QA | 17,789 | 20.89% |
| **Total** | **85,166** | **100.00%** |

### 2.2 History-Derived Website Report Contribution Snapshot

Direct git history evidence shows that my commits were concentrated in system artefacts rather than direct static report page authoring.

| Website Report Contribution Type | History Evidence |
| --- | --- |
| Direct edits under `website/` | No direct authored commits found |
| Technical content support for report sections | Significant (architecture, implementation, testing, validation, package/public features documented through code + technical markdown) |

If needed for final submission, I can map this technical support into your team's website work-package table wording so it aligns with the Moodle/IPAC narrative.

---

## 3. Personal Contributions to System Artefacts

### 3.1 Research and Technical Investigation

Although much of my output was code, a large part of my work was research-driven engineering: identifying failure modes, validating assumptions, and converting known limitations into concrete architectural fixes.

My technical investigation contributions included:

1. Mapping validation gaps in workflow integrity (cycles, self-loops, start-node logic, decision input semantics).
2. Studying why legacy `inputs`/`input_ref` naming caused repeated edge-case bugs and designing a unified `variables` model.
3. Identifying API and state-management coupling issues between chat flow, workflow graph persistence, and execution context.
4. Evaluating failure cases in subworkflow composition and export recursion.
5. Investigating stream and metadata reliability issues between backend orchestrator messages and frontend rendering.
6. Tracking known issues and writing internal issue summaries/plans to structure fixes.

This research work directly informed my major implementation decisions. In other words, I did not just patch symptoms; I repeatedly traced failures to root causes in data contracts, lifecycle ownership, and cross-module invariants.

### 3.2 Workflow Validation and Structural Correctness

One of my earliest high-impact areas was validation hardening.

I implemented and/or integrated:

- Cycle detection and self-loop detection in workflow validation.
- Single-start-node validation.
- Decision-node input validation in strict mode.
- Automatic validation hooks before save/export operations.
- Validation endpoint consistency improvements after internal key renames.
- Library-level validation exposure so users could verify stored workflows.
- Restored validation indicators (tick/cross badges) in library cards after regressions.

These changes improved both correctness and trust. Before this work, invalid graphs could pass too far down the pipeline; after this work, workflow integrity was checked earlier and surfaced clearly in the UI.

### 3.3 Variable System, Type Integrity, and Output Contract

A central part of my contribution was replacing fragmented variable semantics with a coherent system.

Key parts of this work:

- Unified workflow variable representation (`variables` as the canonical key).
- Removal of legacy alias paths that mixed `inputs`, `input_ref`, and backward-compat conversions.
- Introduction and hardening of `modify_workflow_variable` behavior.
- Synchronization of auto-derived variables from calculation and subprocess nodes.
- Guards preventing users from mutating derived variables incorrectly.
- Cleanup logic for derived variables on node deletion/modification.
- Output type declaration and propagation through save/load/socket/execution flows.
- Output node type-preserving behavior and end-node output variable semantics.

I also contributed to the transition to a unified `number` type in place of historical `int/float` split behavior, reducing ambiguity in execution and compiler output.

This variable/type work resolved a broad class of recurring bugs (tool parameter mismatch, stale variable lists, invalid UI assumptions, and execution-time type errors). It was one of the biggest quality multipliers in the whole project.

### 3.4 Subworkflow/Subprocess Composition

I implemented major subworkflow/subprocess capabilities and stabilization work.

Core contributions:

- Added subflow/subprocess support for workflow composition.
- Ensured subprocess execution behavior remained stable even with sparse or empty stored trees.
- Added recursive-subflow warnings in export and Python compilation paths.
- Added handling for missing subflows during bundle export (placeholder files) and Python runtime stubs.
- Implemented transfer behavior and metadata to preserve package/subworkflow relationships.

This moved LEMON beyond single-flat workflows toward reusable hierarchical workflow logic, which was essential for scalability and modularity.

### 3.5 Runtime Execution Engine and Stepped Execution UX

I contributed heavily to execution architecture and the corresponding user experience.

I introduced or integrated:

- `on_step` callback support in the interpreter for step-by-step visualization.
- Stepped workflow execution over socket events.
- Run/Pause/Stop user controls.
- Execution input modal flows.
- Execution modal/UI refactors to improve maintainability.
- Instant execution mode (0 ms animation delay) while preserving logs and trail behavior.
- Alignment work between execution entry points and workflow-preparation flows.

The result was a practical runtime experience where users can both inspect logic interactively and run workflows quickly when they need output rather than animation.

### 3.6 Workflow Persistence, Session Handling, and Library Foundation

I was a primary contributor to persistence and library behavior.

Major work areas:

- User-specific workflow persistence and save/load reliability.
- Library deletion support.
- List-workflows tooling for orchestrator awareness.
- Workflow-ID-centric architecture and tab/workflow isolation.
- Draft workflow handling and save semantics.
- Auto-save and first-message auto-persist behavior.
- Session guard behavior for unsaved changes.
- Importing workflows into new sessions while preserving context.
- Preserving workflow context when navigating between pages.

This established more deterministic workflow ownership and removed classes of bugs where data drifted between session state, chat context, and persisted graph data.

### 3.7 API and Backend Architecture Refactoring

I invested significant effort in maintainability refactors, especially when monolithic files became a scaling bottleneck.

Important architecture changes I drove:

- Split monolithic backend `routes.py` into focused route modules.
- Split large orchestrator configuration content into clearer components.
- Introduced and expanded package routes.
- Consolidated repetitive workflow tool boilerplate through a shared base abstraction.
- Removed dead metadata/search paths and stale wrappers when no longer justified.
- Cleaned compatibility arguments and removed legacy fallback layers after migration completion.

This reduced cognitive load for contributors and made defects easier to localize. It also improved confidence when implementing late-stage features under time pressure.

### 3.8 Frontend UX, Canvas Interaction, and Interface Evolution

I made substantial contributions to frontend architecture and interaction quality.

My frontend work included:

- Canvas zoom and pan mode behavior.
- Run-state integration with modal and workflow UI.
- Right-sidebar redesigns and extraction of node config editors.
- Variable modal integration and variable controls UX.
- Tabbed layout/navigation pages and workflow transitions.
- Workflow transition layer for smooth visual navigation.
- Arrow thickness and hover improvements for graph readability.
- Drag edge-snapping and render-performance improvements.
- Read-only workflow canvas components for public previews.
- Library UI updates (headers, back-button behavior, search filtering, validation indicators).

This work was not just cosmetic. Most UI changes were tightly tied to backend state guarantees, meaning visual behavior was redesigned together with data flow ownership.

### 3.9 Image Annotation and LLM-Guided Image Questions

I contributed to the annotation pipeline and image-related tooling, including both frontend and backend integration.

My contributions covered:

- Canvas annotation-dot rendering and interaction behavior.
- Label-based annotation support in backend structures.
- Full-stack annotation transport through real-time events.
- LLM image-question orchestration tooling integration.
- Synchronizing incoming annotation updates into workflow state.
- Later removal of legacy annotation code paths to reduce instability and dead behavior.

This area was technically challenging because it touched orchestration prompts, event transport, frontend rendering, and stored state representations.

### 3.10 Dev Tools and Internal Debugging Workflow

I helped build and stabilize developer-facing introspection/control surfaces.

Contributions included:

- Dev tools panel integration into the workflow interface.
- Tool execution and logging improvements for debugging.
- API export/listing fixes for dev tools endpoints.
- Alignment of dev tools execution with orchestrator lifecycle.
- Preserving dev-tools workflow state during execution.

This reduced turnaround time when diagnosing tool orchestration failures and significantly improved engineering velocity in the final weeks.

### 3.11 Import/Export, Transfer Reliability, and Validation Ownership

I implemented and hardened major transfer flows in the final phase.

Key functionality:

- Workflow bundle transfer infrastructure.
- Server-owned validation state for imported content.
- Force-import behavior and import-anyway fallback handling.
- Retry improvements for pasted JSON imports.
- Export support for partial/missing subworkflow references.

This was essential for robust interoperability and for practical team usage where workflows move between sessions/users/packages.

### 3.12 Package System and Public Library Lifecycle

A major late-stage contribution was transforming workflow sharing into a package-first model with public features.

I built or integrated:

- Workflow package storage tables and service layer.
- Package management API routes.
- Package-aware library and export flows.
- Package metadata persistence and membership graph helpers.
- Publish/remove behavior refinements.
- Public package voting and cloning behavior.
- Public tab refresh/repeatability improvements.
- Public package summary query optimization.
- Read-only public preview modal/canvas/workflow page integration.
- UI controls to enforce read-only restrictions in public mode.

This expanded LEMON from a private editor into a collaborative artifact platform with clearer reuse/public access semantics.

### 3.13 Security and Access Control

I contributed targeted security hardening in final submission stages:

- Secured upload file access using owner checks.
- Separated private upload ownership from public workflow-preview requirements.
- Allowed public preview access where explicitly intended, while keeping sensitive file routes controlled.

This work balanced usability (public preview) with data governance and user isolation.

### 3.14 Reliability, Regression Recovery, and Technical Debt Reduction

A significant part of my contribution was stability-oriented engineering.

I repeatedly handled:

- Regression recovery after merges.
- Canonical workflow ID format restoration.
- Socket/workflow analysis state synchronization fixes.
- Snapshot persistence recovery.
- Removal of dead code paths and stale components.
- Consolidation cleanup after architecture changes.
- Consistency fixes in message/tool metadata handling.

This was not isolated bug-fixing; it was sustained stabilization work that allowed the project to remain shippable while major features were still being integrated.

### 3.15 Testing Contributions

I made substantial direct contributions to testing and quality assurance.

My testing work included:

- Creating and maintaining dozens of backend/unit/integration tests across validation, variable sync, subflow behavior, persistence, route contracts, and package routes.
- Writing tests around state synchronization events and workflow transfer behavior.
- Coverage for output typing, decision logic, and editor mutation invariants.
- Updating test infrastructure and fixing breakage during architecture refactors.

In total, I created many new tests and modified many others to keep parity with evolving architecture. This was critical because large refactors without synchronized tests would have made the platform unreliable near deadline.

---

## 4. Personal Contributions to Website Report

My direct coding and implementation effort was concentrated in system artefacts. My website-report contribution was primarily technical content support and quality alignment rather than owning large static-page edits.

### 4.1 Website Template and Setup

- I supported implementation-side structure decisions that fed into report organization and consistency.
- I contributed cleanup and architecture summaries that made technical content easier to document.

### 4.2 Home and Video Inputs

- I supported technical messaging around platform capabilities and execution flow, which informed what could be demonstrated accurately.

### 4.3 Requirements and Research Inputs

- I maintained issue/fix tracking and architecture notes that informed requirement realism and technical trade-offs.
- I documented known limitations and migration decisions used to justify design choices.

### 4.4 System Design and Implementation Inputs

- I provided most of the underlying technical implementation that these sections describe: routing architecture, workflow tools, execution, validation, import/export, and package/public-library design.
- I also produced implementation-level cleanup that improved diagram/code correspondence.

### 4.5 Testing and Evaluation Inputs

- I contributed a large body of tests and stability fixes, which supported the Testing and Evaluation sections with concrete technical substance.
- I updated issue tracking and reliability notes used for critical evaluation.

### 4.6 Appendices/Technical Documentation Support

- I contributed technical docs and internal notes (execution behavior, architecture changes, issue plans), which supported deployment/maintenance clarity.

Overall, my website-report contribution was strongest in technical content generation and section substance (what could be claimed accurately), with less emphasis on final page-authoring ownership.

---

## 5. Main Difficulties I Faced and How I Overcame Them

### 5.1 Difficulty 1: Keeping Workflow State Consistent Across Systems

The hardest recurring challenge was state consistency across multiple representations:

- backend workflow record,
- frontend workflow store,
- chat/orchestrator context,
- execution context,
- library/public package views.

Symptoms included stale variables, mismatched IDs, preview inconsistencies, and occasional desync between what users saw and what runtime used.

How I overcame it:

1. Standardized ID contracts (canonical workflow ID format and ID-centric architecture).
2. Removed compatibility aliases that allowed divergent representations.
3. Added targeted synchronization logic for socket events and hydration paths.
4. Added tests focused on persistence and state-sync contracts.

Result: state behavior became much more deterministic and debuggable, especially in navigation, save/load, and runtime transitions.

### 5.2 Difficulty 2: Scaling Codebase Complexity in Monolithic Modules

As features accelerated, several files became too large to modify safely (routes, orchestrator config, socket handling, sidebar node config logic). This increased defect risk and slowed parallel development.

How I overcame it:

1. Broke large files into focused modules with clearer boundaries.
2. Introduced shared abstractions to remove repetitive tool boilerplate.
3. Removed dead legacy code aggressively once migration paths were complete.
4. Updated dependent tests and import paths immediately after refactors.

Result: implementation speed improved, merge conflicts became easier to resolve, and bug localization became faster.

### 5.3 Difficulty 3: Balancing Feature Delivery With Stability Near Deadline

In the final phase, we were delivering major functionality (workflow packages, public previews, import/export robustness) while still handling regressions and integration friction.

How I overcame it:

1. Sequenced work in layers: data model/service layer first, then routes, then frontend integration, then UX polish.
2. Added fallback and recovery flows (force-import/import-anyway, placeholder exports, runtime stubs).
3. Performed repeated cleanup passes to reduce hidden fragility from old code paths.
4. Prioritized high-risk flows (public/private boundaries, package operations, validation display consistency).

Result: package/public-library functionality became deliverable and stable enough for demonstration, while preserving quality in core editing/runtime behavior.

### 5.4 Difficulty 4: Integrating Subworkflow and Type Logic Without Breaking Existing Features

Subworkflow composition, derived variables, output typing, and compiler/runtime behavior are tightly connected. Small changes in one layer could break another silently.

How I overcame it:

1. Implemented explicit synchronization for derived variables.
2. Added guards against invalid manual edits to derived state.
3. Ensured output typing propagated through save/load/socket/runtime.
4. Added warning and fail-safe behavior for recursive/missing subflows.

Result: subworkflow and variable systems became coherent enough for both editing and execution workflows.

### 5.5 Difficulty 5: Merge Pressure and Regression Risk

During heavy parallel development, merge pressure caused regressions and duplicated temporary states.

How I overcame it:

1. Ran regression-focused fix passes after major merges.
2. Restored canonical contracts when drift occurred.
3. Used targeted tests and issue lists to verify high-risk behavior.
4. Cleaned and removed obsolete artifacts/components quickly after resolution.

Result: despite high change velocity, we maintained forward progress and converged to a stable final system.

---

## 6. Detailed Contribution Inventory (Compressed but Comprehensive)

This section is a compact inventory of what I implemented or significantly modified across the project lifecycle.

### 6.1 Core Workflow Engine and Validation

- Force-delete parameter handling robustness.
- Cycle and self-loop detection.
- Start node validation.
- Decision-node input strict validation.
- Pre-save/pre-export validation enforcement.
- Validation endpoint consistency after schema changes.
- Library validation exposure and indicator restoration.

### 6.2 Execution and Runtime UX

- Step callbacks in interpreter.
- Socket-based stepped execution events.
- Run/Pause/Stop controls.
- Execution input modal.
- Modal-based execution UI refactor.
- Instant execution mode.
- Execution preparation alignment across entry points.

### 6.3 Variable and Output System

- Unified variable naming and semantics.
- Removal of legacy input aliases.
- Derived variable synchronization and cleanup.
- Guards on derived-variable mutation.
- Output type declaration and propagation.
- End-node output behavior/type preservation.
- Numeric type unification (`number`).

### 6.4 Persistence and Workflow Identity

- User-specific save/load behavior.
- Library delete behavior.
- Workflow listing tooling.
- Workflow-ID-centric architecture.
- Draft handling and save semantics.
- Auto-save and auto-persist behavior.
- Session guard for unsaved state.
- Workflow import into new sessions.

### 6.5 Frontend UX and Interaction

- Canvas zoom improvements and pan/select modes.
- Right sidebar redesign and modular extraction.
- Variable modal and node-property UX.
- Tabbed layout and navigation pages.
- Transition-layer workflow navigation.
- Canvas arrow and hover readability improvements.
- Edge-snapping and rendering performance updates.
- Library/public preview page refinements.

### 6.6 Image and Annotation Pipeline

- Annotation dots rendering.
- Label-based annotation data handling.
- Full-stack annotation transport.
- Image-question orchestration integration.
- Annotation synchronization into workflow store.
- Legacy annotation path removal and cleanup.

### 6.7 Dev Tools and Internal Operability

- Dev tools sidebar integration.
- Tool execution/logging UX.
- Dev tool API listing/export fixes.
- Live state preservation during execution.
- Alignment with orchestrator execution paths.

### 6.8 Backend/Frontend Refactors for Maintainability

- Route module decomposition.
- Orchestrator config decomposition.
- Socket handler decomposition.
- Workflow tool base abstraction.
- Dead code and stale wrapper removal.
- Legacy fallback cleanup.

### 6.9 Import/Export and Transfer Robustness

- Bundle transfer infrastructure.
- Server-owned validation state.
- Force-import and import-anyway flows.
- Retry path for pasted JSON.
- Missing-subflow export placeholders.
- Runtime stubs for missing Python subflows.

### 6.10 Package and Public Library Platform

- Package storage schema and service layer.
- Package management route set.
- Package-aware library/export behavior.
- Metadata persistence and membership graph helpers.
- Publish/remove behavior refinements.
- Voting and cloning improvements.
- Public summary query optimizations.
- Read-only public preview canvas/workflow integration.
- Read-only UI restriction enforcement.

### 6.11 Security and Access Control

- Owner-based file access hardening for uploads.
- Public-preview auth boundary balancing.

### 6.12 Testing and QA

- Added and maintained broad test coverage across:
  - validator behavior,
  - variable synchronization,
  - subflow integration,
  - persistence contracts,
  - workflow transfer routes,
  - package routes/storage,
  - state-sync events,
  - execution/compiler behavior.

---

## 7. Reflection on Contribution Quality and Project Impact

I believe my strongest contribution was not a single isolated feature, but the combination of:

1. Building major capabilities (subflows, variable/output semantics, package/public system),
2. Refactoring key architecture bottlenecks,
3. Stabilizing integration under deadline pressure,
4. Maintaining testing discipline while the system changed rapidly.

In practical terms, this combination helped move the platform from a fragile prototype into a coherent engineering system that could be demonstrated, maintained, and evaluated with confidence.

I also learned that in systems projects, correctness and maintainability are inseparable. Most severe defects were not from missing syntax checks, but from inconsistent ownership of state, partial migrations, and unclear contracts between modules. Much of my work focused on exactly those boundaries.

---

## 8. Optional Statement on Contribution Table Alignment

If needed, I can add a concise statement here to clarify any parts of the team contribution tables that I think under- or over-represent my contribution, with a professional rationale.

Current draft position: my largest contribution is system artefacts (architecture, implementation, stabilization, and testing), with secondary contribution to report content through technical substance and documentation support.
