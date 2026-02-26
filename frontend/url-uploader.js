/**
 * URL Upload Component for immich-drop
 * Handles downloading from TikTok, Instagram, Reddit, etc.
 */

class UrlUploader {
    constructor(containerSelector, options = {}) {
        this.container = document.querySelector(containerSelector);
        this.onUploadComplete = options.onUploadComplete || (() => {});
        this.onError = options.onError || console.error;
        this.apiBase = options.apiBase || '';

        this.init();
    }

    init() {
        this.render();
        this.attachEventListeners();
        this.loadSupportedPlatforms();
    }

    // NOTE: This render method uses innerHTML to build its own UI shell.
    // All dynamic user content (filenames, URLs, platform names) injected
    // later uses escapeHtml() or textContent -- see addResult() and
    // loadSupportedPlatforms(). This initial template contains only
    // static markup with no user-supplied data.
    render() {
        this.container.innerHTML =
            '<div class="url-uploader">'
          + '<div class="card-header"><h3>Upload from URL</h3></div>'
          + '<p class="text-sm text-secondary mb-3">Paste a link from TikTok, Instagram, Facebook, Reddit, YouTube, Twitter, or any direct image URL</p>'
          + '<div style="display:flex;flex-direction:column;gap:8px;">'
          + '<input type="text" id="url-input" placeholder="https://www.tiktok.com/@user/video/..." class="input" />'
          + '<button id="url-upload-btn" class="btn btn--primary btn--full" style="display:flex;align-items:center;justify-content:center;gap:6px;">'
          + '<span id="url-btn-text">Upload</span>'
          + '<svg id="url-spinner" class="hidden animate-spin" width="18" height="18" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">'
          + '<circle style="opacity:0.25;" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>'
          + '<path style="opacity:0.75;" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>'
          + '</svg></button></div>'
          + '<div id="url-status" class="hidden mt-2 text-sm"></div>'
          + '<div id="supported-platforms" class="platform-tags mt-3"><span class="text-xs text-tertiary">Loading platforms...</span></div>'
          + '<div class="hidden mt-4" id="batch-section">'
          + '<label class="form-label">Batch Upload</label>'
          + '<textarea id="batch-urls" rows="4" placeholder="Paste multiple URLs, one per line..." class="input" style="font-family:var(--font-mono);font-size:0.8125rem;"></textarea>'
          + '<button id="batch-upload-btn" class="btn btn--primary mt-2">Upload All</button>'
          + '</div>'
          + '<div id="url-results" class="mt-3 space-y-sm"></div>'
          + '</div>';
    }

