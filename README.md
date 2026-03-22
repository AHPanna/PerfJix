# PerfJix - Jitsi Stress Testing Tool

A lightweight, highly scalable load testing alternative to `jitsi-meet-torture`. It is written entirely in Python, eliminating bulky Java frameworks, and leverages Dockerized headless Selenium Grid nodes to instantly spin up synthetic meeting participants broadcasting fake media streams.

## Features
- **Headless Bots**: Seamlessly connects bots entirely in the background, circumventing excessive desktop GUI rendering.
- **Auto-Lobby Bypass**: Intelligently scans and clicks through pre-join security screens.
- **Synthetic A/V Injectors**: Auto-grants camera/mic permissions using standard Google Chrome WebRTC media mocks.
- **ThreadPool Architecture**: Python dynamically scales grid requests concurrently for deep server strain.

---

## 🚀 Setup & Execution

1. Initialize your local Selenium Docker grid:
```bash
./run.sh
```

2. Execute a standard headless **Stress Test** (Example: 20 users spread across 4 rooms for 5 minutes):
```bash
./venv/bin/python main.py --url https://192.168.1.2:8443 --rooms 4 --users-per-room 5 --duration 300
```

### Advanced Test Scenarios

**Massive Multi-Room Saturation:**
```bash
./venv/bin/python main.py --url https://192.168.1.2:8443 --rooms 10 --users-per-room 4 --duration 600
```

**Single Bot Visual Debugging (via VNC):**
Watch a bot physically join and broadcast streams via `http://localhost:4444`. 
```bash
./venv/bin/python main.py --url https://192.168.1.2:8443 --rooms 1 --users-per-room 1 --duration 60 --show-browser
```
*(Warning: Running several users with `--show-browser` on a local development machine will crush Docker's virtual display manager! Use strictly in headless mode for actual stress testing).*

---

## 📊 Technical Benchmarks & Server Load

When scaling PerfJix against your `docker-jitsi-meet` server, you must mathematically profile the bandwidth and CPU strain beforehand to identify true platform limits versus artificial network bottlenecks. 

Below are the industry-standard metrics for what the core Jitsi architecture consumes **per active video participant**:

### 1. Resources Per Jitsi Participant
- **Bandwidth (Network Layer)**: 
  - Average Client: **~2.5 Mbps Download / ~1.0 Mbps Upload**
  - *JVB Multiplier Factor*: In a single 50-user room, the Jitsi Videobridge (JVB) must route ~50 simultaneous streams, pushing over **~120+ Mbps** of raw outbound bandwidth from the server.
- **CPU (Processing Limits)**: 
  - The JVB routing engine consumes roughly **~3% to 5%** of a modern CPU core per active video connection.
  - A 100-user conference will mathematically max out a standard 4-Core/8-Thread server entirely.
- **RAM Memory Allocation**: 
  - The `jvb` and `jicofo` Java services run a ~2GB baseline heap.
  - Expect an additional **~10MB to ~15MB** of RAM utilized per active WebRTC pipeline.
  - *Note*: Selenium Nodes (your PerfJix bots) consume approx. **200MB to 400MB** of host memory per headless Chrome instance.

### 2. How to Monitor Your Jitsi Server

While `PerfJix` is actively sending users to your URLs, open a secondary SSH terminal on your Jitsi server and utilize these technical commands:

**Live Docker Container Analytics:**
```bash
docker stats jvb jicofo prosody web
```
*Use this to track JVB CPU% bursting past 100% or Jicofo JVM Memory Limits triggering OutOfMemory errors.*

**Hardware IO & Bandwidth Monitoring:**
```bash
htop
nload eth0  # (or your server's primary network interface)
```
*If `nload` shows outbound traffic hitting your ISP's Gigabit speed limit, your Jitsi server hasn't failed—your bandwidth pipe has simply saturated!*
