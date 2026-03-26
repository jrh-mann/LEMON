import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import {
  addWorkflowToPackage,
  createPackage,
  deletePackage,
  deleteWorkflow,
  getPackage,
  listPackages,
  listPublicWorkflows,
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
  const [newPackageName, setNewPackageName] = useState('')
  const [packageError, setPackageError] = useState<string | null>(null)

  const fetchMine = useCallback(async () => {
    const [workflows, packages] = await Promise.all([listWorkflows(), listPackages()])
    setMyWorkflows(workflows)
    setMyPackages(packages)
  }, [])

  const fetchTabData = useCallback(async (tab: BrowserTab) => {
    if (tab === 'mine' && myWorkflows !== null && myPackages !== null) return
    if (tab === 'published' && publicWorkflows !== null) return
    if (tab === 'peer_review' && peerReviewWorkflows !== null) return

    setIsLoading(true)
    try {
      if (tab === 'mine') {
        await fetchMine()
      } else if (tab === 'published') {
        const published = await listPublicWorkflows('reviewed')
        setPublicWorkflows(published.workflows)
      } else {
        const review = await listPublicWorkflows('unreviewed')
        setPeerReviewWorkflows(review.workflows)
      }
    } finally {
      setIsLoading(false)
    }
  }, [fetchMine, myPackages, myWorkflows, peerReviewWorkflows, publicWorkflows])

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
      } else if (activeTab === 'published') {
        const published = await listPublicWorkflows('reviewed')
        setPublicWorkflows(published.workflows)
      } else {
        const review = await listPublicWorkflows('unreviewed')
        setPeerReviewWorkflows(review.workflows)
      }
    } finally {
      setIsLoading(false)
    }
  }, [activeTab, fetchMine, selectedPackage])

  const filterBySearch = useCallback((name: string, description: string, tags: string[]) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return name.toLowerCase().includes(q) || description.toLowerCase().includes(q) || tags.some(tag => tag.toLowerCase().includes(q))
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
    const created = await createPackage({ name: newPackageName.trim() })
    setNewPackageName('')
    setSelectedPackage(created)
    await refreshActiveTab()
  }, [newPackageName, refreshActiveTab])

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
        </div>

        <div className="library-search">
          <input type="text" placeholder="Search workflows and packages..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
        </div>

        {activeTab === 'mine' && (
          <div className="library-package-create">
            <input value={newPackageName} onChange={(e) => setNewPackageName(e.target.value)} placeholder="New package name (optional)" />
            <button className="primary" onClick={handleCreatePackage}>New Package</button>
          </div>
        )}

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
                  <h3 className="library-card-name">{wf.name}</h3>
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
            {(activeTab === 'published' ? publicWorkflows : peerReviewWorkflows || []).map(wf => (
              <div key={wf.id} className="library-card">
                <div className="library-card-header"><h3 className="library-card-name">{wf.name}</h3></div>
                {wf.description && <p className="library-card-desc">{wf.description}</p>}
                {activeTab === 'peer_review' && (
                  <div className="library-card-votes">
                    <button className={`vote-btn ${wf.user_vote === 1 ? 'voted' : ''}`} onClick={() => voteOnWorkflow(wf.id, wf.user_vote === 1 ? 0 : 1)}>▲</button>
                    <span className="vote-count">{(wf.net_votes || 0) > 0 ? `+${wf.net_votes}` : wf.net_votes || 0}</span>
                    <button className={`vote-btn down ${wf.user_vote === -1 ? 'voted' : ''}`} onClick={() => voteOnWorkflow(wf.id, wf.user_vote === -1 ? 0 : -1)}>▼</button>
                  </div>
                )}
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
              <input value={selectedPackage.name} placeholder="Package name" onChange={async (e) => setSelectedPackage(await updatePackage(selectedPackage.id, { name: e.target.value, description: selectedPackage.description }))} />
              <textarea value={selectedPackage.description} placeholder="Package description" onChange={async (e) => setSelectedPackage(await updatePackage(selectedPackage.id, { name: selectedPackage.name, description: e.target.value }))} />
              <p className="muted">{selectedPackage.workflow_count === 0 ? 'Empty package' : `Head workflow: ${selectedPackage.workflows.find(wf => wf.role === 'head')?.name || 'Not set'}`}</p>
              {selectedPackage.issues?.length ? <div className="validation-warning"><ul>{selectedPackage.issues.map(issue => <li key={`${issue.code}-${issue.workflow_id || issue.message}`}>{issue.message}</li>)}</ul></div> : null}
              <div className="library-grid">
                {selectedPackage.workflows.map(workflow => (
                  <div key={workflow.id} className="library-card">
                    <div className="library-card-header">
                      <h3 className="library-card-name">{workflow.name}</h3>
                    </div>
                    <p className="library-card-desc">{workflow.description || 'No description'}</p>
                    <div className="library-card-meta">
                      {workflow.tags.map(tag => <span key={tag} className="library-card-tag">{tag}</span>)}
                      <span className="library-card-domain">{workflow.role === 'head' ? 'Head workflow' : 'Dependency'}</span>
                    </div>
                    <div className="form-actions">
                      <button className="ghost" onClick={(e) => handleSelectWorkflow(workflow, e as unknown as React.MouseEvent)}>Open</button>
                      {workflow.role !== 'head' && <button className="ghost" onClick={async () => setSelectedPackage(await setPackageHead(selectedPackage.id, workflow.id))}>Set as head workflow</button>}
                      <button className="ghost" onClick={async () => setSelectedPackage(await removeWorkflowFromPackage(selectedPackage.id, workflow.id))}>Remove</button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="form-actions">
                <button className="ghost" onClick={async () => { await deletePackage(selectedPackage.id); setSelectedPackage(null); await refreshActiveTab() }}>Delete Package</button>
                <button className="primary" onClick={async () => setSelectedPackage(await publishPackage(selectedPackage.id))} disabled={!selectedPackage.is_publishable}>Publish Package</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
