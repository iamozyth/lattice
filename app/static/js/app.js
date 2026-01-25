// ============================================================================
// NetDoc IPAM - IP Address Management System
// Version 2.0.0
// ============================================================================

let currentSubnetId = null;
let currentIPId = null;
let allSubnets = [];
let allIPs = [];
let currentSubnetData = null;
let currentTab = 'subnets';
let connectorEditId = null;
let restoreDetailAfterIPModal = false;
let scanInProgress = false;
let currentScanJobId = null;
let currentScanDiscovered = [];
let currentUser = null;
let previewState = { connectorId: null, connectorName: '', data: null };

// Simple helpers to show/hide modals reliably (since we don't have Tailwind utilities built)
function showModal(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.classList.remove('hidden');
    el.style.display = 'flex';
    el.style.alignItems = 'center';
    el.style.justifyContent = 'center';
}

function hideModal(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.classList.add('hidden');
    el.style.display = 'none';
}

function isModalVisible(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return false;
    return !el.classList.contains('hidden') && el.style.display !== 'none';
}

// ============================================================================
// Authentication
// ============================================================================

async function checkPasswordStrength(fieldId) {
    const password = document.getElementById(fieldId).value;
    const strengthContainerId = `${fieldId}Strength`;
    
    // Hide if empty
    if (password.length === 0) {
        document.getElementById(strengthContainerId).classList.add('hidden');
        return;
    }
    
    try {
        const res = await fetch('/api/auth/check-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        
        const data = await res.json();
        
        // Show strength indicator
        document.getElementById(strengthContainerId).classList.remove('hidden');
        
        // Update progress bar
        const barId = `${fieldId}Bar`;
        const bar = document.getElementById(barId);
        const percentage = Math.min((data.score / 10) * 100, 100);
        bar.style.width = percentage + '%';
        bar.style.backgroundColor = data.color;
        
        // Update strength level text
        document.getElementById(`${fieldId}Level`).textContent = data.strength;
        document.getElementById(`${fieldId}Level`).style.color = data.color;
        
        // Update message
        document.getElementById(`${fieldId}Message`).textContent = data.message;
        document.getElementById(`${fieldId}Message`).style.color = data.color;
        
        // Update requirements
        const prefix = fieldId.replace('Password', '').charAt(0).toUpperCase() + fieldId.replace('Password', '').slice(1);
        const reqPrefix = fieldId === 'setupPassword' ? 'setupReq' : 'req';
        
        updateRequirement(`${reqPrefix}Length`, data.requirements.length);
        updateRequirement(`${reqPrefix}Uppercase`, data.requirements.uppercase);
        updateRequirement(`${reqPrefix}Lowercase`, data.requirements.lowercase);
        updateRequirement(`${reqPrefix}Numbers`, data.requirements.numbers);
        updateRequirement(`${reqPrefix}Special`, data.requirements.special);
        
    } catch (error) {
        console.error('Password strength check error:', error);
    }
}

function updateRequirement(elementId, met) {
    const el = document.getElementById(elementId);
    if (!el) return;
    
    if (met) {
        el.textContent = '✓';
        el.style.color = '#10b981';
    } else {
        el.textContent = '✗';
        el.style.color = '#9ca3af';
    }
}

async function checkAuthStatus() {
    try {
        console.log('[Auth] Checking setup status...');
        // First check if system needs setup
        const setupRes = await fetch('/api/auth/setup-status');
        const setupData = await setupRes.json();
        console.log('[Auth] Setup status:', setupData);
        
        if (setupData.needs_setup) {
            console.log('[Auth] System needs initial setup');
            showModal('setupModal');
            return false;
        }
        
        // System is set up, check authentication
        console.log('[Auth] Checking authentication status...');
        const res = await fetch('/api/auth/health');
        const data = await res.json();
        console.log('[Auth] Response:', data);
        
        if (data.authenticated && data.user) {
            console.log('[Auth] User authenticated:', data.user.username);
            currentUser = data.user;
            // User is logged in, hide login modal
            hideModal('loginModal');
            hideModal('registerModal');
            hideModal('setupModal');
            document.body.style.pointerEvents = 'auto';
            return true;
        } else {
            // Not logged in, show login modal and disable interaction
            console.log('[Auth] User not authenticated, showing login modal');
            currentUser = null;
            showModal('loginModal');
            document.body.style.pointerEvents = 'auto';
            document.getElementById('loginModal').style.pointerEvents = 'auto';
            return false;
        }
    } catch (error) {
        console.error('[Auth] Auth check failed:', error);
        currentUser = null;
        showModal('loginModal');
        return false;
    }
}

async function handleLogin(event) {
    event.preventDefault();
    
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    
    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            let errorMsg = 'Login failed';
            if (data.error) {
                if (data.error.includes('not found')) {
                    errorMsg = 'User not found. Please check your username.';
                } else if (data.error.includes('password') || data.error.includes('Invalid')) {
                    errorMsg = 'Incorrect password. Please try again.';
                } else {
                    errorMsg = data.error;
                }
            }
            showToast(errorMsg, 'error');
            return;
        }
        
        currentUser = data.user;
        hideModal('loginModal');
        hideModal('registerModal');
        
        // Reset form
        document.getElementById('loginForm').reset();
        
        showToast('Logged in successfully!', 'success');
        
        // Reload data
        loadSubnets();
        loadStats();
    } catch (error) {
        console.error('Login error:', error);
        showToast('Login failed', 'error');
    }
}

async function handleRegister(event) {
    event.preventDefault();
    
    const username = document.getElementById('registerUsername').value;
    const email = document.getElementById('registerEmail').value;
    const password = document.getElementById('registerPassword').value;
    
    try {
        const res = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password })
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            let errorMsg = 'Registration failed';
            if (data.error) {
                if (data.error.includes('exists') || data.error.includes('already')) {
                    errorMsg = 'Username or email already in use. Please choose a different one.';
                } else if (data.error.includes('email')) {
                    errorMsg = 'Invalid email address. Please check and try again.';
                } else if (data.error.includes('password')) {
                    errorMsg = 'Password does not meet requirements (min 8 chars, uppercase, lowercase, number, special).';
                } else {
                    errorMsg = data.error;
                }
            }
            showToast(errorMsg, 'error');
            return;
        }
        
        // Auto-login after registration
        if (data.user) {
            currentUser = data.user;
            hideModal('loginModal');
            hideModal('registerModal');
            document.getElementById('registerForm').reset();
            showToast('Account created successfully!', 'success');
            loadSubnets();
            loadStats();
        }
    } catch (error) {
        console.error('Register error:', error);
        showToast('Registration failed', 'error');
    }
}

async function handleLogout() {
    try {
        const res = await fetch('/api/auth/logout', { method: 'POST' });
        
        if (res.ok) {
            currentUser = null;
            showToast('Logged out successfully', 'success');
            setTimeout(() => {
                showModal('loginModal');
                closeSettingsModal();
            }, 500);
        }
    } catch (error) {
        console.error('Logout error:', error);
        showToast('Logout failed', 'error');
    }
}

async function handleSetup(event) {
    event.preventDefault();
    
    const username = document.getElementById('setupUsername').value;
    const email = document.getElementById('setupEmail').value;
    const password = document.getElementById('setupPassword').value;
    const confirmPassword = document.getElementById('setupConfirmPassword').value;
    
    if (password !== confirmPassword) {
        showToast('Passwords do not match', 'error');
        return;
    }
    
    try {
        const res = await fetch('/api/auth/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password })
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            console.error('Setup error response:', data);
            // Try to show validation details if available
            if (data.detail) {
                const details = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail;
                showToast(`Setup failed: ${details}`, 'error');
            } else {
                showToast(data.error || 'Setup failed', 'error');
            }
            return;
        }
        
        // Setup complete, auto-login
        if (data.user) {
            currentUser = data.user;
            hideModal('setupModal');
            document.getElementById('setupForm').reset();
            showToast('Admin account created successfully! Welcome to NetDoc IPAM!', 'success');
            loadSubnets();
            loadStats();
        }
    } catch (error) {
        console.error('Setup error:', error);
        showToast('Setup failed', 'error');
    }
}

async function handleChangePassword(event) {
    event.preventDefault();
    
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    
    if (newPassword !== confirmPassword) {
        showToast('Passwords do not match', 'error');
        return;
    }
    
    try {
        const res = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            showToast(data.error || 'Password change failed', 'error');
            return;
        }
        
        showToast('Password changed successfully', 'success');
        document.getElementById('passwordForm').reset();
    } catch (error) {
        console.error('Password change error:', error);
        showToast('Password change failed', 'error');
    }
}

