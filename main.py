import argparse
import time
import concurrent.futures
import uuid
import logging
import threading
import subprocess
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TestStats:
    def __init__(self):
        self.successful_joins = 0
        self.failed_joins = 0
        self.disconnects = 0
        
        self.peak_jvb_cpu = 0.0
        self.peak_jvb_ram = "0MiB"
        self.final_jvb_net = "0B"
        
        self.peak_jicofo_cpu = 0.0
        self.peak_jicofo_ram = "0MiB"
        self.final_jicofo_net = "0B"
        
        # WebRTC per-user metrics (list of dicts)
        self.webrtc_samples = []
        
        self.lock = threading.Lock()

# ---------------------------------------------------------------------------
# JavaScript injected into the browser to extract WebRTC stats from the
# active RTCPeerConnection via the standard getStats() API.
# NOTE: execute_async_script passes a callback as the last argument.
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

// Try to get the active RTCPeerConnection from Jitsi's internal API
var activePc = null;
try {
    var confs = Object.values(APP.conference._room.rtc._peerConnections || {});
    if (confs.length > 0) activePc = confs[0].peerconnection;
} catch(e) {}

// Fallback: scan window for any open RTCPeerConnection
if (!activePc) {
    try {
        var pcs = window._peerConnections || [];
        if (pcs.length > 0) activePc = pcs[0];
    } catch(e) {}
}

if (!activePc || activePc.connectionState === 'closed') {
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

def collect_webrtc_stats(driver, user_id, room_name, url_format):
    """Inject JS to collect WebRTC stats and store them in global stats."""
    try:
        if url_format == 'airtime':
            try:
                iframe = driver.find_element(By.ID, 'jitsiConferenceFrame0')
                driver.switch_to.frame(iframe)
            except Exception as ie:
                logging.warning(f"[User {user_id}]: Could not switch to iframe for stats: {ie}")
        
        # Give the async script up to 10 seconds to resolve
        driver.set_script_timeout(10)
        sample = driver.execute_async_script(WEBRTC_STATS_JS)
        
        if url_format == 'airtime':
            driver.switch_to.default_content()
        
        if sample:
            err = sample.get('_error')
            if err:
                logging.warning(f"[User {user_id}]: WebRTC JS reported: {err}")
                return
            sample['user_id'] = user_id
            with stats.lock:
                stats.webrtc_samples.append(sample)
            
            ai = sample.get('audio_in', {})
            vi = sample.get('video_in', {})
            logging.info(
                f"[User {user_id} -> Room {room_name}]: "
                f"WebRTC | "
                f"Audio in: {ai.get('bitrate_kbps',0)} kbps ({ai.get('codec','?')}) "
                f"jitter={ai.get('jitter_ms',0)}ms loss={ai.get('packets_lost',0)} | "
                f"Video in: {vi.get('bitrate_kbps',0)} kbps ({vi.get('codec','?')}) "
                f"{vi.get('resolution','?')} @{vi.get('frame_rate',0)}fps "
                f"jitter={vi.get('jitter_ms',0)}ms | "
                f"RTT: {sample.get('rtt_ms','?')}ms"
            )
        else:
            logging.warning(f"[User {user_id}]: WebRTC stats returned empty (bot may not be in call)")
    except Exception as e:
        logging.warning(f"[User {user_id}]: WebRTC stats collection error: {e}")

stats = TestStats()

def monitor_docker_stats(stop_event):
    while not stop_event.is_set():
        try:
            output = subprocess.check_output(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.NetIO}}"],
                stderr=subprocess.DEVNULL
            ).decode('utf-8')
            
            for line in output.strip().split('\n'):
                parts = line.split(',')
                if len(parts) < 4: continue
                name, cpu, mem, net = parts
                
                cpu_val = float(cpu.replace('%', '')) if '%' in cpu else 0.0
                
                with stats.lock:
                    if 'jvb' in name.lower():
                        stats.final_jvb_net = net
                        if cpu_val > stats.peak_jvb_cpu:
                            stats.peak_jvb_cpu = cpu_val
                            stats.peak_jvb_ram = mem
                            
                    elif 'jicofo' in name.lower():
                        stats.final_jicofo_net = net
                        if cpu_val > stats.peak_jicofo_cpu:
                            stats.peak_jicofo_cpu = cpu_val
                            stats.peak_jicofo_ram = mem
                            
        except Exception:
            pass
        time.sleep(3)

