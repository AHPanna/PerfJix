"""
Browser-side (Chrome/Selenium) client performance metrics collector.

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT
"""
import logging


# ---------------------------------------------------------------------------
# JS executed synchronously inside the browser session.
# Collects: JS heap, navigation timing, paint timing (FCP/LCP if available),
# and a snapshot of page resource count.
# ---------------------------------------------------------------------------
BROWSER_METRICS_JS = """
var r = {
    heap_used_mb:  null,
    heap_total_mb: null,
    heap_limit_mb: null,
    load_ms:          null,
    dom_ready_ms:     null,
    ttfb_ms:          null,
    transfer_kb:      null,
    fcp_ms:           null,
    resource_count:   null,
};

// ── 1. JS Heap (Chrome-only) ─────────────────────────────────────────────────
try {
    var mem = window.performance.memory;
    if (mem) {
        r.heap_used_mb  = Math.round(mem.usedJSHeapSize  / 1048576 * 10) / 10;
        r.heap_total_mb = Math.round(mem.totalJSHeapSize / 1048576 * 10) / 10;
        r.heap_limit_mb = Math.round(mem.jsHeapSizeLimit / 1048576 * 10) / 10;
    }
} catch(e) {}

// ── 2. Navigation timing ─────────────────────────────────────────────────────
try {
    var nav = performance.getEntriesByType('navigation')[0];
    if (nav) {
        r.load_ms     = Math.round(nav.loadEventEnd          - nav.startTime);
        r.dom_ready_ms= Math.round(nav.domContentLoadedEventEnd - nav.startTime);
        r.ttfb_ms     = Math.round(nav.responseStart         - nav.requestStart);
        r.transfer_kb = Math.round(nav.transferSize          / 1024);
    }
} catch(e) {}

// ── 3. First Contentful Paint ────────────────────────────────────────────────
try {
    var paints = performance.getEntriesByType('paint');
    paints.forEach(function(e) {
        if (e.name === 'first-contentful-paint')
            r.fcp_ms = Math.round(e.startTime);
    });
} catch(e) {}

// ── 4. Resource count ────────────────────────────────────────────────────────
try {
    r.resource_count = performance.getEntriesByType('resource').length;
} catch(e) {}

return r;
"""


class BrowserMetricsCollector:
    """
    Collects Chrome client-side performance data from an active Selenium session.

    Metrics gathered
    ----------------
    Heap      : JS heap used / total / limit (MB)  — Chrome only
    Navigation: page load, DOM ready, TTFB, transfer size
    Paint     : First Contentful Paint (ms)
    Resources : total number of resources fetched
    """

    def __init__(self, stats):
        self._stats = stats

    def collect(self, driver, user_id: int) -> None:
        """Execute the metrics JS and store the result."""
        try:
            sample = driver.execute_script(BROWSER_METRICS_JS)
            if not sample:
                return

            sample["user_id"] = user_id
            with self._stats.lock:
                self._stats.browser_samples.append(sample)

            logging.info(
                f"[User {user_id}] Browser perf | "
                f"Heap: {sample.get('heap_used_mb')} / {sample.get('heap_total_mb')} MB | "
                f"Load: {sample.get('load_ms')} ms | "
                f"TTFB: {sample.get('ttfb_ms')} ms | "
                f"FCP: {sample.get('fcp_ms')} ms | "
                f"Resources: {sample.get('resource_count')}"
            )
        except Exception as e:
            logging.debug(f"[User {user_id}]: Browser metrics error: {e}")