function switchToLogin() {
    hideModal('registerModal');
    showModal('loginModal');
}

function switchToRegister() {
    hideModal('loginModal');
    showModal('registerModal');
}

function showSettingsModal() {
    if (!currentUser) {
        showToast('Please log in first', 'error');
        return;
    }
    
    // Populate settings
    document.getElementById('settingsUsername').textContent = currentUser.username;
    document.getElementById('settingsEmail').textContent = currentUser.email;
    document.getElementById('settingsRole').textContent = currentUser.is_admin ? 'Administrator' : 'User';
    
    // Load and display version
    loadVersion();
    checkForUpdates();
    
    // Show/hide admin panel based on user role
    const adminPanelSection = document.getElementById('adminPanelSection');
    if (currentUser.is_admin) {
        adminPanelSection.classList.remove('hidden');
    } else {
        adminPanelSection.classList.add('hidden');
    }
    
    switchSettingsTab('user');
    showModal('settingsModal');
}

function closeSettingsModal() {
    hideModal('settingsModal');
    document.getElementById('passwordForm').reset();
}

function switchSettingsTab(tab) {
    const userTabBtn = document.getElementById('settingsTabUser');
    const systemTabBtn = document.getElementById('settingsTabSystem');
    const userPane = document.getElementById('settingsUserPane');
    const systemPane = document.getElementById('settingsSystemPane');
    
    if (tab === 'user') {
        // User tab active
        userTabBtn.classList.remove('text-gray-500', 'border-transparent');
        userTabBtn.classList.add('text-primary-600', 'border-primary-600');
        systemTabBtn.classList.remove('text-primary-600', 'border-primary-600');
        systemTabBtn.classList.add('text-gray-500', 'border-transparent');
        userPane.classList.remove('hidden');
        systemPane.classList.add('hidden');
    } else {
        // System tab active
        systemTabBtn.classList.remove('text-gray-500', 'border-transparent');
        systemTabBtn.classList.add('text-primary-600', 'border-primary-600');
        userTabBtn.classList.remove('text-primary-600', 'border-primary-600');
        userTabBtn.classList.add('text-gray-500', 'border-transparent');
        systemPane.classList.remove('hidden');
        userPane.classList.add('hidden');
    }
}

// ============================================================================
// Connectors
// ============================================================================

async function loadConnectorStatus() {
    try {
        const res = await fetch('/api/connectors');
        const data = await res.json();
        const unifi = (data || []).find(c => c.name === 'unifi');
        const badge = document.getElementById('unifiStatusBadge');
        if (unifi && badge) {
            badge.textContent = unifi.configured ? 'Configured' : 'Not Configured';
            badge.className = 'text-xs px-2.5 py-1 rounded-full font-semibold ' + (unifi.configured ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-700');
        }
    } catch (e) {
        console.error('Connector status failed', e);
    }
}

async function syncUnifiConnector() {
    try {
        const btns = document.querySelectorAll('button');
        btns.forEach(b => b.disabled = true);
        const res = await fetch('/api/connectors/unifi/sync', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'UniFi sync failed', 'error');
            return;
        }
        showToast(`UniFi sync: added ${data.added}, updated ${data.updated}, skipped ${data.skipped}`, 'success');
        const last = document.getElementById('unifiLastSync');
        if (last) last.textContent = `Last sync: ${new Date().toLocaleString()}`;
        // Refresh stats after enrichment
        loadStats();
    } catch (e) {
        console.error('UniFi sync error', e);
        showToast('UniFi sync failed', 'error');
    } finally {
        const btns = document.querySelectorAll('button');
        btns.forEach(b => b.disabled = false);
    }
}

function showAddConnectorForm({ resetForm = true } = {}) {
    const el = document.getElementById('addConnectorForm');
    if (el) el.classList.remove('hidden');
    if (resetForm) {
        connectorEditId = null;
        document.getElementById('connectorForm')?.reset();
        const submitBtn = document.getElementById('connectorSubmitBtn');
        if (submitBtn) submitBtn.innerHTML = '<i class="fas fa-save mr-2"></i>Save Connector';
    }
}

function hideAddConnectorForm() {
    const el = document.getElementById('addConnectorForm');
    if (el) el.classList.add('hidden');
    const form = document.getElementById('connectorForm');
    if (form) form.reset();
}

async function saveConnector(event) {
    event.preventDefault();
    const name = document.getElementById('connectorName').value.trim();
    const type = document.getElementById('connectorType').value;
    const enabled = document.getElementById('connectorEnabled').checked;
    const config = {};
    if (type === 'unifi') {
        config.base_url = document.getElementById('unifiBaseUrl').value.trim();
        config.site_id = document.getElementById('unifiSiteId').value.trim() || 'default';
        config.api_key = document.getElementById('unifiApiKey').value.trim();
        config.verify_ssl = document.getElementById('unifiVerifySSL').value === 'true';
        config.username = document.getElementById('unifiUsername').value.trim();
        config.password = document.getElementById('unifiPassword').value.trim();
    }
    try {
        const url = connectorEditId ? `/api/connectors/${connectorEditId}` : '/api/connectors';
        const method = connectorEditId ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, type, enabled, config })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to create connector', 'error');
            return;
        }
        showToast(connectorEditId ? 'Connector updated' : 'Connector created', 'success');
        hideAddConnectorForm();
        loadConnectors();
    } catch (e) {
        console.error('Create connector failed', e);
        showToast('Failed to create connector', 'error');
    }
}

async function loadConnectors() {
    try {
        const res = await fetch('/api/connectors');
        const items = await res.json();
        renderConnectorsList(items || []);
    } catch (e) {
        console.error('Load connectors failed', e);
    }
}

function renderConnectorsList(items) {
    const container = document.getElementById('connectorsList');
    if (!container) return;
    if (!items.length) {
        container.innerHTML = `
            <div class="col-span-full text-center py-12 text-gray-500">
                <i class="fas fa-plug text-3xl mb-3"></i>
                <p>No connectors configured</p>
            </div>
        `;
        return;
    }
    container.innerHTML = items.map(c => {
        const lastSync = c.last_sync_at ? new Date(c.last_sync_at).toLocaleString() : '-';
        const statusCls = c.enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-700';
        const details = c.details || {};
        return `
            <div class="border border-gray-200 rounded-lg p-4 flex flex-col gap-3">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <i class="fas fa-plug text-primary-600"></i>
                        <div>
                            <div class="font-medium text-gray-800">${escapeHtml(c.name)} <span class="text-xs text-gray-500">(${escapeHtml(c.type)})</span></div>
                            <div class="text-xs text-gray-500">${escapeHtml(details.base_url || '')} ${details.site_id ? '('+escapeHtml(details.site_id)+')' : ''}</div>
                        </div>
                    </div>
                    <span class="text-xs px-2.5 py-1 rounded-full font-semibold ${statusCls}">${c.enabled ? 'Enabled' : 'Disabled'}</span>
                </div>
                <div class="text-xs text-gray-500">Last sync: ${lastSync}</div>
                <div class="flex gap-2 flex-wrap">
                    <button class="btn-secondary" onclick="testConnector(${c.id})"><i class="fas fa-vial mr-2"></i>Test</button>
                    <button class="btn-secondary" onclick="previewSyncConnector(${c.id}, ${JSON.stringify(c.name)})"><i class="fas fa-eye mr-2"></i>Preview</button>
                    <button class="btn-secondary" onclick="runSyncConnector(${c.id})"><i class="fas fa-sync mr-2"></i>Sync</button>
                    <button class="btn-secondary" onclick='editConnector(${JSON.stringify(c.id)})'><i class="fas fa-edit mr-2"></i>Edit</button>
                    <button class="btn-danger" onclick="deleteConnector(${c.id})"><i class="fas fa-trash mr-2"></i>Delete</button>
                </div>
            </div>
        `;
    }).join('');
}

async function editConnector(id) {
    try {
        connectorEditId = id;
        const res = await fetch('/api/connectors');
        const items = await res.json();
        const c = (items || []).find(x => x.id === id);
        if (!c) {
            showToast('Connector not found', 'error');
            return;
        }
        showAddConnectorForm({ resetForm: false });
        document.getElementById('connectorName').value = c.name || '';
        document.getElementById('connectorType').value = c.type;
        document.getElementById('connectorEnabled').checked = !!c.enabled;
        const details = c.details || {};
        document.getElementById('unifiBaseUrl').value = details.base_url || '';
        document.getElementById('unifiSiteId').value = details.site_id || 'default';
        document.getElementById('unifiVerifySSL').value = details.verify_ssl === false ? 'false' : 'true';
        // Credentials are not returned for security; user must re-enter
        document.getElementById('unifiApiKey').value = '';
        document.getElementById('unifiUsername').value = '';
        document.getElementById('unifiPassword').value = '';
        const submitBtn = document.getElementById('connectorSubmitBtn');
        if (submitBtn) submitBtn.innerHTML = '<i class="fas fa-save mr-2"></i>Update Connector';
    } catch (e) {
        console.error('Edit connector failed', e);
        showToast('Failed to load connector', 'error');
    }
}