    attachEventListeners() {
        const input = this.container.querySelector('#url-input');
        const uploadBtn = this.container.querySelector('#url-upload-btn');
        const batchTextarea = this.container.querySelector('#batch-urls');
        const batchBtn = this.container.querySelector('#batch-upload-btn');

        // Single URL upload
        uploadBtn.addEventListener('click', () => this.uploadUrl());
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.uploadUrl();
        });

        // Show batch section when multiple URLs detected
        input.addEventListener('input', (e) => {
            const value = e.target.value;
            const urls = value.split(/[\n\s]+/).filter(u => u.trim());
            const batchSection = this.container.querySelector('#batch-section');

            if (urls.length > 1) {
                batchSection.classList.remove('hidden');
                batchTextarea.value = urls.join('\n');
            }
        });

        // Batch upload
        batchBtn.addEventListener('click', () => this.uploadBatch());

        // Handle paste
        input.addEventListener('paste', (e) => {
            setTimeout(() => {
                const value = input.value;
                const urls = value.split(/[\n\s]+/).filter(u => u.trim());
                if (urls.length > 1) {
                    const batchSection = this.container.querySelector('#batch-section');
                    batchSection.classList.remove('hidden');
                    batchTextarea.value = urls.join('\n');
                }
            }, 0);
        });
    }

    async loadSupportedPlatforms() {
        try {
            const resp = await fetch(`${this.apiBase}/api/supported-platforms`);
            const data = await resp.json();
            const platformsDiv = this.container.querySelector('#supported-platforms');
            // Build platform tags using DOM methods (no innerHTML with user data)
            platformsDiv.textContent = '';
            const label = document.createElement('span');
            label.className = 'text-xs text-tertiary';
            label.textContent = 'Supported: ';
            platformsDiv.appendChild(label);
            data.platforms.forEach(function(p) {
                const tag = document.createElement('span');
                tag.className = 'platform-tag';
                tag.textContent = p;
                platformsDiv.appendChild(tag);
            });
        } catch (error) {
            console.warn('Could not load supported platforms:', error);
        }
    }

    setStatus(message, type = 'info') {
        const statusDiv = this.container.querySelector('#url-status');
        statusDiv.classList.remove('hidden');
        const colorMap = {
            error: 'var(--red-text)',
            success: 'var(--green-text)',
            info: 'var(--blue-text)',
            warning: 'var(--amber-text)',
        };
        statusDiv.style.color = colorMap[type] || colorMap.info;
        statusDiv.textContent = message;
    }

    setLoading(loading) {
        const btn = this.container.querySelector('#url-upload-btn');
        const btnText = this.container.querySelector('#url-btn-text');
        const spinner = this.container.querySelector('#url-spinner');
        const input = this.container.querySelector('#url-input');

        btn.disabled = loading;
        input.disabled = loading;

        if (loading) {
            btnText.textContent = 'Downloading...';
            spinner.classList.remove('hidden');
        } else {
            btnText.textContent = 'Upload';
            spinner.classList.add('hidden');
        }
    }

    async uploadUrl() {
        const input = this.container.querySelector('#url-input');
        const url = input.value.trim();

        if (!url) {
            this.setStatus('Please enter a URL', 'warning');
            return;
        }

        this.setLoading(true);
        this.setStatus('Downloading and uploading...', 'info');

        try {
            const resp = await fetch(`${this.apiBase}/api/upload/url`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            });

            const data = await resp.json();

            if (data.success) {
                this.setStatus(
                    data.result.duplicate
                        ? 'Already in library (duplicate)'
                        : 'Successfully uploaded!',
                    data.result.duplicate ? 'warning' : 'success'
                );
                this.addResult(data.result);
                input.value = '';
                this.onUploadComplete(data.result);
            } else {
                this.setStatus(data.error || 'Upload failed', 'error');
                this.onError(data.error);
            }
        } catch (error) {
            this.setStatus(`Error: ${error.message}`, 'error');
            this.onError(error);
        } finally {
            this.setLoading(false);
        }
    }

    async uploadBatch() {
        const textarea = this.container.querySelector('#batch-urls');
        const urls = textarea.value.split('\n').map(u => u.trim()).filter(u => u);

        if (urls.length === 0) {
            this.setStatus('Please enter some URLs', 'warning');
            return;
        }

        if (urls.length > 10) {
            this.setStatus('Maximum 10 URLs at a time', 'warning');
            return;
        }

        this.setLoading(true);
        this.setStatus(`Downloading ${urls.length} items...`, 'info');

        try {
            const resp = await fetch(`${this.apiBase}/api/upload/urls`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls }),
            });

            const data = await resp.json();

            this.setStatus(
                `Done: ${data.successful} uploaded, ${data.duplicates} duplicates, ${data.failed} failed`,
                data.failed > 0 ? 'warning' : 'success'
            );

            data.results.forEach(result => this.addResult(result));
            textarea.value = '';
            this.container.querySelector('#batch-section').classList.add('hidden');

        } catch (error) {
            this.setStatus(`Error: ${error.message}`, 'error');
            this.onError(error);
        } finally {
            this.setLoading(false);
        }
    }

    addResult(result) {
        const resultsDiv = this.container.querySelector('#url-results');
        const status = result.duplicate ? 'duplicate' : result.status;
        const badgeClass = status === 'duplicate' ? 'badge--amber' : status === 'success' ? 'badge--green' : 'badge--red';

        // Build result element using DOM methods to avoid innerHTML with user data
        const resultEl = document.createElement('div');
        resultEl.className = 'upload-item';
        resultEl.style.display = 'flex';
        resultEl.style.alignItems = 'center';
        resultEl.style.justifyContent = 'space-between';

        const left = document.createElement('div');
        left.style.minWidth = '0';
        const nameSpan = document.createElement('span');
        nameSpan.style.fontWeight = '500';
        nameSpan.textContent = result.filename;
        left.appendChild(nameSpan);
        if (result.platform) {
            const platSpan = document.createElement('span');
            platSpan.className = 'text-xs text-secondary';
            platSpan.style.marginLeft = '8px';
            platSpan.textContent = result.platform;
            left.appendChild(platSpan);
        }

        const badge = document.createElement('span');
        badge.className = 'badge ' + badgeClass;
        badge.textContent = result.duplicate ? 'Duplicate' : result.status;

        resultEl.appendChild(left);
        resultEl.appendChild(badge);
        resultsDiv.prepend(resultEl);

        while (resultsDiv.children.length > 10) {
            resultsDiv.removeChild(resultsDiv.lastChild);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UrlUploader;
}
