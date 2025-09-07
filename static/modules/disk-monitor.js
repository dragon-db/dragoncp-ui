/**
 * Disk Monitor Module
 * Handles disk usage monitoring for both local and remote storage
 */
export class DiskMonitor {
    constructor(app) {
        this.app = app;
        this.initializeDiskUsageMonitoring();
    }

    initializeDiskUsageMonitoring() {
        this.loadDiskUsage();
        
        // Add refresh button event listener
        document.getElementById('refreshDiskUsageBtn').addEventListener('click', () => {
            this.refreshDiskUsage();
        });
    }

    async loadDiskUsage() {
        try {
            // Load both local and remote disk usage in parallel
            const [localResponse, remoteResponse] = await Promise.all([
                fetch('/api/disk-usage/local'),
                fetch('/api/disk-usage/remote')
            ]);

            const localData = await localResponse.json();
            const remoteData = await remoteResponse.json();

            this.updateDiskUsageDisplay(localData, remoteData);
            document.getElementById('diskUsageCard').style.display = 'block';

        } catch (error) {
            console.error('Failed to load disk usage:', error);
            // Don't show error for disk usage as it's not critical
        }
    }

    async refreshDiskUsage() {
        try {
            // Show loading state
            const refreshBtn = document.getElementById('refreshDiskUsageBtn');
            const originalHtml = refreshBtn.innerHTML;
            
            // Add spinning class directly to the icon for smooth animation
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise spinning"></i>';
            refreshBtn.disabled = true;

            // Load both local and remote disk usage in parallel
            const [localResponse, remoteResponse] = await Promise.all([
                fetch('/api/disk-usage/local'),
                fetch('/api/disk-usage/remote')
            ]);

            const localData = await localResponse.json();
            const remoteData = await remoteResponse.json();

            this.updateDiskUsageDisplay(localData, remoteData);
            this.app.ui.showAlert('Disk usage refreshed successfully!', 'success');

            // Restore button state
            refreshBtn.innerHTML = originalHtml;
            refreshBtn.disabled = false;

        } catch (error) {
            console.error('Failed to refresh disk usage:', error);
            this.app.ui.showAlert('Failed to refresh disk usage', 'danger');
            
            // Restore button state
            const refreshBtn = document.getElementById('refreshDiskUsageBtn');
            refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
            refreshBtn.disabled = false;
        }
    }

    updateDiskUsageDisplay(localData, remoteData) {
        const container = document.getElementById('diskUsageInfo');
        container.innerHTML = '';

        // Display local disk usage
        if (localData.status === 'success' && localData.disk_info) {
            localData.disk_info.forEach((disk, index) => {
                this.renderDiskUsageItem(container, disk, `Local Disk ${index + 1}`, 'local');
            });
        }

        // Display remote disk usage
        if (remoteData.status === 'success' && remoteData.storage_info) {
            this.renderDiskUsageItem(container, remoteData.storage_info, 'Remote Storage', 'remote');
        } else if (remoteData.status === 'error') {
            // Check if it's a rate limiting error
            const isRateLimit = remoteData.message && remoteData.message.includes('429');
            const errorMessage = isRateLimit ? 
                'Rate limited (2 requests/minute). Please wait before refreshing.' : 
                remoteData.message;
            this.renderDiskUsageError(container, 'Remote Storage', errorMessage);
        }

        // Update last refreshed timestamp
        this.updateLastRefreshTime();
    }

    updateLastRefreshTime() {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        const dateString = now.toLocaleDateString();
        
        // Update button tooltip
        const refreshBtn = document.getElementById('refreshDiskUsageBtn');
        refreshBtn.title = `Last updated: ${timeString} - Click to refresh`;
        
        // Update footer display
        const lastUpdateElement = document.getElementById('diskUsageLastUpdate');
        if (lastUpdateElement) {
            lastUpdateElement.innerHTML = `<i class="bi bi-clock"></i> Last updated: ${dateString} at ${timeString}`;
        }
    }