async function syncConnector(id, { dryRun = false } = {}) {
    try {
        const url = dryRun ? `/api/connectors/${id}/sync?dry_run=true` : `/api/connectors/${id}/sync`;
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.success === false) {
            let errorMsg = dryRun ? 'Preview failed' : 'Sync failed';
            if (data.error) {
                if (data.error.includes('No clients')) {
                    errorMsg = 'Sync failed: Server returned no clients. Check connector configuration and credentials.';
                } else if (data.error.includes('connection') || data.error.includes('Connection')) {
                    errorMsg = 'Sync failed: Cannot connect to the server. Check network and server status.';
                } else if (data.error.includes('credentials') || data.error.includes('Unauthorized')) {
                    errorMsg = 'Sync failed: Authentication error. Update connector credentials.';
                } else {
                    errorMsg = `Sync failed: ${data.error}`;
                }
            }
            showToast(errorMsg, 'error');
            return null;
        }
        if (dryRun) return data;

        showToast(`Sync complete: added ${data.added}, updated ${data.updated}, skipped ${data.skipped}`, 'success');
        loadConnectors();
        loadStats();
        return data;
    } catch (e) {
        console.error('Sync connector failed', e);
        showToast('Sync failed', 'error');
        return null;
    }
}

async function runSyncConnector(id) {
    if (!confirm('Sync now? This will apply changes.')) return;
    await syncConnector(id, { dryRun: false });
}

async function previewSyncConnector(id, connectorName = '') {
    if (!confirm('Run a preview? No changes will be applied.')) return;
    showToast('Building preview…', 'info');
    const data = await syncConnector(id, { dryRun: true });
    if (!data) return;
    renderSyncPreview(data, connectorName);
    showModal('syncPreviewModal');
}

function renderSyncPreview(data, connectorName = '') {
    previewState = { connectorId: data.connector_id || null, connectorName, data };
    document.getElementById('previewConnectorName').textContent = connectorName || `Connector ${data.connector_id || ''}`;
    document.getElementById('previewClientsCount').textContent = data.clients || 0;
    document.getElementById('previewAddedCount').textContent = data.added || 0;
    document.getElementById('previewUpdatedCount').textContent = data.updated || 0;
    document.getElementById('previewSkippedCount').textContent = data.skipped || 0;

    renderPreviewList('previewAddedList', data.added_items, 'No new IPs to add', renderAddedItem);
    renderPreviewList('previewUpdatedList', data.updated_items, 'No updates to apply', renderUpdatedItem);
    renderPreviewList('previewSkippedList', data.skipped_items, 'No skipped records', renderSkippedItem);
}

function renderPreviewList(targetId, items, emptyText, formatter) {
    const container = document.getElementById(targetId);
    if (!container) return;
    if (!items || !items.length) {
        container.innerHTML = `<div class="text-xs text-gray-500">${emptyText}</div>`;
        return;
    }
    container.innerHTML = items.map(formatter).join('');
}

function renderAddedItem(item) {
    const ip = escapeHtml(item.ip || '-');
    const subnet = escapeHtml((item.subnet && item.subnet.cidr) || 'Unknown subnet');
    const hostname = escapeHtml(item.hostname || 'No hostname');
    const mac = escapeHtml(item.mac || 'No MAC');
    return `
        <div class="border border-gray-200 rounded-lg p-2 bg-green-50">
            <div class="text-sm font-semibold text-gray-800">${ip}</div>
            <div class="text-xs text-gray-600">${hostname}</div>
            <div class="text-xs text-gray-500">Subnet: ${subnet}</div>
            <div class="text-xs text-gray-500">MAC: ${mac}</div>
        </div>
    `;
}

function renderUpdatedItem(item) {
    const ip = escapeHtml(item.ip || '-');
    const subnet = escapeHtml((item.subnet && item.subnet.cidr) || 'Unknown subnet');
    const changes = item.changes || {};
    const changeList = Object.keys(changes).length ? Object.entries(changes).map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml(String(v))}`).join(', ') : 'No changes';
    return `
        <div class="border border-gray-200 rounded-lg p-2 bg-blue-50">
            <div class="text-sm font-semibold text-gray-800">${ip}</div>
            <div class="text-xs text-gray-500">Subnet: ${subnet}</div>
            <div class="text-xs text-gray-600">${changeList}</div>
        </div>
    `;
}

function renderSkippedItem(item) {
    const ip = escapeHtml(item.ip || (item.client && item.client.ip) || 'No IP');
    const reason = formatSkipReason(item.reason);
    return `
        <div class="border border-gray-200 rounded-lg p-2 bg-yellow-50">
            <div class="text-sm font-semibold text-gray-800">${ip}</div>
            <div class="text-xs text-gray-600">${reason}</div>
        </div>
    `;
}

function formatSkipReason(reason) {
    if (!reason) return 'Skipped';
    const map = {
        missing_ip: 'Missing IP address',
        no_matching_subnet: 'No matching subnet',
        no_changes: 'No changes to apply'
    };
    return map[reason] || reason;
}

function closePreviewModal() {
    previewState = { connectorId: null, connectorName: '', data: null };
    hideModal('syncPreviewModal');
}

async function applyPreviewSync() {
    if (!previewState.connectorId) {
        showToast('No preview to apply', 'error');
        return;
    }
    if (!confirm('Apply these changes?')) return;
    hideModal('syncPreviewModal');
    await syncConnector(previewState.connectorId, { dryRun: false });
    previewState = { connectorId: null, connectorName: '', data: null };
}

async function testConnector(id) {
    try {
        const res = await fetch(`/api/connectors/${id}/test`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) {
            let errorMsg = 'Connection test failed';
            if (data.error) {
                if (data.error.includes('404') || data.error.includes('not found')) {
                    errorMsg = 'Server not found. Check the base URL and ensure the server is running.';
                } else if (data.error.includes('401') || data.error.includes('Unauthorized') || data.error.includes('credentials')) {
                    errorMsg = 'Authentication failed. Check your API key, username, or password.';
                } else if (data.error.includes('SSL') || data.error.includes('certificate')) {
                    errorMsg = 'SSL certificate error. Try disabling SSL verification if using self-signed cert.';
                } else if (data.error.includes('timeout') || data.error.includes('Timeout')) {
                    errorMsg = 'Connection timeout. The server is not responding. Check network connectivity.';
                } else if (data.error.includes('No clients')) {
                    errorMsg = 'Authentication succeeded but no clients found. Verify the site ID is correct.';
                } else {
                    errorMsg = data.error;
                }
            }
            showToast(errorMsg, 'error');
            return;
        }
        showToast('✓ Connection successful! Credentials are valid.', 'success');
    } catch (e) {
        console.error('Test connector failed', e);
        showToast('Test failed', 'error');
    }
}

async function deleteConnector(id) {
    if (!confirm('Delete this connector?')) return;
    try {
        const res = await fetch(`/api/connectors/${id}`, { method: 'DELETE' });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showToast(data.error || 'Delete failed', 'error');
            return;
        }
        showToast('Connector deleted', 'success');
        loadConnectors();
    } catch (e) {
        console.error('Delete connector failed', e);
        showToast('Delete failed', 'error');
    }
}
function closeLoginModal() {
    if (currentUser) {
        hideModal('loginModal');
    }
}

function closeRegisterModal() {
    if (currentUser) {
        hideModal('registerModal');
    }
}

// ============================================================================
// Admin Panel Functions
// ============================================================================

function showAdminUsersModal() {
    if (!currentUser || !currentUser.is_admin) {
        showToast('Admin access required', 'error');
        return;
    }
    showModal('adminUsersModal');
    loadAdminUsers();
}

function closeAdminUsersModal() {
    hideModal('adminUsersModal');
    document.getElementById('adminCreateUserForm').reset();
}

function loadAdminUsers() {
    fetch('/api/auth/admin/users', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    })
    .then(data => {
        // Handle the response which wraps users in a 'users' property
        const users = data.users || data;
        const usersList = document.getElementById('adminUsersList');
        if (!users || users.length === 0) {
            usersList.innerHTML = '<p class="text-gray-400 text-center py-4">No users found</p>';
            return;
        }
        
        usersList.innerHTML = users.map(user => `
            <div class="border border-gray-700 rounded p-3 mb-2 bg-gray-800">
                <div class="flex justify-between items-center mb-2">
                    <div class="flex-1">
                        <div class="font-semibold text-white">${escapeHtml(user.username)}</div>
                        <div class="text-sm text-gray-400">${escapeHtml(user.email)}</div>
                    </div>
                    <div class="text-sm text-gray-400">
                        ${user.is_admin ? '<span class="bg-red-900 text-red-200 px-2 py-1 rounded text-xs mr-2">Admin</span>' : ''}
                        ${!user.is_active ? '<span class="bg-yellow-900 text-yellow-200 px-2 py-1 rounded text-xs">Inactive</span>' : ''}
                    </div>
                </div>
                <div class="flex gap-2 flex-wrap">
                    <button class="text-sm bg-blue-600 hover:bg-blue-700 text-white px-2 py-1 rounded" onclick="handleAdminToggleAdmin('${user.id}', ${!user.is_admin})">
                        ${user.is_admin ? 'Remove Admin' : 'Make Admin'}
                    </button>
                    <button class="text-sm bg-yellow-600 hover:bg-yellow-700 text-white px-2 py-1 rounded" onclick="handleAdminToggleActive('${user.id}', ${!user.is_active})">
                        ${user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    ${currentUser.id !== user.id ? `<button class="text-sm bg-red-600 hover:bg-red-700 text-white px-2 py-1 rounded" onclick="handleAdminDeleteUser('${user.id}')">Delete</button>` : ''}
                </div>
            </div>
        `).join('');
    })
    .catch(error => {
        console.error('Error loading users:', error);
        showToast('Failed to load users: ' + error.message, 'error');
    });
}

function handleAdminCreateUser(event) {
    event.preventDefault();
    
    const username = document.getElementById('adminNewUsername').value.trim();
    const email = document.getElementById('adminNewEmail').value.trim();
    const password = document.getElementById('adminNewPassword').value;
    const isAdmin = document.getElementById('adminNewIsAdmin').checked;
    
    if (!username || !email || !password) {
        showToast('Please fill in all fields', 'error');
        return;
    }
    
    fetch('/api/auth/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password, is_admin: isAdmin })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `HTTP ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        showToast(`User ${username} created successfully`, 'success');
        document.getElementById('adminCreateUserForm').reset();
        loadAdminUsers();
    })
    .catch(error => {
        console.error('Error creating user:', error);
        showToast('Failed to create user: ' + error.message, 'error');
    });
}

