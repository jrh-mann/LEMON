

**SOFTWARE REQUIREMENTS**

**& SPECIFICATION**

|   |
| :---- |

LEMON

Cloud Surge / Avanade

Prepared for NHS

| Project Name: | LEMON | Version: | 1.0 |
| :---- | :---- | :---- | :---- |
| **Status:** | Draft | **Author:** | Team 27 |
| **Client:** | Cloud Surge / Avanade | **Date:** | 05/02/26 |
| **Reviewed By:** |  | **Approved By:** |  |

# **Version History**

| Version | Date | Author | Changes |
| :---- | :---- | :---- | :---- |
| 1.0 | 05/02/26 | Team 27 | Initial draft |

# **Table of Contents**

[**Version History	2**](#heading=)

[**Table of Contents	3**](#heading=)

[**1\. Introduction	4**](#heading=)

[**1.1 Purpose	4**](#heading=)

[**1.2 Project Overview	4**](#heading=)

[**1.3 Scope	4**](#heading=)

[**1.4 Definitions, Acronyms and Abbreviations	4**](#heading=)

[**1.5 References	4**](#heading=)

[**2\. Stakeholders and Users	5**](#heading=)

[**2.1 Stakeholder Register	5**](#heading=)

[**2.2 User Personas	5**](#heading=)

[**3\. Functional Requirements	6**](#heading=)

[**3.1 Workflow Creation and Editing	6**](#heading=)

[**3.2 Data Processing	6**](#heading=)

[**3.3 Shared Library	7**](#heading=)

[**4\. Non-Functional Requirements	8**](#heading=)

[**4.1 Performance	8**](#heading=)

[**4.2 Non-Functional Requirements Summary	8**](#heading=)

[**5\. Data Requirements	9**](#heading=)

[**5.1 Data Requirements	9**](#heading=)

[**6\. Constraints and Assumptions	10**](#heading=)

[**6.1 Constraints	10**](#heading=)

[**6.2 Assumptions and Dependencies	10**](#heading=)

[**6.3 Risks	10**](#heading=)

[**7\. Acceptance Criteria and Testing Strategy	11**](#heading=)

[**7.1 Acceptance Criteria	11**](#heading=)

[**7.2 Testing Approach	11**](#heading=)

[**8\. Glossary	12**](#heading=)

[**9\. Appendices	12**](#heading=)

[**Document Sign-Off	12**](#heading=)  
*Right-click and select 'Update Field' in Word to populate the table of contents.*

# **1\. Introduction**

## **1.1 Purpose**

This Document will specify the features, constraints, and goals of the LEMON system as agreed by Cloud Surge, Avanade, and UCL.

## **1.2 Project Overview**

The project is an attempt to simplify the formalisation, storage, and sharing of medical knowledge in a safe and quick manner’; allowing doctors to create rich workflows that represent best practices and common methods. The workflows will be peer reviewed before being eligible for use by others, ensuring safety. The value proposition is the speed that it allows information to be recorded at. Whereas previously doctors have had to explain a workflow to someone technical, they can now specify the program themselves without knowledge of programming. Large datasets can be run against the workflows automatically  providing the benefit of automatic preliminary diagnoses on large populations quickly.

## **1.3 Scope**

The project will cover a number of systems. There will be a workflow editor; a chatbot which allows users to record systems;a library of workflows that can be ‘peer reviewed’ and shared with other users; a system to run the workflows against large datasets quickly. Apart from the ability to run the workflows on data, the platform will not have any substantial data storage or manipulation abilities.

## **1.4 Definitions, Acronyms and Abbreviations**

| Term | Definition |
| :---- | :---- |
| **LEMON** | *The name given to the whole system, including every feature and the frontend website.* |
| **Workflow** | *A logic flowchart defined by a doctor on the LEMON platform. Can contain mathematical expressions, as well as the usual flowchart components.* |
| **The orchestrator** | *The chatbot that the doctor will interface with in order to create workflows. Can delegate sub tasks taken from the user’s prompt to sub-agents. An LLM.* |
| **Sub-agents** | *LLMs that can have tasks delegated to them by the orchestrator. They complete sub tasks like ‘analyse this image’, ‘add this node’, etc.* |

## 

## 

## 

## 

## **1.5 References**

# **2\. Stakeholders and Users**

## **2.1 Stakeholder Register**

| Stakeholder | Role | Contact |
| :---- | :---- | :---- |
| Cloud Surge | Project Supervisor | ilyas@cloudsurge.uk |
| Avanade | Advisor and Facilitator | tarun.b.arora@avanade.com |
| UCL | Project Supervisor | yun.fu@ucl.ac.uk |

## **2.2 User Personas**

The primary user will be a doctor (GP) who wants to quickly assess patient data using a system they already have knowledge of, or one that they find on the platform and trust. They will have limited technical ability, but strong knowledge of the medical domain. They will interface with the system on the website, primarily through the orchestrator chat window.

LEMON will be used by both GPs, for workflow creation, and administrative staff, for applying the executable workflows to patient records to surface high level statistics and automate diagnosis

# **3\. Functional Requirements**

Must / Should / Could / Won’t

## **3.1 Workflow Creation and Editing**

Covers the creation of workflows through the editor and orchestrator.

| Req ID | Requirement Description | Priority |
| :---- | :---- | :---- |
| FR1-001 | The user will utilise the orchestrator to autonomously analyse images of pre-existing workflows that are to be created in the editor. | **Must** |
| FR1-002 | The user will create (define) and edit workflows in the visual editor. | **Must** |
| FR1-003 | The user will export workflows in multiple data formats. Export formats will include JSON, Python, and PNG. | **Should** |
| FR1-004 | The user will utilise the orchestrator to create and edit workflows from scratch using plain english. | **Must** |
| FR1-005 | The user will utilise the orchestrator to reason about workflows as they are created to ensure accuracy. | **Must** |
| FR1-006 | The user will define the input variables of a workflow by hand and autonomously through the orchestrator. | **Must** |
| FR1-007 | The user will create and edit multiple workflows using the workflow tabs. | **Must** |
| FR1-008 | The user will define mathematical formulas to aid workflow logic by hand and autonomously through the orchestrator. | **Must** |
| FR1-009 | The user will be able to watch the execution of a workflow in the editor using a set, manually inputted, patient’s data. | **Must** |

## **3.2 Data Processing**

Covers the processing of data-sets against the workflows.

| Req ID | Requirement Description | Priority |
| :---- | :---- | :---- |
| FR2-001 | The user will upload patient data in CSV format to be processed through an existing workflow on the platform. | **Must** |
| FR2-002 | The user will view the result of a batch run of data and review the mapping of patients to results to ensure accuracy. | **Must** |
| FR2-003 | The user may upload disparate and separated data in multiple CSV files which will be intelligently combined by the system to be run against the workflows. | **Should** |
| FR2-004 | The user will manually define the mapping of column/data name in the files to input in the workflow to ensure accuracy. | **Must** |
| FR2-005 | Workflows will be compiled into C code in the backend for batch running for speed. | **Should** |

## **3.3 Shared Library**

Covers the sharing and peer review features that allow doctors to publish workflows.

| Req ID | Requirement Description | Priority |
| :---- | :---- | :---- |
| FR3-001 | The user will choose to save their workflows to their local library for future edits, data execution, and sharing. | **Must** |
| FR3-002 | The user will choose to publish their workflow to the shared library. | **Must** |
| FR3-003 | Newly published workflows will remain in a probation state until they receive the necessary amount of net positive votes to be published. | **Must** |
| FR3-004 | The user will upvote and downvote published workflows (even ones past the probation phase to indicate satisfaction with accuracy and techniques. | **Must** |
| FR3-005 | The user will comment on published workflows to make suggestions to the publisher for logic changes. | **Must** |
| FR3-006 | The user will browse the shared library for workflows to extend, edit, and execute data on. | **Must** |

# **4\. Non-Functional Requirements**

## **4.1 Performance**

The system should be able to handle many concurrent users, and thousands of workflows running at once (helped by workflow compilation to C). The orchestrator should have response times less than one minute.

## **4.2 Non-Functional Requirements Summary**

| Req ID | Requirement | Acceptance Criteria | Priority |
| :---- | :---- | :---- | :---- |
| NFR-001 | System response time \< 2s | Average orchestrator response time under two seconds. | **Should** |
| NFR-002 | 99.9% uptime during core hours for data processing | Uptime as registered on Azure. | **Should** |

# **5\. Data Requirements**

## **5.1 Data Requirements**

The system will not store patient data long term (after an individual session ends) except for the workflows created on, and shared to the platform. Images of workflows can be uploaded to the orchestrator, but are disposed of after consumption and workflow generation.

The system will allow users to upload large datasets of information about patients in CSV files. This data will be sent to, and processed on the LEMON server before it is run through a compiled version of a LEMON workflow. The data will not persist on the server after a workflow execution, nor will the results of the execution.

Workflows can be kept private by users and need not be uploaded to the shared library. If a workflow is uploaded to the shared library, then it is kept in a preview tab until approved by the appropriate amount of peers. At that point, it is available for everyone to use on the website.

# **6\. Constraints and Assumptions**

## **6.1 Constraints**

The system will be developed over 3 months by a team of 4 developers. The team will have access to cloud resources through Avanade which will allow a production MVP. Use of LLM APIs is costly, and could bump up against budget constraints if the system is heavily used.

## **6.2 Assumptions and Dependencies**

The project assumes steady access to the Anthropic API. It also assumes uptime from Azure, where the project is to be hosted.

## **6.3 Risks**

| Risk ID | Description | Likelihood | Impact | Mitigation |
| :---- | :---- | :---- | :---- | :---- |
| R-001 | Identifiable patient data leak | Low | Very High | Patient data **won’t** be stored long term on the server. Patient data **should** be anonymised. |
| R-002 | Abuse of access to LLM | High | Medium | Messages **must** be checked against a usage policy as they are sent to the orchestrator to prevent prompt injection and other malicious usage. |
| R-003 | Incorrect or malicious workflows | Medium | High | Peer review **must** have a high barrier (of net positive votes) for workflows that are to be published to the shared library, to prevent patient data being incorrectly processed. |

# **7\. Acceptance Criteria and Testing Strategy**

## **7.1 Acceptance Criteria**

The project will be accepted following a thorough fulfilment of each feature and requirement unless alternatively agreed otherwise. Cloud Surge will be the primary point of contact for approval.

## **7.2 Testing Approach**

Workflow creation will be tested against existing workflows (from GPs) that can be treated as a ground truth. Data will be processed through them to test the orchestrators accuracy. In this way, data processing can also be evaluated. The remaining features are mostly quality of life or frontend simple data manipulation and can be tested with unit tests as well as by hand with reports made for each.

Clinical safety is a priority for this project so the accuracy of workflows and correct diagnoses and advice must be ensured through conscientious system design.

# **8\. Glossary**

*\[Additional terms not covered in Section 1.4.\]*

# **9\. Appendices**

*\[Supporting material: wireframes, process flows, data models, meeting notes, etc.\]*

# **Document Sign-Off**

By signing below, the undersigned confirm that this requirements specification has been reviewed and approved.

| Name | Role | Signature | Date |
| :---- | :---- | :---- | :---- |
|  |  |  |  |

