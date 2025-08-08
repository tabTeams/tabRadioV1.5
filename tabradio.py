# globalPlugins/tabradio/globalPlugin.py
# ปรับปรุง: เก็บสถานะ (resume) หลังปิด addon และปรับปรุงการเพิ่ม/ลดเสียง
# ปรับแม็ปปิ้ง: NVDA+Shift+F3 = ลดเสียง, NVDA+Shift+F4 = เพิ่มเสียง
# และเลือกเปิด วิทยุ/ทีวี ด้วย NVDA+Shift+F1, NVDA+Shift+F2
import os
import json
import subprocess
import signal
import shutil
import atexit
import time

import globalPluginHandler
import ui
from scriptHandler import script

ADDON_PATH = os.path.dirname(__file__)
STATE_FILE = os.path.join(ADDON_PATH, "state.json")

player_process = None
current_channel_list = {}
channel_keys = []
current_index = 0
volume = 100
current_channel_name = ""
player = "ffplay"  # default

# ตรวจสอบ media player ที่มีในระบบ: vlc ก่อน ถ้าไม่มีใช้ ffplay
if shutil.which("vlc"):
    player = "vlc"
elif shutil.which("ffplay"):
    player = "ffplay"

def load_channels(file_name):
    fn = os.path.join(ADDON_PATH, file_name)
    try:
        with open(fn, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# โหลดรายการช่อง
radio_channels = load_channels("channels_radio.json")
tv_channels = load_channels("channels_tv.json")

def _load_state():
    global volume, current_channel_name, current_index, current_channel_list, channel_keys
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
            if isinstance(s.get("volume"), int):
                volume = max(0, min(100, s.get("volume")))
            last_key = s.get("current_channel_key")
            last_type = s.get("channel_type")
            if last_type == "tv":
                current_channel_list = tv_channels or {}
            else:
                current_channel_list = radio_channels or {}
            channel_keys.clear()
            channel_keys.extend(sorted(current_channel_list.keys()))
            if last_key and last_key in current_channel_list:
                try:
                    current_index = channel_keys.index(last_key)
                except Exception:
                    current_index = 0
            else:
                current_index = 0
    except Exception:
        pass

def _save_state(is_running=False, channel_type="radio"):
    try:
        current_key = None
        if 0 <= current_index < len(channel_keys):
            current_key = channel_keys[current_index]
        state = {
            "current_channel_key": current_key,
            "volume": int(max(0, min(100, volume))),
            "channel_type": channel_type,
            "is_running": bool(is_running)
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

_load_state()

def _vlc_args_for_url(url, vol):
    try:
        gain = float(vol) / 10.0
        if gain < 0.0:
            gain = 0.0
    except Exception:
        gain = 1.0
    return ["vlc", "--intf", "dummy", "--no-video", f"--gain={gain}", url]

def _ffplay_args_for_url(url, vol):
    return ["ffplay", "-nodisp", "-autoexit", "-volume", str(int(vol)), url]

def play_stream(url):
    global player_process, volume
    stop_stream()
    if not player:
        ui.message("TABRadio: ไม่มีโปรแกรมเล่น (vlc/ffplay) ในระบบ")
        return
    args = _vlc_args_for_url(url, volume) if player == "vlc" else _ffplay_args_for_url(url, volume)
    popen_kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == 'nt':
        try:
            popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        except Exception:
            pass
    else:
        popen_kwargs['start_new_session'] = True
    try:
        player_process = subprocess.Popen(args, **popen_kwargs)
        time.sleep(0.05)
    except Exception as e:
        player_process = None
        ui.message(f"TABRadio: เริ่มตัวเล่นล้มเหลว ({e})")

def stop_stream():
    global player_process
    if not player_process:
        return
    try:
        if os.name != 'nt':
            try:
                os.killpg(os.getpgid(player_process.pid), signal.SIGTERM)
            except Exception:
                player_process.terminate()
        else:
            player_process.terminate()
        player_process.wait(timeout=3)
    except Exception:
        try:
            player_process.kill()
        except Exception:
            pass
    finally:
        player_process = None

def _on_exit():
    try:
        stop_stream()
    finally:
        _save_state(is_running=False, channel_type="radio")

atexit.register(_on_exit)

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self.channel_type = "radio"
        self._is_running = False
        _load_state()
        stop_stream()

    def terminate(self):
        try:
            stop_stream()
        except Exception:
            pass
        try:
            _save_state(is_running=False, channel_type=self.channel_type)
        except Exception:
            pass
        try:
            super().terminate()
        except Exception:
            pass

    def _ensure_channel_list(self):
        global current_channel_list, channel_keys
        current_channel_list = tv_channels if self.channel_type == "tv" else radio_channels
        channel_keys.clear()
        channel_keys.extend(sorted(current_channel_list.keys()))

    def activate_radio(self):
        global current_index
        self.channel_type = "radio"
        self._ensure_channel_list()
        if not channel_keys:
            ui.message("TABRadio: ไม่มีช่องวิทยุ")
            return
        if not (0 <= current_index < len(channel_keys)):
            current_index = 0
        self.play_current()
        self._is_running = True
        _save_state(is_running=True, channel_type="radio")

    def activate_tv(self):
        global current_index
        self.channel_type = "tv"
        self._ensure_channel_list()
        if not channel_keys:
            ui.message("TABRadio: ไม่มีช่องทีวี")
            return
        if not (0 <= current_index < len(channel_keys)):
            current_index = 0
        self.play_current()
        self._is_running = True
        _save_state(is_running=True, channel_type="tv")

    def play_current(self):
        global current_index, current_channel_name
        if not channel_keys:
            ui.message("TABRadio: ยังไม่มีช่องให้เล่น")
            return
        if not (0 <= current_index < len(channel_keys)):
            ui.message("TABRadio: ดัชนีช่องไม่ถูกต้อง")
            return
        key = channel_keys[current_index]
        url = current_channel_list.get(key)
        if not url:
            ui.message(f"TABRadio: ไม่พบ URL สำหรับช่อง {key}")
            return
        current_channel_name = key
        play_stream(url)
        ui.message(f"กำลังเล่น: {key}")
        _save_state(is_running=True, channel_type=self.channel_type)

    @script(description="เปิดหรือปิด Addon")
    def script_toggleAddon(self, gesture):
        if self._is_running:
            stop_stream()
            self._is_running = False
            _save_state(is_running=False, channel_type=self.channel_type)
            ui.message("ปิด TABRadio แล้ว (สถานะถูกบันทึกแล้ว)")
        else:
            _load_state()
            try:
                if os.path.exists(STATE_FILE):
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        s = json.load(f)
                    stype = s.get("channel_type", "radio")
                else:
                    stype = "radio"
            except Exception:
                stype = "radio"
            if stype == "tv":
                self.activate_tv()
            else:
                self.activate_radio()

    @script(description="เปิดฟังวิทยุ")
    def script_radio(self, gesture):
        self.activate_radio()

    @script(description="ฟังทีวี")
    def script_tv(self, gesture):
        self.activate_tv()

    @script(description="ประกาศสิ่งที่กำลังฟัง")
    def script_announce(self, gesture):
        if self._is_running:
            ui.message(f"กำลังฟัง: {current_channel_name}")
        else:
            ui.message("ยังไม่ได้เล่นวิทยุหรือทีวี")

    @script(description="เพิ่มเสียง")
    def script_volumeUp(self, gesture):
        global volume
        if volume < 100:
            volume = min(100, volume + 10)
            ui.message(f"ระดับเสียง: {volume}%")
            if self._is_running:
                self.play_current()
            _save_state(is_running=self._is_running, channel_type=self.channel_type)
        else:
            ui.message("เสียงดังสุดแล้ว")

    @script(description="ลดเสียง")
    def script_volumeDown(self, gesture):
        global volume
        if volume > 0:
            volume = max(0, volume - 10)
            ui.message(f"ระดับเสียง: {volume}%")
            if self._is_running:
                self.play_current()
            _save_state(is_running=self._is_running, channel_type=self.channel_type)
        else:
            ui.message("เสียงเบาที่สุดแล้ว")

    @script(description="ช่องถัดไป")
    def script_nextChannel(self, gesture):
        global current_index
        if self._is_running and channel_keys:
            current_index = (current_index + 1) % len(channel_keys)
            self.play_current()
            _save_state(is_running=True, channel_type=self.channel_type)
        else:
            ui.message("ยังไม่ได้เล่นวิทยุหรือทีวี")

    @script(description="ช่องก่อนหน้า")
    def script_previousChannel(self, gesture):
        global current_index
        if self._is_running and channel_keys:
            current_index = (current_index - 1) % len(channel_keys)
            self.play_current()
            _save_state(is_running=True, channel_type=self.channel_type)
        else:
            ui.message("ยังไม่ได้เล่นวิทยุหรือทีวี")

    __gestures = {
        "kb:NVDA+shift+space": "toggleAddon",
        "kb:NVDA+alt+space": "announce",
        "kb:NVDA+shift+f4": "volumeUp",
        "kb:NVDA+shift+f3": "volumeDown",
        "kb:NVDA+shift+f1": "radio",       # ใหม่: ฟังวิทยุ
        "kb:NVDA+shift+f2": "tv",          # ใหม่: ฟังทีวี
        "kb:NVDA+shift+rightArrow": "nextChannel",
        "kb:NVDA+shift+leftArrow": "previousChannel"
    }
