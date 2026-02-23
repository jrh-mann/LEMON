# Image Eval Diagnostics: iter0_baseline

## Bucket Counts

- missed node: 9
- extra hallucinated node: 9
- wrong branch direction/label: 9
- variable extraction miss: 9
- ambiguity unresolved: 9

## Per-Case Bucket Distribution

### diabetes_treatment
- missed node: 3
- extra hallucinated node: 3
- wrong branch direction/label: 3
- variable extraction miss: 3
- ambiguity unresolved: 3

### liver_pathology
- missed node: 3
- extra hallucinated node: 3
- wrong branch direction/label: 3
- variable extraction miss: 3
- ambiguity unresolved: 3

### workflow_test
- missed node: 3
- extra hallucinated node: 3
- wrong branch direction/label: 3
- variable extraction miss: 3
- ambiguity unresolved: 3

## Trial Notes

### workflow_test trial 1 - composite 20.78
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The exact threshold for 'Normal' total cholesterol is stated as ≤5 or below but noted to vary from clinic to clinic. The precise value used in decision logic is unclear.; The diagram shows 'Under Specialist Clinic?' leading to either 'No Further Action' (Yes branch) or to 'Primary/Secondary Treatment' (No branch). It is unclear at what point in the workflow this decision occurs relative to 'Assess Total Cholesterol Result'—it appears to be a preliminary check but spatial layout suggests it might be evaluated in parallel or after initial assessment.; The workflow references 'Are They Optimised on treatment?' in both Primary and Secondary prevention contexts. The diagram shows this decision branching differently depending on context, but the exact input or measurement criteria for 'optimised' is not explicitly defined.; The node 'Assess LDL' leads to multiple LDL-based decisions (LDL 2-2.5, LDL ≥2.6, LDL <2, LDL ≥2.0). The exact branching logic and order of evaluation for these thresholds is ambiguous and may overlap.; The 'Initiate Inclisiran' output depends on the patient having had 6 months of Inclisiran, but the workflow does not specify an input for this time-based condition. It is unclear if this is an implicit state or requires an additional input.

### workflow_test trial 2 - composite 17.06
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The node 'Add in Ezetimibe' appears twice (n18 and n19) as separate branches - should these converge or lead to different outcomes?; The QRISK2/3 calculation node leads to different pathways based on percentage thresholds (≥10%, <10%) shown in the diagram, but the exact branching logic after 'Calculate QRISK2/3' is unclear - should there be a decision node for QRISK percentage ranges?; The 'Assess LDL' node appears to have multiple threshold branches (LDL ≥2.6, LDL 2-2.5, LDL <2) leading to different outputs ('Send Lipid Lowering Acute', 'Send High Cholesterol Low QRISK', 'No Further Action') - the tree structure should branch here but is not fully clear from the visual layout; The 'Primary or Secondary Prevention?' action node should likely be a decision node with two branches (Primary/Secondary) leading to different paths - one to QRISK calculation and one to Maximally Tolerated Statin check; Some yellow sticky notes contain additional context (e.g., 'not coded, assume no', 'We assume Normal to be 5 or below', 'Primary/Secondary Treatment') - should these inform the decision logic or input constraints?

### workflow_test trial 3 - composite 17.21
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The workflow shows multiple branches from 'Calculate QRISK2/3' but the exact QRISK threshold routing is ambiguous in the diagram - I've interpreted ≥10% routes and <10% routes based on visible labels; The 'Repeat Lipids at 3 months' node appears to loop back to LDL assessment but the exact flow after repeat measurement is not completely clear from the diagram; Some output nodes have similar names (e.g., multiple 'Send Lipid Lowering Therapy Acute with self booking link') - I've distinguished them by context (Primary/Secondary/general); The exact threshold for 'Normal' vs 'Raised' cholesterol is not specified numerically in the diagram

### diabetes_treatment trial 1 - composite 12.04
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The 'Or' labels between Gliptin, Pioglitazone, and Gliclazide suggest these are alternative choices, not parallel outputs. Should these be modeled as a decision node with three branches instead of multiple outputs?; The flow from 'Metformin + Gliptin/Pioglitazone/Gliclazide' leads to 'Add GLP' and then splits to 'High prognostic value → Ozempic' and 'Low prognostic Value → Mounjaro'. It's unclear if 'Add GLP' is a separate output or an intermediate action before the prognostic value decision.; The 'SGLT2i' node appears both as a tolerated add-on branch and is mentioned in the triple therapy note '(consider SGLT2i)'. The exact flow and decision points are ambiguous.; The 'Metformin' output labeled 'Not at risk of CVD' appears as an intermediate step with further downstream decisions, not a terminal output. Should this be modeled as an action node instead?; There appears to be a 'Despite Optimisation and maximally tolerated dose A1c >58' condition leading to 'Refer to Insulin Initiator', but the exact decision point and parent node in the flow is unclear from the diagram.

