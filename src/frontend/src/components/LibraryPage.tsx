import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import {
  addWorkflowToPackage,
  applyPackageAutofetch,
  clonePackage,
  createPackage,
  deletePackage,
  deleteWorkflow,
  getPackage,
  getPublicPackage,
  getPublicPackageWorkflow,
  listPackages,
  listPublicWorkflows,
  previewPackageAutofetch,
  listWorkflows,
  publishPackage,
  removeWorkflowFromPackage,
  setPackageHead,
  updatePackage,
  voteOnWorkflow,
} from '../api/workflows'
import type { WorkflowPackage, WorkflowSummary } from '../types'
import '../styles/LibraryPage.css'

type BrowserTab = 'mine' | 'published' | 'peer_review'

export default function LibraryPage() {
  const navigate = useNavigate()
  const { setZoomingCard, setZoomPhase } = useUIStore()
  const currentWorkflowId = useWorkflowStore(s => s.currentWorkflow?.id)
  const libraryRefreshTrigger = useWorkflowStore(s => s.libraryRefreshTrigger)

  const [activeTab, setActiveTab] = useState<BrowserTab>('mine')
  const [myWorkflows, setMyWorkflows] = useState<WorkflowSummary[] | null>(null)
  const [myPackages, setMyPackages] = useState<WorkflowPackage[] | null>(null)
  const [publicWorkflows, setPublicWorkflows] = useState<WorkflowSummary[] | null>(null)
  const [peerReviewWorkflows, setPeerReviewWorkflows] = useState<WorkflowSummary[] | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [selectedPackage, setSelectedPackage] = useState<WorkflowPackage | null>(null)
  const [draggedWorkflowId, setDraggedWorkflowId] = useState<string | null>(null)
  const [packageError, setPackageError] = useState<string | null>(null)
  const [autofetchPreview, setAutofetchPreview] = useState<{ additions: Array<Record<string, string>>; conflicts: Array<Record<string, string>> } | null>(null)
  const [selectedPublicPackage, setSelectedPublicPackage] = useState<WorkflowPackage | null>(null)
  const [selectedPublicWorkflowPreview, setSelectedPublicWorkflowPreview] = useState<{ id: string; metadata: { name: string; description: string; domain?: string; tags: string[]; is_validated: boolean }; output_type: string; variables: Array<{ name: string; type?: string }>; outputs: Array<{ name: string; type?: string }>; nodes: Array<unknown>; edges: Array<unknown> } | null>(null)

  const refreshPublicTabs = useCallback(async () => {
    const [published, review] = await Promise.all([
      listPublicWorkflows('reviewed'),
      listPublicWorkflows('unreviewed'),
    ])
    setPublicWorkflows(published.workflows)
    setPeerReviewWorkflows(review.workflows)
  }, [])

  const fetchMine = useCallback(async () => {
    const [workflows, packages] = await Promise.all([listWorkflows(), listPackages()])
    setMyWorkflows(workflows)
    setMyPackages(packages)
  }, [])

  const fetchTabData = useCallback(async (tab: BrowserTab) => {
    if (tab === 'mine' && myWorkflows !== null && myPackages !== null) return

    setIsLoading(true)
    try {
      if (tab === 'mine') {
        await fetchMine()
      } else {
        await refreshPublicTabs()
      }
    } finally {
      setIsLoading(false)
    }
  }, [fetchMine, myPackages, myWorkflows, refreshPublicTabs])

  useEffect(() => { fetchTabData(activeTab) }, [activeTab, fetchTabData])
  useEffect(() => {
    if (libraryRefreshTrigger === 0) return
    setMyWorkflows(null)
    setMyPackages(null)
    setPublicWorkflows(null)
    setPeerReviewWorkflows(null)
  }, [libraryRefreshTrigger])

  const refreshActiveTab = useCallback(async () => {
    setIsLoading(true)
    try {
      if (activeTab === 'mine') {
        await fetchMine()
        if (selectedPackage?.id) {
          setSelectedPackage(await getPackage(selectedPackage.id))
        }
      } else {
        await refreshPublicTabs()
        if (selectedPublicPackage?.id) {
          setSelectedPublicPackage(await getPublicPackage(selectedPublicPackage.id))
        }
      }
    } finally {
      setIsLoading(false)
    }
  }, [activeTab, fetchMine, refreshPublicTabs, selectedPackage, selectedPublicPackage])

  const applyVoteToLists = useCallback((packageId: string, vote: { net_votes: number; review_status: 'unreviewed' | 'reviewed'; user_vote: number | null }) => {
    const updateList = (list: WorkflowSummary[] | null) => (list || []).map(item =>
      item.id === packageId
        ? { ...item, net_votes: vote.net_votes, review_status: vote.review_status, user_vote: vote.user_vote }
        : item
    )
    setPublicWorkflows(updateList)
    setPeerReviewWorkflows(updateList)
    setSelectedPublicPackage(current => current && current.id === packageId
      ? { ...current, net_votes: vote.net_votes, review_status: vote.review_status, user_vote: vote.user_vote }
      : current)
  }, [])

  const handleVote = useCallback(async (packageId: string, currentVote: number | null | undefined, nextVote: 1 | -1) => {
    const resolvedVote = currentVote === nextVote ? 0 : nextVote
    const response = await voteOnWorkflow(packageId, resolvedVote)
    applyVoteToLists(packageId, response)
    await refreshPublicTabs()
    if (selectedPublicPackage?.id === packageId) {
      setSelectedPublicPackage(await getPublicPackage(packageId))
    }
  }, [applyVoteToLists, refreshPublicTabs, selectedPublicPackage])

  const filterBySearch = useCallback((name: string, description: string, tags: string[]) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return (name || '').toLowerCase().includes(q) || (description || '').toLowerCase().includes(q) || (tags || []).some(tag => tag.toLowerCase().includes(q))
  }, [searchQuery])

  const visibleWorkflows = useMemo(() => (myWorkflows || []).filter(wf => filterBySearch(wf.name, wf.description, wf.tags)), [filterBySearch, myWorkflows])
  const visiblePackages = useMemo(() => (myPackages || []).filter(pkg => filterBySearch(pkg.name || 'Empty package', pkg.description, pkg.workflows.flatMap(wf => wf.tags))), [filterBySearch, myPackages])

  const workflowReturnPath = currentWorkflowId ? `/workflow/${currentWorkflowId}` : '/workflow'

  const handleSelectWorkflow = useCallback((workflowSummary: { id: string; name: string }, e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setZoomingCard({ id: workflowSummary.id, title: workflowSummary.name, rect })
    setTimeout(() => {
      navigate(`/workflow/${workflowSummary.id}`)
      setTimeout(() => setZoomPhase('fading'), 50)
    }, 150)
  }, [navigate, setZoomPhase, setZoomingCard])

  const handleCreatePackage = useCallback(async () => {
    const created = await createPackage({})
    setSelectedPackage(created)
    await refreshActiveTab()
  }, [refreshActiveTab])

  const handleDropWorkflow = useCallback(async (packageId: string) => {
    if (!draggedWorkflowId) return
    try {
      await addWorkflowToPackage(packageId, draggedWorkflowId)
      await refreshActiveTab()
    } catch (error) {
      setPackageError(error instanceof Error ? error.message : 'Failed to move workflow')
    } finally {
      setDraggedWorkflowId(null)
    }
  }, [draggedWorkflowId, refreshActiveTab])

  const packageCards = activeTab === 'mine' ? visiblePackages : []
  const packageMemberIds = new Set(packageCards.flatMap(pkg => pkg.workflows.map(wf => wf.id)))
  const standaloneWorkflows = visibleWorkflows.filter(wf => !packageMemberIds.has(wf.id))

  return (
    <div className="library-page">
      <header className="library-header">
        <div className="library-header-left">
          <button className="ghost library-back-btn" onClick={() => navigate(workflowReturnPath)}>Back</button>
          <div className="logo"><span className="logo-mark">L</span><span className="logo-text">LEMON</span></div>
        </div>
        <h1 className="library-title">Library</h1>
        <div className="library-header-right" />
      </header>

      <div className="library-body">
        <div className="library-tabs">
          {(['mine', 'published', 'peer_review'] as BrowserTab[]).map(tab => (
            <button key={tab} className={`library-tab ${activeTab === tab ? 'active' : ''}`} onClick={() => setActiveTab(tab)}>
              {tab === 'mine' ? 'My Library' : tab === 'published' ? 'Published' : 'Peer Review'}
            </button>
          ))}
          {activeTab === 'mine' && <div className="library-tabs-spacer" />}
          {activeTab === 'mine' && <button className="primary library-new-package-btn" onClick={handleCreatePackage}>New Package</button>}
        </div>

        <div className="library-search">
          <input type="text" placeholder="Search workflows and packages..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
        </div>
        {packageError && <p className="error-text">{packageError}</p>}

        {activeTab === 'mine' ? (
          <div className="library-grid">
            {packageCards.map(pkg => (
              <div
                key={pkg.id}
                className="library-card"
                onClick={() => setSelectedPackage(pkg)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => handleDropWorkflow(pkg.id)}
              >
                <div className="library-card-header">
                  <h3 className="library-card-name">{pkg.name || 'Empty package'}</h3>
                </div>
                <p className="library-card-desc">{pkg.head_workflow_id ? `Head workflow set` : 'No head workflow yet'}</p>
                <div className="library-card-meta">
                  <span className="library-card-domain">Package</span>
                  <span className="library-card-tag">{pkg.workflow_count} workflows</span>
                </div>
              </div>
            ))}
            {standaloneWorkflows.map(wf => (
              <div key={wf.id} className="library-card" draggable onDragStart={() => setDraggedWorkflowId(wf.id)} onClick={(e) => handleSelectWorkflow(wf, e)}>
                <div className="library-card-header">
                  <h3 className="library-card-name">
                    {wf.name}
                    {wf.building && <span className="library-card-building">Building...</span>}
                  </h3>
                  <button className="library-card-delete" onClick={async (e) => {
                    e.stopPropagation()
                    if (deleteConfirm === wf.id) {
                      await deleteWorkflow(wf.id)
                      setDeleteConfirm(null)
                      await refreshActiveTab()
                    } else {
                      setDeleteConfirm(wf.id)
                      setTimeout(() => setDeleteConfirm(null), 3000)
                    }
                  }}>{deleteConfirm === wf.id ? '✓ Confirm' : '✕'}</button>
                </div>
                {wf.description && <p className="library-card-desc">{wf.description}</p>}
                <div className="library-card-meta">
                  {wf.tags.slice(0, 3).map(tag => <span key={tag} className="library-card-tag">{tag}</span>)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="library-grid">
            {((activeTab === 'published' ? publicWorkflows : peerReviewWorkflows) || []).map(wf => (
              <div key={wf.id} className="library-card" onClick={async () => setSelectedPublicPackage(await getPublicPackage(wf.id))}>
                <div className="library-card-header"><h3 className="library-card-name">{wf.name}</h3></div>
                {wf.description && <p className="library-card-desc">{wf.description}</p>}
                <div className="library-card-meta">
                  {(wf.tags || []).slice(0, 3).map(tag => <span key={tag} className="library-card-tag">{tag}</span>)}
                </div>
                {
                  <div className="library-card-votes">
                    <button className={`vote-btn ${wf.user_vote === 1 ? 'voted' : ''}`} onClick={async (e) => { e.stopPropagation(); await handleVote(wf.id, wf.user_vote, 1) }}>▲</button>
                    <span className="vote-count">{(wf.net_votes || 0) > 0 ? `+${wf.net_votes}` : wf.net_votes || 0}</span>
                    <button className={`vote-btn down ${wf.user_vote === -1 ? 'voted' : ''}`} onClick={async (e) => { e.stopPropagation(); await handleVote(wf.id, wf.user_vote, -1) }}>▼</button>
                  </div>
                }
              </div>
            ))}
          </div>
        )}
      </div>

      {selectedPackage && (
        <div className="modal">
          <div className="modal-backdrop" onClick={() => setSelectedPackage(null)} />
          <div className="modal-content">
            <div className="modal-header">
              <h3>{selectedPackage.name || 'Empty package'}</h3>
              <button className="modal-close" onClick={() => setSelectedPackage(null)}>x</button>
            </div>
            <div className="modal-body">
              <p className="muted">{selectedPackage.workflow_count === 0 ? 'Empty package' : `Head workflow: ${selectedPackage.workflows.find(wf => wf.role === 'head')?.name || 'Not set'}`}</p>
              {selectedPackage.workflow_count > 0 && (
                <>
                  <h4>{selectedPackage.workflows.find(wf => wf.role === 'head')?.name || 'Head workflow'}</h4>
                  <p className="muted">{selectedPackage.workflows.find(wf => wf.role === 'head')?.description || 'No description'}</p>
                </>
              )}
              {selectedPackage.issues?.length ? <div className="validation-warning"><ul>{selectedPackage.issues.map(issue => <li key={`${issue.code}-${issue.workflow_id || issue.message}`}>{issue.message}</li>)}</ul></div> : null}
              <div className="library-grid">
                {selectedPackage.workflows.map(workflow => (
                  <div key={workflow.id} className="library-card" onClick={(e) => handleSelectWorkflow(workflow, e as unknown as React.MouseEvent)}>
                    <div className="library-card-header">
                      <h3 className="library-card-name">
                        {workflow.name}
                        {workflow.building && <span className="library-card-building">Building...</span>}
                      </h3>
                    </div>
                    <p className="library-card-desc">{workflow.description || 'No description'}</p>
                    <div className="library-card-meta">
                      {workflow.tags.map(tag => <span key={tag} className="library-card-tag">{tag}</span>)}
                      <span className="library-card-domain">{workflow.role === 'head' ? 'Head workflow' : 'Dependency'}</span>
                      {workflow.invalid_public && <span className="library-card-tag">Not validated</span>}
                    </div>
                    <div className="form-actions">
                      {workflow.role !== 'head' && <button className="ghost" onClick={async (e) => { e.stopPropagation(); setSelectedPackage(await setPackageHead(selectedPackage.id, workflow.id)) }}>Set as head workflow</button>}
                      <button className="ghost" onClick={async (e) => { e.stopPropagation(); setSelectedPackage(await removeWorkflowFromPackage(selectedPackage.id, workflow.id)) }}>Remove</button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="form-actions">
                <button className="ghost" onClick={async () => { await deletePackage(selectedPackage.id); setSelectedPackage(null); await refreshActiveTab() }}>Delete Package</button>
                {selectedPackage.head_workflow_id && <button className="ghost" onClick={async () => {
                  const preview = await previewPackageAutofetch(selectedPackage.id)
                  setAutofetchPreview(preview)
                }}>Automatically fetch all subflows</button>}
                <button className="primary" onClick={async () => {
                  if (selectedPackage.is_published) return
                  try {
                    setSelectedPackage(await publishPackage(selectedPackage.id))
                  } catch (error) {
                    const message = error instanceof Error ? error.message : 'Publish failed'
                    if (message.toLowerCase().includes('not validated') || message.toLowerCase().includes('draft')) {
                      const proceed = confirm(`${message}\n\nPublish anyway?`)
                      if (proceed) {
                        setSelectedPackage(await publishPackage(selectedPackage.id, true))
                      }
                    } else {
                      setPackageError(message)
                    }
                  }
                }}>{selectedPackage.is_published ? 'Already published!' : 'Publish Package'}</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {selectedPublicPackage && (
        <div className="modal">
          <div className="modal-backdrop" onClick={() => setSelectedPublicPackage(null)} />
          <div className="modal-content">
            <div className="modal-header">
              <h3>{selectedPublicPackage.name || 'Package'}</h3>
              <button className="modal-close" onClick={() => setSelectedPublicPackage(null)}>x</button>
            </div>
            <div className="modal-body">
              <p className="muted">Head workflow: {selectedPublicPackage.workflows.find(wf => wf.role === 'head')?.name || 'Not set'}</p>
              <div className="library-card-votes">
                <button className={`vote-btn ${selectedPublicPackage.user_vote === 1 ? 'voted' : ''}`} onClick={async () => {
                  await handleVote(selectedPublicPackage.id, selectedPublicPackage.user_vote, 1)
                }}>▲</button>
                <span className="vote-count">{(selectedPublicPackage.net_votes || 0) > 0 ? `+${selectedPublicPackage.net_votes}` : selectedPublicPackage.net_votes || 0}</span>
                <button className={`vote-btn down ${selectedPublicPackage.user_vote === -1 ? 'voted' : ''}`} onClick={async () => {
                  await handleVote(selectedPublicPackage.id, selectedPublicPackage.user_vote, -1)
                }}>▼</button>
              </div>
              <div className="library-grid">
                {selectedPublicPackage.workflows.map(workflow => (
                  <div key={workflow.id} className="library-card" onClick={async () => setSelectedPublicWorkflowPreview(await getPublicPackageWorkflow(selectedPublicPackage.id, workflow.id))}>
                    <div className="library-card-header"><h3 className="library-card-name">{workflow.name}</h3></div>
                    <p className="library-card-desc">{workflow.description || 'No description'}</p>
                    <div className="library-card-meta">
                      {workflow.tags.map(tag => <span key={tag} className="library-card-tag">{tag}</span>)}
                      <span className="library-card-domain">{workflow.role === 'head' ? 'Head workflow' : 'Dependency'}</span>
                      {workflow.invalid_public && <span className="library-card-tag">Not validated</span>}
                    </div>
                  </div>
                ))}
              </div>
              <div className="form-actions">
                <button className="primary" onClick={async () => {
                  const cloned = await clonePackage(selectedPublicPackage.id)
                  setSelectedPublicPackage(null)
                  setActiveTab('mine')
                  await fetchMine()
                  setSelectedPackage(cloned)
                }}>Clone to My Library</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {selectedPackage && autofetchPreview && (
        <div className="modal">
          <div className="modal-backdrop" onClick={() => setAutofetchPreview(null)} />
          <div className="modal-content">
            <div className="modal-header">
              <h3>Auto-fetch subflows</h3>
              <button className="modal-close" onClick={() => setAutofetchPreview(null)}>x</button>
            </div>
            <div className="modal-body">
              <p>{autofetchPreview.additions.length} workflows will be added.</p>
              {autofetchPreview.conflicts.length > 0 && (
                <div className="validation-warning">
                  <p>These workflows are already in another package and will be cloned:</p>
                  <ul>
                    {autofetchPreview.conflicts.map(conflict => (
                      <li key={conflict.workflow_id}>{conflict.workflow_name} ({conflict.workflow_id})</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="form-actions">
                <button className="ghost" onClick={() => setAutofetchPreview(null)}>Cancel</button>
                <button className="primary" onClick={async () => {
                  const result = await applyPackageAutofetch(selectedPackage.id, autofetchPreview.conflicts.map(conflict => conflict.workflow_id))
                  setSelectedPackage(result)
                  setAutofetchPreview(null)
                  await refreshActiveTab()
                }}>Apply</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {selectedPublicWorkflowPreview && (
        <div className="modal">
          <div className="modal-backdrop" onClick={() => setSelectedPublicWorkflowPreview(null)} />
          <div className="modal-content">
            <div className="modal-header">
              <h3>{selectedPublicWorkflowPreview.metadata.name}</h3>
              <button className="modal-close" onClick={() => setSelectedPublicWorkflowPreview(null)}>x</button>
            </div>
            <div className="modal-body">
              <p className="muted">Read-only workflow preview</p>
              <p>{selectedPublicWorkflowPreview.metadata.description || 'No description'}</p>
              <div className="library-card-meta">
                {(selectedPublicWorkflowPreview.metadata.tags || []).map(tag => <span key={tag} className="library-card-tag">{tag}</span>)}
                {selectedPublicWorkflowPreview.metadata.domain && <span className="library-card-domain">{selectedPublicWorkflowPreview.metadata.domain}</span>}
                {!selectedPublicWorkflowPreview.metadata.is_validated && <span className="library-card-tag">Not validated</span>}
              </div>
              <div className="library-grid">
                <div className="library-card">
                  <div className="library-card-header"><h3 className="library-card-name">Structure</h3></div>
                  <p className="library-card-desc">{selectedPublicWorkflowPreview.nodes.length} nodes, {selectedPublicWorkflowPreview.edges.length} edges</p>
                </div>
                <div className="library-card">
                  <div className="library-card-header"><h3 className="library-card-name">Inputs</h3></div>
                  <p className="library-card-desc">{selectedPublicWorkflowPreview.variables.length ? selectedPublicWorkflowPreview.variables.map(v => v.name).join(', ') : 'No inputs'}</p>
                </div>
                <div className="library-card">
                  <div className="library-card-header"><h3 className="library-card-name">Outputs</h3></div>
                  <p className="library-card-desc">{selectedPublicWorkflowPreview.outputs.length ? selectedPublicWorkflowPreview.outputs.map(o => o.name).join(', ') : 'No outputs'}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