function handleAdminToggleAdmin(userId, makeAdmin) {
    const action = makeAdmin ? 'make admin' : 'remove admin';
    if (!confirm(`Are you sure you want to ${action}?`)) return;
    
    fetch(`/api/auth/admin/users/${userId}/toggle-admin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `HTTP ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        showToast(`User ${data.username} ${makeAdmin ? 'is now admin' : 'is no longer admin'}`, 'success');
        loadAdminUsers();
    })
    .catch(error => {
        console.error('Error toggling admin:', error);
        showToast('Failed to toggle admin: ' + error.message, 'error');
    });
}

function handleAdminToggleActive(userId, activate) {
    const action = activate ? 'activate' : 'deactivate';
    if (!confirm(`Are you sure you want to ${action} this user?`)) return;
    
    fetch(`/api/auth/admin/users/${userId}/toggle-active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `HTTP ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        showToast(`User ${data.username} is now ${activate ? 'active' : 'inactive'}`, 'success');
        loadAdminUsers();
    })
    .catch(error => {
        console.error('Error toggling active:', error);
        showToast('Failed to toggle user status: ' + error.message, 'error');
    });
}

function handleAdminDeleteUser(userId) {
    if (!confirm('Are you sure you want to delete this user? This cannot be undone.')) return;
    
    fetch(`/api/auth/admin/users/${userId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `HTTP ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        showToast('User deleted successfully', 'success');
        loadAdminUsers();
    })
    .catch(error => {
        console.error('Error deleting user:', error);
        showToast('Failed to delete user: ' + error.message, 'error');
    });
}

// Helper function to escape HTML entities
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Check auth status first
    checkAuthStatus().then(isAuthenticated => {
        if (isAuthenticated) {
            loadSubnets();
            loadStats();
            loadVersion();
            checkForUpdates();
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeyboard);
    
    // Close modals on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeAllModals();
        }
    });
});

function handleKeyboard(e) {
    // Ctrl/Cmd + K for global search focus
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        document.getElementById('globalSearch').focus();
    }
    // Ctrl/Cmd + N for new subnet
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        showSubnetModal();
    }
}

