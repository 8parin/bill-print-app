// Frontend logic for Bill Print webapp

// Tab switching
const tabBtns = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        if (btn.disabled) return;

        // Remove active from all
        tabBtns.forEach(b => b.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));

        // Add active to clicked
        btn.classList.add('active');
        const tabId = btn.getAttribute('data-tab');
        document.getElementById(tabId).classList.add('active');
    });
});

// Function to switch to a specific tab
function switchToTab(tabName) {
    const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (btn && !btn.disabled) {
        btn.click();
    }
}

// Elements
const csvFileInput = document.getElementById('csvFile');
const uploadArea = document.getElementById('uploadArea');
const uploadStatus = document.getElementById('uploadStatus');
const mappingTab = document.getElementById('mappingTab');
const printingTab = document.getElementById('printingTab');
const salesReportTab = document.getElementById('salesReportTab');
const sortCsvTab = document.getElementById('sortCsvTab');
const mappingGrid = document.getElementById('mappingGrid');
const saveMappingBtn = document.getElementById('saveMappingBtn');
const mappingStatus = document.getElementById('mappingStatus');
const previewBtn = document.getElementById('previewBtn');
const generateBtn = document.getElementById('generateBtn');
const downloadBtn = document.getElementById('downloadBtn');
const invoiceCount = document.getElementById('invoiceCount');
const progress = document.getElementById('progress');
const progressFill = document.getElementById('progressFill');
const generateStatus = document.getElementById('generateStatus');
const previewModal = document.getElementById('previewModal');
const previewFrame = document.getElementById('previewFrame');
const closeModal = document.querySelector('#previewModal .close');
const paperSizeSelect = document.getElementById('paperSize');
const orientationSelect = document.getElementById('orientation');
const startingBillNumberInput = document.getElementById('startingBillNumber');

let detectedColumns = [];
let fieldDefinitions = {};
let currentMapping = {};

// ── Company Profiles ──
const saveCompanyBtn = document.getElementById('saveCompanyBtn');
const companyStatus = document.getElementById('companyStatus');
const profileSelect = document.getElementById('companyProfileSelect');
const profileNameRow = document.getElementById('profileNameRow');
const profileNameInput = document.getElementById('profileNameInput');
const deleteProfileBtn = document.getElementById('deleteProfileBtn');

async function loadProfiles(selectProfileName) {
    try {
        const res = await fetch('/api/company-profiles');
        const data = await res.json();
        profileSelect.innerHTML = '';

        data.profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.profile_name;
            opt.textContent = p.profile_name;
            profileSelect.appendChild(opt);
        });

        // "Add New" option
        const addOpt = document.createElement('option');
        addOpt.value = '__new__';
        addOpt.textContent = '＋ Add New...';
        profileSelect.appendChild(addOpt);

        // Select the requested profile, or first available
        if (selectProfileName && [...profileSelect.options].some(o => o.value === selectProfileName)) {
            profileSelect.value = selectProfileName;
        } else if (data.profiles.length > 0) {
            profileSelect.value = data.profiles[0].profile_name;
        }

        handleProfileChange();
    } catch (err) {
        console.error('Failed to load profiles:', err);
    }
}

