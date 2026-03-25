"""
WebRTC stats collection via in-browser JavaScript injection.

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT
"""
import logging

from selenium.webdriver.common.by import By

# ---------------------------------------------------------------------------
# JavaScript injected into the browser to extract WebRTC stats from the
# active RTCPeerConnection via the standard getStats() API.
# execute_async_script passes a callback as the last argument.
# ---------------------------------------------------------------------------
WEBRTC_STATS_JS = """
var done = arguments[arguments.length - 1];
var result = {
    audio_in:  { codec: null, bitrate_kbps: 0, packets_lost: 0, jitter_ms: 0 },
    audio_out: { codec: null, bitrate_kbps: 0 },
    video_in:  { codec: null, bitrate_kbps: 0, packets_lost: 0, frame_rate: 0,
                 resolution: null, jitter_ms: 0 },
    video_out: { codec: null, bitrate_kbps: 0, frame_rate: 0, resolution: null },
    rtt_ms: null,
};

// ── 1. Use CDP-intercepted list (most reliable, version-agnostic) ────────────
var activePc = null;
var pcs = window.__pjPCs || [];

// Pick the best (most connected, non-closed) PC
var PREF = { 'connected': 3, 'checking': 2, 'new': 1 };
var bestScore = -1;
for (var i = 0; i < pcs.length; i++) {
    var pc = pcs[i];
    var state = pc.connectionState || pc.iceConnectionState || '';
    if (state === 'closed' || state === 'failed') continue;
    var score = PREF[state] || 0;
    if (score > bestScore) { bestScore = score; activePc = pc; }
}

// ── 2. Jitsi APP internal API (multiple version paths) ───────────────────────
if (!activePc) {
    var paths = [
        // Jitsi 8000-series
        function() { return Object.values(APP.conference._room.rtc._peerConnections||{})[0].peerconnection; },
        // Jitsi newer
        function() { return APP.conference._room._conference.rtc._peerConnections[Object.keys(APP.conference._room._conference.rtc._peerConnections)[0]].peerconnection; },
        // Simple fallback
        function() { return APP.conference._room.rtc.peerConnections && APP.conference._room.rtc.peerConnections[0]; },
    ];
    for (var p = 0; p < paths.length; p++) {
        try { var c = paths[p](); if (c && c.connectionState !== 'closed') { activePc = c; break; } } catch(e) {}
    }
}

if (!activePc) {
    result._error = 'no_peer_connection';
    done(result); return;
}

activePc.getStats().then(function(stats) {
    var prev  = window.__perfJixPrevStats || {};
    var now   = Date.now();
    var dt    = ((now - (window.__perfJixPrevTs || now)) / 1000) || 1;
    window.__perfJixPrevTs = now;
    var newPrev = {};

    stats.forEach(function(r) {
        if (r.type === 'inbound-rtp' && r.kind === 'audio') {
            var p = prev[r.id] || r;
            result.audio_in.bitrate_kbps = Math.round((r.bytesReceived - (p.bytesReceived||0)) * 8 / dt / 1000);
            result.audio_in.packets_lost = r.packetsLost || 0;
            result.audio_in.jitter_ms    = Math.round((r.jitter || 0) * 1000);
            newPrev[r.id] = r;
        }
        if (r.type === 'inbound-rtp' && r.kind === 'video') {
            var p = prev[r.id] || r;
            result.video_in.bitrate_kbps = Math.round((r.bytesReceived - (p.bytesReceived||0)) * 8 / dt / 1000);
            result.video_in.packets_lost = r.packetsLost || 0;
            result.video_in.jitter_ms    = Math.round((r.jitter || 0) * 1000);
            result.video_in.frame_rate   = Math.round(r.framesPerSecond || 0);
            if (r.frameWidth) result.video_in.resolution = r.frameWidth + 'x' + r.frameHeight;
            newPrev[r.id] = r;
        }
        if (r.type === 'outbound-rtp' && r.kind === 'audio') {
            var p = prev[r.id] || r;
            result.audio_out.bitrate_kbps = Math.round((r.bytesSent - (p.bytesSent||0)) * 8 / dt / 1000);
            newPrev[r.id] = r;
        }
        if (r.type === 'outbound-rtp' && r.kind === 'video') {
            var p = prev[r.id] || r;
            result.video_out.bitrate_kbps = Math.round((r.bytesSent - (p.bytesSent||0)) * 8 / dt / 1000);
            result.video_out.frame_rate   = Math.round(r.framesPerSecond || 0);
            if (r.frameWidth) result.video_out.resolution = r.frameWidth + 'x' + r.frameHeight;
            newPrev[r.id] = r;
        }
        if (r.type === 'codec') {
            var mime = (r.mimeType || '').split('/')[1];
            if (r.mimeType.startsWith('audio') && !result.audio_in.codec)
                result.audio_in.codec = result.audio_out.codec = mime;
            if (r.mimeType.startsWith('video') && !result.video_in.codec)
                result.video_in.codec = result.video_out.codec = mime;
        }
        if (r.type === 'remote-inbound-rtp' && r.kind === 'audio') {
            result.rtt_ms = Math.round((r.roundTripTime || 0) * 1000);
        }
    });
    window.__perfJixPrevStats = Object.assign({}, prev, newPrev);
    done(result);
}).catch(function(err) {
    result._error = err.toString();
    done(result);
});
"""


class WebRTCCollector:
    """Injects JS into a running browser session to sample WebRTC metrics."""

    def __init__(self, stats):
        """
        Parameters
        ----------
        stats : TestStats
            Shared stats container to append samples to.
        """
        self._stats = stats

    def collect(self, driver, user_id: str, room_name: str, url_format: str) -> None:
        """Collect one WebRTC sample and store it in *stats*."""
        try:
            if url_format == "airtime":
                try:
                    iframe = driver.find_element(By.ID, "jitsiConferenceFrame0")
                    driver.switch_to.frame(iframe)
                except Exception as ie:
                    logging.warning(f"[User {user_id}]: Could not switch to iframe for stats: {ie}")

            driver.set_script_timeout(10)
            sample = driver.execute_async_script(WEBRTC_STATS_JS)

            if url_format == "airtime":
                driver.switch_to.default_content()

            if not sample:
                logging.warning(f"[User {user_id}]: WebRTC stats returned empty (bot may not be in call)")
                return

            err = sample.get("_error")
            if err:
                logging.warning(f"[User {user_id}]: WebRTC JS reported: {err}")
                return

            sample["user_id"] = user_id
            with self._stats.lock:
                self._stats.webrtc_samples.append(sample)

            ai = sample.get("audio_in", {})
            vi = sample.get("video_in", {})
            logging.info(
                f"[User {user_id} -> Room {room_name}]: WebRTC | "
                f"Audio in: {ai.get('bitrate_kbps', 0)} kbps ({ai.get('codec', '?')}) "
                f"jitter={ai.get('jitter_ms', 0)}ms loss={ai.get('packets_lost', 0)} | "
                f"Video in: {vi.get('bitrate_kbps', 0)} kbps ({vi.get('codec', '?')}) "
                f"{vi.get('resolution', '?')} @{vi.get('frame_rate', 0)}fps "
                f"jitter={vi.get('jitter_ms', 0)}ms | "
                f"RTT: {sample.get('rtt_ms', '?')}ms"
            )

        except Exception as e:
            logging.warning(f"[User {user_id}]: WebRTC stats collection error: {e}")
