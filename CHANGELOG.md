# Changelog

All notable changes to **PerfJix** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-25
### Added
- **Remote SSH Monitoring**: Added support for polling Docker containers over SSH, including Bastion/Jump host routing.
- **Browser Client Metrics**: Added memory (JS heap) tracking, First Contentful Paint (FCP), Time to First Byte (TTFB), DOM render times, and resource counts via Chrome native Performance API.
- **Results Logging**: Final test results are now automatically saved to timestamped text files in the `results/` directory.
- **Project Structure**: Modularized previously monolithic `main.py` into `perfjix/` Python package.
- **Metadata**: Added MIT License and Author information (Panna @ PNAX.io Lab).

### Changed
- WebRTC stat collection hook relies on CDP and executes at page load to bypass specific Jitsi `APP.` structure dependencies.

### Fixed
- Fixed `no_peer_connection` failures in modern Jitsi Meet builds by intercepting `RTCPeerConnection` construction.

## [1.0.0] - 2026-03-24
### Added
- Initial creation of PerfJix.
- Headless Selenium WebRTC stress testing capability.
- Local Docker container cpu/ram/network tracking via `docker stats`.
- Wimi AirTime (iframe) and standard Jitsi support.
- Jitter, Packet Loss, RTT, and Bitrate metric extractions.