async function handleProfileChange() {
    const val = profileSelect.value;

    if (val === '__new__') {
        // Show profile name input, clear fields
        profileNameRow.style.display = '';
        profileNameInput.value = '';
        document.getElementById('companyName').value = '';
        document.getElementById('companyTaxId').value = '';
        document.getElementById('companyAddress').value = '';
        document.getElementById('companyPhone').value = '';
        deleteProfileBtn.style.display = 'none';
        return;
    }

    profileNameRow.style.display = 'none';
    deleteProfileBtn.style.display = '';

    try {
        const res = await fetch(`/api/company-profiles/select/${encodeURIComponent(val)}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            document.getElementById('companyName').value = data.name || '';
            document.getElementById('companyTaxId').value = data.tax_id || '';
            document.getElementById('companyAddress').value = data.address || '';
            document.getElementById('companyPhone').value = data.phone || '';
        }
    } catch (err) {
        console.error('Failed to load profile:', err);
    }
}

profileSelect.addEventListener('change', handleProfileChange);

// Save profile
saveCompanyBtn.addEventListener('click', async () => {
    saveCompanyBtn.disabled = true;
    companyStatus.innerHTML = '⏳ Saving...';
    companyStatus.className = 'status-message info';

    const isNew = profileSelect.value === '__new__';
    const profileName = isNew ? profileNameInput.value.trim() : profileSelect.value;

    if (!profileName || profileName === '__new__') {
        companyStatus.innerHTML = '❌ Please enter a profile name.';
        companyStatus.className = 'status-message error';
        saveCompanyBtn.disabled = false;
        return;
    }

    try {
        const response = await fetch('/save-company', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_name: profileName,
                name: document.getElementById('companyName').value,
                tax_id: document.getElementById('companyTaxId').value,
                address: document.getElementById('companyAddress').value,
                phone: document.getElementById('companyPhone').value
            })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Save failed');

        companyStatus.innerHTML = `✅ ${data.message}`;
        companyStatus.className = 'status-message success';

        // Refresh dropdown and select the saved profile
        await loadProfiles(profileName);
    } catch (error) {
        companyStatus.innerHTML = `❌ Error: ${error.message}`;
        companyStatus.className = 'status-message error';
    }
    saveCompanyBtn.disabled = false;
});

// Delete profile
deleteProfileBtn.addEventListener('click', async () => {
    const profileName = profileSelect.value;
    if (!profileName || profileName === '__new__') return;

    if (!confirm(`Delete profile "${profileName}"?`)) return;

    try {
        const res = await fetch(`/api/company-profiles/${encodeURIComponent(profileName)}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Delete failed');

        companyStatus.innerHTML = '✅ Profile deleted.';
        companyStatus.className = 'status-message success';
        await loadProfiles();
    } catch (error) {
        companyStatus.innerHTML = `❌ Error: ${error.message}`;
        companyStatus.className = 'status-message error';
    }
});

// Load profiles on page load
loadProfiles();

// Upload area click
uploadArea.addEventListener('click', () => {
    csvFileInput.click();
});

// Drag and drop
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('drag-over');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('drag-over');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('drag-over');

    if (e.dataTransfer.files.length > 0) {
        csvFileInput.files = e.dataTransfer.files;
        handleFileUpload();
    }
});

// File input change
csvFileInput.addEventListener('change', handleFileUpload);

// Show notification modal
function showNotification(type, title, message, details = null) {
    const modal = document.getElementById('notificationModal');
    const modalContent = modal.querySelector('.notification-content');
    const icon = document.getElementById('notificationIcon');
    const titleEl = document.getElementById('notificationTitle');
    const messageEl = document.getElementById('notificationMessage');
    const detailsEl = document.getElementById('notificationDetails');

    // Update content
    titleEl.textContent = title;
    messageEl.innerHTML = message;

    // Set icon and type
    if (type === 'error') {
        icon.textContent = '🚨';
        modalContent.className = 'modal-content notification-content notification-error';
    } else if (type === 'warning') {
        icon.textContent = '⚠️';
        modalContent.className = 'modal-content notification-content notification-warning';
    } else if (type === 'success') {
        icon.textContent = '✅';
        modalContent.className = 'modal-content notification-content notification-success';
    }

    // Show details if provided
    if (details && details.length > 0) {
        detailsEl.innerHTML = '<ul>' + details.map(d => `<li>${d}</li>`).join('') + '</ul>';
        detailsEl.style.display = 'block';
    } else {
        detailsEl.style.display = 'none';
    }

    // Show modal
    modal.style.display = 'block';
}

