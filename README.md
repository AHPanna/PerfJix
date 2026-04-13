# PerfJix – WebRTC Stress Testing Tool

A lightweight, highly scalable load testing tool for **Jitsi Meet** and **Wimi AirTime** servers. Written entirely in Python, it uses Dockerized headless Selenium Grid nodes to spin up synthetic meeting participants that broadcast fake media streams and collect granular WebRTC metrics.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Multi-Platform** | Tests both Jitsi Meet (`/<room>`) and Wimi AirTime (`#/?room=<id>`) |
| **Headless Bots** | Chrome bots run completely in the background |
| **Auto-Join Flow** | Handles pre-join screens, lobby pages, and iframe-embedded instances |
| **Synthetic A/V** | Auto-grants camera/mic permissions with Chrome WebRTC media mocks |
| **ThreadPool Architecture** | Dynamically scales concurrent bot sessions |
| **Local & SSH Monitoring** | Tracks JVB/Jicofo CPU, RAM, and net I/O — locally or on a remote server via SSH |
| **Bastion / Jump Support** | SSH monitor can tunnel through a jump host to reach VMs behind a bastion |
| **WebRTC Metrics** | Collects bitrate, jitter, packet loss, frame rate, codec, RTT per bot |
| **Staggered Join** | Prevents server-side race conditions by launching bots with a configurable delay (`--join-stagger`). |
| **Disconnect Detection** | Monitors for mid-test connection drops |

---

> ⚠️ Running many bots with `--show-browser` on a local machine will exhaust Docker's virtual display. Use headless mode for real stress testing.

---

## 📁 Project Structure

```
PerfJix/
├── main.py                  # Thin CLI entry point
├── perfjix/
│   ├── __init__.py          # Package exports
│   ├── stats.py             # TestStats – thread-safe metrics container
│   ├── webrtc.py            # WebRTCCollector + in-browser JS injection
│   ├── monitoring.py        # LocalMonitor / SSHMonitor classes
│   ├── bot.py               # JitsiBot – one headless Selenium participant
│   └── reporter.py          # Reporter – final results printer
├── docker-compose.yml       # Selenium Grid (Hub + Chrome nodes)
├── jitsi-server.yml         # Optional local Jitsi server
├── .env                     # Environment config
├── .env.jitsi               # Default Jitsi env template
├── run.sh                   # One-command setup script
└── requirements.txt         # Python dependencies
```

---

## 🚀 Setup

### 1. Start the Selenium Grid

```bash
./run.sh
```

This will:
- Start Selenium Hub + Chrome nodes via Docker Compose
- Create a Python virtual environment
- Install all dependencies (`selenium`, `paramiko`, …)

To scale Chrome nodes for higher bot load:
```bash
docker-compose up -d --scale chrome=10
```

### 2. (Optional) Spin Up a Local Jitsi Server

```bash
cp .env.jitsi .env
docker-compose -f jitsi-server.yml --env-file .env up -d
```

---

## 🧪 Usage

### CLI Reference

#### Core options

| Argument | Default | Description |
|---|---|---|
| `--url` | *(required)* | Base URL of the server |
| `--rooms` | `1` | Concurrent rooms (ignored if `--room-id` is set) |
| `--room-id` | `None` | Specific room ID to join |
| `--users-per-room` | `2` | Bot users per room |
| `--duration` | `60` | Seconds each bot stays in the room |
| `--hub-url` | `http://localhost:4444/wd/hub` | Selenium Hub URL |
| `--url-format` | `jitsi` | `jitsi` = `/<room>`, `airtime` = `#/?room=<id>` |
| `--join-stagger` | `None` | Launch delay between bots (5s for airtime, 0.5s for jitsi). Prevents simultaneous "Start" clicks from racing the server. |
| `--show-browser` | `false` | Disable headless (use with VNC) |

#### SSH Remote Monitoring options

| Argument | Default | Description |
|---|---|---|
| `--ssh-host` | `None` | Remote host IP/hostname — **activates SSH mode** |
| `--ssh-user` | `root` | SSH login user for the **target** host |
| `--ssh-key` | `~/.ssh/id_ed25519` | Private key for the **target** host |
| `--ssh-jump` | `None` | Jump/bastion host, e.g. `bastion.host` or `host:port` |
| `--ssh-jump-user` | *(same as `--ssh-user`)* | SSH login user for the **bastion** host |
| `--ssh-jump-key` | *(same as `--ssh-key`)* | Private key for the **bastion** host |

