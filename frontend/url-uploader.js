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

    render() {
        this.container.innerHTML = `
            <div class="url-uploader">
                <div class="url-input-section">
                    <h3 class="text-lg font-semibold mb-2 dark:text-white">Upload from URL</h3>
                    <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
                        Paste a link from TikTok, Instagram, Facebook, Reddit, YouTube, or Twitter
                    </p>

                    <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                        <input
                            type="text"
                            id="url-input"
                            placeholder="https://www.tiktok.com/@user/video/..."
                            class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                        />
                        <button
                            id="url-upload-btn"
                            class="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            style="display: flex; align-items: center; justify-content: center; gap: 0.5rem;"
                        >
                            <span id="url-btn-text">Upload</span>
                            <svg id="url-spinner" class="hidden animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                        </button>
                    </div>

                    <div id="url-status" class="mt-2 text-sm hidden"></div>

                    <div id="supported-platforms" class="mt-4 text-xs text-gray-400 dark:text-gray-500">
                        Loading supported platforms...
                    </div>
                </div>

                <div class="url-batch-section mt-6 hidden" id="batch-section">
                    <h4 class="text-md font-semibold mb-2 dark:text-white">Batch Upload</h4>
                    <textarea
                        id="batch-urls"
                        rows="4"
                        placeholder="Paste multiple URLs, one per line..."
                        class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                    ></textarea>
                    <button
                        id="batch-upload-btn"
                        class="mt-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                    >
                        Upload All
                    </button>
                </div>

                <div id="url-results" class="mt-4 space-y-2"></div>
            </div>
        `;
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
            const platformList = data.platforms.map(p =>
                `<span class="inline-block px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded mr-1 mb-1">${p}</span>`
            ).join('');

            platformsDiv.innerHTML = `Supported: ${platformList}`;
        } catch (error) {
            console.warn('Could not load supported platforms:', error);
        }
    }

    setStatus(message, type = 'info') {
        const statusDiv = this.container.querySelector('#url-status');
        statusDiv.classList.remove('hidden', 'text-red-500', 'text-green-500', 'text-blue-500', 'text-yellow-500');

        const colorMap = {
            error: 'text-red-500',
            success: 'text-green-500',
            info: 'text-blue-500',
            warning: 'text-yellow-500',
        };

        statusDiv.classList.add(colorMap[type] || 'text-blue-500');
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

        const statusColors = {
            success: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200',
            error: 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200',
            duplicate: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200',
        };

        const status = result.duplicate ? 'duplicate' : result.status;
        const colorClass = statusColors[status] || statusColors.error;

        const resultEl = document.createElement('div');
        resultEl.className = `p-3 rounded-lg ${colorClass} flex justify-between items-center`;
        resultEl.innerHTML = `
            <div>
                <span class="font-medium">${this.escapeHtml(result.filename)}</span>
                ${result.platform ? `<span class="ml-2 text-xs opacity-75">${result.platform}</span>` : ''}
            </div>
            <span class="px-2 py-1 rounded text-xs font-semibold uppercase">
                ${result.duplicate ? 'Duplicate' : result.status}
            </span>
        `;

        resultsDiv.prepend(resultEl);

        // Keep only last 10 results
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