// Upload handler
async function handleFileUpload() {
    const file = csvFileInput.files[0];

    if (!file) return;

    if (!file.name.endsWith('.csv')) {
        showError('Please select a CSV file');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    // Include selected platform
    const platformSelect = document.getElementById('platformSelect');
    if (platformSelect) {
        formData.append('platform', platformSelect.value);
    }

    uploadStatus.innerHTML = '⏳ Uploading and detecting columns...';
    uploadStatus.className = 'status-message info';

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Upload failed');
        }

        // Check if format validation failed
        if (data.validation && !data.format_valid) {
            // Show detailed notification about format changes
            const errors = data.validation.errors || [];
            const warnings = data.validation.warnings || [];
            const missingCols = data.validation.missing_columns || [];

            let detailsList = [];

            // Add main errors
            if (errors.length > 0) {
                detailsList.push('<strong>❌ Errors:</strong>');
                detailsList.push(...errors);
            }

            // Add missing column details
            if (missingCols.length > 0) {
                detailsList.push('<br><strong>📋 Missing Required Columns:</strong>');
                missingCols.forEach(col => {
                    detailsList.push(`• ${col.field}: Expected column "${col.expected_name}"`);
                });
            }

            // Add warnings
            if (warnings.length > 0) {
                detailsList.push('<br><strong>⚠️ Warnings:</strong>');
                detailsList.push(...warnings);
            }

            // Add instructions
            detailsList.push('<br><strong>💡 What to do:</strong>');
            detailsList.push('• Click "OK" to continue to Step 2');
            detailsList.push('• In Step 2, remap the columns to match your CSV format');
            detailsList.push('• Make sure all required fields are mapped correctly');

            showNotification(
                'error',
                '⚠️ CSV Format Changed',
                'The uploaded CSV format does not match the expected format.<br>The platform may have updated their export format, or the wrong platform was selected.',
                detailsList
            );

            // Show warning in status
            uploadStatus.innerHTML = `⚠️ ${data.message}`;
            uploadStatus.className = 'status-message error';
        } else if (data.first_column_error) {
            // First column name is wrong - likely corrupted CSV
            showNotification(
                'error',
                '⚠️ CSV File May Be Corrupted',
                data.first_column_error,
                ['Please re-export the CSV from the platform and try again.']
            );
            uploadStatus.innerHTML = `⚠️ ${data.message}`;
            uploadStatus.className = 'status-message error';
        } else {
            // Show success
            uploadStatus.innerHTML = `✅ ${data.message}`;
            uploadStatus.className = 'status-message success';
        }

        // Show platform mismatch warning if applicable
        if (data.platform_mismatch) {
            const badge = document.getElementById('platformDetected');
            if (badge) {
                badge.textContent = data.platform_mismatch;
                badge.style.display = 'inline';
                badge.style.color = '#e67e00';
                badge.style.fontSize = '0.85em';
            }
        }

        // Store detected columns
        detectedColumns = data.columns;

        // Load field definitions and show mapping section
        await loadFieldDefinitions();
        buildMappingUI();

        // Enable mapping tab and switch to it
        mappingTab.disabled = false;
        switchToTab('mapping');

    } catch (error) {
        showError(error.message);
    }
}

// Load field definitions
async function loadFieldDefinitions() {
    try {
        const response = await fetch('/get-field-definitions');
        const data = await response.json();

        fieldDefinitions = data.fields;
        currentMapping = data.current_mapping;

    } catch (error) {
        console.error('Failed to load field definitions:', error);
    }
}

// Build mapping UI
function buildMappingUI() {
    mappingGrid.innerHTML = '';

    // Create mapping row for each field
    Object.keys(fieldDefinitions).forEach(fieldKey => {
        const fieldLabel = fieldDefinitions[fieldKey];
        const currentValue = currentMapping[fieldKey] || '';

        const row = document.createElement('div');
        row.className = 'mapping-row';

        const label = document.createElement('label');
        label.className = 'mapping-label';
        label.textContent = fieldLabel;

        const select = document.createElement('select');
        select.className = 'mapping-select';
        select.dataset.field = fieldKey;

        // Add empty option
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '-- Select Column --';
        select.appendChild(emptyOption);

        // Add detected columns as options
        detectedColumns.forEach(col => {
            const option = document.createElement('option');
            option.value = col;
            option.textContent = col;

            // Pre-select if matches current mapping
            if (col === currentValue) {
                option.selected = true;
            }

            select.appendChild(option);
        });

        row.appendChild(label);
        row.appendChild(select);
        mappingGrid.appendChild(row);
    });
}

