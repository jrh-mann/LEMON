// LEMON Frontend - Real-time progress monitoring

let eventSource = null;
let isRunning = false;

// DOM Elements
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const statusDot = statusIndicator.querySelector('.status-dot');
const logContainer = document.getElementById('logContainer');
const codeDisplay = document.getElementById('codeDisplay');
const refreshCodeBtn = document.getElementById('refreshCodeBtn');
const testResults = document.getElementById('testResults');

// Metrics
const metricIteration = document.getElementById('metricIteration');
const metricPassRate = document.getElementById('metricPassRate');
const metricPassed = document.getElementById('metricPassed');
const metricTotal = document.getElementById('metricTotal');
const metricTokens = document.getElementById('metricTokens');
const metricInputTokens = document.getElementById('metricInputTokens');
const metricOutputTokens = document.getElementById('metricOutputTokens');
const metricRequestCount = document.getElementById('metricRequestCount');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadWorkflowImage();
    loadGeneratedCode();
    loadTokenStats();
    setupEventListeners();
    
    // Refresh token stats every 5 seconds
    setInterval(loadTokenStats, 5000);
});

function setupEventListeners() {
    startBtn.addEventListener('click', startPipeline);
    stopBtn.addEventListener('click', stopPipeline);
    refreshCodeBtn.addEventListener('click', loadGeneratedCode);
}

function loadWorkflowImage() {
    const img = document.getElementById('workflowImage');
    img.src = '/api/workflow-image';
    img.onerror = () => {
        img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><text x="50%25" y="50%25" text-anchor="middle" fill="%23999">Workflow image not found</text></svg>';
    };
}

function loadGeneratedCode() {
    fetch('/api/generated-code')
        .then(res => res.json())
        .then(data => {
            if (data.exists) {
                codeDisplay.textContent = data.code;
                Prism.highlightElement(codeDisplay);
            } else {
                codeDisplay.textContent = '# No code generated yet. Start the pipeline to generate code.';
            }
        })
        .catch(err => console.error('Error loading code:', err));
}

function loadTokenStats() {
    fetch('/api/token-stats')
        .then(res => res.json())
        .then(stats => {
            const total = stats.total_tokens || 0;
            const input = stats.total_input_tokens || 0;
            const output = stats.total_output_tokens || 0;
            const requests = stats.request_count || 0;
            
            metricTokens.textContent = formatNumber(total);
            metricInputTokens.textContent = formatNumber(input);
            metricOutputTokens.textContent = formatNumber(output);
            metricRequestCount.textContent = formatNumber(requests);
        })
        .catch(err => console.error('Error loading token stats:', err));
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toLocaleString();
}

function startPipeline() {
    if (isRunning) return;
    
    const maxIterations = document.getElementById('maxIterations').value;
    
    fetch('/api/start', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            workflow_image: 'workflow.jpeg',
            max_iterations: maxIterations ? parseInt(maxIterations) : null
        })
    })
    .then(res => res.json())
    .then(data => {
        isRunning = true;
        startBtn.disabled = true;
        stopBtn.disabled = false;
        statusDot.className = 'status-dot active';
        statusText.textContent = 'Running...';
        
        // Clear previous logs
        logContainer.innerHTML = '';
        
        // Start listening for progress
        startProgressStream();
    })
    .catch(err => {
        console.error('Error starting pipeline:', err);
        addLog('error', `Failed to start pipeline: ${err.message}`);
    });
}

function stopPipeline() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    
    isRunning = false;
    startBtn.disabled = false;
    stopBtn.disabled = true;
    statusDot.className = 'status-dot idle';
    statusText.textContent = 'Stopped';
    
    addLog('info', 'Pipeline stopped by user');
}

function startProgressStream() {
    eventSource = new EventSource('/api/progress');
    
    eventSource.onmessage = (event) => {
        try {
            const update = JSON.parse(event.data);
            handleProgressUpdate(update);
        } catch (err) {
            console.error('Error parsing progress update:', err);
        }
    };
    
    eventSource.onerror = (err) => {
        console.error('EventSource error:', err);
        if (eventSource.readyState === EventSource.CLOSED) {
            // Stream closed - pipeline finished or error
            isRunning = false;
            startBtn.disabled = false;
            stopBtn.disabled = true;
            if (statusDot.className.includes('error')) {
                statusText.textContent = 'Error';
            } else {
                statusText.textContent = 'Complete';
            }
        }
    };
}