// ============================================================================
// Toast Notifications
// ============================================================================

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    
    const colors = {
        success: 'bg-emerald-500',
        error: 'bg-red-500',
        warning: 'bg-amber-500',
        info: 'bg-primary-500'
    };
    
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    toast.className = `toast ${colors[type]} text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 min-w-[300px]`;
    toast.innerHTML = `
        <i class="fas ${icons[type]}"></i>
        <span class="flex-1">${escapeHtml(message)}</span>
        <button onclick="this.parentElement.remove()" class="hover:opacity-75">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// ============================================================================
// Stats & Dashboard
// ============================================================================

async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();
        
        document.getElementById('statTotalSubnets').textContent = stats.total_subnets;
        document.getElementById('statTotalIPs').textContent = stats.total_ips;
        document.getElementById('statUtilization').textContent = stats.utilization + '%';
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// ============================================================================
// Subnets
// ============================================================================

async function loadSubnets() {
    try {
        console.log('[Subnets] Loading subnets...');
        const params = new URLSearchParams();
        const search = document.getElementById('globalSearch')?.value || '';
        const environment = document.getElementById('filterEnvironment')?.value || '';
        const vlan = document.getElementById('filterVLAN')?.value || '';
        const sortBy = document.getElementById('sortBy')?.value || 'cidr';
        
        if (search) params.append('search', search);
        if (environment) params.append('environment', environment);
        if (vlan) params.append('vlan', vlan);
        params.append('sort', sortBy);
        
        console.log('[Subnets] Fetching from /api/subnets?', params.toString());
        const response = await fetch(`/api/subnets?${params}`);
        console.log('[Subnets] Response status:', response.status, 'redirected:', response.redirected);
        
        const contentType = response.headers.get('content-type') || '';
        const looksJson = contentType.includes('application/json');
        
        if (response.status === 401 || response.status === 403 || response.redirected || !looksJson) {
            // Likely not authenticated anymore; show login modal and stop.
            console.warn('[Subnets] Not authorized or redirected, showing login modal');
            showModal('loginModal');
            throw new Error('Not authenticated. Please log in.');
        }
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        allSubnets = await response.json();
        console.log('[Subnets] Loaded', allSubnets.length, 'subnets');
        renderSubnets(allSubnets);
        loadStats();
    } catch (error) {
        console.error('[Subnets] Error loading subnets:', error);
        document.getElementById('subnetsContainer').innerHTML = `
            <div class="col-span-full text-center py-12 text-red-500">
                <i class="fas fa-exclamation-triangle text-3xl mb-3"></i>
                <p>Error loading subnets: ${escapeHtml(error.message || 'Unknown error')}</p>
            </div>
        `;
    }
}

function renderSubnets(subnets) {
    const container = document.getElementById('subnetsContainer');
    
    if (subnets.length === 0) {
        container.innerHTML = `
            <div class="col-span-full text-center py-16">
                <i class="fas fa-network-wired text-5xl text-gray-300 mb-4"></i>
                <h3 class="text-xl font-semibold text-gray-600 mb-2">No Subnets Found</h3>
                <p class="text-gray-500 mb-6">Create your first subnet to get started</p>
                <button onclick="showSubnetModal()" class="btn-primary">
                    <i class="fas fa-plus mr-2"></i>Create Subnet
                </button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = subnets.map(subnet => {
        const envClass = subnet.environment ? `env-${subnet.environment}` : '';
        const utilizationColor = subnet.utilization > 80 ? 'bg-red-500' : subnet.utilization > 50 ? 'bg-amber-500' : 'bg-emerald-500';
        
        return `
            <div class="subnet-card border-l-4 ${envClass} p-5 fade-in" onclick="viewSubnetDetail(${subnet.id})">
                <div class="flex justify-between items-start mb-3">
                    <div class="flex-1 min-w-0">
                        <h3 class="text-lg font-semibold text-gray-800 truncate">${escapeHtml(subnet.name)}</h3>
                        <p class="text-sm font-mono text-gray-500">${subnet.cidr}</p>
                    </div>
                    <div class="flex flex-col items-end gap-1">
                        ${subnet.vlan ? `<span class="bg-purple-100 text-purple-700 text-xs px-2 py-0.5 rounded font-medium">VLAN ${subnet.vlan}</span>` : ''}
                        ${subnet.environment ? `<span class="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded capitalize">${subnet.environment}</span>` : ''}
                    </div>
                </div>
                
                <p class="text-sm text-gray-600 mb-4 line-clamp-2">${escapeHtml(subnet.description || 'No description')}</p>
                
                <!-- Utilization Bar -->
                <div class="mb-4">
                    <div class="flex justify-between text-xs text-gray-500 mb-1">
                        <span>Utilization</span>
                        <span>${subnet.used_ips}/${subnet.usable_ips} (${subnet.utilization}%)</span>
                    </div>
                    <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div class="h-full ${utilizationColor} progress-bar" style="width: ${subnet.utilization}%"></div>
                    </div>
                </div>
                
                <div class="grid grid-cols-2 gap-3 text-xs">
                    <div class="bg-gray-50 rounded-lg p-2">
                        <span class="text-gray-500">Range</span>
                        <p class="font-mono font-medium text-gray-700 truncate">${subnet.first_ip || '-'}</p>
                        <p class="font-mono font-medium text-gray-700 truncate">${subnet.last_ip || '-'}</p>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-2">
                        <span class="text-gray-500">Gateway</span>
                        <p class="font-mono font-medium text-gray-700">${subnet.gateway || '-'}</p>
                        <span class="text-gray-500">Netmask</span>
                        <p class="font-mono font-medium text-gray-700">/${subnet.prefix_length || '-'}</p>
                    </div>
                </div>
                
                ${subnet.location ? `
                    <div class="mt-3 pt-3 border-t border-gray-100">
                        <span class="text-xs text-gray-500"><i class="fas fa-map-marker-alt mr-1"></i>${escapeHtml(subnet.location)}</span>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function handleGlobalSearch(value) {
    if (currentTab === 'subnets') {
        loadSubnets();
    } else {
        loadAllIPs();
    }
}

function applyFilters() {
    loadSubnets();
}

function clearFilters() {
    document.getElementById('filterEnvironment').value = '';
    document.getElementById('filterVLAN').value = '';
    document.getElementById('sortBy').value = 'cidr';
    document.getElementById('globalSearch').value = '';
    loadSubnets();
}

// ============================================================================
// Tabs
// ============================================================================

function switchTab(tab) {
    currentTab = tab;
    
    // Update tab styles
    document.getElementById('tabSubnets').classList.toggle('tab-active', tab === 'subnets');
    document.getElementById('tabSubnets').classList.toggle('text-gray-500', tab !== 'subnets');
    document.getElementById('tabIPs').classList.toggle('tab-active', tab === 'ips');
    document.getElementById('tabIPs').classList.toggle('text-gray-500', tab !== 'ips');
    const tabConn = document.getElementById('tabConnectors');
    if (tabConn) {
        tabConn.classList.toggle('tab-active', tab === 'connectors');
        tabConn.classList.toggle('text-gray-500', tab !== 'connectors');
    }
    
    // Show/hide views
    document.getElementById('subnetsView').classList.toggle('hidden', tab !== 'subnets');
    document.getElementById('ipsView').classList.toggle('hidden', tab !== 'ips');
    const connectorsView = document.getElementById('connectorsView');
    if (connectorsView) {
        connectorsView.classList.toggle('hidden', tab !== 'connectors');
    }
    
    if (tab === 'ips') {
        loadAllIPs();
    }
    if (tab === 'connectors') {
        loadConnectors();
    }
}

async function loadAllIPs() {
    try {
        const params = new URLSearchParams();
        const search = document.getElementById('globalSearch')?.value || '';
        const status = document.getElementById('ipFilterStatus')?.value || '';
        
        if (search) params.append('search', search);
        if (status) params.append('status', status);
        
        const response = await fetch(`/api/ips?${params}`);
        allIPs = await response.json();
        renderIPsTable(allIPs);
    } catch (error) {
        console.error('Error loading IPs:', error);
    }
}

function renderIPsTable(ips) {
    const tbody = document.getElementById('ipsTableBody');
    document.getElementById('ipCount').textContent = `${ips.length} IP addresses`;
    
    if (ips.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="px-4 py-12 text-center text-gray-500">
                    <i class="fas fa-ethernet text-3xl mb-3"></i>
                    <p>No IP addresses found</p>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = ips.map(ip => `
        <tr class="hover:bg-gray-50 transition-colors">
            <td class="px-4 py-3">
                <span class="font-mono font-medium text-gray-800">${ip.address}</span>
            </td>
            <td class="px-4 py-3">
                <span class="text-gray-700">${escapeHtml(ip.hostname || '-')}</span>
                ${ip.fqdn ? `<p class="text-xs text-gray-500">${escapeHtml(ip.fqdn)}</p>` : ''}
            </td>
            <td class="px-4 py-3">
                <span class="text-sm text-gray-600">${escapeHtml(ip.subnet_name || '-')}</span>
                <p class="text-xs font-mono text-gray-400">${ip.subnet_cidr || ''}</p>
            </td>
            <td class="px-4 py-3">
                <span class="status-${ip.status} text-xs px-2 py-1 rounded-full font-medium">${ip.status}</span>
            </td>
            <td class="px-4 py-3 text-sm text-gray-600">${escapeHtml(ip.device_type || '-')}</td>
            <td class="px-4 py-3 text-sm text-gray-600">${escapeHtml(ip.owner || '-')}</td>
            <td class="px-4 py-3">
                <div class="flex gap-2">
                    <button onclick="event.stopPropagation(); editIPFromTable(${ip.id})" class="text-primary-600 hover:text-primary-800" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button onclick="event.stopPropagation(); deleteIPFromTable(${ip.id})" class="text-red-600 hover:text-red-800" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

async function editIPFromTable(ipId) {
    try {
        const response = await fetch(`/api/ips/${ipId}`);
        const ip = await response.json();
        currentSubnetId = ip.subnet_id;
        editIP(ip);
    } catch (error) {
        console.error('Error loading IP:', error);
        showToast('Error loading IP', 'error');
    }
}

async function deleteIPFromTable(ipId) {
    if (!confirm('Are you sure you want to delete this IP?')) return;
    
    try {
        const response = await fetch(`/api/ips/${ipId}`, { method: 'DELETE' });
        if (response.ok) {
            showToast('IP deleted successfully', 'success');
            loadAllIPs();
            loadStats();
        }
    } catch (error) {
        console.error('Error deleting IP:', error);
        showToast('Error deleting IP', 'error');
    }
}

// ============================================================================
// Subnet Modal
// ============================================================================

function showSubnetModal() {
    currentSubnetId = null;
    document.getElementById('modalTitle').textContent = 'New Subnet';
    document.getElementById('subnetForm').reset();
    showModal('subnetModal');
    console.debug('showSubnetModal invoked, modal should now be visible');
}

function closeSubnetModal() {
    hideModal('subnetModal');
}

async function saveSubnet(event) {
    event.preventDefault();
    
    const tags = document.getElementById('subnetTags').value;
    const data = {
        name: document.getElementById('subnetName').value,
        cidr: document.getElementById('subnetCIDR').value,
        description: document.getElementById('subnetDescription').value || null,
        vlan: document.getElementById('subnetVLAN').value ? parseInt(document.getElementById('subnetVLAN').value) : null,
        gateway: document.getElementById('subnetGateway').value || null,
        dns_primary: document.getElementById('subnetDNS1').value || null,
        dns_secondary: document.getElementById('subnetDNS2').value || null,
        environment: document.getElementById('subnetEnvironment').value || null,
        location: document.getElementById('subnetLocation').value || null,
        tags: tags ? tags.split(',').map(t => t.trim()) : []
    };
    
    try {
        const url = currentSubnetId ? `/api/subnets/${currentSubnetId}` : '/api/subnets';
        const method = currentSubnetId ? 'PUT' : 'POST';
        
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const error = await response.json();
            showToast(error.error, 'error');
            return;
        }
        
        closeSubnetModal();
        loadSubnets();
        showToast(currentSubnetId ? 'Subnet updated successfully' : 'Subnet created successfully', 'success');
    } catch (error) {
        console.error('Error saving subnet:', error);
        showToast('Error saving subnet', 'error');
    }
}

// ============================================================================
// Subnet Detail
// ============================================================================

async function viewSubnetDetail(id) {
    try {
        const response = await fetch(`/api/subnets/${id}`);
        const subnet = await response.json();
        currentSubnetId = id;
        currentSubnetData = subnet;
        
        document.getElementById('detailSubnetName').textContent = subnet.name;
        document.getElementById('detailCIDR').textContent = subnet.cidr;
        document.getElementById('detailVLAN').textContent = subnet.vlan || '-';
        document.getElementById('detailGateway').textContent = subnet.gateway || '-';
        document.getElementById('detailEnvironment').textContent = subnet.environment ? subnet.environment.charAt(0).toUpperCase() + subnet.environment.slice(1) : '-';
        document.getElementById('detailLocation').textContent = subnet.location || '-';
        document.getElementById('detailDescription').textContent = subnet.description || 'No description provided';
        document.getElementById('detailUsedIPs').textContent = subnet.used_ips;
        document.getElementById('detailTotalIPs').textContent = subnet.usable_ips;
        document.getElementById('detailAvailableIPs').textContent = subnet.available_ips;
        
        // Update utilization bar
        const utilizationBar = document.getElementById('utilizationBar');
        utilizationBar.style.width = `${subnet.utilization}%`;
        utilizationBar.className = `h-full progress-bar ${subnet.utilization > 80 ? 'bg-red-500' : subnet.utilization > 50 ? 'bg-amber-500' : 'bg-gradient-to-r from-emerald-500 to-emerald-400'}`;
        
        // Update environment header color
        const header = document.getElementById('detailHeader');
        const envColors = {
            prod: 'from-red-600 to-red-700',
            staging: 'from-amber-600 to-amber-700',
            dev: 'from-emerald-600 to-emerald-700',
            test: 'from-blue-600 to-blue-700'
        };
        header.className = `bg-gradient-to-r ${envColors[subnet.environment] || 'from-primary-600 to-primary-700'} text-white p-5`;
        
        renderDetailIPList(subnet.ips);
        
        // Load next available IP
        loadNextAvailableIP();
        showModal('detailModal');
    } catch (error) {
        console.error('Error loading subnet detail:', error);
        showToast('Error loading subnet details', 'error');
    }
}

function renderDetailIPList(ips, filter = '') {
    const ipList = document.getElementById('detailIPList');
    
    let filteredIPs = ips;
    if (filter) {
        filteredIPs = ips.filter(ip => ip.status === filter);
    }
    
    if (filteredIPs.length === 0) {
        ipList.innerHTML = `
            <div class="text-center py-8 text-gray-500">
                <i class="fas fa-ethernet text-3xl mb-3"></i>
                <p>${filter ? 'No IPs match the filter' : 'No IPs documented yet'}</p>
            </div>
        `;
        return;
    }
    
    ipList.innerHTML = filteredIPs.map(ip => `
        <div class="bg-gray-50 rounded-lg p-4 hover:bg-gray-100 transition-colors">
            <div class="flex justify-between items-start">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-2">
                        <span class="font-mono font-bold text-gray-800 text-lg">${ip.address}</span>
                        <span class="status-${ip.status} text-xs px-2.5 py-1 rounded-full font-medium">${ip.status}</span>
                    </div>
                    ${ip.hostname ? `<p class="text-gray-700 font-medium">${escapeHtml(ip.hostname)}</p>` : ''}
                    ${ip.fqdn ? `<p class="text-sm text-gray-500">${escapeHtml(ip.fqdn)}</p>` : ''}
                    ${ip.description ? `<p class="text-sm text-gray-600 mt-1">${escapeHtml(ip.description)}</p>` : ''}
                    
                    <div class="flex flex-wrap gap-2 mt-3">
                        ${ip.device_type ? `<span class="text-xs bg-slate-200 text-slate-700 px-2 py-1 rounded"><i class="fas fa-server mr-1"></i>${escapeHtml(ip.device_type)}</span>` : ''}
                        ${ip.mac_address ? `<span class="text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded font-mono">${escapeHtml(ip.mac_address)}</span>` : ''}
                        ${ip.owner ? `<span class="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded"><i class="fas fa-user mr-1"></i>${escapeHtml(ip.owner)}</span>` : ''}
                        ${ip.department ? `<span class="text-xs bg-purple-100 text-purple-700 px-2 py-1 rounded">${escapeHtml(ip.department)}</span>` : ''}
                    </div>
                </div>
                <div class="flex gap-2 ml-4">
                    <button onclick="editIP(${JSON.stringify(ip).replace(/"/g, '&quot;')})" class="p-2 text-primary-600 hover:bg-primary-100 rounded-lg transition-colors" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button onclick="deleteIP(${ip.id})" class="p-2 text-red-600 hover:bg-red-100 rounded-lg transition-colors" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function filterDetailIPs() {
    const filter = document.getElementById('detailIPFilter').value;
    if (currentSubnetData) {
        renderDetailIPList(currentSubnetData.ips, filter);
    }
}

function closeDetailModal() {
    hideModal('detailModal');
    currentSubnetData = null;
}

function editCurrentSubnet() {
    const subnet = allSubnets.find(s => s.id === currentSubnetId);
    if (!subnet) return;
    
    document.getElementById('modalTitle').textContent = 'Edit Subnet';
    document.getElementById('subnetName').value = subnet.name;
    document.getElementById('subnetCIDR').value = subnet.cidr;
    document.getElementById('subnetDescription').value = subnet.description || '';
    document.getElementById('subnetVLAN').value = subnet.vlan || '';
    document.getElementById('subnetGateway').value = subnet.gateway || '';
    document.getElementById('subnetDNS1').value = subnet.dns_primary || '';
    document.getElementById('subnetDNS2').value = subnet.dns_secondary || '';
    document.getElementById('subnetEnvironment').value = subnet.environment || '';
    document.getElementById('subnetLocation').value = subnet.location || '';
    document.getElementById('subnetTags').value = (subnet.tags || []).join(', ');
    
    closeDetailModal();
    document.getElementById('subnetModal').classList.remove('hidden');
}

async function deleteCurrentSubnet() {
    const subnet = allSubnets.find(s => s.id === currentSubnetId);
    if (!subnet) return;
    
    if (!confirm(`Are you sure you want to delete "${subnet.name}"?\n\nThis will also delete ${subnet.used_ips} IP address(es).`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/subnets/${currentSubnetId}`, { method: 'DELETE' });
        if (response.ok) {
            closeDetailModal();
            loadSubnets();
            showToast('Subnet deleted successfully', 'success');
        }
    } catch (error) {
        console.error('Error deleting subnet:', error);
        showToast('Error deleting subnet', 'error');
    }
}

// ============================================================================
// Subnet Scanning (Async with Live Logs)
// ============================================================================

function showScanModal() {
    if (!currentSubnetId) return;
    // Reset UI
    currentScanJobId = null;
    currentScanDiscovered = [];
    document.querySelector('input[name="scanType"][value="ping"]').checked = true;
    document.getElementById('scanLogs').textContent = '';
    document.getElementById('scanDiscoveredList').innerHTML = '';
    document.getElementById('scanDiscoveredCount').textContent = '0 hosts discovered';
    document.getElementById('scanProgressBar').style.width = '0%';
    document.getElementById('scanImportControls').classList.add('hidden');
    const btn = document.getElementById('startScanBtn');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-play mr-2"></i>Start Scan';
    showModal('scanModal');
}

function closeScanModal() {
    hideModal('scanModal');
}

async function startScanJob() {
    if (!currentSubnetId || scanInProgress) return;
    const type = document.querySelector('input[name="scanType"]:checked')?.value || 'ping';
    scanInProgress = true;
    const btn = document.getElementById('startScanBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Starting...';

    try {
        const res = await fetch(`/api/scanner/scan-subnet/${currentSubnetId}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scan_type: type })
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            showToast(data.error || 'Failed to start scan', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play mr-2"></i>Start Scan';
            scanInProgress = false;
            return;
        }
        currentScanJobId = data.job_id;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Scanning...';
        pollScanJob();
    } catch (e) {
        console.error('Error starting scan job:', e);
        showToast('Error starting scan', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play mr-2"></i>Start Scan';
        scanInProgress = false;
    }
}

async function pollScanJob() {
    if (!currentScanJobId) return;
    try {
        const res = await fetch(`/api/scanner/scan-jobs/${currentScanJobId}`);
        const job = await res.json();
        if (!res.ok || job.error) {
            showToast(job.error || 'Scan error', 'error');
            scanInProgress = false;
            document.getElementById('startScanBtn').disabled = false;
            document.getElementById('startScanBtn').innerHTML = '<i class="fas fa-play mr-2"></i>Start Scan';
            return;
        }

        // Update logs
        const logsEl = document.getElementById('scanLogs');
        logsEl.textContent = (job.logs || []).join('\n');
        logsEl.scrollTop = logsEl.scrollHeight;

        // Update discovered list
        currentScanDiscovered = job.discovered || [];
        document.getElementById('scanDiscoveredCount').textContent = `${currentScanDiscovered.length} host(s) discovered`;
        renderScanDiscovered(currentScanDiscovered);

        // Update progress bar (indeterminate until complete)
        const bar = document.getElementById('scanProgressBar');
        bar.style.width = job.status === 'completed' ? '100%' : (bar.style.width === '0%' ? '25%' : bar.style.width);

        if (job.status === 'completed') {
            scanInProgress = false;
            const btn = document.getElementById('startScanBtn');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-rotate-right mr-2"></i>Run Again';
            document.getElementById('scanImportControls').classList.remove('hidden');
            showToast(`Scan complete: ${job.total_discovered} host(s) found`, 'success');
            return;
        }

        if (job.status === 'error') {
            scanInProgress = false;
            const btn = document.getElementById('startScanBtn');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play mr-2"></i>Start Scan';
            showToast('Scan failed', 'error');
            return;
        }

        // Continue polling
        setTimeout(pollScanJob, 1000);
    } catch (e) {
        console.error('Error polling scan job:', e);
        setTimeout(pollScanJob, 1500);
    }
}

function renderScanDiscovered(items) {
    const list = document.getElementById('scanDiscoveredList');
    if (!items || items.length === 0) {
        list.innerHTML = '<p class="text-sm text-gray-500">No hosts discovered yet...</p>';
        return;
    }
    list.innerHTML = items.map((h, idx) => `
        <label class="flex items-start gap-3 p-2 rounded-lg hover:bg-gray-100">
            <input type="checkbox" class="mt-1.5" data-sel-index="${idx}" checked>
            <div class="flex-1">
                <div class="flex items-center gap-2">
                    <span class="font-mono font-semibold text-gray-800">${h.address}</span>
                    ${h.hostname ? `<span class="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">${escapeHtml(h.hostname)}</span>` : ''}
                </div>
                <div class="text-xs text-gray-600 mt-1">
                    ${h.mac_address ? `<span class="mr-2">MAC: <span class="font-mono">${escapeHtml(h.mac_address)}</span></span>` : ''}
                    ${h.manufacturer ? `<span class="mr-2">${escapeHtml(h.manufacturer)}</span>` : ''}
                </div>
                ${Array.isArray(h.open_ports) && h.open_ports.length ? `
                <div class="text-xs text-gray-700 mt-1">
                    Ports: ${h.open_ports.slice(0,5).map(p => `${p.port}/${p.proto} ${escapeHtml(p.service || '')}`).join(', ')}
                    ${h.open_ports.length > 5 ? '…' : ''}
                </div>` : ''}
                ${h.os_info ? `<div class="text-xs text-gray-700 mt-1">OS: ${escapeHtml(h.os_info)}</div>` : ''}
            </div>
        </label>
    `).join('');
}

async function importScanResults(importAll) {
    if (!currentSubnetId) return;
    const fields = {
        hostname: document.getElementById('importHostname').checked,
        mac: document.getElementById('importMAC').checked,
        device: document.getElementById('importDeviceType').checked,
        os: document.getElementById('importOS').checked
    };

    let selected = [];
    if (importAll) {
        selected = currentScanDiscovered.slice();
    } else {
        const checks = Array.from(document.querySelectorAll('#scanDiscoveredList input[type="checkbox"][data-sel-index]'));
        const indices = checks.filter(c => c.checked).map(c => parseInt(c.getAttribute('data-sel-index')));
        selected = indices.map(i => currentScanDiscovered[i]).filter(Boolean);
    }

    if (!selected.length) {
        showToast('No hosts selected to import', 'warning');
        return;
    }

    const payloadIps = selected.map(h => ({
        address: h.address,
        status: 'in-use',
        ...(fields.hostname && h.hostname ? { hostname: h.hostname } : {}),
        ...(fields.mac && h.mac_address ? { mac_address: h.mac_address } : {}),
        ...(fields.device && h.open_ports && h.open_ports.length ? { device_type: (h.open_ports[0].service || 'Unknown Device') } : {}),
        ...(fields.os && h.os_info ? { os_info: h.os_info } : {})
    }));

    try {
        const res = await fetch('/api/scanner/bulk-import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subnet_id: currentSubnetId, ips: payloadIps, auto_enrich: true })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Import failed', 'error');
            return;
        }
        showToast(`${data.imported_count} imported, ${data.failed_count} failed`, 'success');
        // Refresh subnet details and stats
        viewSubnetDetail(currentSubnetId);
        loadStats();
        closeScanModal();
    } catch (e) {
        console.error('Error importing scan results:', e);
        showToast('Error importing results', 'error');
    }
}