// Save mapping button
saveMappingBtn.addEventListener('click', async () => {
    saveMappingBtn.disabled = true;
    mappingStatus.innerHTML = '⏳ Saving mapping and parsing CSV...';
    mappingStatus.className = 'status-message info';

    try {
        // Collect mapping from UI
        const mapping = {};
        document.querySelectorAll('.mapping-select').forEach(select => {
            const field = select.dataset.field;
            const value = select.value;
            if (value) {
                mapping[field] = value;
            }
        });

        // Save mapping
        const response = await fetch('/save-mapping', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ mapping })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Mapping save failed. ' + (data.details ? data.details.join(', ') : ''));
        }

        // Check if return items need review
        if (data.needs_return_review && data.return_items && data.return_items.length > 0) {
            mappingStatus.innerHTML = `⚠️ ${data.message}`;
            mappingStatus.className = 'status-message warning';
            showReturnReviewModal(data.return_items);
            saveMappingBtn.disabled = false;
            return;
        }

        // Show success
        mappingStatus.innerHTML = `✅ ${data.message}`;
        mappingStatus.className = 'status-message success';

        // Update invoice count
        if (data.invoice_count) {
            invoiceCount.innerHTML = `📊 Found <strong>${data.invoice_count}</strong> invoices`;
        }

        // Enable printing tab and switch to it
        printingTab.disabled = false;
        salesReportTab.disabled = false;
        sortCsvTab.disabled = false;
        switchToTab('printing');

        saveMappingBtn.disabled = false;

    } catch (error) {
        mappingStatus.innerHTML = `❌ Error: ${error.message}`;
        mappingStatus.className = 'status-message error';
        saveMappingBtn.disabled = false;
    }
});

// Preview button
previewBtn.addEventListener('click', async () => {
    try {
        const billNum = startingBillNumberInput.value || 2600001;
        const response = await fetch(`/preview?starting_bill_number=${billNum}`);

        if (!response.ok) {
            throw new Error('Preview failed');
        }

        const html = await response.text();

        // Show modal with preview
        previewFrame.srcdoc = html;
        previewModal.style.display = 'block';

    } catch (error) {
        showError(error.message);
    }
});

// Generate button
generateBtn.addEventListener('click', async () => {
    generateBtn.disabled = true;
    generateStatus.innerHTML = '⏳ Generating ALL PDFs (this may take 1-2 minutes)...';
    generateStatus.className = 'status-message info';
    progress.style.display = 'block';

    try {
        const response = await fetch('/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                paper_size: paperSizeSelect.value,
                orientation: orientationSelect.value,
                starting_bill_number: startingBillNumberInput.value.trim() || '2600001'
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Generation failed');
        }

        // Show success
        progressFill.style.width = '100%';
        generateStatus.innerHTML = `✅ ${data.message}`;
        generateStatus.className = 'status-message success';

        // Show download section - set mode to 'batch' for download-all
        document.getElementById('downloadSection').style.display = 'block';
        downloadBtn.dataset.mode = 'batch';
        downloadBtn.innerHTML = '📥 Download All Bills (PDF)';

        generateBtn.disabled = false;

    } catch (error) {
        showError(error.message);
        generateBtn.disabled = false;
    }
});