function handleProgressUpdate(update) {
    if (update.stage === 'heartbeat') return;
    
    const stage = update.stage;
    const message = update.message;
    const data = update.data || {};
    
    // Update timeline
    updateTimeline(stage, message, data);
    
    // Add log entry
    addLog(stage, message, data);
    
    // Update metrics
    if (data.iteration !== undefined) {
        metricIteration.textContent = data.iteration;
    }
    if (data.score !== undefined) {
        metricPassRate.textContent = `${(data.score * 100).toFixed(1)}%`;
        metricPassed.textContent = data.passed || '-';
        metricTotal.textContent = data.total || '-';
    }
    
    // Update status indicator
    if (stage === 'complete') {
        statusDot.className = 'status-dot success';
        statusText.textContent = 'Complete';
        isRunning = false;
        startBtn.disabled = false;
        stopBtn.disabled = true;
        loadGeneratedCode();
    } else if (stage === 'error') {
        statusDot.className = 'status-dot error';
        statusText.textContent = 'Error';
        isRunning = false;
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
    
    // Update code if available
    if (data.code) {
        codeDisplay.textContent = data.code;
        Prism.highlightElement(codeDisplay);
    }
    
    // Update test results
    if (data.failures && data.failures.length > 0) {
        updateTestResults(data.failures, data.passed, data.total);
    }
}

function updateTimeline(stage, message, data) {
    const timelineItems = document.querySelectorAll('.timeline-item');
    
    // Reset all items
    timelineItems.forEach(item => {
        item.classList.remove('active', 'completed');
    });
    
    // Map stage to timeline item
    const stageMap = {
        'setup': 0,
        'analysis': 1,
        'test_generation': 2,
        'refinement': 3,
        'code_generation': 3,
        'validation': 3,
        'testing': 3,
        'final_validation': 4,
        'complete': 4
    };
    
    const itemIndex = stageMap[stage];
    if (itemIndex !== undefined) {
        const item = timelineItems[itemIndex];
        if (stage === 'complete') {
            item.classList.add('completed');
        } else {
            item.classList.add('active');
        }
        
        // Update message
        const messageEl = item.querySelector('.timeline-message');
        if (messageEl) {
            messageEl.textContent = message;
        }
    }
}

function addLog(stage, message, data) {
    const time = new Date().toLocaleTimeString();
    const logEntry = document.createElement('div');
    logEntry.className = 'log-entry';
    
    const icon = getStageIcon(stage);
    const color = getStageColor(stage);
    
    logEntry.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-message" style="color: ${color}">${icon} ${message}</span>
    `;
    
    logContainer.insertBefore(logEntry, logContainer.firstChild);
    
    // Keep only last 100 entries
    while (logContainer.children.length > 100) {
        logContainer.removeChild(logContainer.lastChild);
    }
    
    // Add data details if available
    if (data && Object.keys(data).length > 0) {
        const details = Object.entries(data)
            .filter(([key]) => !['code'].includes(key))
            .map(([key, value]) => {
                if (typeof value === 'object') {
                    return `${key}: ${JSON.stringify(value).substring(0, 100)}`;
                }
                return `${key}: ${value}`;
            })
            .join(', ');
        
        if (details) {
            const detailEntry = document.createElement('div');
            detailEntry.className = 'log-entry';
            detailEntry.style.marginLeft = '95px';
            detailEntry.style.fontSize = '0.8rem';
            detailEntry.style.color = 'var(--text-muted)';
            detailEntry.textContent = `  └─ ${details}`;
            logContainer.insertBefore(detailEntry, logEntry.nextSibling);
        }
    }
}

function updateTestResults(failures, passed, total) {
    if (!failures || failures.length === 0) {
        testResults.innerHTML = '<p class="empty-state">All tests passed! ✅</p>';
        return;
    }
    
    const passedCount = passed || 0;
    const totalCount = total || failures.length + passedCount;
    const passRate = ((passedCount / totalCount) * 100).toFixed(1);
    
    let html = `
        <div class="test-summary">
            <h3>Test Summary</h3>
            <p>Passed: ${passedCount} / ${totalCount} (${passRate}%)</p>
        </div>
        <div class="failure-list">
            <h4>Failures (showing first ${Math.min(failures.length, 10)}):</h4>
            <ul>
    `;
    
    failures.slice(0, 10).forEach((failure, idx) => {
        html += `
            <li>
                <strong>Error ${idx + 1}:</strong> ${failure.error || 'Unknown error'}
                ${failure.test_case ? `<br><small>Input: ${JSON.stringify(failure.test_case).substring(0, 150)}...</small>` : ''}
            </li>
        `;
    });
    
    html += '</ul></div>';
    testResults.innerHTML = html;
}

function getStageIcon(stage) {
    const icons = {
        'setup': '🚀',
        'analysis': '🔍',
        'test_generation': '🧪',
        'refinement': '🔄',
        'code_generation': '💻',
        'validation': '✓',
        'testing': '🧪',
        'final_validation': '🔒',
        'complete': '✅',
        'error': '❌',
        'warning': '⚠️',
        'progress': '📈',
        'success': '🎉'
    };
    return icons[stage] || '📌';
}

function getStageColor(stage) {
    const colors = {
        'setup': '#3b82f6',
        'analysis': '#8b5cf6',
        'test_generation': '#ec4899',
        'refinement': '#6366f1',
        'code_generation': '#10b981',
        'validation': '#22c55e',
        'testing': '#f59e0b',
        'final_validation': '#06b6d4',
        'complete': '#22c55e',
        'error': '#ef4444',
        'warning': '#f59e0b',
        'progress': '#3b82f6',
        'success': '#22c55e'
    };
    return colors[stage] || 'var(--text)';
}