    renderDiskUsageItem(container, diskInfo, label, type) {
        const col = document.createElement('div');
        col.className = 'col-lg-3 col-md-6 mb-3';

        let content = '';
        
        if (type === 'local' && diskInfo.available) {
            const usageColor = this.getDiskUsageColor(diskInfo.usage_percent);
            
            // Standardize local disk units (convert G to GB, T to TB, etc.)
            const usedSize = this.standardizeUnit(diskInfo.used_size);
            const availableSize = this.standardizeUnit(diskInfo.available_size);
            const totalSize = this.standardizeUnit(diskInfo.total_size);
            
            content = `
                <div class="card h-100 disk-usage-card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6 class="card-title mb-0">
                                <i class="bi bi-hdd disk-usage-icon"></i> ${label}
                            </h6>
                            <span class="badge bg-${usageColor}">${diskInfo.usage_percent}%</span>
                        </div>
                        <div class="progress mb-2" style="height: 8px;">
                            <div class="progress-bar bg-${usageColor}" 
                                 style="width: ${diskInfo.usage_percent}%"></div>
                        </div>
                        <div class="disk-details">
                            <small class="text-muted d-block">
                                <i class="bi bi-folder"></i> ${this.app.ui.escapeHtml(diskInfo.path)}
                            </small>
                            <small class="text-muted d-block">
                                <i class="bi bi-device-hdd"></i> ${diskInfo.filesystem}
                            </small>
                            <div class="d-flex justify-content-between mt-1">
                                <small><strong>Used:</strong> ${usedSize}</small>
                                <small><strong>Free:</strong> ${availableSize}</small>
                            </div>
                            <small class="text-muted">
                                <strong>Total:</strong> ${totalSize}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        } else if (type === 'remote' && diskInfo.available) {
            const usageColor = this.getDiskUsageColor(diskInfo.usage_percent);
            content = `
                <div class="card h-100 disk-usage-card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6 class="card-title mb-0">
                                <i class="bi bi-cloud disk-usage-icon"></i> ${label}
                            </h6>
                            <span class="badge bg-${usageColor}">${diskInfo.usage_percent}%</span>
                        </div>
                        <div class="progress mb-2" style="height: 8px;">
                            <div class="progress-bar bg-${usageColor}" 
                                 style="width: ${diskInfo.usage_percent}%"></div>
                        </div>
                        <div class="disk-details">
                            <div class="d-flex justify-content-between">
                                <small><strong>Used:</strong> ${diskInfo.used_display || (diskInfo.used_storage_value + ' ' + diskInfo.used_storage_unit)}</small>
                                <small><strong>Free:</strong> ${diskInfo.free_display || (diskInfo.free_storage_gb + ' GB')}</small>
                            </div>
                            <small class="text-muted">
                                <strong>Total:</strong> ${diskInfo.total_display || (diskInfo.total_storage_value + ' ' + diskInfo.total_storage_unit)}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        } else {
            // Error state
            content = `
                <div class="card h-100 disk-usage-card border-danger">
                    <div class="card-body">
                        <h6 class="card-title text-danger">
                            <i class="bi bi-exclamation-triangle"></i> ${label}
                        </h6>
                        <small class="text-danger">
                            ${diskInfo.error || 'Unavailable'}
                        </small>
                    </div>
                </div>
            `;
        }

        col.innerHTML = content;
        container.appendChild(col);
    }

    standardizeUnit(sizeString) {
        if (!sizeString) return 'N/A';
        
        // Convert abbreviated units to full names
        return sizeString
            .replace(/(\d+)T$/, '$1 TB')
            .replace(/(\d+)G$/, '$1 GB')
            .replace(/(\d+)M$/, '$1 MB')
            .replace(/(\d+)K$/, '$1 KB')
            .replace(/(\d+\.?\d*)T$/, '$1 TB')
            .replace(/(\d+\.?\d*)G$/, '$1 GB')
            .replace(/(\d+\.?\d*)M$/, '$1 MB')
            .replace(/(\d+\.?\d*)K$/, '$1 KB');
    }

    renderDiskUsageError(container, label, errorMessage) {
        const col = document.createElement('div');
        col.className = 'col-lg-3 col-md-6 mb-3';
        
        col.innerHTML = `
            <div class="card h-100 disk-usage-card border-danger">
                <div class="card-body">
                    <h6 class="card-title text-danger">
                        <i class="bi bi-exclamation-triangle"></i> ${label}
                    </h6>
                    <small class="text-danger">
                        ${this.app.ui.escapeHtml(errorMessage)}
                    </small>
                </div>
            </div>
        `;
        
        container.appendChild(col);
    }

    getDiskUsageColor(percentage) {
        if (percentage >= 90) return 'danger';
        if (percentage >= 75) return 'warning';
        if (percentage >= 50) return 'info';
        return 'success';
    }
}