// Generate One button
const generateOneBtn = document.getElementById('generateOneBtn');
generateOneBtn.addEventListener('click', async () => {
    generateOneBtn.disabled = true;
    generateStatus.innerHTML = '⏳ Generating first bill PDF...';
    generateStatus.className = 'status-message info';

    try {
        const response = await fetch('/generate-one', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                paper_size: paperSizeSelect.value,
                orientation: orientationSelect.value,
                starting_bill_number: startingBillNumberInput.value.trim() || '2600001'
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Generation failed');
        }

        // Show success
        generateStatus.innerHTML = `✅ ${data.message}`;
        generateStatus.className = 'status-message success';

        // Show download section for single file
        document.getElementById('downloadSection').style.display = 'block';
        downloadBtn.dataset.mode = 'single';
        downloadBtn.dataset.filename = data.filename;
        downloadBtn.innerHTML = '📥 Download Bill PDF';

        generateOneBtn.disabled = false;

    } catch (error) {
        generateStatus.innerHTML = `❌ Error: ${error.message}`;
        generateStatus.className = 'status-message error';
        generateOneBtn.disabled = false;
    }
});

// Preview by Order Number button
const previewByOrderBtn = document.getElementById('previewByOrderBtn');

previewByOrderBtn.addEventListener('click', async () => {
    const orderNumber = orderNumberInput.value.trim();

    if (!orderNumber) {
        generateStatus.innerHTML = '❌ Please enter an order number';
        generateStatus.className = 'status-message error';
        return;
    }

    previewByOrderBtn.disabled = true;

    try {
        const response = await fetch('/preview-by-order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                order_number: orderNumber,
                starting_bill_number: startingBillNumberInput.value.trim() || '2600001'
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Preview failed');
        }

        // Show modal with preview
        previewFrame.srcdoc = data.html;
        previewModal.style.display = 'block';

        previewByOrderBtn.disabled = false;

    } catch (error) {
        generateStatus.innerHTML = `❌ Error: ${error.message}`;
        generateStatus.className = 'status-message error';
        previewByOrderBtn.disabled = false;
    }
});

// Generate by Order Number button
const generateByOrderBtn = document.getElementById('generateByOrderBtn');
const orderNumberInput = document.getElementById('orderNumberInput');

generateByOrderBtn.addEventListener('click', async () => {
    const orderNumber = orderNumberInput.value.trim();

    if (!orderNumber) {
        generateStatus.innerHTML = '❌ Please enter an order number';
        generateStatus.className = 'status-message error';
        return;
    }

    generateByOrderBtn.disabled = true;
    generateStatus.innerHTML = `⏳ Generating bill for order ${orderNumber}...`;
    generateStatus.className = 'status-message info';

    try {
        const response = await fetch('/generate-by-order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                order_number: orderNumber,
                paper_size: paperSizeSelect.value,
                orientation: orientationSelect.value,
                starting_bill_number: startingBillNumberInput.value.trim() || '2600001'
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Generation failed');
        }

        // Show success
        generateStatus.innerHTML = `✅ ${data.message}`;
        generateStatus.className = 'status-message success';

        // Show download section for single file
        document.getElementById('downloadSection').style.display = 'block';
        downloadBtn.dataset.mode = 'single';
        downloadBtn.dataset.filename = data.filename;
        downloadBtn.innerHTML = '📥 Download Bill PDF';

        generateByOrderBtn.disabled = false;

    } catch (error) {
        generateStatus.innerHTML = `❌ Error: ${error.message}`;
        generateStatus.className = 'status-message error';
        generateByOrderBtn.disabled = false;
    }
});

// Allow Enter key in order number input
orderNumberInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        generateByOrderBtn.click();
    }
});

// Download button
downloadBtn.addEventListener('click', () => {
    const cacheBust = '?t=' + Date.now();
    if (downloadBtn.dataset.mode === 'single') {
        window.location.href = `/download/${downloadBtn.dataset.filename}${cacheBust}`;
    } else {
        window.location.href = '/download-all' + cacheBust;
    }
});

// Modal close
closeModal.addEventListener('click', () => {
    previewModal.style.display = 'none';
});

window.addEventListener('click', (e) => {
    if (e.target === previewModal) {
        previewModal.style.display = 'none';
    }
});