### diabetes_treatment trial 2 - composite 10.93
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The diagram shows 'A1c Not Controlled Start Triple Therapy' followed by triple therapy options (Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)), then 'Add GLP'. The path then splits to 'High prognostic value' → Ozempic and 'Low prognostic Value' → Mounjaro. After this point, the diagram shows 'Despite Optimisation and maximally tolerated dose A1C >58' → Refer to Insulin Initiator. It is unclear whether the prognostic value decision and Ozempic/Mounjaro prescriptions are part of the triple therapy flow or if they represent alternative endpoints. The tree structure is ambiguous here.; The 'Or' connectors between Gliptin, Pioglitazone, and Gliclazide suggest mutually exclusive choices, but the diagram does not clearly indicate if all three are outputs or if one must be selected via an upstream decision.; It is unclear if the 'A1c Not Controlled Start Triple Therapy' node should lead to multiple medication outputs (Metformin + Gliptin/Pioglitazone/Gliclazide), or if there should be a decision node to choose among them.; The 'Add GLP' action followed by prognostic value decision suggests that GLP (Ozempic or Mounjaro) is added on top of triple therapy if A1c is still not controlled. However, the diagram does not explicitly show this as a conditional branch, making the exact workflow unclear.; The two separate SGLT2i nodes (one for tolerated metformin and one for not tolerated) both lead to the same Ozempic titration flow, but it's unclear if they should be represented as distinct paths in the tree or consolidated.

### diabetes_treatment trial 3 - composite 11.15
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The diagram shows 'Not tolerated** switch to' from Metformin, but the destination is unclear. It appears to loop back to SGLT2i, but the workflow structure is ambiguous.; After the dual therapy (Gliptin/Pioglitazone/Gliclazide), there is a 'A1c Not Controlled Start Triple Therapy' node that leads to triple therapy, then branches to 'Add GLP' and prognostic value decisions (High/Low), leading to Ozempic/Mounjaro, which eventually loops back to 'Refer to Insulin Initiator'. This creates a complex flow that's difficult to represent as a single rooted tree without creating disconnected paths or cycles.; The 'Or' nodes between Gliptin, Pioglitazone, and Gliclazide suggest these are alternative options, but the tree structure requires each to be a separate child of the decision node.; The prognostic value decision (High/Low) appears to determine whether to use Ozempic or Mounjaro, but the exact condition for this decision is not explicitly stated in terms of inputs.

### liver_pathology trial 1 - composite 6.83
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The workflow has multiple parallel paths that eventually converge, but the image structure suggests some actions (like Mandatory Testing, Conditional Testing, and various screening tests) may run in parallel or have dependencies that aren't clearly shown by single-parent tree structure.; The exact branching logic for 'Need to rationalise which additional tests should be done for rare conditions' is unclear - it appears to have a Yes path and an alternate path, but the conditions aren't explicitly labeled.; The flow from 'Manage risk factors and co-morbidities. Annual Screening' to 'Intermediate or High Risk' suggests a sequential relationship, but it's unclear if this is a decision point or a continuation.; Multiple testing nodes (Wilsons Disease Screen, Transferrin test, Haemochromatosis, Primary Biliary Cirrhosis, Autoimmune Hepatitis screens) appear to be parallel actions under Mandatory Testing, but the tree structure requires sequential representation.; The 'NAFLD Fibrosis Score Categories' decision appears to have multiple outcomes but the exact branching structure and how it relates to FIB-4 categories is ambiguous.

### liver_pathology trial 2 - composite 9.1
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The workflow diagram has multiple parallel paths and complex interconnections that make it difficult to represent as a single rooted tree. Some nodes appear to converge from multiple sources.; The exact flow between 'Phase 3', 'FIB 4 Score & NAFLD Fibrosis Score', and subsequent decision points is unclear due to overlapping paths.; Some text in the diagram is too small or unclear to read precisely (e.g., some labels in conditional testing section).; The relationship between the three knowledge summary boxes (Repeating LFTs, Initial consultation, Additional testing) and the main workflow is unclear.; The 'Phase 4 Bloods' section appears twice in the diagram with different contexts, making the tree structure ambiguous.

### liver_pathology trial 3 - composite 3.65
- Buckets: missed node, extra hallucinated node, wrong branch direction/label, variable extraction miss, ambiguity unresolved
- Doubts: The workflow has multiple parallel paths after 'Baseline & Phase 2 Bloods' that are not clearly connected in a single tree structure. I've attempted to represent the main decision flow, but some parallel testing paths (Phase 3, Phase 4) may not be accurately represented as a strict tree.; The connection between 'FIB 4 Score & NAFLD Fibrosis Score' and subsequent decision nodes is complex with multiple interweaving paths that don't form a strict tree structure. Some nodes appear to have multiple parents.; The 'Phase 4 Bloods' node appears multiple times in the diagram at different locations, making it unclear whether these should be represented as separate nodes or the same node with multiple incoming edges (which would violate tree structure).; The exact conditions for when 'Fibroscan Scan if available' leads to 'Phase 4 Bloods' versus other outcomes are not clearly labeled with edge conditions.; Some testing procedures in Phase 3 and Phase 4 appear to run in parallel rather than sequentially, which is difficult to represent in a strict tree structure.
