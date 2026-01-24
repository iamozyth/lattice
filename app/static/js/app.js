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

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadSubnets();
    loadStats();
    
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
        const params = new URLSearchParams();
        const search = document.getElementById('globalSearch')?.value || '';
        const environment = document.getElementById('filterEnvironment')?.value || '';
        const vlan = document.getElementById('filterVLAN')?.value || '';
        const sortBy = document.getElementById('sortBy')?.value || 'cidr';
        
        if (search) params.append('search', search);
        if (environment) params.append('environment', environment);
        if (vlan) params.append('vlan', vlan);
        params.append('sort', sortBy);
        
        const response = await fetch(`/api/subnets?${params}`);
        allSubnets = await response.json();
        renderSubnets(allSubnets);
        loadStats();
    } catch (error) {
        console.error('Error loading subnets:', error);
        document.getElementById('subnetsContainer').innerHTML = `
            <div class="col-span-full text-center py-12 text-red-500">
                <i class="fas fa-exclamation-triangle text-3xl mb-3"></i>
                <p>Error loading subnets</p>
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
    
    // Show/hide views
    document.getElementById('subnetsView').classList.toggle('hidden', tab !== 'subnets');
    document.getElementById('ipsView').classList.toggle('hidden', tab !== 'ips');
    
    if (tab === 'ips') {
        loadAllIPs();
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
    document.getElementById('subnetModal').classList.remove('hidden');
}

function closeSubnetModal() {
    document.getElementById('subnetModal').classList.add('hidden');
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
        
        document.getElementById('detailModal').classList.remove('hidden');
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
    document.getElementById('detailModal').classList.add('hidden');
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
    
    document.getElementById('ipModal').classList.remove('hidden');
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
    
    document.getElementById('ipModal').classList.remove('hidden');
}

function closeIPModal() {
    document.getElementById('ipModal').classList.add('hidden');
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
    document.getElementById('bulkModal').classList.remove('hidden');
}

function closeBulkModal() {
    document.getElementById('bulkModal').classList.add('hidden');
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
    document.getElementById('lookupModal').classList.remove('hidden');
    document.getElementById('lookupIP').focus();
}

function closeLookupModal() {
    document.getElementById('lookupModal').classList.add('hidden');
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
