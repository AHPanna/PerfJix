"""
JitsiBot – one simulated meeting participant using Selenium.

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT
"""
import logging
import random
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .webrtc import WebRTCCollector
from .browser_metrics import BrowserMetricsCollector

# Pool of messages bots will pick from randomly
BOT_MESSAGES = [
    "👋 Hello everyone!",
    "🤖 Bot checking in — stream ok?",
    "🔥 Stress test running…",
    "📶 Network feels good!",
    "🎉 Anyone else here?",
    "💬 Testing audio latency…",
    "🚀 Jitsi perf test in progress",
    "👍 Video quality looks fine",
    "⚡ Measuring RTT right now",
    "😅 So many bots in here lol",
    "🎤 Can you hear me?",
    "📊 Collecting metrics…",
    "🌐 Ping pong!",
    "🤙 Load test!",
    "❓ Any packet loss?",
]


class JitsiBot:
    """
    Simulates a single meeting participant for stress-testing.

    Parameters
    ----------
    stats      : TestStats   – shared stats container
    hub_url    : str         – Selenium RemoteWebDriver endpoint
    show_browser : bool      – if True, runs in non-headless mode (VNC)
    url_format : str         – 'jitsi' or 'airtime'
    """

    def __init__(self, stats, hub_url: str, show_browser: bool = False, url_format: str = "jitsi"):
        self._stats = stats
        self._hub_url = hub_url
        self._show_browser = show_browser
        self._url_format = url_format
        self._collector = WebRTCCollector(stats)
        self._browser = BrowserMetricsCollector(stats)

    # ------------------------------------------------------------------
    # Public entry point (called from ThreadPoolExecutor)
    # ------------------------------------------------------------------

    def run(self, base_url: str, room_name: str, duration: int, user_id: int) -> None:
        """Join *room_name* and stay for *duration* seconds, collecting metrics."""
        room_url = self._build_room_url(base_url, room_name, user_id)
        logging.info(f"[User {user_id} -> Room {room_name}]: Attempting to join {room_url}")

        driver = None
        try:
            driver = webdriver.Remote(
                command_executor=self._hub_url,
                options=self._build_options(),
            )

            driver.get(room_url)
            time.sleep(2)  # brief wait for initial page render

            # ── RTCPeerConnection interceptor ──────────────────────────────
            # Injected AFTER page load but BEFORE the join click.
            # Jitsi only creates PeerConnections after the user joins, so this
            # timing is sufficient. Works on webdriver.Remote (no CDP needed).
            self._inject_rtc_hook(driver, user_id)

            if self._url_format == "airtime":
                self._join_airtime(driver, user_id, room_name)
            else:
                self._join_jitsi(driver, user_id)

            with self._stats.lock:
                self._stats.successful_joins += 1

            logging.info(f"[User {user_id} -> Room {room_name}]: Joined. Starting active interactions …")
            self._interaction_loop(driver, room_name, duration, user_id)
            logging.info(f"[User {user_id} -> Room {room_name}]: Time is up. Disconnecting gracefully.")

        except Exception as e:
            with self._stats.lock:
                self._stats.failed_joins += 1
            logging.error(f"[User {user_id} -> Room {room_name}]: Failed to join – {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # URL builder
    # ------------------------------------------------------------------

    def _build_room_url(self, base_url: str, room_name: str, user_id: int) -> str:
        if self._url_format == "airtime":
            return f"{base_url}#/?room={room_name}"
        return (
            f"{base_url}/{room_name}"
            f"#config.prejoinPageEnabled=false"
            f'&userInfo.displayName="Bot_{user_id}"'
        )

    # ------------------------------------------------------------------
    # Chrome options
    # ------------------------------------------------------------------

    def _build_options(self) -> webdriver.ChromeOptions:
        options = webdriver.ChromeOptions()
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--use-fake-device-for-media-stream")
        options.add_argument("--disable-infobars")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--auto-select-desktop-capture-source=Entire screen")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,720")
        options.add_argument("--ignore-certificate-errors")
        options.accept_insecure_certs = True
        options.add_experimental_option(
            "prefs",
            {
                "profile.default_content_setting_values.media_stream_mic": 1,
                "profile.default_content_setting_values.media_stream_camera": 1,
                "profile.default_content_setting_values.notifications": 1,
            },
        )
        if not self._show_browser:
            options.add_argument("--headless=new")
        return options

    # ------------------------------------------------------------------
    # Platform-specific join flows
    # ------------------------------------------------------------------

    def _join_jitsi(self, driver, user_id: int) -> None:
        """Standard Jitsi Meet join flow."""
        try:
            input_box = driver.find_element(By.CSS_SELECTOR, 'input[placeholder="Enter your name"]')
            input_box.send_keys(f"PerfJixBot_{user_id}")
            input_box.send_keys(Keys.RETURN)
            time.sleep(2)
        except Exception:
            pass  # Bypassed correctly via URL params

    def _join_airtime(self, driver, user_id: int, room_name: str) -> None:
        """Wimi AirTime join flow (iframe-embedded Jitsi).

        Flow
        ----
        1. Wait for SPA loading overlay to disappear.
        2. Fill username + click Start (skip silently if form not found —
           means a meeting is already active for this room).
        3. Wait up to 20 s for the Jitsi iframe src to be populated.
        4. If src is still empty → the SPA JS is stuck.
           Do a hard cache-busting reload and repeat steps 1-3 with a
           longer 30 s timeout.  (User's diagnosis: page needs a refresh.)
        5. Switch into the iframe (3 quick retries, name then index-0).
        6. Click "Join meeting" or "Join without audio".
        7. Raises RuntimeError if we never entered the iframe, so the
           caller correctly counts this as a failed join.
        """
        START_SELECTORS = [
            "button.button-green",
            "button[type='submit']",
            "button.btn-primary",
            "button.join-button",
            "input[type='submit']",
        ]
        USERNAME_COMPOUND = (
            "input#join-username, "
            "input[name='username'], "
            "input[placeholder*='name' i], "
            "input[placeholder*='pseudo' i]"
        )

        # ------------------------------------------------------------------
        # Helpers (closures so they share locals)
        # ------------------------------------------------------------------

        def wait_for_spa():
            """Wait for #main-load overlay to vanish (SPA boot)."""
            try:
                WebDriverWait(driver, 40).until(
                    EC.invisibility_of_element_located((By.ID, "main-load"))
                )
                logging.info(f"[User {user_id} -> Room {room_name}]: SPA ready.")
            except Exception:
                logging.debug(f"[User {user_id}]: No #main-load overlay, continuing.")

        def do_login():
            """Fill username + click Start.  Silent if form is absent."""
            try:
                inp = WebDriverWait(driver, 12).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, USERNAME_COMPOUND))
                )
                fid = inp.get_attribute("id") or inp.get_attribute("name") or "?"
                logging.info(f"[User {user_id}]: Username field found (id='{fid}')")
                inp.clear()
                inp.send_keys(f"PerfJixBot_{user_id}")
                time.sleep(0.4)
                for sel in START_SELECTORS:
                    try:
                        btn = driver.find_element(By.CSS_SELECTOR, sel)
                        if btn.is_displayed():
                            btn.click()
                            logging.info(
                                f"[User {user_id} -> Room {room_name}]: "
                                f"Clicked Start via '{sel}', waiting for lobby …"
                            )
                            time.sleep(3)
                            return
                    except Exception:
                        continue
                raise RuntimeError("Start button not found")
            except Exception as e:
                # Form is likely absent because the meeting is already active;
                # the iframe may load directly without the login step.
                logging.info(
                    f"[User {user_id}]: Login form not found or unusable ({e}). "
                    f"Meeting may already be running — proceeding to iframe."
                )

        def wait_iframe_src(timeout: int) -> bool:
            """Return True when jitsiConferenceFrame0.src is non-empty."""
            try:
                # Presence first (fast)
                WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.ID, "jitsiConferenceFrame0"))
                )
                # Then src populated
                WebDriverWait(driver, timeout).until(lambda d: (
                    d.find_element(By.ID, "jitsiConferenceFrame0").get_attribute("src") or ""
                ).strip() != "")
                src = driver.find_element(By.ID, "jitsiConferenceFrame0").get_attribute("src")
                logging.info(f"[User {user_id}]: iframe src ready → {src}")
                return True
            except Exception:
                return False

        # ------------------------------------------------------------------
        # Pass 1: Normal attempt
        # ------------------------------------------------------------------
        logging.info(f"[User {user_id} -> Room {room_name}]: AirTime join — pass 1")
        wait_for_spa()
        do_login()

        if not wait_iframe_src(timeout=20):
            # ------------------------------------------------------------------
            # Pass 2: Hard cache-busting reload and retry
            # The SPA JS can get stuck after a concurrent Start click by another
            # user.  A hard reload forces it to re-fetch room credentials and
            # repopulate the iframe src.
            # ------------------------------------------------------------------
            logging.warning(
                f"[User {user_id} -> Room {room_name}]: "
                f"iframe src not populated — doing hard reload (pass 2) …"
            )
            driver.execute_script("location.reload(true)")
            time.sleep(3)
            wait_for_spa()
            do_login()

            if not wait_iframe_src(timeout=30):
                raise RuntimeError(
                    "iframe src never populated even after hard reload — "
                    "giving up so the join is counted as failed."
                )

        # ------------------------------------------------------------------
        # Switch into the iframe — 3 quick attempts
        # ------------------------------------------------------------------
        time.sleep(1)  # let Chrome spin up the frame renderer
        switched = False
        for attempt in range(3):
            try:
                try:
                    driver.switch_to.frame("jitsiConferenceFrame0")
                except Exception:
                    driver.switch_to.frame(0)
                self._inject_rtc_hook(driver, user_id)
                logging.info(
                    f"[User {user_id} -> Room {room_name}]: "
                    f"Switched to iframe (attempt {attempt + 1})."
                )
                switched = True
                break
            except Exception as e:
                logging.warning(
                    f"[User {user_id}]: iframe switch attempt {attempt + 1}/3 "
                    f"failed – {type(e).__name__}. Retrying in 2 s …"
                )
                driver.switch_to.default_content()
                time.sleep(2)

        if not switched:
            raise RuntimeError("Could not switch into Jitsi iframe after 3 attempts.")

        # ------------------------------------------------------------------
        # Click "Join meeting" (inside iframe)
        # ------------------------------------------------------------------
        try:
            WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[aria-label="Join meeting"]'))
            ).click()
            logging.info(f"[User {user_id} -> Room {room_name}]: Clicked 'Join meeting'!")
            time.sleep(3)
        except Exception:
            try:
                logging.info(f"[User {user_id} -> Room {room_name}]: Trying 'Join without audio' …")
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, 'div[aria-label="Join without audio"]')
                    )
                ).click()
                time.sleep(3)
            except Exception as e2:
                logging.warning(
                    f"[User {user_id} -> Room {room_name}]: "
                    f"Could not click any join button: {e2}"
                )

        driver.switch_to.default_content()

    # ------------------------------------------------------------------
    # RTCPeerConnection hook injection (execute_script, no CDP required)
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_rtc_hook(driver, user_id: int) -> None:
        """Monkey-patch RTCPeerConnection so every instance is captured."""
        try:
            driver.execute_script("""
                if (window.__pjHooked) return;
                window.__pjHooked = true;
                window.__pjPCs = [];
                var _Orig = window.RTCPeerConnection;
                if (!_Orig) return;
                window.RTCPeerConnection = function() {
                    var pc = new _Orig(...arguments);
                    window.__pjPCs.push(pc);
                    return pc;
                };
                window.RTCPeerConnection.prototype = _Orig.prototype;
            """)
            logging.info(f"[User {user_id}]: RTCPeerConnection hook installed.")
        except Exception as e:
            logging.warning(f"[User {user_id}]: RTCPeerConnection hook failed: {e}")

    # ------------------------------------------------------------------
    # Main interaction + metrics loop
    # ------------------------------------------------------------------

    def _interaction_loop(self, driver, room_name: str, duration: int, user_id: int) -> None:
        end_time = time.time() + duration

        while time.time() < end_time:
            # ── Disconnect check ───────────────────────────────────────
            current_url = driver.current_url
            if room_name not in current_url and "jitsi" not in current_url.lower():
                logging.warning(
                    f"[User {user_id} -> Room {room_name}]: CONNECTION LOST! URL: {current_url}"
                )
                with self._stats.lock:
                    self._stats.disconnects += 1
                break

            # ── Simulated interactions ────────────────────────────────
            try:
                # Toggle mute via toolbar button (more reliable than hotkey)
                for sel in [
                    'button[aria-label="Mute microphone"]',
                    'button[aria-label="Unmute microphone"]',
                    'button[aria-label="Toggle mute"]',
                ]:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                    if btns:
                        btns[0].click()
                        time.sleep(0.3)
                        btns[0].click()  # restore state
                        break

                # Open chat panel via toolbar button
                chat_opened = False
                for sel in [
                    'button[aria-label="Open chat"]',
                    'button[aria-label="Chat"]',
                    'button[data-testid="toolbar.chat"]',
                ]:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                    if btns:
                        btns[0].click()
                        chat_opened = True
                        time.sleep(1)
                        break

                # ── Open chat ──────────────────────────────────────────
                chat_opened = False

                # Try CSS selectors first
                for sel in [
                    'button[aria-label="Open chat"]',
                    'button[aria-label="Chat"]',
                    'button[data-testid="toolbar.chat"]',
                ]:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                    if btns and btns[0].is_displayed():
                        btns[0].click()
                        chat_opened = True
                        time.sleep(0.8)
                        break

                # JS fallback: click the 4th toolbar button (chat icon position)
                if not chat_opened:
                    try:
                        driver.execute_script("""
                            var btns = document.querySelectorAll(
                                'div[data-testid="toolbox.toolbar"] button, ' +
                                '#new-toolbox button'
                            );
                            for (var i = 0; i < btns.length; i++) {
                                var l = (btns[i].getAttribute('aria-label') || '').toLowerCase();
                                if (l.includes('chat')) { btns[i].click(); break; }
                            }
                        """)
                        chat_opened = True
                        time.sleep(0.8)
                    except Exception:
                        pass

                if chat_opened:
                    msg = random.choice(BOT_MESSAGES)
                    # does not work fix in future.
                    # ── Type into Slate.js editor (Paste Event) ────────
                    # Slate.js ignores execCommand and send_keys. The most
                    # reliable way to inject text is a synthetic paste event.
                    sent = driver.execute_script("""
                        var msg = arguments[0];
                        var selectors = [
                            'div[data-slate-editor="true"]',
                            'p[data-slate-node="element"]',
                            'div[contenteditable="true"]',
                            'div[role="textbox"]',
                            'textarea[placeholder="Type a message"]',
                        ];
                        for (var s of selectors) {
                            var el = document.querySelector(s);
                            if (el && el.offsetParent !== null) {
                                el.focus();
                                
                                // Create synthetic paste event with DataTransfer
                                var pasteEvent = new ClipboardEvent('paste', {
                                    bubbles: true,
                                    cancelable: true,
                                    clipboardData: new DataTransfer()
                                });
                                pasteEvent.clipboardData.setData('text/plain', msg);
                                el.dispatchEvent(pasteEvent);
                                
                                return true;
                            }
                        }
                        return false;
                    """, msg)

                    if sent:
                        # Press Enter to submit
                        ActionChains(driver).send_keys(Keys.RETURN).perform()
                        time.sleep(0.3)
                        logging.info(
                            f"[User {user_id} -> Room {room_name}]: "
                            f"Chat sent: {msg}"
                        )
                    else:
                        logging.debug(
                            f"[User {user_id} -> Room {room_name}]: "
                            f"Chat input not found (chat panel may not be open)."
                        )

                    # ── Close chat ─────────────────────────────────────
                    for sel in [
                        'button[aria-label="Close chat"]',
                        'button[aria-label="Open chat"]',
                        'button[aria-label="Chat"]',
                    ]:
                        btns = driver.find_elements(By.CSS_SELECTOR, sel)
                        if btns and btns[0].is_displayed():
                            btns[0].click()
                            break


            except Exception as loop_e:
                logging.debug(
                    f"[User {user_id} -> Room {room_name}]: Interaction loop exception – {loop_e}"
                )

            # ── Collect WebRTC + browser metrics ─────────────────────
            self._collector.collect(driver, user_id, room_name, self._url_format)
            self._browser.collect(driver, user_id)

            time.sleep(max(0, min(15, end_time - time.time())))
