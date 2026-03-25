"""
Final results reporter.

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT
"""
import io


class Reporter:
    """Formats and prints the post-test summary to stdout."""

    def __init__(self, stats, total_users: int, elapsed: float):
        self._s = stats
        self._total = total_users
        self._elapsed = elapsed

    def print_summary(self) -> str:
        """Prints the summary to stdout and returns the full text as a string."""
        s = self._s
        w = "=" * 60
        out = io.StringIO()

        out.write(f"\n{w}\n")
        out.write(" 📊 PERFJIX DEEP TEST RESULTS & SERVER METRICS 📊 \n")
        out.write(f"{w}\n")
        out.write(f"⏱️  Total Wall-Clock Runtime:   {self._elapsed:.2f} seconds\n")
        out.write(f"✅  Total Successful Joins:     {s.successful_joins}/{self._total}\n")
        out.write(f"⚠️  Total Mid-Test Disconnects: {s.disconnects}\n")
        out.write(f"❌  Total Hard Join Failures:   {s.failed_joins}\n")
        out.write("-" * 60 + "\n")

        out.write(" 🖥️  JITSI BACKEND STRAIN (DOCKER) \n")
        out.write(f"   ➤ JVB (Videobridge) CPU:     {s.peak_jvb_cpu:.1f}%\n")
        out.write(f"   ➤ JVB (Videobridge) RAM:     {s.peak_jvb_ram}\n")
        out.write(f"   ➤ JVB Total Traffic In/Out:  {s.final_jvb_net}\n\n")
        
        out.write(f"   ➤ Jicofo (Focus Room) CPU:   {s.peak_jicofo_cpu:.1f}%\n")
        out.write(f"   ➤ Jicofo (Focus Room) RAM:   {s.peak_jicofo_ram}\n")
        out.write(f"   ➤ Jicofo Total Net I/O:      {s.final_jicofo_net}\n")

        if s.webrtc_samples:
            self._print_webrtc(out)

        if s.browser_samples:
            self._print_browser(out)

        out.write(f"{w}\n\n")
        
        text = out.getvalue()
        print(text)
        return text

    # ------------------------------------------------------------------

    @staticmethod
    def _avg(samples: list, *keys):
        vals = []
        for s in samples:
            v = s
            for k in keys:
                v = v.get(k) if isinstance(v, dict) else None
            if isinstance(v, (int, float)):
                vals.append(v)
        return round(sum(vals) / len(vals), 1) if vals else "N/A"

    @staticmethod
    def _first(samples: list, *keys):
        for s in samples:
            v = s
            for k in keys:
                v = v.get(k) if isinstance(v, dict) else None
            if v:
                return v
        return "N/A"

    def _print_webrtc(self, out: io.StringIO) -> None:
        samples = self._s.webrtc_samples
        avg = lambda *keys: self._avg(samples, *keys)   # noqa: E731
        first = lambda *keys: self._first(samples, *keys)  # noqa: E731

        out.write("-" * 60 + "\n")
        out.write(" 🌐  WEBRTC NETWORK METRICS (averaged across all bots) \n")
        out.write(f"   Audio Codec:               {first('audio_in', 'codec')}\n")
        out.write(f"   Video Codec:               {first('video_in', 'codec')}\n")
        out.write(f"   Video Resolution:          {first('video_in', 'resolution')}\n\n")
        
        out.write(f"   ➤ Audio IN  bitrate:        {avg('audio_in', 'bitrate_kbps')} kbps\n")
        out.write(f"   ➤ Audio IN  jitter:         {avg('audio_in', 'jitter_ms')} ms\n")
        out.write(f"   ➤ Audio IN  packet loss:    {avg('audio_in', 'packets_lost')} pkts\n")
        out.write(f"   ➤ Audio OUT bitrate:        {avg('audio_out', 'bitrate_kbps')} kbps\n\n")
        
        out.write(f"   ➤ Video IN  bitrate:        {avg('video_in', 'bitrate_kbps')} kbps\n")
        out.write(f"   ➤ Video IN  framerate:      {avg('video_in', 'frame_rate')} fps\n")
        out.write(f"   ➤ Video IN  jitter:         {avg('video_in', 'jitter_ms')} ms\n")
        out.write(f"   ➤ Video IN  packet loss:    {avg('video_in', 'packets_lost')} pkts\n")
        out.write(f"   ➤ Video OUT bitrate:        {avg('video_out', 'bitrate_kbps')} kbps\n")
        out.write(f"   ➤ Video OUT framerate:      {avg('video_out', 'frame_rate')} fps\n\n")
        
        out.write(f"   ➤ Round-Trip Time (RTT):    {avg('rtt_ms')} ms\n")
        out.write(f"   Total WebRTC samples:      {len(samples)}\n")

    def _print_browser(self, out: io.StringIO) -> None:
        samples = self._s.browser_samples
        # Direct key access (flat dict, not nested)
        def avg(key):
            vals = [s[key] for s in samples if isinstance(s.get(key), (int, float))]
            return round(sum(vals) / len(vals), 1) if vals else "N/A"

        out.write("-" * 60 + "\n")
        out.write(" 🖥️  CHROME CLIENT METRICS (averaged across all bots) \n\n")
        out.write(" Memory (JS Heap)\n")
        out.write(f"   ➤ Heap Used:               {avg('heap_used_mb')} MB\n")
        out.write(f"   ➤ Heap Total:              {avg('heap_total_mb')} MB\n")
        out.write(f"   ➤ Heap Limit:              {avg('heap_limit_mb')} MB\n\n")
        
        out.write(" Page Performance\n")
        out.write(f"   ➤ Page Load Time:          {avg('load_ms')} ms\n")
        out.write(f"   ➤ DOM Content Loaded:      {avg('dom_ready_ms')} ms\n")
        out.write(f"   ➤ Time to First Byte:      {avg('ttfb_ms')} ms\n")
        out.write(f"   ➤ First Contentful Paint:  {avg('fcp_ms')} ms\n")
        out.write(f"   ➤ Transfer Size:           {avg('transfer_kb')} KB\n")
        out.write(f"   ➤ Total Resources Fetched: {avg('resource_count')}\n")
        out.write(f"   Total browser samples:     {len(samples)}\n")

