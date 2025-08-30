/**
 * Backup Manager Module
 * Handles backup operations, file restoration, deletion, and backup UI management
 */
export class BackupManager {
    constructor(app) {
        this.app = app;
        this.currentBackupContext = null;
        this.createBackupsUIElements();
    }

    createBackupsUIElements() {
        try {
            // Hook up backups card controls
            const refreshBtn = document.getElementById('refreshBackupsBtn');
            if (refreshBtn) refreshBtn.addEventListener('click', () => this.loadBackups());
            
            const importBtn = document.getElementById('importBackupsBtn');
            if (importBtn) importBtn.addEventListener('click', () => this.importBackupsFromDisk());
            
            const selectAll = document.getElementById('backupFilesSelectAll');
            if (selectAll) selectAll.addEventListener('change', (e) => {
                const checked = e.target.checked;
                document.querySelectorAll('#backupFilesTable input[type="checkbox"]').forEach(cb => cb.checked = checked);
                this.updateSelectedFilesCount();
            });
            
            const restoreSelectedBtn = document.getElementById('restoreSelectedBtn');
            if (restoreSelectedBtn) restoreSelectedBtn.addEventListener('click', () => this.restoreSelectedFiles());
            
            const restoreAllBtn = document.getElementById('restoreAllBtn');
            if (restoreAllBtn) restoreAllBtn.addEventListener('click', () => this.startRestoreAllFromFiles());
            
            const applyRestoreBtn = document.getElementById('applyRestoreBtn');
            if (applyRestoreBtn) applyRestoreBtn.addEventListener('click', () => this.applyPlannedRestore());
            
            const cancelRestoreBtn = document.getElementById('cancelRestoreBtn');
            if (cancelRestoreBtn) cancelRestoreBtn.addEventListener('click', () => this.showBackupFilesStage());

            // Delete stage event handlers
            const cancelDeleteBtn = document.getElementById('cancelDeleteBtn');
            if (cancelDeleteBtn) cancelDeleteBtn.addEventListener('click', () => this.showBackupsListStage());
            
            const cancelDeleteBtn2 = document.getElementById('cancelDeleteBtn2');
            if (cancelDeleteBtn2) cancelDeleteBtn2.addEventListener('click', () => this.showBackupsListStage());
            
            const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
            if (confirmDeleteBtn) confirmDeleteBtn.addEventListener('click', () => this.executeDelete());
            
            // Delete options change handlers
            const deleteRecordCheck = document.getElementById('deleteRecordCheck');
            const deleteFilesCheck = document.getElementById('deleteFilesCheck');
            const deleteFilesPreview = document.getElementById('deleteFilesPreview');
            
            if (deleteRecordCheck && deleteFilesCheck && confirmDeleteBtn) {
                const updateDeleteButton = () => {
                    const hasSelection = deleteRecordCheck.checked || deleteFilesCheck.checked;
                    confirmDeleteBtn.disabled = !hasSelection;
                    
                    if (deleteFilesCheck.checked && deleteFilesPreview) {
                        deleteFilesPreview.style.display = 'block';
                    } else if (deleteFilesPreview) {
                        deleteFilesPreview.style.display = 'none';
                    }
                };
                
                deleteRecordCheck.addEventListener('change', updateDeleteButton);
                deleteFilesCheck.addEventListener('change', updateDeleteButton);
                updateDeleteButton(); // Initial state
            }

            // Manage Backups button toggles the dedicated card
            const manageBtn = document.getElementById('manageBackupsBtn');
            if (manageBtn) {
                manageBtn.addEventListener('click', () => {
                    this.toggleBackupsCard();
                    // Always refresh list when opening
                    if (document.getElementById('backupsCard').style.display !== 'none') {
                        this.loadBackups();
                    }
                });
            }
        } catch (e) {
            console.warn('Failed to create backups UI:', e);
        }
    }

    toggleBackupsCard() {
        const card = document.getElementById('backupsCard');
        if (!card) return;
        const visible = card.style.display !== 'none';
        card.style.display = visible ? 'none' : 'block';
        if (!visible) {
            this.loadBackups();
        }
    }

