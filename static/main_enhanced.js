// Enhanced main.js -- NetworkPT frontend logic with session persistence and ANSI colors

// Global variables
let currentUser = null;
let currentProjectId = null;
let currentProjectName = null;
let scanUpdateInterval = null;
let scanOutputsCache = {};
let scanDropdownRefreshTimer = null;
let dashboardUpdateInterval = null;

// Session timeout variables
let sessionTimeoutWarning = null;
let sessionTimeoutTimer = null;

// Function to convert ANSI escape codes to HTML with colors
function convertAnsiToHtml(text) {
    if (!text) return text;

    // ANSI color codes mapping
    const ansiColors = {
        '30': '#000000', '31': '#ff0000', '32': '#00ff00', '33': '#ffff00',
        '34': '#0000ff', '35': '#ff00ff', '36': '#00ffff', '37': '#ffffff',
        '90': '#808080', '91': '#ff6b6b', '92': '#51cf66', '93': '#ffd43b',
        '94': '#339af0', '95': '#f783ac', '96': '#3bc9db', '97': '#f8f9fa'
    };

    const ansiBgColors = {
        '40': '#000000', '41': '#ff0000', '42': '#00ff00', '43': '#ffff00',
        '44': '#0000ff', '45': '#ff00ff', '46': '#00ffff', '47': '#ffffff',
        '100': '#808080', '101': '#ff6b6b', '102': '#51cf66', '103': '#ffd43b',
        '104': '#339af0', '105': '#f783ac', '106': '#3bc9db', '107': '#f8f9fa'
    };

    let result = text;

    // Handle ANSI escape sequences
    result = result.replace(/\x1b\[(\d+(?:;\d+)*)m/g, (match, codes) => {
        const codeList = codes.split(';');
        let styles = [];

        for (let code of codeList) {
            if (code === '0' || code === '00') {
                return '</span>';
            } else if (code === '1') {
                styles.push('font-weight: bold');
            } else if (code === '4') {
                styles.push('text-decoration: underline');
            } else if (ansiColors[code]) {
                styles.push(`color: ${ansiColors[code]}`);
            } else if (ansiBgColors[code]) {
                styles.push(`background-color: ${ansiBgColors[code]}`);
            }
        }

        if (styles.length > 0) {
            return `<span style="${styles.join('; ')}">`;
        }
        return '';
    });

    // Ensure we close any open spans
    const openSpans = (result.match(/<span/g) || []).length;
    const closeSpans = (result.match(/<\/span>/g) || []).length;
    const unclosedSpans = openSpans - closeSpans;

    for (let i = 0; i < unclosedSpans; i++) {
        result += '</span>';
    }

    return result;
}

// Authentication Functions
async function login(event) {
    event.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();

        if (data.success) {
            currentUser = data.username;
            document.getElementById('userInfo').textContent = data.username;
            showDashboard();
            loadProjects();
            startSessionTimeout();
        } else {
            showNotification('Login failed: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

async function logout() {
    try {
        // Clear session timers
        if (sessionTimeoutWarning) clearTimeout(sessionTimeoutWarning);
        if (sessionTimeoutTimer) clearTimeout(sessionTimeoutTimer);

        await fetch('/api/logout', { method: 'POST' });
        currentUser = null;
        currentProjectId = null;
        if (scanUpdateInterval) {
            clearInterval(scanUpdateInterval);
            scanUpdateInterval = null;
        }
        if (dashboardUpdateInterval) {
            clearInterval(dashboardUpdateInterval);
            dashboardUpdateInterval = null;
        }
        showLogin();
    } catch (error) {
        console.error('Logout error:', error);
        showLogin();
    }
}

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth-status');
        const data = await response.json();

        if (data.authenticated) {
            currentUser = data.username;
            document.getElementById('userInfo').textContent = data.username;
            showDashboard();
            loadProjects();
            startSessionTimeout();
        } else {
            currentUser = null;
            currentProjectId = null;
            currentProjectName = null;
            showLogin();
        }
    } catch (error) {
        console.log('Auth check failed:', error);
        currentUser = null;
        showLogin();
    }
}

// Session timeout management
function startSessionTimeout() {
    if (sessionTimeoutWarning) clearTimeout(sessionTimeoutWarning);
    if (sessionTimeoutTimer) clearTimeout(sessionTimeoutTimer);

    // Warn 5 minutes before expiry (235 minutes)
    sessionTimeoutWarning = setTimeout(() => {
        showNotification('Session will expire in 5 minutes. Please save your work.', 'warning');
    }, 235 * 60 * 1000);

    // Auto-logout after 4 hours
    sessionTimeoutTimer = setTimeout(() => {
        showNotification('Session expired. Please log in again.', 'error');
        logout();
    }, 4 * 60 * 60 * 1000);
}

function resetSessionTimeout() {
    if (currentUser) {
        startSessionTimeout();
    }
}

// Reset session timeout on user activity
['click', 'keypress', 'scroll', 'mousemove'].forEach(event => {
    document.addEventListener(event, resetSessionTimeout, { passive: true });
});


function showLogin() {
    document.getElementById('loginScreen').style.display = 'flex';
    document.getElementById('dashboard').style.display = 'none';
    if (dashboardUpdateInterval) {
        clearInterval(dashboardUpdateInterval);
        dashboardUpdateInterval = null;
    }
}

function showDashboard() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('dashboard').style.display = 'block';
    document.getElementById('dashboardView').style.display = 'block';
    document.getElementById('projectView').style.display = 'none';
    
    if (scanUpdateInterval) {
        clearInterval(scanUpdateInterval);
        scanUpdateInterval = null;
    }
    
    // Start dashboard live updates
    startDashboardUpdates();
}

function openProject(projectId, projectName) {
    currentProjectId = projectId;
    currentProjectName = projectName;
    document.getElementById('dashboardView').style.display = 'none';
    document.getElementById('projectView').style.display = 'block';
    document.getElementById('projectTitle').textContent = `🎯 Project: ${projectName}`;
    
    loadTargets();
    showTab('targets');
    
    if (scanUpdateInterval) {
        clearInterval(scanUpdateInterval);
    }
    if (dashboardUpdateInterval) {
        clearInterval(dashboardUpdateInterval);
        dashboardUpdateInterval = null;
    }
    
    scanUpdateInterval = setInterval(updateScanStatus, 3000);
    updateScanStatus();
}

// Replace the existing showTab function with this corrected version:

function showTab(tabName) {
  // Hide all tab contents
  document.querySelectorAll('.tab-content').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Remove active class from all tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Show selected tab content
  const tabContent = document.getElementById(tabName + 'Tab');
  if (tabContent) {
    tabContent.classList.add('active');
  }
  
  // Find and activate the corresponding tab button using data-tab attribute
  document.querySelectorAll('.tab').forEach(tab => {
    if (tab.getAttribute('data-tab') === tabName) {
      tab.classList.add('active');
    }
  });
  
  // Tab-specific actions
  if (tabName === 'results') {
    updateScanStatus();
  } else if (tabName === 'export') {
    setTimeout(checkExportStatus, 100);
  }
}

// New function to enable copy results when results tab is active
function enableCopyResults() {
    // Show copy tab and make it visible
    setTimeout(() => {
        const copyTab = document.querySelector('.tab[data-tab="copy"]');
        if (copyTab) {
            copyTab.style.display = 'block';
            copyTab.style.opacity = '1';
            copyTab.style.background = 'rgba(59, 130, 246, 0.1)';
            copyTab.style.borderLeft = '3px solid #3B82F6';
        }
        showNotification('📁 Copy Results feature activated!', 'info');
    }, 500);
}

// Enhanced dashboard updates with live scan counts
function startDashboardUpdates() {
    if (dashboardUpdateInterval) {
        clearInterval(dashboardUpdateInterval);
    }
    
    // Update dashboard every 5 seconds
    dashboardUpdateInterval = setInterval(updateDashboardStatus, 5000);
    updateDashboardStatus();
}

async function updateDashboardStatus() {
    if (!currentUser || document.getElementById('dashboardView').style.display === 'none') {
        return;
    }
    
    try {
        // Get all projects and their scan status
        const response = await fetch('/api/projects');
        const data = await response.json();
        
        if (data.projects && data.projects.length > 0) {
            // Update each project card with live scan status
            updateProjectsWithLiveStatus(data.projects);
        }
    } catch (error) {
        console.log('Dashboard update error:', error);
    }
}

async function updateProjectsWithLiveStatus(projects) {
    const projectsList = document.getElementById('projectsList');
    if (!projectsList) return;
    
    let projectCardsHtml = '';
    
    for (const project of projects) {
        // Get scan status for this project
        const scanStatus = await getProjectScanStatus(project.id);
        const statusText = formatScanStatus(scanStatus);
        
        projectCardsHtml += `
            <div class="project-card modern-card" onclick="openProject('${project.id}', '${project.name}')">
                <div class="project-header">
                    <h3>${project.name}</h3>
                    <div class="project-meta">
                        <span class="stat-item">📅 ${project.created ? new Date(project.created).toLocaleDateString() : 'Unknown'}</span>
                    </div>
                </div>
                <p class="project-description">${project.description || 'No description provided'}</p>
                <div class="project-stats">
                    <span class="stat-item">🎯 ${project.targets || project.targets_count || 0} targets</span>
                    <div class="scan-status-live">
                        ${statusText || '<span class="status-badge status-info">No active scans</span>'}
                    </div>
                </div>
            </div>
        `;
    }
    
    projectsList.innerHTML = projectCardsHtml;
    document.getElementById('projectCount').textContent = projects.length;
}

async function getProjectScanStatus(projectId) {
    try {
        const response = await fetch(`/api/projects/${projectId}/live-output-by-scan`);
        const data = await response.json();
        const scanOutputs = data.scan_outputs || {};
        
        let running = 0, paused = 0, stopped = 0, completed = 0, error = 0;
        
        Object.values(scanOutputs).forEach(scan => {
            switch (scan.status) {
                case "running": running++; break;
                case "paused": paused++; break;
                case "stopped": stopped++; break;
                case "completed": completed++; break;
                case "error": error++; break;
            }
        });
        
        return { running, paused, stopped, completed, error };
    } catch (error) {
        return null;
    }
}

function formatScanStatus(status) {
    if (!status) return null;
    
    const { running, paused, stopped, completed, error } = status;
    const total = running + paused + stopped + completed + error;
    
    if (total === 0) return null;
    
    let statusParts = [];
    if (running > 0) statusParts.push(`<span class="status-mini status-running">${running} running</span>`);
    if (completed > 0) statusParts.push(`<span class="status-mini status-completed">${completed} completed</span>`);
    if (paused > 0) statusParts.push(`<span class="status-mini status-paused">${paused} paused</span>`);
    if (stopped > 0) statusParts.push(`<span class="status-mini status-stopped">${stopped} stopped</span>`);
    if (error > 0) statusParts.push(`<span class="status-mini status-error">${error} error</span>`);
    
    return `<div class="scan-status-summary">📊 ${statusParts.join(' ')}</div>`;
}

// Project Management Functions
async function loadProjects() {
    try {
        const response = await fetch('/api/projects');
        const data = await response.json();
        
        if (data.projects && data.projects.length > 0) {
            // Use the enhanced project loading with live status
            updateProjectsWithLiveStatus(data.projects);
        } else {
            const projectsList = document.getElementById('projectsList');
            projectsList.innerHTML = '<div class="empty-state"><h3>No Projects Yet</h3><p>Create your first project to get started with penetration testing.</p></div>';
            document.getElementById('projectCount').textContent = '0';
        }
    } catch (error) {
        showNotification('Failed to load projects: ' + error.message, 'error');
    }
}

async function createProject() {
    const projectName = document.getElementById('projectName').value.trim();
    const projectDescription = document.getElementById('projectDescription').value.trim();
    
    if (!projectName) {
        showNotification('Project name is required', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: projectName,
                description: projectDescription
            })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification('Project created successfully!', 'success');
            document.getElementById('projectName').value = '';
            document.getElementById('projectDescription').value = '';
            loadProjects();
            closeCreateProject();
        } else {
            showNotification('Failed to create project: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

function showCreateProject() {
    document.getElementById('createProjectModal').style.display = 'flex';
}

function closeCreateProject() {
    document.getElementById('createProjectModal').style.display = 'none';
}

// Target Management Functions
async function loadTargets() {
    if (!currentProjectId) return;
    
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/targets`);
        const data = await response.json();
        
        const targetsInput = document.getElementById('targetsInput');
        const targetsStatus = document.getElementById('targetsStatus');
        
        if (data.targets) {
            targetsInput.value = data.targets.join('\n');
            updateTargetsCount();
        }
    } catch (error) {
        showNotification('Failed to load targets: ' + error.message, 'error');
    }
}

async function saveTargets() {
    if (!currentProjectId) return;
    
    const targetsText = document.getElementById('targetsInput').value.trim();
    const targets = targetsText.split('\n').map(t => t.trim()).filter(t => t);
    const validTargetRegex = /^((?:\d{1,3}\.){3}\d{1,3}|(?:[a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,})$/;

    const invalidTargets = targets.filter(t => !validTargetRegex.test(t));
    if (invalidTargets.length > 0) {
    showNotification(`Invalid target(s) detected:\n${invalidTargets.join('\n')}`, 'error');
    return;
}

    
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/targets`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ targets: targetsText, mode: 'replace' })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification('Targets saved successfully!', 'success');
            updateTargetsCount();
        } else {
            showNotification('Failed to save targets: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

function updateTargetsCount() {
    const targetsText = document.getElementById('targetsInput').value.trim();
    const targets = targetsText.split('\n').map(t => t.trim()).filter(t => t);
    const status = document.getElementById('targetsStatus');
    
    if (targets.length === 0) {
        status.textContent = 'No targets defined';
        status.className = 'status-badge status-error';
    } else {
        status.textContent = `${targets.length} target${targets.length === 1 ? '' : 's'} configured`;
        status.className = 'status-badge status-success';
    }
}

// Enhanced Scan Management Functions with individual controls
async function startScan(scanType) {
    if (!currentProjectId) {
        showNotification('No project selected', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scan_type: scanType })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification(`${scanType} scan started successfully!`, 'success');
            updateScanStatus();
        } else {
            showNotification('Failed to start scan: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

// New function to pause selected scan only
async function pauseSelectedScan() {
    const scanSelector = document.getElementById('scanSelector');
    const selectedScanId = scanSelector.value;
    
    if (!selectedScanId || selectedScanId === 'no-scans') {
        showNotification('Please select a scan to pause', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/api/scan/pause', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scan_id: selectedScanId })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification('Selected scan paused successfully!', 'success');
            updateScanStatus();
        } else {
            showNotification('Failed to pause scan: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

// New function to delete selected scan only
async function deleteSelectedScan() {
    const scanSelector = document.getElementById('scanSelector');
    const selectedScanId = scanSelector.value;
    
    if (!selectedScanId || selectedScanId === 'no-scans') {
        showNotification('Please select a scan to delete', 'warning');
        return;
    }
    
    // Confirm deletion
    if (!confirm('Are you sure you want to delete this scan? This action cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch('/api/scan/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scan_id: selectedScanId })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification('Selected scan deleted successfully!', 'success');
            // Reset dropdown to default
            scanSelector.value = 'no-scans';
            updateScanStatus();
        } else {
            showNotification('Failed to delete scan: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

async function stopAllScans() {
    if (!currentProjectId) return;
    
    try {
        const response = await fetch('/api/scans/stop-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProjectId })
        });
        
        const data = await response.json();
        if (data.success) {
            showNotification('All scans stopped successfully!', 'success');
            updateScanStatus();
        } else {
            showNotification('Failed to stop scans: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + error.message, 'error');
    }
}

async function updateScanStatus() {
    if (!currentProjectId) return;
    
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/live-output-by-scan`);
        const data = await response.json();
        
        updateScanDropdown(data.scan_outputs || {});
        updateScanOutput(data.scan_outputs || {});
        
    } catch (error) {
        console.log('Failed to load scan information:', error.message);
        document.getElementById('scanStatusTitle').innerHTML = `<div class="error-state">Failed to load scan information: ${error.message}</div>`;
    }
}

function updateScanDropdown(scanOutputs) {
    const scanSelector = document.getElementById('scanSelector');
    const scanCount = Object.keys(scanOutputs).length;
    
    // Update status title with live counts
    let running = 0, paused = 0, stopped = 0, completed = 0, error = 0;
    Object.values(scanOutputs).forEach(scan => {
        switch (scan.status) {
            case "running": running++; break;
            case "paused": paused++; break;
            case "stopped": stopped++; break;
            case "completed": completed++; break;
            case "error": error++; break;
        }
    });
    
    let statusText = [];
    if (running) statusText.push(`${running} running`);
    if (completed) statusText.push(`${completed} completed`);
    if (stopped) statusText.push(`${stopped} stopped`);  
    if (paused) statusText.push(`${paused} paused`);
    if (error) statusText.push(`${error} error`);
    
    const statusTitle = document.getElementById('scanStatusTitle');
    if (statusTitle) {
        statusTitle.textContent = `📊 Live Scan Status (${statusText.join(', ') || 'no scans'})`;
    }
    
    if (scanCount === 0) {
        scanSelector.innerHTML = '<option value="no-scans">No scans available</option>';
        return;
    }
    
    const currentSelection = scanSelector.value;
    scanSelector.innerHTML = '<option value="no-scans">Select a scan to view output</option>';
    
    Object.entries(scanOutputs).forEach(([scanId, scan]) => {
        const option = document.createElement('option');
        option.value = scanId;
        const displayName = scan.display_name || scan.scan_type;
        const statusIcon = getStatusIcon(scan.status);
        option.textContent = `${displayName} ${statusIcon} (${scan.started ? new Date(scan.started).toLocaleTimeString() : ''})`;
        scanSelector.appendChild(option);
    });
    
    // Restore previous selection if still valid
    if (currentSelection && scanOutputs[currentSelection]) {
        scanSelector.value = currentSelection;
    }
}

function updateScanOutput(scanOutputs) {
    const scanSelector = document.getElementById('scanSelector');
    const selectedScanId = scanSelector.value;
    const scanOutputDiv = document.getElementById('scanOutputContent');
    
    if (!selectedScanId || selectedScanId === 'no-scans') {
        scanOutputDiv.innerHTML = '<div class="empty-state"><h4>🔍 No scan selected</h4><p>Choose a scan from the dropdown above to view live output</p><p><strong>Individual Control:</strong> Use pause and delete buttons to control the selected scan specifically.</p></div>';
        return;
    }
    
    const selectedScan = scanOutputs[selectedScanId];
    if (!selectedScan) {
        scanOutputDiv.innerHTML = '<div class="error-state">Selected scan not found</div>';
        return;
    }
    
    const output = selectedScan.output || 'No output yet...';
    const displayName = selectedScan.display_name || selectedScan.scan_type;
    const status = selectedScan.status || 'unknown';
    const started = selectedScan.started || 'unknown';
    
    scanOutputDiv.innerHTML = `
        <div class="scan-output-container">
            <div class="scan-info-header">
                <div class="scan-meta">
                    <h4>${displayName}</h4>
                    <span class="status-badge status-${status.toLowerCase()}">${status.toUpperCase()}</span>
                </div>
                <div class="scan-timing">Started: ${started}</div>
            </div>
            <pre class="scan-output-ansi">${convertAnsiToHtml(output)}</pre>
        </div>
    `;
}

function getStatusIcon(status) {
    switch (status) {
        case 'running': return '🟢';
        case 'completed': return '✅';
        case 'paused': return '⏸️';
        case 'stopped': return '⏹️';
        case 'error': return '❌';
        default: return '⚪';
    }
}

function onScanDropdownChange() {
    const scanSelector = document.getElementById('scanSelector');
    const scanId = scanSelector.value;
    updateScanOutput(scanOutputsCache);
}

// Export Functions
async function exportResults(format) {
  if (!currentProjectId) {
    showNotification("No project selected", "error");
    return;
  }
  try {
    const response = await fetch(`api/projects/${currentProjectId}/export/${format}`, {
      method: "GET"
    });
    if (response.ok) {
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentProjectName}_results.${format === "zip" ? "zip" : format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      showNotification(`Results exported as ${format.toUpperCase()}!`, "success");
    } else {
      let errorData;
      try {
        errorData = await response.json();
      } catch {
        errorData = { error: response.statusText };
      }
      showNotification(`Export failed: ${errorData.error}`, "error");
    }
  } catch (error) {
    showNotification(`Export error: ${error.message}`, "error");
  }
}

async function copyResults() {
    const destPath = document.getElementById('destPath').value.trim();

    if (!destPath) {
        showNotification('Please enter a destination path', 'error');
        return;
    }

    // Require an absolute /home path with at least one subdirectory segment
    // Segments may contain letters, numbers, dot, underscore, or dash
    // Disallow ".." segments to avoid traversal
    const homePathPattern = /^\/home(?:\/(?!\.\.)(?:[A-Za-z0-9._-]+))+\/?$/;

    if (!homePathPattern.test(destPath)) {
        showNotification(
            'Destination must start with /home and use only letters, numbers, dot, underscore, or dash in each segment (no "..").',
            'error'
        );
        return;
    }

    if (!currentProjectId) {
        showNotification('No project selected', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/copy_output`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dest_path: destPath })
        });

        const data = await response.json();
        if (data.success) {
            showNotification('Results copied successfully!', 'success');
        } else {
            showNotification('Copy failed: ' + data.message, 'error');
        }
    } catch (error) {
        showNotification('Copy error: ' + error.message, 'error');
    }
}


async function checkExportStatus() {
    if (!currentProjectId) return;
    
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/live-output-by-scan`);
        const data = await response.json();
        const scanOutputs = data.scan_outputs || {};
        const scanCount = Object.keys(scanOutputs).length;
        
        const exportNote = document.getElementById('exportNote');
        if (exportNote) {
            exportNote.innerHTML = scanCount > 0 
                ? '✅ Ready to export! All scan data will be included in your download.'
                : '⚠️ No scan data available for export. Start some scans first.';
        }
    } catch (error) {
        console.log('Failed to check export status:', error);
    }
}

// Utility Functions
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };
    
    notification.innerHTML = `
        <div class="notification-content">
            <span class="notification-icon">${icons[type] || icons.info}</span>
            <span class="notification-message">${message}</span>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => notification.classList.add('show'), 10);
    
    setTimeout(() => {
        notification.classList.add('fade-out');
        setTimeout(() => document.body.removeChild(notification), 300);
    }, 5000);
}

// Theme Management
function toggleTheme() {
    const body = document.body;
    const currentTheme = body.getAttribute('data-color-scheme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    body.setAttribute('data-color-scheme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    const themeToggle = document.querySelector('.theme-toggle');
    themeToggle.textContent = newTheme === 'dark' ? '☀️' : '🌙';
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    
    document.body.setAttribute('data-color-scheme', savedTheme);
    
    const themeToggle = document.querySelector('.theme-toggle');
    if (themeToggle) {
        themeToggle.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
    }
    
    checkAuthStatus();
    
    // Add event listeners
    const targetsInput = document.getElementById('targetsInput');
    if (targetsInput) {
        targetsInput.addEventListener('input', updateTargetsCount);
    }
    
    // Cache scan outputs
    scanOutputsCache = {};
});

async function copyMultiScanResults() {
    if (!currentProjectId) {
        showNotification('No project selected', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/copy_output`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                dest_path: '/tmp/copied_results'  // or get from user input
            })
        });
        
        // Check if response is ok first
        if (!response.ok) {
            showNotification(`Copy failed: Server returned ${response.status}`, 'error');
            return;
        }
        
        // Get response text first
        const text = await response.text();
        
        // Try to parse as JSON
        let data;
        try {
            data = JSON.parse(text);
        } catch (parseError) {
            console.log('Raw response:', text);
            showNotification('Copy failed: Invalid server response', 'error');
            return;
        }
        
        // Check if the copy operation was successful
        if (data.success) {
            showNotification('Multi-scan results copied successfully!', 'success');
        } else {
            showNotification('Copy failed: ' + (data.message || data.error || 'Unknown error'), 'error');
        }
        
    } catch (networkError) {
        console.error('Copy error:', networkError);
        showNotification('Copy error: ' + networkError.message, 'error');
    }
}
async function startNmapTargeted() {
  if (!currentProjectId) { showNotification("No project selected", "error"); return; }
  try {
    const r = await fetch(`/api/projects/${currentProjectId}/nmap-targeted`, { method: "POST" });
    const d = await r.json();
    if (d.success) { showNotification("Nmap targeted started", "success"); updateScanStatus(); }
    else { showNotification(d.error || "Failed to start Nmap", "error"); }
  } catch (e) { showNotification(e.message, "error"); }
}

async function runAutoWebFollowups() {
  if (!currentProjectId) { showNotification("No project selected", "error"); return; }
  try {
    const r = await fetch(`/api/projects/${currentProjectId}/auto-web-followups`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({}) });
    const d = await r.json();
    if (d.success) { showNotification("Web follow-ups started", "success"); updateScanStatus(); }
    else { showNotification(d.error || "Failed to start web follow-ups", "error"); }
  } catch (e) { showNotification(e.message, "error"); }
}

async function runAutoServiceFollowups() {
  if (!currentProjectId) { showNotification("No project selected", "error"); return; }
  try {
    const r = await fetch(`/api/projects/${currentProjectId}/auto-service-followups`, { method: "POST" });
    const d = await r.json();
    if (d.success) { showNotification("Service follow-ups started", "success"); updateScanStatus(); }
    else { showNotification(d.error || "Failed to start service follow-ups", "error"); }
  } catch (e) { showNotification(e.message, "error"); }
}

async function fetchMsfCandidates() {
  if (!currentProjectId) { showNotification("No project selected", "error"); return; }
  try {
    const r = await fetch(`/api/projects/${currentProjectId}/msf/candidates`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({}) });
    const d = await r.json();
    if (d.success) {
      console.log("MSF candidates", d.candidates);
      showNotification("Fetched MSF candidates (see console)", "info");
    } else { showNotification(d.error || "Failed to fetch MSF candidates", "error"); }
  } catch (e) { showNotification(e.message, "error"); }
}

async function runMsfModule(module, rhost, rport, payload) {
  if (!currentProjectId) { showNotification("No project selected", "error"); return; }
  if (!confirm(`Run module ${module} on ${rhost}:${rport}?`)) { return; }
  try {
    const r = await fetch(`/api/msf/run`, { method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ project_id: currentProjectId, module, rhost, rport, payload, confirm: true }) });
    const d = await r.json();
    if (d.success) { showNotification("Metasploit module run started", "success"); updateScanStatus(); }
    else { showNotification(d.error || "Failed to start module run", "error"); }
  } catch (e) { showNotification(e.message, "error"); }
}

async function summarizeFindings() {
  if (!currentProjectId) { showNotification("No project selected", "error"); return; }
  try {
    const r = await fetch(`/api/projects/${currentProjectId}/summarize`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({}) });
    const d = await r.json();
    if (d.success) { showNotification("Summary saved: " + d.summary_path, "success"); }
    else { showNotification(d.error || "Failed to summarize", "error"); }
  } catch (e) { showNotification(e.message, "error"); }
}

// Global function assignments for HTML onclick handlers
window.pauseSelectedScan = pauseSelectedScan;
window.deleteSelectedScan = deleteSelectedScan;
window.resumeSelectedScan = resumeSelectedScan;
window.createProject = createProject;
window.showCreateProject = showCreateProject;
window.closeCreateProject = closeCreateProject;

// Page load event listener
document.addEventListener('DOMContentLoaded', function() {
    // Initialize theme
    const savedTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.body.setAttribute('data-color-scheme', savedTheme);
    const themeToggle = document.querySelector('.theme-toggle');
    if (themeToggle) {
        themeToggle.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
    }

    // Check authentication status on page load
    checkAuthStatus();

    // Add event listeners
    const targetsInput = document.getElementById('targetsInput');
    if (targetsInput) {
        targetsInput.addEventListener('input', updateTargetsCount);
    }

    // Initialize scan outputs cache
    scanOutputsCache = {};
});

// New function to resume selected scan only
async function resumeSelectedScan() {
    const scanSelector = document.getElementById('scanSelector');
    const selectedScanId = scanSelector ? scanSelector.value : null;

    if (!selectedScanId || selectedScanId === 'no-scans') {
        showNotification('Please select a scan to resume', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/scan/resume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scan_id: selectedScanId })
        });

        const data = await response.json();
        if (data.success) {
            showNotification('Selected scan resumed successfully!', 'success');
            // Refresh status and output to reflect change
            await updateScanStatus();
        } else {
            showNotification('Failed to resume scan: ' + (data.error || data.message || 'unknown'), 'error');
        }
    } catch (error) {
        showNotification('Network error: ' + (error.message || error), 'error');
    }
}