// ============================================================================
// IP Modal
// ============================================================================

async function loadNextAvailableIP() {
    if (!currentSubnetId) return;
    
    try {
        const response = await fetch(`/api/subnets/${currentSubnetId}/available-ips?limit=1`);
        const data = await response.json();
        
        const nextIPEl = document.getElementById('nextIPAddress');
        if (data.next_available) {
            nextIPEl.textContent = data.next_available;
        } else {
            nextIPEl.textContent = 'No IPs available';
        }
    } catch (error) {
        console.error('Error loading next available IP:', error);
    }
}

function useNextAvailableIP() {
    const nextIP = document.getElementById('nextIPAddress').textContent;
    if (nextIP && nextIP !== 'No IPs available' && nextIP !== '-') {
        document.getElementById('ipAddress').value = nextIP;
    }
}

function showIPModal() {
    if (!currentSubnetId) return;
    
    currentIPId = null;
    document.getElementById('ipModalTitle').textContent = 'New IP Address';
    document.getElementById('ipForm').reset();
    document.getElementById('ipStatus').value = 'in-use';
    document.getElementById('nextAvailableIP').classList.remove('hidden');
    
    loadNextAvailableIP();
    restoreDetailAfterIPModal = isModalVisible('detailModal');
    if (restoreDetailAfterIPModal) hideModal('detailModal');
    showModal('ipModal');
}