// Notification modal close
const notificationModal = document.getElementById('notificationModal');
const notificationClose = document.querySelector('.notification-close');
const notificationBtn = document.getElementById('notificationBtn');

notificationClose.addEventListener('click', () => {
    notificationModal.style.display = 'none';
});

notificationBtn.addEventListener('click', () => {
    notificationModal.style.display = 'none';
});

window.addEventListener('click', (e) => {
    if (e.target === notificationModal) {
        notificationModal.style.display = 'none';
    }
});

// ========== Return Review Modal ==========

let currentReturnItems = [];

function showReturnReviewModal(returnItems) {
    currentReturnItems = returnItems;
    const modal = document.getElementById('returnReviewModal');
    const list = document.getElementById('returnItemsList');

    // Group by order_id for display
    const byOrder = {};
    returnItems.forEach(item => {
        if (!byOrder[item.order_id]) byOrder[item.order_id] = [];
        byOrder[item.order_id].push(item);
    });

    let html = '';
    for (const [orderId, items] of Object.entries(byOrder)) {
        html += `<div style="border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin-bottom: 12px;">`;
        html += `<strong>Order: ${orderId}</strong>`;

        items.forEach((item, i) => {
            const isConfirmed = item.category === 'confirmed';
            const statusColor = isConfirmed ? '#dc3545' : '#fd7e14';
            const statusLabel = isConfirmed ? 'Confirmed Return' : 'Unknown Status';

            html += `<div style="margin: 8px 0; padding: 8px; background: #f8f9fa; border-radius: 4px;">`;
            html += `<div style="display: flex; justify-content: space-between; align-items: start;">`;
            html += `<div>`;
            html += `<div>${item.product}</div>`;
            if (item.variant) html += `<small style="color: #666;">${item.variant}</small><br>`;
            html += `<span style="color: ${statusColor}; font-size: 0.85em; font-weight: bold;">${statusLabel}: ${item.return_status}</span>`;
            html += `</div>`;
            html += `<div>`;

            if (isConfirmed) {
                // Confirmed returns use global policy — show label
                html += `<span class="return-action-label" data-row="${item.row_index}" data-category="confirmed" style="color: #666; font-size: 0.85em;">Uses default policy ↑</span>`;
            } else {
                // Unknown status — show per-item decision buttons
                html += `<select class="return-action-select" data-row="${item.row_index}" data-category="unknown" style="padding: 4px 8px; border-radius: 4px; border: 1px solid #ccc;">`;
                html += `<option value="keep">Proceed (keep)</option>`;
                html += `<option value="remove_product">Remove this product</option>`;
                html += `<option value="remove_bill">Cancel entire bill</option>`;
                html += `</select>`;
            }

            html += `</div></div></div>`;
        });

        html += `</div>`;
    }

    list.innerHTML = html;
    modal.style.display = 'block';
}

// Close return review modal
document.getElementById('returnReviewClose').addEventListener('click', () => {
    document.getElementById('returnReviewModal').style.display = 'none';
});

// Apply return decisions
document.getElementById('applyReturnDecisions').addEventListener('click', async () => {
    const applyBtn = document.getElementById('applyReturnDecisions');
    applyBtn.disabled = true;
    applyBtn.textContent = 'Applying...';

    try {
        // Get global policy for confirmed returns
        const policyRadio = document.querySelector('input[name="returnPolicy"]:checked');
        const confirmedPolicy = policyRadio ? policyRadio.value : 'remove_product';

        // Build decisions list
        const decisions = [];

        currentReturnItems.forEach(item => {
            if (item.category === 'confirmed') {
                decisions.push({
                    row_index: item.row_index,
                    action: confirmedPolicy
                });
            } else {
                // Get per-item decision from select
                const select = document.querySelector(`.return-action-select[data-row="${item.row_index}"]`);
                const action = select ? select.value : 'keep';
                decisions.push({
                    row_index: item.row_index,
                    action: action
                });
            }
        });

        const response = await fetch('/apply-return-decisions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ decisions })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to apply return decisions');
        }

        // Close modal
        document.getElementById('returnReviewModal').style.display = 'none';

        // Show success
        mappingStatus.innerHTML = `✅ ${data.message}`;
        mappingStatus.className = 'status-message success';

        // Update invoice count
        if (data.invoice_count) {
            invoiceCount.innerHTML = `📊 Found <strong>${data.invoice_count}</strong> invoices`;
        }

        // Enable printing tab and switch to it
        printingTab.disabled = false;
        salesReportTab.disabled = false;
        sortCsvTab.disabled = false;
        switchToTab('printing');

    } catch (error) {
        mappingStatus.innerHTML = `❌ Error: ${error.message}`;
        mappingStatus.className = 'status-message error';
    }

    applyBtn.disabled = false;
    applyBtn.textContent = 'Apply Decisions & Continue';
});

