#!/usr/bin/env python3
"""
PerfJix – CLI entry point.

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT

All logic lives inside the perfjix/ package:
  perfjix/stats.py      – TestStats (thread-safe metrics container)
  perfjix/webrtc.py     – WebRTCCollector + WEBRTC_STATS_JS
  perfjix/monitoring.py – LocalMonitor / SSHMonitor
  perfjix/bot.py        – JitsiBot (one headless Selenium participant)
  perfjix/reporter.py   – Reporter (final results printer)
"""
import argparse
import concurrent.futures
import logging
import time
import os
import uuid
from datetime import datetime
from pathlib import Path

from perfjix.stats import TestStats
from perfjix.monitoring import LocalMonitor, SSHMonitor
from perfjix.bot import JitsiBot
from perfjix.reporter import Reporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PerfJix – WebRTC stress-testing tool for Jitsi / Wimi AirTime",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Core ───────────────────────────────────────────────────────────
    parser.add_argument("--url", required=True,
                        help="Base URL of the server (e.g. https://jitsi.pnax.io)")
    parser.add_argument("--rooms", type=int, default=1,
                        help="Number of concurrent rooms (ignored when --room-id is set)")
    parser.add_argument("--room-id", default=None,
                        help="Specific room ID to join")
    parser.add_argument("--users-per-room", type=int, default=2,
                        help="Bot users per room")
    parser.add_argument("--duration", type=int, default=60,
                        help="Seconds each bot stays in the room")
    parser.add_argument("--hub-url", default="http://localhost:4444/wd/hub",
                        help="Selenium Grid / Hub URL")
    parser.add_argument("--show-browser", action="store_true",
                        help="Disable headless mode (useful with VNC)")
    parser.add_argument("--url-format", choices=["jitsi", "airtime"], default="jitsi",
                        help="URL scheme: 'jitsi' = /<room>, 'airtime' = #/?room=<id>")

    # ── SSH Remote Monitoring ──────────────────────────────────────────
    ssh = parser.add_argument_group(
        "SSH Remote Monitoring",
        "Poll docker stats on a remote machine instead of locally. "
        "Requires paramiko (pip install paramiko).",
    )
    ssh.add_argument("--ssh-host", default=None,
                     help="Remote host IP / hostname. Enables SSH monitoring mode.")
    ssh.add_argument("--ssh-user", default="root",
                     help="SSH login user")
    ssh.add_argument("--ssh-key", default="~/.ssh/id_ed25519",
                     help="Path to SSH private key")
    ssh.add_argument("--ssh-jump", default=None,
                     help="Jump / bastion host, e.g. 'user@bastion.host' or 'host:port'")
    ssh.add_argument("--ssh-jump-user", default=None,
                     help="Login user for the jump host (defaults to --ssh-user if omitted)")
    ssh.add_argument("--ssh-jump-key", default=None,
                     help="Private key for the jump host (defaults to --ssh-key if omitted)")

    return parser


def main() -> None:
    args = build_parser().parse_args()

    # ── Room list ──────────────────────────────────────────────────────
    if args.room_id:
        room_names = [args.room_id]
        num_rooms = 1
    else:
        room_names = [f"PerfJixRoom_{uuid.uuid4().hex[:8]}" for _ in range(args.rooms)]
        num_rooms = args.rooms

    total_users = num_rooms * args.users_per_room
    logging.info(f"🚀 Starting PerfJix: {num_rooms} room(s), {args.users_per_room} users/room, {args.duration}s")

    # ── Shared stats ───────────────────────────────────────────────────
    stats = TestStats()

    # ── Monitor ───────────────────────────────────────────────────────
    if args.ssh_host:
        logging.info(
            f"[Monitor] SSH → {args.ssh_user}@{args.ssh_host}"
            + (f" via {args.ssh_jump}" if args.ssh_jump else " (direct)")
            + f"  key={args.ssh_key}"
        )
        monitor = SSHMonitor(
            stats,
            ssh_host=args.ssh_host,
            ssh_user=args.ssh_user,
            ssh_key=args.ssh_key,
            ssh_jump=args.ssh_jump,
            ssh_jump_user=args.ssh_jump_user,
            ssh_jump_key=args.ssh_jump_key,
        )
    else:
        logging.info("[Monitor] Using local docker stats.")
        monitor = LocalMonitor(stats)

    monitor.start()
    start_wall = time.time()

    # ── Bot pool ───────────────────────────────────────────────────────
    bot = JitsiBot(
        stats=stats,
        hub_url=args.hub_url,
        show_browser=args.show_browser,
        url_format=args.url_format,
    )

    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=total_users) as executor:
        uid = 0
        for room_name in room_names:
            for _ in range(args.users_per_room):
                futures.append(
                    executor.submit(bot.run, args.url, room_name, args.duration, uid)
                )
                uid += 1
        concurrent.futures.wait(futures)

    # ── Teardown & Reporting ───────────────────────────────────────────
    monitor.stop()
    elapsed = time.time() - start_wall

    report_text = Reporter(stats, total_users, elapsed).print_summary()
    
    # Save report to file
    try:
        results_dir = Path("results")
        results_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_url = args.url.replace("https://", "").replace("http://", "").replace("/", "_")
        
        filename = f"perf_{timestamp}_{safe_url}_{total_users}users_{args.duration}s.txt"
        file_path = results_dir / filename
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report_text)
            
        logging.info(f"✅ Detailed report saved to: {file_path}")
    except Exception as e:
        logging.error(f"Failed to save report to file: {e}")


if __name__ == "__main__":
    main()