def join_room(url, room_name, hub_url, duration, user_id, show_browser, url_format='jitsi'):
    if url_format == 'airtime':
        room_url = f"{url}#/?room={room_name}"
    else:
        room_url = f"{url}/{room_name}#config.prejoinPageEnabled=false&userInfo.displayName=\"Bot_{user_id}\""
    
    options = webdriver.ChromeOptions()
    options.add_argument('--use-fake-ui-for-media-stream')
    options.add_argument('--use-fake-device-for-media-stream')
    options.add_argument('--disable-infobars')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--auto-select-desktop-capture-source=Entire screen')
    options.add_argument('--disable-notifications')
    
    # Auto-grant camera & microphone permissions (1 = allow)
    prefs = {
        "profile.default_content_setting_values.media_stream_mic": 1,
        "profile.default_content_setting_values.media_stream_camera": 1,
        "profile.default_content_setting_values.notifications": 1,
    }
    options.add_experimental_option("prefs", prefs)
    
    if not show_browser:
        options.add_argument('--headless=new')
        
    options.add_argument('--window-size=1280,720')
    options.add_argument('--ignore-certificate-errors')
    options.accept_insecure_certs = True
    
    driver = None
    logging.info(f"[User {user_id} -> Room {room_name}]: Attempting to join {room_url}")
    try:
        driver = webdriver.Remote(
            command_executor=hub_url,
            options=options
        )
        driver.get(room_url)
        time.sleep(5)
        
        if url_format == 'airtime':
            # === AIRTIME JOIN FLOW ===
            # Step 1: Enter username and click Start (on main page)
            try:
                logging.info(f"[User {user_id} -> Room {room_name}]: Filling username...")
                username_input = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input#join-username'))
                )
                username_input.clear()
                username_input.send_keys(f"PerfJixBot_{user_id}")
                time.sleep(1)
                
                start_btn = driver.find_element(By.CSS_SELECTOR, 'button.button-green')
                start_btn.click()
                logging.info(f"[User {user_id} -> Room {room_name}]: Clicked Start, waiting for lobby...")
                time.sleep(3)
            except Exception as e:
                logging.warning(f"[User {user_id} -> Room {room_name}]: Username/Start step failed: {e}")
            
            # Step 2: Switch into the Jitsi iframe
            try:
                logging.info(f"[User {user_id} -> Room {room_name}]: Switching to Jitsi iframe...")
                iframe = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, 'jitsiConferenceFrame0'))
                )
                driver.switch_to.frame(iframe)
                logging.info(f"[User {user_id} -> Room {room_name}]: Switched to iframe successfully.")
            except Exception as e:
                logging.warning(f"[User {user_id} -> Room {room_name}]: Could not switch to iframe: {e}")
            
            # Step 3: Click "Join meeting" button (inside iframe)
            try:
                join_btn = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[aria-label="Join meeting"]'))
                )
                join_btn.click()
                logging.info(f"[User {user_id} -> Room {room_name}]: Clicked 'Join meeting'!")
                time.sleep(3)
            except Exception:
                # Fallback: try "Join without audio" dropdown
                try:
                    logging.info(f"[User {user_id} -> Room {room_name}]: Join meeting not clickable, trying 'Join without audio'...")
                    join_no_audio = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[aria-label="Join without audio"]'))
                    )
                    join_no_audio.click()
                    time.sleep(3)
                except Exception as e2:
                    logging.warning(f"[User {user_id} -> Room {room_name}]: Could not click any join button: {e2}")
            
            # Switch back to main page context for any further interactions
            driver.switch_to.default_content()
        else:
            # === JITSI JOIN FLOW ===
            try:
                input_box = driver.find_element(By.CSS_SELECTOR, 'input[placeholder="Enter your name"]')
                input_box.send_keys(f"PerfJixBot_{user_id}")
                input_box.send_keys(Keys.RETURN)
                time.sleep(2)
            except Exception:
                pass  # Bypassed correctly via URL
            
        with stats.lock:
            stats.successful_joins += 1
            
        logging.info(f"[User {user_id} -> Room {room_name}]: Joined. Starting active WebRTC interactions...")
        
        # Test Interaction Loop: Simulate real user testing
        end_time = time.time() + duration
        while time.time() < end_time:
            time_left = end_time - time.time()
            if time_left <= 0: break
            
            # --- Disconnect Check ---
            # If the driver's current URL loses the room name context, it got kicked or disconnected.
            current_url = driver.current_url
            if room_name not in current_url and "jitsi" not in current_url.lower():
                logging.warning(f"[User {user_id} -> Room {room_name}]: CONNECTION LOST! Bot was disconnected. URL: {current_url}")
                with stats.lock:
                    stats.disconnects += 1
                break
            
            # --- Simulated Interactions ---
            try:
                # Toggle Mute Hotkey (M) repeatedly to simulate active chatter
                ActionChains(driver).send_keys('m').perform()
                time.sleep(0.5)
                ActionChains(driver).send_keys('m').perform()
                
                # Check for Chat Box and type something
                ActionChains(driver).send_keys('c').perform() # standard Jitsi hotkey to open chat
                time.sleep(1)
                
                # Look for generic Jitsi textareas
                textareas = driver.find_elements(By.CSS_SELECTOR, "textarea")
                for box in textareas:
                    if box.is_displayed():
                        box.send_keys(f"🤖 Bot {user_id} actively testing stream latency...")
                        box.send_keys(Keys.RETURN)
                        break
                        
                ActionChains(driver).send_keys('c').perform() # close chat back up
                
                logging.info(f"[User {user_id} -> Room {room_name}]: Interacted (Muted/Unmuted & Chat sent).")
                
            except Exception as loop_e:
                logging.debug(f"[User {user_id} -> Room {room_name}]: Interaction loop exception (safe to ignore) - {loop_e}")
            
            # Collect WebRTC metrics every cycle
            collect_webrtc_stats(driver, user_id, room_name, url_format)
            
            # Wait 15 seconds before next interaction
            time.sleep(max(0, min(15, end_time - time.time())))
            
        logging.info(f"[User {user_id} -> Room {room_name}]: Time is up. Disconnecting gracefully.")
    except Exception as e:
        with stats.lock:
            stats.failed_joins += 1
        logging.error(f"[User {user_id} -> Room {room_name}]: Failed to join completely - {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="PerfJix - Complete Jitsi Stress Tester")
    parser.add_argument('--url', required=True, help="Base URL of server (e.g. https://jitsi.pnax.io or https://wimi.wimi.pro/airtime/)")
    parser.add_argument('--rooms', type=int, default=1, help="Number of concurrent rooms (ignored if --room-id is set)")
    parser.add_argument('--room-id', type=str, default=None, help="Specific room ID to join (e.g. 69bc00dda81f10f2db938513a9cb5fc8)")
    parser.add_argument('--users-per-room', type=int, default=2, help="Number of users per room")
    parser.add_argument('--duration', type=int, default=60, help="Duration in seconds to stay")
    parser.add_argument('--hub-url', default="http://localhost:4444/wd/hub", help="Selenium Hub URL")
    parser.add_argument('--show-browser', action='store_true', help="Disable headless mode to visually monitor in VNC")
    parser.add_argument('--url-format', choices=['jitsi', 'airtime'], default='jitsi',
                        help="URL format: 'jitsi' = /<room> (default), 'airtime' = #/?room=<id>")
    
    args = parser.parse_args()
    
    # Determine rooms to use
    if args.room_id:
        room_names = [args.room_id]
        num_rooms = 1
    else:
        room_names = None  # Will be generated dynamically
        num_rooms = args.rooms
    
    total_users = num_rooms * args.users_per_room
    logging.info(f"🚀 Starting Deep TEST: {num_rooms} Room(s), {args.users_per_room} Users/Room, {args.duration}s")
    futures = []
    
    # Start the Docker monitoring background thread
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_docker_stats, args=(stop_event,))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    start_wall_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=total_users) as executor:
        for r in range(num_rooms):
            if room_names:
                room_name = room_names[r] if r < len(room_names) else room_names[0]
            else:
                room_name = f"PerfJixRoom_{uuid.uuid4().hex[:8]}"
            for u in range(args.users_per_room):
                futures.append(
                    executor.submit(join_room, args.url, room_name, args.hub_url, args.duration, u, args.show_browser, args.url_format)
                )
        
        concurrent.futures.wait(futures)
        
    # Stop monitoring thread
    stop_event.set()
    monitor_thread.join(timeout=3)
    elapsed_time = time.time() - start_wall_time
    
    # Analyze Final Stats
    print("\n" + "="*60)
    print(" 📊 PERFJIX DEEP TEST RESULTS & SERVER METRICS 📊 ")
    print("="*60)
    print(f"⏱️  Total Wall-Clock Runtime:   {elapsed_time:.2f} seconds")
    print(f"✅  Total Successful Joins:     {stats.successful_joins}/{total_users}")
    print(f"⚠️  Total Mid-Test Disconnects: {stats.disconnects}")
    print(f"❌  Total Hard Join Failures:   {stats.failed_joins}")
    print("-" * 60)
    print(" 🖥️  JITSI BACKEND STRAIN (DOCKER) ")
    print(f"   ➤ JVB (Videobridge) CPU:     {stats.peak_jvb_cpu:.1f}%")
    print(f"   ➤ JVB (Videobridge) RAM:     {stats.peak_jvb_ram}")
    print(f"   ➤ JVB Total Traffic In/Out:  {stats.final_jvb_net}")
    print("")
    print(f"   ➤ Jicofo (Focus Room) CPU:   {stats.peak_jicofo_cpu:.1f}%")
    print(f"   ➤ Jicofo (Focus Room) RAM:   {stats.peak_jicofo_ram}")
    print(f"   ➤ Jicofo Total Net I/O:      {stats.final_jicofo_net}")
    
    # WebRTC Metrics Summary
    if stats.webrtc_samples:
        samples = stats.webrtc_samples
        def avg(key_path):
            vals = []
            for s in samples:
                v = s
                for k in key_path:
                    v = v.get(k, None) if isinstance(v, dict) else None
                if isinstance(v, (int, float)):
                    vals.append(v)
            return round(sum(vals) / len(vals), 1) if vals else 'N/A'
        
        def first_str(key_path):
            for s in samples:
                v = s
                for k in key_path:
                    v = v.get(k, None) if isinstance(v, dict) else None
                if v: return v
            return 'N/A'
        
        print("-" * 60)
        print(" 🌐  WEBRTC NETWORK METRICS (averaged across all bots) ")
        print(f"   Audio Codec:               {first_str(['audio_in','codec'])}")
        print(f"   Video Codec:               {first_str(['video_in','codec'])}")
        print(f"   Video Resolution:          {first_str(['video_in','resolution'])}")
        print("")
        print(f"   ➤ Audio IN  bitrate:        {avg(['audio_in','bitrate_kbps'])} kbps")
        print(f"   ➤ Audio IN  jitter:         {avg(['audio_in','jitter_ms'])} ms")
        print(f"   ➤ Audio IN  packet loss:    {avg(['audio_in','packets_lost'])} pkts")
        print(f"   ➤ Audio OUT bitrate:        {avg(['audio_out','bitrate_kbps'])} kbps")
        print("")
        print(f"   ➤ Video IN  bitrate:        {avg(['video_in','bitrate_kbps'])} kbps")
        print(f"   ➤ Video IN  framerate:      {avg(['video_in','frame_rate'])} fps")
        print(f"   ➤ Video IN  jitter:         {avg(['video_in','jitter_ms'])} ms")
        print(f"   ➤ Video IN  packet loss:    {avg(['video_in','packets_lost'])} pkts")
        print(f"   ➤ Video OUT bitrate:        {avg(['video_out','bitrate_kbps'])} kbps")
        print(f"   ➤ Video OUT framerate:      {avg(['video_out','frame_rate'])} fps")
        print("")
        print(f"   ➤ Round-Trip Time (RTT):    {avg(['rtt_ms'])} ms")
        print(f"   Total WebRTC samples:      {len(samples)}")
    
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