// ========== Sales Report ==========

const generateSalesReportBtn = document.getElementById('generateSalesReportBtn');
const exportSalesReportCsvBtn = document.getElementById('exportSalesReportCsvBtn');
const exportSalesReportXlsxBtn = document.getElementById('exportSalesReportXlsxBtn');
const salesReportStatus = document.getElementById('salesReportStatus');

generateSalesReportBtn.addEventListener('click', async () => {
    generateSalesReportBtn.disabled = true;
    salesReportStatus.innerHTML = '⏳ Generating sales report...';
    salesReportStatus.className = 'status-message info';

    try {
        const response = await fetch('/sales-report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                starting_bill_number: startingBillNumberInput.value.trim() || '2600001'
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'Failed to generate report');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'sales_report.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);

        salesReportStatus.innerHTML = '✅ Sales report downloaded!';
        salesReportStatus.className = 'status-message success';
    } catch (error) {
        salesReportStatus.innerHTML = `❌ Error: ${error.message}`;
        salesReportStatus.className = 'status-message error';
    }

    generateSalesReportBtn.disabled = false;
});

async function exportSalesReport(format) {
    const btn = format === 'xlsx' ? exportSalesReportXlsxBtn : exportSalesReportCsvBtn;
    btn.disabled = true;
    salesReportStatus.innerHTML = `⏳ Exporting as ${format.toUpperCase()}...`;
    salesReportStatus.className = 'status-message info';

    try {
        const response = await fetch('/sales-report-export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                format: format,
                starting_bill_number: startingBillNumberInput.value.trim() || '2600001'
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'Export failed');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `sales_report.${format}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);

        salesReportStatus.innerHTML = `✅ Exported as ${format.toUpperCase()}!`;
        salesReportStatus.className = 'status-message success';
    } catch (error) {
        salesReportStatus.innerHTML = `❌ Error: ${error.message}`;
        salesReportStatus.className = 'status-message error';
    }

    btn.disabled = false;
}

exportSalesReportCsvBtn.addEventListener('click', () => exportSalesReport('csv'));
exportSalesReportXlsxBtn.addEventListener('click', () => exportSalesReport('xlsx'));

// ========== Tab 5: Sort CSV ==========

document.getElementById('sortCsvBtn').addEventListener('click', async () => {
    const btn = document.getElementById('sortCsvBtn');
    const status = document.getElementById('sortCsvStatus');

    btn.disabled = true;
    status.innerHTML = '⏳ Sorting CSV...';
    status.className = 'status-message info';

    try {
        const response = await fetch('/sort-csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'Sort failed');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'sorted_bills.xlsx';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);

        status.innerHTML = '✅ sorted_bills.xlsx downloaded!';
        status.className = 'status-message success';
    } catch (error) {
        status.innerHTML = `❌ Error: ${error.message}`;
        status.className = 'status-message error';
    }

    btn.disabled = false;
});

// ========== Helper functions ==========

function showError(message) {
    uploadStatus.innerHTML = `❌ Error: ${message}`;
    uploadStatus.className = 'status-message error';
}
