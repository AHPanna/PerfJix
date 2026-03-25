"""
Shared test statistics container (thread-safe).

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT
"""
import threading


class TestStats:
    """Accumulates metrics across all bot threads and the monitor thread."""

    def __init__(self):
        # --- Bot counters ---
        self.successful_joins: int = 0
        self.failed_joins: int = 0
        self.disconnects: int = 0

        # --- JVB (Videobridge) ---
        self.peak_jvb_cpu: float = 0.0
        self.peak_jvb_ram: str = "0MiB"
        self.final_jvb_net: str = "0B"

        # --- Jicofo ---
        self.peak_jicofo_cpu: float = 0.0
        self.peak_jicofo_ram: str = "0MiB"
        self.final_jicofo_net: str = "0B"

        # --- WebRTC per-user samples (list of dicts) ---
        self.webrtc_samples: list = []

        # --- Browser (Chrome) client-side performance samples ---
        self.browser_samples: list = []

        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    # Helpers used by the monitor threads
    # ------------------------------------------------------------------

    def update_from_docker_line(self, line: str) -> None:
        """Parse one 'docker stats --no-stream' CSV line and update fields."""
        parts = line.split(",")
        if len(parts) < 4:
            return
        name, cpu, mem, net = parts[0], parts[1], parts[2], parts[3]
        cpu_val = float(cpu.replace("%", "")) if "%" in cpu else 0.0

        with self.lock:
            if "jvb" in name.lower():
                self.final_jvb_net = net
                if cpu_val > self.peak_jvb_cpu:
                    self.peak_jvb_cpu = cpu_val
                    self.peak_jvb_ram = mem
            elif "jicofo" in name.lower():
                self.final_jicofo_net = net
                if cpu_val > self.peak_jicofo_cpu:
                    self.peak_jicofo_cpu = cpu_val
                    self.peak_jicofo_ram = mem
