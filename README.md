# PerfJix - WebRTC Stress Testing Tool

A lightweight, highly scalable load testing tool for Jitsi Meet and Wimi AirTime servers. Written entirely in Python, it leverages Dockerized headless Selenium Grid nodes to spin up synthetic meeting participants broadcasting fake media streams.

## Features

- **Multi-Platform Support**: Test both **Jitsi Meet** (`/<room>`) and **Wimi AirTime** (`#/?room=<id>`) servers
- **Headless Bots**: Connects bots entirely in the background via headless Chrome
- **Auto-Join Flow**: Automatically handles pre-join screens, lobby pages, and iframe-embedded Jitsi instances
- **Synthetic A/V**: Auto-grants camera/mic permissions using Chrome WebRTC media mocks
- **ThreadPool Architecture**: Dynamically scales concurrent bot sessions for deep server strain
- **Live Docker Monitoring**: Tracks JVB and Jicofo CPU, RAM, and network usage in real time
- **Disconnect Detection**: Monitors for mid-test connection drops

---

> ⚠️ Running several users with `--show-browser` on a local machine will crush Docker's virtual display manager. Use headless mode for actual stress testing.

---

## 🚀 Setup

### 1. Start the Selenium Grid

```bash
./run.sh
```

This will:
- Start Selenium Hub + Chrome nodes via Docker Compose
- Create a Python virtual environment
- Install dependencies

To scale Chrome nodes for higher load:
```bash
docker-compose up -d --scale chrome=10
```

### 2. (Optional) Spin Up a Local Jitsi Server

If you don't have a Jitsi server to test against:

```bash
cp .env.jitsi .env
docker-compose -f jitsi-server.yml --env-file .env up -d
```

---

## 🧪 Usage

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--url` | *(required)* | Base URL of the server |
| `--rooms` | `1` | Number of concurrent rooms (ignored if `--room-id` is set) |
| `--room-id` | `None` | Specific room ID to join |
| `--users-per-room` | `2` | Number of bot users per room |
| `--duration` | `60` | Duration in seconds to stay in the room |
| `--hub-url` | `http://localhost:4444/wd/hub` | Selenium Hub URL |
| `--url-format` | `jitsi` | URL format: `jitsi` = `/<room>`, `airtime` = `#/?room=<id>` |
| `--show-browser` | `false` | Show browser in VNC (disable headless) |

### Jitsi Meet (Standard)

Test against a Jitsi server with 20 users across 4 auto-generated rooms for 5 minutes:

```bash
./venv/bin/python main.py \
  --url https://jitsi.xxx.io \
  --rooms 4 \
  --users-per-room 5 \
  --duration 300
```

### Wimi AirTime (Specific Room)

Test against a Wimi AirTime server with a specific room ID:

```bash
./venv/bin/python main.py \
  --url https://tenantx.company.com/jitsi/ \
  --room-id 69bc00dda81f10f2db938513a9cb5fc8 \
  --url-format jitsi \
  --users-per-room 5 \
  --duration 120
```

---

## 📊 Output

After each test, PerfJix prints a summary report:

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
============================================================
```

---

## 📐 Capacity Planning

### Resources Per Jitsi Participant

| Resource | Per User | Notes |
|---|---|---|
| **Bandwidth** | ~2.5 Mbps ↓ / ~1.0 Mbps ↑ | JVB routes all streams; 50 users ≈ 120+ Mbps outbound |
| **CPU** | ~3-5% per core | 100 users saturates a 4-core/8-thread server |
| **RAM** | ~10-15 MB | JVB/Jicofo baseline heap: ~2 GB |
| **Selenium Node** | ~200-400 MB | Per headless Chrome instance |

### Scaling Limits

| Chrome Nodes | Max Sessions Each | Total Bots |
|---|---|---|
| 2 (default) | 5 | 10 |
| 5 | 5 | 25 |
| 10 | 5 | 50 |

Scale with: `docker-compose up -d --scale chrome=<N>`

---

## 🔍 Monitoring During Tests

While PerfJix is running, monitor your server in a separate terminal:

```bash
# Live Docker container stats
docker stats jvb jicofo prosody web

# System-level monitoring
htop
nload eth0
```

---

## 📁 Project Structure

```
PerfJix/
├── main.py              # Core stress testing engine
├── docker-compose.yml   # Selenium Grid (Hub + Chrome nodes)
├── jitsi-server.yml     # Optional local Jitsi server
├── .env                 # Environment config
├── .env.jitsi           # Default Jitsi server env template
├── run.sh               # One-command setup script
└── requirements.txt     # Python dependencies (selenium)
```