function editIP(ip) {
    currentIPId = ip.id;
    document.getElementById('ipModalTitle').textContent = 'Edit IP Address';
    document.getElementById('nextAvailableIP').classList.add('hidden');
    
    document.getElementById('ipAddress').value = ip.address;
    document.getElementById('ipHostname').value = ip.hostname || '';
    document.getElementById('ipFQDN').value = ip.fqdn || '';
    document.getElementById('ipDescription').value = ip.description || '';
    document.getElementById('ipStatus').value = ip.status;
    document.getElementById('ipMAC').value = ip.mac_address || '';
    document.getElementById('ipDeviceType').value = ip.device_type || '';
    document.getElementById('ipManufacturer').value = ip.manufacturer || '';
    document.getElementById('ipModel').value = ip.model || '';
    document.getElementById('ipOwner').value = ip.owner || '';
    document.getElementById('ipDepartment').value = ip.department || '';
    document.getElementById('ipNotes').value = ip.notes || '';

    restoreDetailAfterIPModal = isModalVisible('detailModal');
    if (restoreDetailAfterIPModal) hideModal('detailModal');
    showModal('ipModal');
}

function closeIPModal() {
    hideModal('ipModal');
    if (restoreDetailAfterIPModal) {
        showModal('detailModal');
        restoreDetailAfterIPModal = false;
    }
    currentIPId = null;
}

async function saveIP(event) {
    event.preventDefault();
    
    const data = {
        address: document.getElementById('ipAddress').value,
        hostname: document.getElementById('ipHostname').value || null,
        fqdn: document.getElementById('ipFQDN').value || null,
        description: document.getElementById('ipDescription').value || null,
        subnet_id: currentSubnetId,
        status: document.getElementById('ipStatus').value,
        mac_address: document.getElementById('ipMAC').value || null,
        device_type: document.getElementById('ipDeviceType').value || null,
        manufacturer: document.getElementById('ipManufacturer').value || null,
        model: document.getElementById('ipModel').value || null,
        owner: document.getElementById('ipOwner').value || null,
        department: document.getElementById('ipDepartment').value || null,
        notes: document.getElementById('ipNotes').value || null
    };
    
    try {
        const url = currentIPId ? `/api/ips/${currentIPId}` : '/api/ips';
        const method = currentIPId ? 'PUT' : 'POST';
        
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const error = await response.json();
            showToast(error.error, 'error');
            return;
        }
        
        closeIPModal();
        viewSubnetDetail(currentSubnetId);
        loadStats();
        showToast(currentIPId ? 'IP updated successfully' : 'IP added successfully', 'success');
    } catch (error) {
        console.error('Error saving IP:', error);
        showToast('Error saving IP', 'error');
    }
}