    async loadBackups() {
        try {
            const res = await fetch('/api/backups');
            const data = await res.json();
            if (data.status !== 'success') {
                this.app.ui.showAlert('Failed to load backups', 'danger');
                return;
            }
            this.renderBackupsTable(data.backups || []);
            const sum = document.getElementById('backupsSummary');
            if (sum) sum.textContent = `${(data.backups || []).length} backups`;
        } catch (e) {
            console.error('Failed to load backups:', e);
            this.app.ui.showAlert('Failed to load backups', 'danger');
        }
    }

    renderBackupsTable(backups) {
        const tbody = document.getElementById('backupsTable');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (!backups || backups.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No backups found</td></tr>';
            return;
        }
        backups.forEach(b => {
            const tr = document.createElement('tr');
            const title = (b.folder_name || '') + (b.season_name ? ` - ${b.season_name}` : '') + (b.episode_name ? ` - ${b.episode_name}` : '');
            tr.innerHTML = `
                <td>${this.app.ui.escapeHtml(title || b.transfer_id || b.backup_id)}</td>
                <td><span class="badge bg-secondary">${this.app.ui.escapeHtml(b.media_type || '')}</span></td>
                <td>${b.file_count || 0}</td>
                <td>${this.app.ui.humanReadableBytes(b.total_size || 0)}</td>
                <td><span class="badge ${b.status === 'ready' ? 'bg-success' : (b.status === 'restored' ? 'bg-info' : 'bg-secondary')}">${b.status}</span></td>
                <td><small>${this.app.ui.escapeHtml(this.app.ui.timeAgo(b.created_at))}</small></td>
                <td>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-success" title="Restore all" data-action="restore" data-id="${b.backup_id}"><i class="bi bi-arrow-counterclockwise"></i></button>
                        <button class="btn btn-outline-info" title="View files" data-action="files" data-id="${b.backup_id}"><i class="bi bi-eye"></i></button>
                        <button class="btn btn-outline-danger" title="Delete" data-action="delete" data-id="${b.backup_id}"><i class="bi bi-trash"></i></button>
                    </div>
                </td>`;
            tbody.appendChild(tr);
        });
        // Delegate actions
        tbody.querySelectorAll('button[data-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = btn.getAttribute('data-action');
                const id = btn.getAttribute('data-id');
                if (action === 'restore') this.startRestoreAllFlow(id);
                if (action === 'files') this.showBackupFilesInline(id);
                if (action === 'delete') this.deleteBackupEnhanced(id);
            });
        });
    }

    applyGlobalBackgroundBlur(shouldBlur, modalEl) {
        try {
            // Blur everything except the active modal
            const bodyChildren = Array.from(document.body.children);
            bodyChildren.forEach(el => {
                if (el === modalEl || el.classList.contains('modal-backdrop')) return;
                el.style.transition = 'filter 150ms ease';
                el.style.filter = shouldBlur ? 'blur(3px) brightness(0.9)' : '';
            });
            // Also ensure the backdrop stays dark
            const bd = document.querySelector('.modal-backdrop');
            if (bd) {
                bd.style.backgroundColor = '';
            }
        } catch (e) {
            // no-op
        }
    }

    async showBackupFiles(backupId) {
        try {
            const res = await fetch(`/api/backups/${backupId}/files`);
            const data = await res.json();
            if (data.status !== 'success') {
                this.app.ui.showAlert('Failed to load backup files', 'danger');
                return;
            }
            // Store context for actions
            this.currentBackupContext = { backupId, files: data.files || [] };
            this.renderBackupFilesInline(data.files || []);
            const meta = document.getElementById('backupFilesMeta');
            if (meta) meta.textContent = `${(data.files || []).length} file(s)`;
            this.showBackupFilesStage();
        } catch (e) {
            console.error('Failed to load backup files:', e);
            this.app.ui.showAlert('Failed to load backup files', 'danger');
        }
    }

    renderBackupFilesInline(files) {
        const tbody = document.getElementById('backupFilesTable');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (!files || files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No files</td></tr>';
            return;
        }
        files.forEach(f => {
            const tr = document.createElement('tr');
            const dt = f.modified_time ? new Date(f.modified_time * 1000).toLocaleString() : '';
            tr.innerHTML = `
                <td><input type="checkbox" data-path="${this.app.ui.escapeHtml(f.relative_path)}"></td>
                <td><code>${this.app.ui.escapeHtml(f.context_display || '')}</code></td>
                <td><code>${this.app.ui.escapeHtml(f.relative_path)}</code></td>
                <td>${this.app.ui.humanReadableBytes(f.file_size || 0)}</td>
                <td><small>${this.app.ui.escapeHtml(dt)}</small></td>`;
            tbody.appendChild(tr);
        });
        tbody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', () => this.updateSelectedFilesCount());
        });
        this.updateSelectedFilesCount();
    }

    async restoreBackup(backupId, files = null) {
        try {
            console.log('Starting restore planning for backup:', backupId, 'files:', files);
            
            // Plan first
            const planPayload = files && files.length ? { files } : {};
            console.log('Sending plan request with payload:', planPayload);
            
            const planRes = await fetch(`/api/backups/${backupId}/plan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(planPayload)
            });
            const planData = await planRes.json();
            
            console.log('Plan response:', planData);
            
            if (planData.status !== 'success') {
                this.app.ui.showAlert(planData.message || 'Failed to plan restore', 'danger');
                return;
            }
            
            console.log('Rendering restore plan...');
            this.renderRestorePlan(planData.plan || {});
            
            // Move to confirmation stage instead of using inline confirmation
            console.log('Moving to confirmation stage...');
            this.showConfirmStage();
            
            // Store pending plan and payload for later application
            this.currentBackupContext.plan = planData.plan || {};
            this.currentBackupContext.payload = planPayload;
        } catch (e) {
            console.error('Restore failed:', e);
            this.app.ui.showAlert('Restore failed', 'danger');
        }
    }

    async confirmInline(message) {
        return new Promise((resolve) => {
            // Reuse the top-right alert style but anchored above plan
            const container = document.getElementById('restorePlanContainer');
            if (!container) {
                resolve(confirm(message));
                return;
            }
            // Clear existing confirmations
            const existing = container.querySelector('.inline-confirm');
            if (existing) existing.remove();
            const div = document.createElement('div');
            div.className = 'inline-confirm alert alert-warning d-flex justify-content-between align-items-center';
            div.innerHTML = `
                <div>${this.app.ui.escapeHtml(message)}</div>
                <div class="btn-group">
                    <button class="btn btn-sm btn-warning" data-action="yes"><i class="bi bi-check"></i> Apply</button>
                    <button class="btn btn-sm btn-outline-secondary" data-action="no"><i class="bi bi-x"></i> Cancel</button>
                </div>
            `;
            container.prepend(div);
            const onClick = (e) => {
                const act = e.target.closest('button')?.getAttribute('data-action');
                if (!act) return;
                e.preventDefault();
                div.remove();
                container.removeEventListener('click', onClick);
                resolve(act === 'yes');
            };
            container.addEventListener('click', onClick);
        });
    }

    // Card actions
    restoreSelectedFiles() {
        const ctx = this.currentBackupContext || {};
        const rows = document.querySelectorAll('#backupFilesTable input[type="checkbox"]:checked');
        const files = Array.from(rows).map(cb => cb.getAttribute('data-path'));
        if (!files.length) {
            this.app.ui.showAlert('No files selected', 'warning');
            return;
        }
        this.restoreBackup(ctx.backupId, files);
    }

    restoreAllFiles() {
        const ctx = this.currentBackupContext || {};
        this.restoreBackup(ctx.backupId, null);
    }

    // Aliases for updated handlers used in backupsTable
    async showBackupFilesInline(backupId) {
        return this.showBackupFiles(backupId);
    }

    async deleteBackupEnhanced(backupId) {
        console.log('Starting delete flow for backup:', backupId);
        
        // Store the backup context
        this.currentBackupContext = this.currentBackupContext || {};
        this.currentBackupContext.backupId = backupId;
        
        // Load backup files to show what will be deleted
        await this.loadDeleteFiles(backupId);
        
        // Show delete stage
        this.showDeleteStage();
    }

    async loadDeleteFiles(backupId) {
        try {
            console.log('Loading files for delete preview:', backupId);
            
            // Load both files and backup info
            const [filesRes, backupRes] = await Promise.all([
                fetch(`/api/backups/${backupId}/files`),
                fetch(`/api/backups/${backupId}`)
            ]);
            
            const filesData = await filesRes.json();
            const backupData = await backupRes.json();
            
            if (filesData.status === 'success') {
                this.currentBackupContext.deleteFiles = filesData.files || [];
            } else {
                console.error('Failed to load backup files:', filesData.message);
                this.currentBackupContext.deleteFiles = [];
            }
            
            if (backupData.status === 'success') {
                this.currentBackupContext.backupInfo = backupData.backup || {};
            } else {
                console.error('Failed to load backup info:', backupData.message);
                this.currentBackupContext.backupInfo = {};
            }
            
            this.renderDeleteFilesPreview(this.currentBackupContext.deleteFiles);
            
        } catch (e) {
            console.error('Error loading delete files:', e);
            this.currentBackupContext.deleteFiles = [];
            this.currentBackupContext.backupInfo = {};
            this.renderDeleteFilesPreview([]);
        }
    }

    renderDeleteFilesPreview(files) {
        const tbody = document.getElementById('deleteFilesTable');
        if (!tbody) return;
        
        tbody.innerHTML = '';
        
        if (files.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="2" class="text-center text-muted">
                        <i class="bi bi-info-circle"></i> No files found in backup
                    </td>
                </tr>
            `;
            return;
        }
        
        // Get backup directory path from context for display
        const ctx = this.currentBackupContext || {};
        const backupInfo = ctx.backupInfo || {};
        const backupDir = backupInfo.backup_dir || 'Unknown backup location';
        
        files.forEach(file => {
            const tr = document.createElement('tr');
            // Show backup path (backup_dir + relative_path), not original destination path
            const backupFilePath = file.relative_path ? `${backupDir}/${file.relative_path}` : 'Unknown path';
            
            tr.innerHTML = `
                <td>
                    <div><strong>Backup file:</strong> <code>${this.app.ui.escapeHtml(file.relative_path || 'Unknown')}</code></div>
                    <div class="text-muted small"><i class="bi bi-folder"></i> ${this.app.ui.escapeHtml(backupFilePath)}</div>
                </td>
                <td class="text-center">
                    ${file.file_size ? this.app.ui.humanReadableBytes(file.file_size) : 'Unknown'}
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    async executeDelete() {
        try {
            const deleteRecordCheck = document.getElementById('deleteRecordCheck');
            const deleteFilesCheck = document.getElementById('deleteFilesCheck');
            
            if (!deleteRecordCheck || !deleteFilesCheck) {
                this.app.ui.showAlert('Delete options not found', 'danger');
                return;
            }
            
            const deleteRecord = deleteRecordCheck.checked;
            const deleteFiles = deleteFilesCheck.checked;
            
            if (!deleteRecord && !deleteFiles) {
                this.app.ui.showAlert('Please select at least one delete option', 'warning');
                return;
            }
            
            const ctx = this.currentBackupContext || {};
            const backupId = ctx.backupId;
            
            if (!backupId) {
                this.app.ui.showAlert('No backup selected for deletion', 'danger');
                return;
            }
            
            console.log('Executing delete:', { backupId, deleteRecord, deleteFiles });
            
            // Show loading state
            const confirmBtn = document.getElementById('confirmDeleteBtn');
            if (confirmBtn) {
                confirmBtn.disabled = true;
                confirmBtn.innerHTML = '<i class="bi bi-spinner-border spinner-border-sm"></i> Deleting...';
            }
            
            const res = await fetch(`/api/backups/${backupId}/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delete_record: deleteRecord, delete_files: deleteFiles })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                this.app.ui.showAlert(data.message || 'Delete completed successfully', 'success');
                this.loadBackups(); // Refresh the list
                this.showBackupsListStage(); // Return to main view
            } else {
                this.app.ui.showAlert(data.message || 'Delete failed', 'danger');
            }
            
        } catch (e) {
            console.error('Delete execution failed:', e);
            this.app.ui.showAlert('Delete failed', 'danger');
        } finally {
            // Reset button state
            const confirmBtn = document.getElementById('confirmDeleteBtn');
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = '<i class="bi bi-trash"></i> Delete Selected';
            }
        }
    }

    async importBackupsFromDisk() {
        try {
            const btn = document.getElementById('importBackupsBtn');
            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Importing...';
            const res = await fetch('/api/backups/reindex', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                this.app.ui.showAlert(data.message || 'Import completed', 'success');
                await this.loadBackups();
            } else {
                this.app.ui.showAlert(data.message || 'Import failed', 'danger');
            }
            btn.innerHTML = original;
            btn.disabled = false;
        } catch (e) {
            console.error('Import backups failed:', e);
            this.app.ui.showAlert('Import failed', 'danger');
            const btn = document.getElementById('importBackupsBtn');
            if (btn) {
                btn.innerHTML = '<i class="bi bi-download"></i> Import from Disk';
                btn.disabled = false;
            }
        }
    }

    restoreSelectedFilesFromModal() {
        const ctx = this.currentBackupContext || {};
        const rows = document.querySelectorAll('#backupFilesTable input[type="checkbox"]:checked');
        const files = Array.from(rows).map(cb => cb.getAttribute('data-path'));
        if (!files.length) {
            this.app.ui.showAlert('No files selected', 'warning');
            return;
        }
        this.restoreBackup(ctx.backupId, files);
    }

    restoreAllFromModal() {
        const ctx = this.currentBackupContext || {};
        this.restoreBackup(ctx.backupId, null);
    }

    // New helpers for backups card
    renderRestorePlan(plan) {
        try {
            const ops = (plan && plan.operations) || [];
            const container = document.getElementById('restorePlanContainer');
            const tbody = document.getElementById('restorePlanTable');
            if (!container || !tbody) {
                console.warn('Missing restorePlanContainer or restorePlanTable elements');
                return;
            }
            
            tbody.innerHTML = '';
            
            if (ops.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="2" class="text-center text-muted">
                            <i class="bi bi-info-circle"></i> No files to restore or no context matches found
                        </td>
                    </tr>
                `;
                container.style.display = 'block';
                return;
            }
            
            console.log('Rendering restore plan with operations:', ops);
            
            ops.forEach(op => {
                const tr = document.createElement('tr');
                
                // Build context display
                let contextHtml = '';
                if (op.context_display && op.context_display !== op.backup_relative) {
                    contextHtml = `<div class="text-info small"><i class="bi bi-tag"></i> ${this.app.ui.escapeHtml(op.context_display)}</div>`;
                } else {
                    contextHtml = `<div class="text-muted small"><i class="bi bi-file-earmark"></i> No context detected</div>`;
                }
                
                // Build target action display
                let actionHtml = '';
                if (op.target_delete && op.target_delete !== op.copy_to) {
                    actionHtml = `
                        <div class="text-warning small">
                            <i class="bi bi-arrow-repeat"></i> Replace: <code>${this.app.ui.escapeHtml(op.target_delete)}</code>
                        </div>
                        <div class="text-success small">
                            <i class="bi bi-plus-circle"></i> Copy to: <code>${this.app.ui.escapeHtml(op.copy_to)}</code>
                        </div>
                    `;
                } else {
                    actionHtml = `
                        <div class="text-success small">
                            <i class="bi bi-plus-circle"></i> New file: <code>${this.app.ui.escapeHtml(op.copy_to)}</code>
                        </div>
                    `;
                }
                
                tr.innerHTML = `
                    <td>
                        <div><strong><code>${this.app.ui.escapeHtml(op.backup_relative)}</code></strong></div>
                        ${contextHtml}
                    </td>
                    <td>
                        ${actionHtml}
                    </td>
                `;
                tbody.appendChild(tr);
            });
            
            container.style.display = 'block';
        } catch (e) {
            console.error('Error rendering restore plan:', e);
        }
    }

    updateSelectedFilesCount() {
        const countBadge = document.getElementById('selectedFilesCount');
        if (!countBadge) return;
        const count = document.querySelectorAll('#backupFilesTable input[type="checkbox"]:checked').length;
        if (count > 0) {
            countBadge.style.display = 'inline-block';
            countBadge.textContent = `${count} selected`;
        } else {
            countBadge.style.display = 'none';
        }
    }

    async applyPlannedRestore() {
        try {
            const ctx = this.currentBackupContext || {};
            const res = await fetch(`/api/backups/${ctx.backupId}/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ctx.payload || {})
            });
            const data = await res.json();
            if (data.status === 'success') {
                this.app.ui.showAlert('Restore completed successfully', 'success');
                this.loadBackups();
                this.showBackupsListStage();
            } else {
                this.app.ui.showAlert(data.message || 'Restore failed', 'danger');
            }
        } catch (e) {
            console.error('Apply restore failed:', e);
            this.app.ui.showAlert('Apply restore failed', 'danger');
        }
    }

    async startRestoreAllFlow(backupId) {
        await this.showBackupFilesInline(backupId);
        this.restoreAllFiles();
    }

    async startRestoreAllFromFiles() {
        const ctx = this.currentBackupContext || {};
        await this.restoreBackup(ctx.backupId, null);
    }

    showBackupsListStage() {
        const list = document.getElementById('backupsListSection');
        const files = document.getElementById('backupFilesSection');
        const confirm = document.getElementById('backupConfirmSection');
        const deleteSection = document.getElementById('backupDeleteSection');
        if (list) list.style.display = 'block';
        if (files) files.style.display = 'none';
        if (confirm) confirm.style.display = 'none';
        if (deleteSection) deleteSection.style.display = 'none';
        this.updateBackupsBreadcrumb([]);
    }

    showBackupFilesStage() {
        const list = document.getElementById('backupsListSection');
        const files = document.getElementById('backupFilesSection');
        const confirm = document.getElementById('backupConfirmSection');
        const deleteSection = document.getElementById('backupDeleteSection');
        if (list) list.style.display = 'none';
        if (files) files.style.display = 'block';
        if (confirm) confirm.style.display = 'none';
        if (deleteSection) deleteSection.style.display = 'none';
        this.updateBackupsBreadcrumb(['Backups', 'Files']);
    }

    showConfirmStage() {
        const list = document.getElementById('backupsListSection');
        const files = document.getElementById('backupFilesSection');
        const confirm = document.getElementById('backupConfirmSection');
        const deleteSection = document.getElementById('backupDeleteSection');
        if (list) list.style.display = 'none';
        if (files) files.style.display = 'none';
        if (deleteSection) deleteSection.style.display = 'none';
        if (confirm) confirm.style.display = 'block';
        this.updateBackupsBreadcrumb(['Backups', 'Files', 'Confirmation']);
    }

    showDeleteStage() {
        const list = document.getElementById('backupsListSection');
        const files = document.getElementById('backupFilesSection');
        const confirm = document.getElementById('backupConfirmSection');
        const deleteSection = document.getElementById('backupDeleteSection');
        if (list) list.style.display = 'none';
        if (files) files.style.display = 'none';
        if (confirm) confirm.style.display = 'none';
        if (deleteSection) deleteSection.style.display = 'block';
        this.updateBackupsBreadcrumb(['Backups', 'Delete Backup']);
    }

    updateBackupsBreadcrumb(parts) {
        const bc = document.getElementById('backupsBreadcrumb');
        const ol = document.getElementById('backupsBreadcrumbItems');
        if (!bc || !ol) return;
        ol.innerHTML = '';
        if (!parts || parts.length === 0) {
            bc.style.display = 'none';
            return;
        }
        bc.style.display = 'block';
        parts.forEach((name, i) => {
            const li = document.createElement('li');
            const isLast = i === parts.length - 1;
            li.className = `breadcrumb-item ${isLast ? 'active' : ''}`;
            if (isLast) {
                li.textContent = name;
            } else {
                const a = document.createElement('a');
                a.href = '#';
                a.textContent = name;
                a.onclick = (e) => {
                    e.preventDefault();
                    if (i === 0) this.showBackupsListStage();
                    if (i === 1) this.showBackupFilesStage();
                };
                li.appendChild(a);
            }
            ol.appendChild(li);
        });
    }
}
