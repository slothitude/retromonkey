/* RetroMonkey - Application JavaScript */

(function () {
    'use strict';

    /**
     * Toggle between light and dark themes.
     * Persists choice in localStorage.
     */
    function toggleTheme() {
        const html = document.documentElement;
        const current = html.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('retromonkey-theme', next);
        updateThemeButton(next);
    }

    /**
     * Update the theme toggle button icon.
     */
    function updateThemeButton(theme) {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;
        // Sun icon for dark mode (click to go light), moon for light mode
        btn.innerHTML = theme === 'dark' ? '&#9788;' : '&#9790;';
    }

    /**
     * Restore saved theme on page load.
     */
    function restoreTheme() {
        const saved = localStorage.getItem('retromonkey-theme');
        if (saved) {
            document.documentElement.setAttribute('data-theme', saved);
            updateThemeButton(saved);
        } else {
            updateThemeButton('dark');
        }
    }

    /**
     * Global search handler - auto-show/hide results dropdown.
     */
    function initGlobalSearch() {
        const input = document.getElementById('global-search');
        const results = document.getElementById('search-results');
        if (!input || !results) return;

        document.addEventListener('click', function (e) {
            if (!input.contains(e.target) && !results.contains(e.target)) {
                results.style.display = 'none';
            }
        });

        input.addEventListener('focus', function () {
            if (results.innerHTML.trim()) {
                results.style.display = 'block';
            }
        });
    }

    /**
     * Tab switching helper - works with data-tab attributes.
     */
    function initTabs() {
        document.querySelectorAll('.tab-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var tabGroup = this.closest('.tabs-wrapper') || this.parentElement.parentElement;
                var tabId = this.getAttribute('data-tab');

                // Deactivate all tabs in this group
                tabGroup.querySelectorAll('.tab-btn').forEach(function (b) {
                    b.classList.remove('active');
                });
                tabGroup.querySelectorAll('.tab-content').forEach(function (c) {
                    c.classList.remove('active');
                });

                // Activate selected
                this.classList.add('active');
                var content = tabGroup.querySelector('#' + tabId);
                if (content) content.classList.add('active');
            });
        });
    }

    /**
     * Modal helpers.
     */
    function initModals() {
        // Close on overlay click
        document.querySelectorAll('.modal-overlay').forEach(function (overlay) {
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) {
                    closeModal(overlay.id);
                }
            });
        });

        // Close on close button click
        document.querySelectorAll('.modal-close').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var overlay = this.closest('.modal-overlay');
                if (overlay) closeModal(overlay.id);
            });
        });
    }

    function openModal(id) {
        var el = document.getElementById(id);
        if (el) el.classList.add('active');
    }

    function closeModal(id) {
        var el = document.getElementById(id);
        if (el) el.classList.remove('active');
    }

    // Expose globally
    window.toggleTheme = toggleTheme;
    window.openModal = openModal;
    window.closeModal = closeModal;

    // Init on DOM ready
    document.addEventListener('DOMContentLoaded', function () {
        restoreTheme();
        initGlobalSearch();
        initTabs();
        initModals();
    });
})();