async function deleteIP(ipId) {
    if (!confirm('Are you sure you want to delete this IP?')) return;
    
    try {
        const response = await fetch(`/api/ips/${ipId}`, { method: 'DELETE' });
        if (response.ok) {
            viewSubnetDetail(currentSubnetId);
            loadStats();
            showToast('IP deleted successfully', 'success');
        }
    } catch (error) {
        console.error('Error deleting IP:', error);
        showToast('Error deleting IP', 'error');
    }
}

// ============================================================================
// Bulk Add
// ============================================================================

function showBulkAddModal() {
    document.getElementById('bulkIPs').value = '';
    showModal('bulkModal');
}

function closeBulkModal() {
    hideModal('bulkModal');
}

async function processBulkAdd() {
    const input = document.getElementById('bulkIPs').value.trim();
    if (!input) {
        showToast('Please enter at least one IP', 'warning');
        return;
    }
    
    const lines = input.split('\n').filter(l => l.trim());
    const ips = lines.map(line => {
        const parts = line.split(',').map(p => p.trim());
        return {
            address: parts[0],
            hostname: parts[1] || null,
            status: parts[2] || 'in-use'
        };
    });
    
    try {
        const response = await fetch('/api/ips/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                subnet_id: currentSubnetId,
                ips: ips
            })
        });
        
        const result = await response.json();
        
        if (result.created > 0) {
            showToast(`Added ${result.created} IP(s)${result.errors > 0 ? `, ${result.errors} failed` : ''}`, result.errors > 0 ? 'warning' : 'success');
        } else {
            showToast('No IPs were added', 'error');
        }
        
        closeBulkModal();
        viewSubnetDetail(currentSubnetId);
        loadStats();
    } catch (error) {
        console.error('Error bulk adding IPs:', error);
        showToast('Error adding IPs', 'error');
    }
}

// ============================================================================
// IP Lookup
// ============================================================================

function showIPLookupModal() {
    document.getElementById('lookupIP').value = '';
    document.getElementById('lookupResult').classList.add('hidden');
    showModal('lookupModal');
    document.getElementById('lookupIP').focus();
}

function closeLookupModal() {
    hideModal('lookupModal');
}

async function performIPLookup() {
    const ip = document.getElementById('lookupIP').value.trim();
    if (!ip) return;
    
    try {
        const response = await fetch(`/api/lookup/ip/${encodeURIComponent(ip)}`);
        const result = await response.json();
        
        const resultDiv = document.getElementById('lookupResult');
        resultDiv.classList.remove('hidden');
        
        if (result.subnet) {
            resultDiv.innerHTML = `
                <div class="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
                    <h4 class="font-semibold text-emerald-800 mb-2"><i class="fas fa-check-circle mr-2"></i>IP Found</h4>
                    <p class="text-sm text-gray-700 mb-2"><strong>Subnet:</strong> ${escapeHtml(result.subnet.name)} (${result.subnet.cidr})</p>
                    ${result.registered ? `
                        <div class="mt-3 pt-3 border-t border-emerald-200">
                            <p class="text-sm"><strong>Status:</strong> <span class="status-${result.registered.status} text-xs px-2 py-0.5 rounded">${result.registered.status}</span></p>
                            ${result.registered.hostname ? `<p class="text-sm"><strong>Hostname:</strong> ${escapeHtml(result.registered.hostname)}</p>` : ''}
                            ${result.registered.owner ? `<p class="text-sm"><strong>Owner:</strong> ${escapeHtml(result.registered.owner)}</p>` : ''}
                        </div>
                    ` : `<p class="text-sm text-amber-600 mt-2"><i class="fas fa-info-circle mr-1"></i>IP not documented in this subnet</p>`}
                    <button onclick="viewSubnetDetail(${result.subnet.id}); closeLookupModal();" class="mt-3 btn-primary text-sm">View Subnet</button>
                </div>
            `;
        } else {
            resultDiv.innerHTML = `
                <div class="bg-amber-50 border border-amber-200 rounded-lg p-4">
                    <h4 class="font-semibold text-amber-800"><i class="fas fa-exclamation-triangle mr-2"></i>Not Found</h4>
                    <p class="text-sm text-gray-700 mt-2">${escapeHtml(result.message)}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Error looking up IP:', error);
        showToast('Error looking up IP', 'error');
    }
}

// ============================================================================
// Export/Import
// ============================================================================

function showExportModal() {
    window.location.href = '/api/export';
    showToast('Exporting data...', 'info');
}

function showImportModal() {
    document.getElementById('importFile').value = '';
    document.getElementById('importReplace').checked = false;
    document.getElementById('importModal').classList.remove('hidden');
}

function closeImportModal() {
    document.getElementById('importModal').classList.add('hidden');
}

async function handleImportFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const data = JSON.parse(e.target.result);
            const mode = document.getElementById('importReplace').checked ? 'replace' : 'merge';
            
            if (mode === 'replace' && !confirm('This will DELETE all existing data. Are you sure?')) {
                return;
            }
            
            const response = await fetch(`/api/import?mode=${mode}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            closeImportModal();
            loadSubnets();
            showToast(`Imported ${result.imported_subnets} subnet(s) and ${result.imported_ips} IP(s)`, 'success');
        } catch (error) {
            console.error('Error importing data:', error);
            showToast('Error importing data. Check file format.', 'error');
        }
    };
    reader.readAsText(file);
}

// ============================================================================
// Sidebar
// ============================================================================

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    sidebar.classList.toggle('open');
    overlay.classList.toggle('hidden');
}

// ============================================================================
// Utility Functions
// ============================================================================

function closeAllModals() {
    closeSubnetModal();
    closeIPModal();
    closeDetailModal();
    closeLookupModal();
    closeBulkModal();
    closeImportModal();
}

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}
// ============================================================================
// Version and Update Checking
// ============================================================================

async function loadVersion() {
    try {
        const res = await fetch('/api/auth/version');
        const data = await res.json();
        document.getElementById('appVersion').textContent = data.version || '-';
    } catch (error) {
        console.error('Error loading version:', error);
        document.getElementById('appVersion').textContent = 'unknown';
    }
}

async function checkForUpdates() {
    const btn = document.getElementById('updateCheckBtn');
    if (btn) btn.disabled = true;
    const versionBadge = document.getElementById('versionBadge');
    const headerBadge = document.getElementById('headerUpdateBadge');

    const setPill = (el, text, colorClass) => {
        if (!el) return;
        el.textContent = text;
        el.className = `text-xs px-2.5 py-1 rounded-full font-semibold ${colorClass}`;
    };

    setPill(versionBadge, 'Checking...', 'bg-gray-200 text-gray-700');

    try {
        console.log('[Updates] Checking for updates...');
        const res = await fetch('/api/auth/check-updates');
        console.log('[Updates] Response status:', res.status);
        
        if (!res.ok) {
            console.error('[Updates] HTTP error:', res.status, res.statusText);
            showToast(`Update check failed: ${res.status}`, 'error');
            setPill(versionBadge, 'Check failed', 'bg-red-100 text-red-700');
            if (headerBadge) headerBadge.classList.add('hidden');
            return;
        }
        
        const data = await res.json();
        console.log('[Updates] Response data:', data);
        
        if (data.error) {
            console.warn('[Updates] API error:', data.error);
            setPill(versionBadge, 'Check failed', 'bg-red-100 text-red-700');
            if (headerBadge) headerBadge.classList.add('hidden');
            showToast(`Update check failed: ${data.error}`, 'warning');
        } else if (data.update_available) {
            console.log('[Updates] Update available:', data.latest_version);
            const latest = data.latest_version || 'new version';
            setPill(versionBadge, 'Update available', 'bg-amber-100 text-amber-700');
            if (headerBadge) headerBadge.classList.remove('hidden');
            showToast(`Version ${latest} available!`, 'info');
            if (data.release_url) {
                const updateLink = document.querySelector('.update-link');
                if (updateLink) updateLink.href = data.release_url;
            }
        } else {
            console.log('[Updates] Already up to date');
            setPill(versionBadge, 'Up to date', 'bg-emerald-100 text-emerald-700');
            if (headerBadge) headerBadge.classList.add('hidden');
            // No toast on up-to-date to avoid noise
        }
    } catch (error) {
        console.error('[Updates] Error checking updates:', error);
        showToast(`Update check error: ${error.message}`, 'error');
        setPill(versionBadge, 'Check failed', 'bg-red-100 text-red-700');
        if (headerBadge) headerBadge.classList.add('hidden');
    } finally {
        if (btn) btn.disabled = false;
    }
}