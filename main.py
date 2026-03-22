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
        
        self.lock = threading.Lock()

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

def join_room(url, room_name, hub_url, duration, user_id, show_browser):
    room_url = f"{url}/{room_name}#config.prejoinPageEnabled=false&userInfo.displayName=\"Bot_{user_id}\""
    
    options = webdriver.ChromeOptions()
    options.add_argument('--use-fake-ui-for-media-stream')
    options.add_argument('--use-fake-device-for-media-stream')
    options.add_argument('--disable-infobars')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
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
        
        # Fallback prejoin screen bypass
        try:
            input_box = driver.find_element(By.CSS_SELECTOR, 'input[placeholder="Enter your name"]')
            input_box.send_keys(f"PerfJixBot_{user_id}")
            input_box.send_keys(Keys.RETURN)
            time.sleep(2)
        except Exception:
            pass # Bypassed correctly via URL
            
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
    parser.add_argument('--url', required=True, help="Base URL of Jitsi server")
    parser.add_argument('--rooms', type=int, default=1, help="Number of concurrent rooms")
    parser.add_argument('--users-per-room', type=int, default=2, help="Number of users per room")
    parser.add_argument('--duration', type=int, default=60, help="Duration in seconds to stay")
    parser.add_argument('--hub-url', default="http://localhost:4444/wd/hub", help="Selenium Hub URL")
    parser.add_argument('--show-browser', action='store_true', help="Disable headless mode to visually monitor in VNC")
    
    args = parser.parse_args()
    
    logging.info(f"🚀 Starting Deep TEST: {args.rooms} Rooms, {args.users_per_room} Users/Room, {args.duration}s")
    total_users = args.rooms * args.users_per_room
    futures = []
    
    # Start the Docker monitoring background thread
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_docker_stats, args=(stop_event,))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    start_wall_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=total_users) as executor:
        for r in range(args.rooms):
            room_name = f"PerfJixRoom_{uuid.uuid4().hex[:8]}"
            for u in range(args.users_per_room):
                futures.append(
                    executor.submit(join_room, args.url, room_name, args.hub_url, args.duration, u, args.show_browser)
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
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