---

### Examples

#### Jitsi Meet — standard test

```bash
./venv/bin/python main.py \
  --url https://jitsi.pnax.io \
  --rooms 4 \
  --users-per-room 5 \
  --duration 300
```

#### Wimi AirTime — specific room

```bash
./venv/bin/python main.py \
  --url https://tenantx.company.com/jitsi/ \
  --room-id 69bc00dda81f10f2db938513a9cb5fc8 \
  --url-format airtime \
  --users-per-room 5 \
  --duration 120
```

#### SSH remote monitoring — direct connection

Monitor docker stats on `51.159.154.92` over SSH using your ed25519 key:

```bash
./venv/bin/python main.py \
  --url https://jitsi.pnax.io \
  --rooms 2 \
  --users-per-room 3 \
  --duration 120 \
  --ssh-host 51.159.154.92 \
  --ssh-user root \
  --ssh-key ~/.ssh/id_ed25519
```

#### SSH remote monitoring — via bastion / jump host

Reach a private VM (`10.0.0.5`) that sits behind the bastion (`51.159.154.92`), where the bastion has a **different user and key**:

```bash
./venv/bin/python main.py \
  --url https://jitsi.pnax.io \
  --rooms 2 \
  --users-per-room 3 \
  --duration 120 \
  --ssh-host 10.0.0.5 \
  --ssh-user root \
  --ssh-key ~/.ssh/id_ed25519 \
  --ssh-jump 51.159.154.92 \
  --ssh-jump-user ubuntu \
  --ssh-jump-key ~/.ssh/id_rsa
```

> `--ssh-jump-user` and `--ssh-jump-key` are **optional** — they fall back to `--ssh-user` / `--ssh-key` when omitted.
> The bastion host format is `[user@]host[:port]`. Any `user@` prefix in `--ssh-jump` is accepted but `--ssh-jump-user` takes precedence.

---

## 📊 Output

```
============================================================
 📊 PERFJIX DEEP TEST RESULTS & SERVER METRICS 📊
============================================================
⏱️  Total Wall-Clock Runtime:   65.23 seconds
✅  Total Successful Joins:     10/10
⚠️  Total Mid-Test Disconnects: 0
❌  Total Hard Join Failures:   0
------------------------------------------------------------
 🖥️  JITSI BACKEND STRAIN (DOCKER)
   ➤ JVB (Videobridge) CPU:     45.2%
   ➤ JVB (Videobridge) RAM:     512MiB / 2GiB
   ➤ JVB Total Traffic In/Out:  1.2GB / 3.8GB

   ➤ Jicofo (Focus Room) CPU:   12.3%
   ➤ Jicofo (Focus Room) RAM:   256MiB / 1GiB
   ➤ Jicofo Total Net I/O:      45MB / 120MB
------------------------------------------------------------
 🌐  WEBRTC NETWORK METRICS (averaged across all bots)
   Audio Codec:               opus
   Video Codec:               vp8
   Video Resolution:          640x360
   ➤ Audio IN  bitrate:        32 kbps   ➤ Audio IN  jitter: 4 ms
   ➤ Video IN  bitrate:        820 kbps  ➤ Video IN  framerate: 30 fps
   ➤ Round-Trip Time (RTT):    18 ms
   Total WebRTC samples:      120
============================================================
```

---

## 📐 Capacity Planning

### Resources Per Jitsi Participant

| Resource | Per User | Notes |
|---|---|---|
| **Bandwidth** | ~2.5 Mbps ↓ / ~1.0 Mbps ↑ | 50 users ≈ 120+ Mbps outbound |
| **CPU** | ~3–5% per core | 100 users saturates a 4-core server |
| **RAM** | ~10–15 MB | JVB/Jicofo baseline heap: ~2 GB |
| **Selenium Node** | ~200–400 MB | Per headless Chrome instance |

### Scaling

| Chrome Nodes | Max Sessions Each | Total Bots |
|---|---|---|
| 2 (default) | 5 | 10 |
| 5 | 5 | 25 |
| 10 | 5 | 50 |

```bash
docker-compose up -d --scale chrome=<N>
```

---

## 🔍 Manual Monitoring (while test runs)

```bash
# Live local container stats
docker stats jvb jicofo prosody web

# System-level
htop
nload eth0
```

With `--ssh-host`, PerfJix handles remote monitoring automatically inside the process.
