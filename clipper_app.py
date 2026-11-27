"""Clip Ça: a replay-buffer clipper for Windows and Linux (X11, made for Linux Mint XFCE), built on OBS Studio.

OBS keeps the last N seconds in memory (its own "Clipper" profile, so other OBS setups stay untouched); this app sets
it up for the PC it runs on, keeps the replay buffer on, and saves a clip on a hotkey or when you say "clip ça" /
"clip that". Settings window + tray icon; runs at login with --background."""
import ctypes, glob, json, os, queue, re, shutil, socket, subprocess, sys, threading, time, uuid
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

WIN = sys.platform == 'win32'
if WIN:
    import ctypes.wintypes, winreg, winsound

APP, VERSION = 'Clip Ça', '1.0.3'
BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
CONFIG_HOME = os.environ['APPDATA'] if WIN else os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
DATA = os.path.join(CONFIG_HOME, 'ClipCa')
SETTINGS = os.path.join(DATA, 'settings.json')
LOG = os.path.join(DATA, 'clipper.log')
OBS_CFG = os.path.join(CONFIG_HOME, 'obs-studio')
WS_CFG = os.path.join(OBS_CFG, 'plugin_config', 'obs-websocket', 'config.json')
PROFILE_INI = os.path.join(OBS_CFG, 'basic', 'profiles', 'Clipper', 'basic.ini')
COLLECTION = os.path.join(OBS_CFG, 'basic', 'scenes', 'Clipper.json')
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
AUTOSTART = os.path.join(CONFIG_HOME, 'autostart', 'clipca.desktop')  # Linux login item
PORT = 47811  # single instance: a second launch asks the first to show its window
NOWIN = subprocess.CREATE_NO_WINDOW if WIN else 0
# Background ffmpeg: idle priority on Windows, nice 19 on Linux, so the game comes first
LOW_PRIORITY = {'creationflags': NOWIN | subprocess.IDLE_PRIORITY_CLASS} if WIN else {'preexec_fn': lambda: os.nice(19)}
CHIME_OK = r'C:\Windows\Media\Windows Notify System Generic.wav' if WIN else \
    '/usr/share/sounds/freedesktop/stereo/complete.oga'
CHIME_FAIL = r'C:\Windows\Media\Windows Critical Stop.wav' if WIN else \
    '/usr/share/sounds/freedesktop/stereo/dialog-error.oga'
# OBS sources: screen and audio capture have different plugins per OS (Linux: X11 screen + PulseAudio/PipeWire)
SCREEN_SRC, SCREEN_PROP = ('monitor_capture', 'monitor_id') if WIN else ('xshm_input', 'screen')
DESK_SRC, MIC_SRC = ('wasapi_output_capture', 'wasapi_input_capture') if WIN else \
    ('pulse_output_capture', 'pulse_input_capture')
PHRASES = {'voice_fr': ('vosk-model-small-fr-0.22', 'clip ça'), 'voice_en': ('vosk-model-small-en-us-0.15', 'clip that')}
QUALITY = {'High': 'Small', 'Very high': 'HQ'}  # OBS simple-mode names
RESOLUTIONS = ['Native', '1440p', '1080p', '900p', '720p', '480p']
FPS_CHOICES = [30, 60, 120, 144]
# Mic effects, in the order OBS runs them. Boost is driven by the mic level slider.
FX = [('fx_noise', 'JC Noise suppression', 'noise_suppress_filter_v2', {'method': 'rnnoise', 'suppress_level': -30}),
      ('fx_gate', 'JC Noise gate', 'noise_gate_filter', {}),
      (None, 'JC Boost', 'gain_filter', {'db': 0.0}),
      ('fx_comp', 'JC Compressor', 'compressor_filter', {}),
      ('fx_limit', 'JC Limiter', 'limiter_filter', {'threshold': -3.0})]


def videos_dir():
    try:
        if WIN:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders') as k:
                return winreg.QueryValueEx(k, 'My Video')[0]
        out = subprocess.run(['xdg-user-dir', 'VIDEOS'], capture_output=True, text=True).stdout.strip()
        if out and out != os.path.expanduser('~'):  # xdg-user-dir answers $HOME when the folder isn't set
            return out
    except OSError:
        pass
    return os.path.join(os.path.expanduser('~'), 'Videos')


def play(sound):
    if WIN:
        winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC)
    elif os.path.exists(sound) and shutil.which('paplay'):
        subprocess.Popen(['paplay', sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_path(path):
    os.startfile(path) if WIN else subprocess.Popen(['xdg-open', path])


DEFAULTS = {'clip_seconds': 60, 'folder': os.path.join(videos_dir(), 'Clips'),
            'hotkey': 'Alt+F10' if WIN else 'Ctrl+Alt+C',  # Alt+F10 maximizes windows in XFCE
            'voice_fr': True, 'voice_en': True, 'chime': True, 'popup': True, 'screen': '', 'resolution': 'Native', 'fps': 60,
            'quality': 'High', 'encoder': '', 'desktop_device': 'default', 'desktop_db': 0.0,
            'mic_device': 'default', 'mic_db': 0.0, 'fx_noise': True, 'fx_gate': False, 'fx_comp': False,
            'fx_limit': True, 'compress_clips': True}


def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}\n')
    except OSError:
        pass


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.load(open(SETTINGS, encoding='utf-8')))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SETTINGS)


# ---------- compression ----------
COMPRESS_LOCK = threading.Lock()  # one clip at a time, so a burst of clips never floods the CPU


def ffmpeg_dir():
    found = shutil.which('ffmpeg') or next(iter(glob.glob(os.path.join(
        os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Packages', 'Gyan.FFmpeg*', '*', 'bin',
        'ffmpeg.exe'))), None)
    return os.path.dirname(found) if found else None


def duration(bin_dir, path):
    out = subprocess.run([os.path.join(bin_dir, 'ffprobe'), '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'csv=p=0', path], capture_output=True, text=True, creationflags=NOWIN)
    return float(out.stdout.strip() or 0)


def compress_clip(path):
    """Re-encodes a saved clip to about a third of its size with no visible loss (x264 CRF 20, VMAF ~98).
    The original is only replaced once the new file is complete, smaller and as long."""
    bin_dir = ffmpeg_dir()
    if not bin_dir:
        log('compress skipped: ffmpeg not found (' + ('winget install Gyan.FFmpeg' if WIN else 'sudo apt install ffmpeg') + ')')
        return
    tmp = path + '.part'  # not .mp4, so the clip list and the Discord button never pick up a half-written file
    with COMPRESS_LOCK:
        try:
            r = subprocess.run([os.path.join(bin_dir, 'ffmpeg'), '-v', 'error', '-y', '-i', path, '-map', '0',
                                '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-c:a', 'copy',
                                '-movflags', '+faststart', '-f', 'mp4', tmp], capture_output=True, text=True,
                               **LOW_PRIORITY)
            if r.returncode:
                raise RuntimeError(r.stderr.strip()[-300:])
            old, new = os.path.getsize(path), os.path.getsize(tmp)
            if new >= old:
                log(f'compress: kept original, already small ({old // 1_000_000} MB)')
                return
            if abs(duration(bin_dir, tmp) - duration(bin_dir, path)) > 1:
                raise RuntimeError('compressed clip has the wrong length')
            st = os.stat(path)
            os.utime(tmp, (st.st_atime, st.st_mtime))  # keep the clip's date so lists stay in order
            for attempt in range(10):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:  # clip open in a player for a moment
                    if attempt == 9:
                        raise
                    time.sleep(1)
            log(f'compressed {os.path.basename(path)}: {old // 1_000_000} MB -> {new // 1_000_000} MB')
        except Exception as e:
            log(f'compress failed, original kept: {e!r}')
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


# ---------- hotkey ----------
MODS = {'Ctrl': 2, 'Alt': 1, 'Shift': 4}
NAMED_VK = {'Pause': 0x13, 'Insert': 0x2D, 'Delete': 0x2E, 'Home': 0x24, 'End': 0x23, 'PageUp': 0x21,
            'PageDown': 0x22, 'ScrollLock': 0x91, 'PrintScreen': 0x2C, 'Space': 0x20}
VK_NAMES = {**{0x70 + i: f'F{i + 1}' for i in range(24)}, **{vk: name for name, vk in NAMED_VK.items()},
            **{vk: chr(vk) for vk in [*range(0x30, 0x3A), *range(0x41, 0x5B)]}}
MOD_VKS = (('Ctrl', 0x11), ('Alt', 0x12), ('Shift', 0x10))


def parse_hotkey(text):
    """'Alt+F10' -> (modifier flags, virtual key), or None if it isn't a key combo we can register."""
    *mods, key = text.split('+')
    flags = 0
    for m in mods:
        if m not in MODS:
            return None
        flags |= MODS[m]
    if re.fullmatch(r'F([1-9]|1\d|2[0-4])', key):
        return flags, 0x6F + int(key[1:])
    if re.fullmatch(r'[A-Z0-9]', key):
        return (flags, ord(key)) if flags else None  # a bare letter would fire while typing
    return (flags, NAMED_VK[key]) if key in NAMED_VK else None


def keys_down():
    """The combo held right now, read from the keyboard itself: Tk never sees Alt+<key> (Windows keeps it for menus)."""
    down = lambda vk: ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
    key = next((name for vk, name in VK_NAMES.items() if down(vk)), None)
    return key and '+'.join([m for m, vk in MOD_VKS if down(vk)] + [key])


class Hotkey(threading.Thread):
    WM_HOTKEY, WM_REREGISTER = 0x0312, 0x8001

    def __init__(self, get_combo, on_press, on_status):
        super().__init__(daemon=True)
        self.get_combo, self.on_press, self.on_status, self.tid = get_combo, on_press, on_status, None

    def run(self):
        u = ctypes.windll.user32
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register(u)
        msg = ctypes.wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == self.WM_HOTKEY:
                self.on_press()
            elif msg.message == self.WM_REREGISTER:
                self._register(u)

    def _register(self, u):
        u.UnregisterHotKey(None, 1)
        hk = parse_hotkey(self.get_combo())
        self.on_status(bool(hk and u.RegisterHotKey(None, 1, hk[0] | 0x4000, hk[1])))  # 0x4000: no auto-repeat

    def changed(self):
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, self.WM_REREGISTER, 0, 0)


class LinuxHotkey:
    """Linux (X11) has no RegisterHotKey: follow the keyboard with pynput and fire when the held combo matches.
    The keys still reach the focused app, like NVIDIA's Alt+F10 on Windows. Also tells the hotkey picker what's held."""

    def __init__(self, get_combo, on_press, on_status):
        self.get_combo, self.on_press, self.on_status = get_combo, on_press, on_status
        self.mods, self.key, self.esc, self.fired = set(), None, False, 0.0

    def start(self):
        try:
            from pynput import keyboard
            K = keyboard.Key
            mods = {'Alt': ('alt', 'alt_l', 'alt_r', 'alt_gr'), 'Ctrl': ('ctrl', 'ctrl_l', 'ctrl_r'),
                    'Shift': ('shift', 'shift_l', 'shift_r')}
            self.mod_of = {getattr(K, n): m for m, names in mods.items() for n in names if hasattr(K, n)}
            named = {'pause': 'Pause', 'insert': 'Insert', 'delete': 'Delete', 'home': 'Home', 'end': 'End',
                     'page_up': 'PageUp', 'page_down': 'PageDown', 'scroll_lock': 'ScrollLock',
                     'print_screen': 'PrintScreen', 'space': 'Space', **{f'f{i}': f'F{i}' for i in range(1, 25)}}
            self.name_of = {getattr(K, n): v for n, v in named.items() if hasattr(K, n)}
            self.esc_key = K.esc
            listener = keyboard.Listener(on_press=self._down, on_release=self._up)
            listener.daemon = True
            listener.start()
            self.changed()
        except Exception as e:  # no X11 session (Wayland, SSH): voice and the buttons still work
            log(f'hotkey: {e!r}')
            self.on_status(False)

    def _name(self, key):
        if key in self.name_of:
            return self.name_of[key]
        c = (getattr(key, 'char', None) or '').upper()
        # shortcut: AZERTY digits arrive as &é"'( so only letters, F-keys and named keys work there
        return c if re.fullmatch(r'[A-Z0-9]', c) else None

    def combo(self):
        return self.key and '+'.join([m for m in ('Ctrl', 'Alt', 'Shift') if m in self.mods] + [self.key])

    def _down(self, key, *_):
        if key == self.esc_key:
            self.esc = True
        elif key in self.mod_of:
            self.mods.add(self.mod_of[key])
        elif self._name(key):
            self.key = self._name(key)
            if self.combo() == self.get_combo() and time.time() - self.fired > 1:  # X11 auto-repeat re-sends keys
                self.fired = time.time()
                self.on_press()

    def _up(self, key, *_):
        if key == self.esc_key:
            self.esc = False
        elif key in self.mod_of:
            self.mods.discard(self.mod_of[key])
        elif self._name(key) == self.key:
            self.key = None

    def changed(self):
        self.on_status(bool(parse_hotkey(self.get_combo())))


if not WIN:
    Hotkey = LinuxHotkey


# ---------- OBS ----------
def find_obs():
    if not WIN:
        return shutil.which('obs')
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r'SOFTWARE\OBS Studio') as k:
                exe = os.path.join(winreg.QueryValue(k, None), 'bin', '64bit', 'obs64.exe')
                if os.path.exists(exe):
                    return exe
        except OSError:
            pass
    exe = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'obs-studio', 'bin', '64bit', 'obs64.exe')
    return exe if os.path.exists(exe) else None


def obs_running():
    if not WIN:
        return subprocess.run(['pgrep', '-x', 'obs'], capture_output=True).returncode == 0
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq obs64.exe', '/NH'], capture_output=True, text=True,
                         creationflags=NOWIN).stdout
    return 'obs64.exe' in out


def detect_encoder():
    try:
        cmd = ['powershell', '-NoProfile', '-Command', '(Get-CimInstance Win32_VideoController).Name'] if WIN \
            else ['lspci']
        out = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN).stdout.lower()
    except OSError:
        return 'x264'
    if not WIN:  # OBS's simple mode only offers NVENC as a GPU encoder on Linux
        return 'nvenc' if any('nvidia' in l for l in out.splitlines() if 'vga' in l or '3d' in l) else 'x264'
    for word, enc in (('nvidia', 'nvenc'), ('radeon', 'amd'), ('amd', 'amd'), ('intel', 'qsv')):
        if word in out:
            return enc
    return 'x264'


def primary_size():
    if WIN:
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    try:
        out = subprocess.run(['xrandr', '--query'], capture_output=True, text=True).stdout
        m = re.search(r' connected primary (\d+)x(\d+)', out) or re.search(r' connected (\d+)x(\d+)', out) \
            or re.search(r'current (\d+) x (\d+)', out)
        if m:
            return int(m[1]), int(m[2])
    except OSError:
        pass
    return 1920, 1080


def out_size(bw, bh, choice):
    """Output size for a resolution choice, keeping the screen's shape; never upscales."""
    if choice == 'Native' or int(choice[:-1]) >= bh:
        return bw, bh
    h = int(choice[:-1])
    return round(bw * h / bh / 2) * 2, h


def prepare_obs(s):
    """Writes the Clipper profile/collection and turns on OBS's websocket. Only while OBS is closed (it rewrites
    these files on exit)."""
    os.makedirs(os.path.dirname(PROFILE_INI), exist_ok=True)
    if not os.path.exists(PROFILE_INI):
        bw, bh = primary_size()
        ow, oh = out_size(bw, bh, s['resolution'])
        with open(PROFILE_INI, 'w', encoding='utf-8') as f:
            f.write(f"[General]\nName=Clipper\n\n[Output]\nMode=Simple\n\n[SimpleOutput]\n"
                    f"FilePath={s['folder'].replace(chr(92), chr(92) * 2)}\nRecFormat2=mp4\n"
                    f"RecQuality={QUALITY[s['quality']]}\nRecEncoder={s['encoder']}\nRecRB=true\n"
                    f"RecRBTime={s['clip_seconds']}\nRecRBSize=4096\nRecRBPrefix=Clip\n\n"
                    f"[Video]\nBaseCX={bw}\nBaseCY={bh}\nOutputCX={ow}\nOutputCY={oh}\nFPSType=0\nFPSCommon={s['fps']}\n")
    else:  # this app owns the hotkey now; an old OBS binding would save every clip twice
        lines = open(PROFILE_INI, encoding='utf-8-sig').read().splitlines()
        with open(PROFILE_INI, 'w', encoding='utf-8') as f:
            f.write('\n'.join(l for l in lines if not l.startswith('ReplayBuffer=')) + '\n')
    os.makedirs(os.path.dirname(COLLECTION), exist_ok=True)
    if not os.path.exists(COLLECTION):
        def src(kind, name, settings):
            return {'id': kind, 'versioned_id': kind, 'name': name, 'uuid': str(uuid.uuid4()), 'settings': settings,
                    'enabled': True}
        display = src(SCREEN_SRC, 'Clip Display', {'capture_cursor': True} if WIN else {'show_cursor': True})
        # Windows also hooks fullscreen games; on Linux (X11) the screen capture already sees them
        shown = [display, src('game_capture', 'Clip Game', {'capture_mode': 'any_fullscreen'})] if WIN else [display]
        items = [{'name': x['name'], 'source_uuid': x['uuid'], 'id': i + 1, 'visible': True, 'locked': True,
                  'pos': {'x': 0, 'y': 0}, 'scale': {'x': 1, 'y': 1}, 'bounds_type': 2,
                  'bounds': {'x': primary_size()[0], 'y': primary_size()[1]}, 'align': 5}
                 for i, x in enumerate(shown)]
        desk = src(DESK_SRC, 'Desktop Audio', {'device_id': 'default'})
        mic = src(MIC_SRC, 'Mic/Aux', {'device_id': 'default'})
        for a in (desk, mic):
            a['mixers'] = 255
        json.dump({'name': 'Clipper', 'current_scene': 'Clipper', 'current_program_scene': 'Clipper',
                   'scene_order': [{'name': 'Clipper'}], 'groups': [],
                   'sources': [src('scene', 'Clipper', {'id_counter': len(shown), 'items': items}), *shown],
                   'DesktopAudioDevice1': desk, 'AuxAudioDevice1': mic}, open(COLLECTION, 'w', encoding='utf-8'))
    os.makedirs(os.path.dirname(WS_CFG), exist_ok=True)
    try:
        ws = json.load(open(WS_CFG, encoding='utf-8-sig'))
    except (OSError, ValueError):
        ws = {'server_port': 4455, 'first_load': False, 'alerts_enabled': False}
    if not ws.get('server_password'):
        ws['server_password'] = uuid.uuid4().hex[:16]
    ws.update(server_enabled=True, auth_required=True)
    json.dump(ws, open(WS_CFG, 'w', encoding='utf-8'), indent=2)
    user_ini = os.path.join(OBS_CFG, 'user.ini')
    if not os.path.exists(user_ini) and not os.path.exists(os.path.join(OBS_CFG, 'global.ini')):
        with open(user_ini, 'w', encoding='utf-8') as f:  # fresh OBS: skip its first-run wizard, keep a tray icon
            f.write('[General]\nFirstRun=true\n\n[BasicWindow]\nSysTrayEnabled=true\n')


class Obs(threading.Thread):
    """Owns OBS: starts it, applies settings, keeps the replay buffer on, saves clips."""

    def __init__(self, app):
        super().__init__(daemon=True)
        self.app, self.client, self.lock = app, None, threading.Lock()
        self.wake, self.apply_needed = threading.Event(), threading.Event()
        self.screens, self.mics, self.speakers, self.fails = [], [], [], 0

    def call(self, fn):
        import obsws_python as obsws
        with self.lock:
            if self.client is None:
                cfg = json.load(open(WS_CFG, encoding='utf-8-sig'))
                self.client = obsws.ReqClient(host='localhost', port=cfg.get('server_port', 4455),
                                              password=cfg.get('server_password', ''), timeout=5)
            try:
                return fn(self.client)
            except Exception:
                self.client = None
                raise

    def run(self):
        applied = False
        while True:
            s = self.app.settings
            try:
                exe = find_obs()
                if not exe:
                    self.app.status('missing')
                elif not obs_running():
                    prepare_obs(s)
                    subprocess.Popen([exe, '--profile', 'Clipper', '--collection', 'Clipper', '--startreplaybuffer',
                                      '--minimize-to-tray', '--disable-shutdown-check'], cwd=os.path.dirname(exe))
                    self.client, applied = None, False
                    self.app.status('starting')
                    self.wake.wait(10)
                elif self.call(lambda c: c.get_profile_list().current_profile_name) != 'Clipper':
                    self.app.status('other_profile')  # someone is using OBS for something else: hands off
                else:
                    if not applied or self.apply_needed.is_set():
                        self.apply_needed.clear()
                        self.apply(s)
                        applied = True
                    if self.call(lambda c: c.get_replay_buffer_status().output_active):
                        self.fails = 0
                        self.app.status('ok')
                    else:
                        self.restart_replay()
            except Exception as e:
                log(f'obs: {e!r}')
                self.client, applied = None, False
                self.app.status('connecting')
            self.wake.wait(5)
            self.wake.clear()

    def restart_replay(self):
        self.fails += 1
        if self.fails >= 3 and self.app.settings['encoder'] != 'x264':  # the GPU encoder won't start: use the CPU one
            log(f"encoder {self.app.settings['encoder']} failed, switching to x264")
            self.app.update_setting('encoder', 'x264')
            self.apply(self.app.settings)
            self.fails = 0
        try:
            log(f'replay buffer was off, started it: {"ok" if self.start_replay() else "still off"}')
        except Exception as e:
            log(f'start replay: {e!r}')

    def start_replay(self):
        """Starts it and waits until it runs, so a check right after doesn't see it 'off' and start it again."""
        self.call(lambda c: c.start_replay_buffer())
        for _ in range(80):
            if self.call(lambda c: c.get_replay_buffer_status().output_active):
                return True
            time.sleep(0.1)
        return False

    def stop_replay(self):
        if self.call(lambda c: c.get_replay_buffer_status().output_active):
            self.call(lambda c: c.stop_replay_buffer())
            for _ in range(50):
                if not self.call(lambda c: c.get_replay_buffer_status().output_active):
                    return
                time.sleep(0.1)

    def items(self, source, prop):
        return [(i['itemName'], i['itemValue']) for i in
                self.call(lambda c: c.get_input_properties_list_property_items(source, prop).property_items)]

    def apply(self, s):
        restart = []  # what changed, for the log
        params = [('Output', 'Mode', 'Simple'), ('Output', 'FilenameFormatting', '%CCYY-%MM-%DD %hh-%mm-%ss'),
                  ('SimpleOutput', 'RecRB', 'true'), ('SimpleOutput', 'RecRBTime', str(s['clip_seconds'])),
                  ('SimpleOutput', 'FilePath', s['folder']), ('SimpleOutput', 'RecFormat2', 'mp4'),
                  ('SimpleOutput', 'RecQuality', QUALITY[s['quality']]), ('SimpleOutput', 'RecEncoder', s['encoder']),
                  ('SimpleOutput', 'RecRBPrefix', 'Clip'), ('SimpleOutput', 'RecRBSize', '4096')]
        os.makedirs(s['folder'], exist_ok=True)
        for cat, key, val in params:
            if self.call(lambda c: c.get_profile_parameter(cat, key).parameter_value) != val:
                self.call(lambda c: c.set_profile_parameter(cat, key, val))
                restart.append(key)
        # Screen and size
        self.screens = self.items('Clip Display', SCREEN_PROP)
        ids = [v for _, v in self.screens]
        screen = s['screen'] if s['screen'] in ids else next(
            (v for n, v in self.screens if 'Primary' in n), ids[0] if ids else '')
        if self.call(lambda c: c.get_input_settings('Clip Display').input_settings.get(SCREEN_PROP)) != screen:
            self.call(lambda c: c.set_input_settings('Clip Display', {SCREEN_PROP: screen}, True))
        name = next((n for n, v in self.screens if v == screen), '')
        m = re.search(r'(\d+)x(\d+)', name)
        bw, bh = (int(m[1]), int(m[2])) if m else primary_size()
        ow, oh = out_size(bw, bh, s['resolution'])
        v = self.call(lambda c: c.get_video_settings())
        if (v.base_width, v.base_height, v.output_width, v.output_height, v.fps_numerator, v.fps_denominator) != \
                (bw, bh, ow, oh, s['fps'], 1):
            self.stop_replay()
            self.call(lambda c: c.set_video_settings(s['fps'], 1, bw, bh, ow, oh))
            for it in self.call(lambda c: c.get_scene_item_list('Clipper').scene_items):
                self.call(lambda c: c.set_scene_item_transform('Clipper', it['sceneItemId'], {
                    'positionX': 0, 'positionY': 0, 'boundsType': 'OBS_BOUNDS_SCALE_INNER',
                    'boundsWidth': bw, 'boundsHeight': bh}))
            restart.append('video')
        # Audio
        self.speakers = self.items('Desktop Audio', 'device_id')
        self.mics = self.items('Mic/Aux', 'device_id')
        self.call(lambda c: c.set_input_settings('Desktop Audio', {'device_id': s['desktop_device']}, True))
        self.call(lambda c: c.set_input_volume('Desktop Audio', vol_db=float(s['desktop_db'])))
        mic_off = s['mic_device'] == 'off'
        self.call(lambda c: c.set_input_mute('Mic/Aux', mic_off))
        if not mic_off:
            self.call(lambda c: c.set_input_settings('Mic/Aux', {'device_id': s['mic_device']}, True))
        level = float(s['mic_db'])  # below 0: turn the mic down; above 0: boost it with a gain filter
        self.call(lambda c: c.set_input_volume('Mic/Aux', vol_db=min(level, 0.0)))
        have = {f['filterName'] for f in self.call(lambda c: c.get_source_filter_list('Mic/Aux').filters)}
        for key, fname, kind, settings in FX:
            if fname not in have:
                self.call(lambda c: c.create_source_filter('Mic/Aux', fname, kind, settings))
            on = level > 0 if key is None else bool(s[key])
            if key is None:
                self.call(lambda c: c.set_source_filter_settings('Mic/Aux', fname, {'db': max(level, 0.0)}, True))
            self.call(lambda c: c.set_source_filter_enabled('Mic/Aux', fname, on))
        if restart:
            self.stop_replay()
            self.start_replay()
            log(f'settings applied ({", ".join(restart)}), replay restarted')
        self.app.lists_changed()

    def save(self, source):
        try:
            before = self.call(lambda c: c.get_last_replay_buffer_replay().saved_replay_path)
        except Exception:
            before = None
        try:
            self.call(lambda c: c.save_replay_buffer())
        except Exception as e:
            log(f'save failed: {e!r}')
            play(CHIME_FAIL)
            self.app.status('save_failed')
            self.app.ui.put(('toast', False))
            return
        if self.app.settings['chime']:  # OBS took the order: say so now, writing the file can take a while
            play(CHIME_OK)
        self.app.clip_saved()
        path = None
        try:
            for _ in range(1200):  # up to 2 min: a busy PC can take a while to write a long clip
                p = self.call(lambda c: c.get_last_replay_buffer_replay().saved_replay_path)
                if p and p != before:  # never take (and re-compress) the previous clip
                    path = p
                    break
                time.sleep(0.1)
        except Exception as e:
            log(f'waiting for the clip: {e!r}')
        log(f'clip saved ({source}): {path or "not written after 2 min"}')
        self.app.ui.put(('clips', None))
        if path and self.app.settings['compress_clips']:
            compress_clip(path)
            self.app.ui.put(('clips', None))


# ---------- voice ----------
def voice_loop(app):
    import sounddevice as sd
    import vosk
    vosk.SetLogLevel(-1)
    models = {k: vosk.Model(os.path.join(BASE, 'models', m)) for k, (m, _) in PHRASES.items()}
    last = 0.0
    while True:
        on = [k for k in PHRASES if app.settings[k]]
        if not on:
            time.sleep(1)
            continue
        recs = {k: vosk.KaldiRecognizer(models[k], 16000, json.dumps([PHRASES[k][1], '[unk]'], ensure_ascii=False))
                for k in on}
        audio = queue.Queue()
        try:
            with sd.RawInputStream(samplerate=16000, blocksize=4000, dtype='int16', channels=1,
                                   callback=lambda data, *_: audio.put(bytes(data))):
                while [k for k in PHRASES if app.settings[k]] == on:  # reopen when the phrases change
                    try:
                        chunk = audio.get(timeout=1)
                    except queue.Empty:
                        continue
                    for k, rec in recs.items():
                        if rec.AcceptWaveform(chunk) and json.loads(rec.Result()).get('text') == PHRASES[k][1] \
                                and time.time() - last > 3:
                            last = time.time()
                            threading.Thread(target=app.obs.save, args=(PHRASES[k][1],), daemon=True).start()
        except Exception as e:  # mic unplugged or busy: try again shortly
            log(f'voice: {e!r}')
            time.sleep(5)


# ---------- window ----------
STATUS = {'ok': ('#3ecf8e', 'Recording. Clips save the last {s} seconds.'),
          'starting': ('#f5a524', 'Starting OBS…'),
          'connecting': ('#f5a524', 'Connecting to OBS…'),
          'missing': ('#f31260', 'OBS Studio is not installed. Install it to start clipping.'),
          'other_profile': ('#f5a524', 'OBS is open on another profile, so clipping is paused. Switch OBS back to '
                                       'the Clipper profile (Profile menu) to resume.'),
          'save_failed': ('#f31260', "Couldn't save the clip. Check that the clips folder exists."),
          'saved': ('#3ecf8e', 'Clip saved.')}
BG, CARD, FG, MUTED, ACCENT = '#16181d', '#1f232b', '#e8eaed', '#9aa0a6', '#7c5cff'


class App:
    def __init__(self, background, server):
        self.server = server
        self.settings = load_settings()
        if not self.settings['encoder']:
            self.settings['encoder'] = detect_encoder()
            save_settings(self.settings)
        self.ui = queue.Queue()
        self.root = tk.Tk()
        self.root.title(APP)
        self.root.geometry('620x560')
        self.root.minsize(560, 500)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW', self.hide)
        try:
            if WIN:
                self.root.iconbitmap(os.path.join(BASE, 'icon.ico'))
            else:
                self.root.iconphoto(True, tk.PhotoImage(file=os.path.join(BASE, 'icon.png')))
        except tk.TclError:
            pass
        self.style()
        if WIN:  # dark title bar to match (Windows 10 2004+ / 11); on Linux the desktop theme draws it
            try:
                self.root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
            except OSError:
                pass
        self.vars = {}
        self.build()
        if background:
            self.root.withdraw()
        self.obs = Obs(self)
        self.hotkey = Hotkey(lambda: self.settings['hotkey'], lambda: self.save_clip('hotkey'), self.hotkey_status)
        self.obs.start()
        self.hotkey.start()
        threading.Thread(target=voice_loop, args=(self,), daemon=True).start()
        threading.Thread(target=self.serve_show, daemon=True).start()
        self.tray()
        self.root.after(150, self.pump)

    # thread-safe bridges into the UI
    def status(self, key):
        self.ui.put(('status', key))

    def clip_saved(self):
        self.ui.put(('status', 'saved'))
        self.ui.put(('clips', None))
        self.ui.put(('toast', True))

    def lists_changed(self):
        self.ui.put(('lists', None))

    def hotkey_status(self, ok):
        self.ui.put(('hotkey', ok))

    def update_setting(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)

    def save_clip(self, source):
        threading.Thread(target=self.obs.save, args=(source,), daemon=True).start()

    def pump(self):
        while not self.ui.empty():
            kind, val = self.ui.get()
            if kind == 'status':
                color, text = STATUS[val]
                self.dot.configure(fg=color)
                self.status_text.configure(text=text.format(s=self.settings['clip_seconds']))
                self.install_btn.pack_forget() if val != 'missing' else self.install_btn.pack(anchor='w', pady=(8, 0))
            elif kind == 'clips':
                self.refresh_clips()
            elif kind == 'lists':
                self.refresh_lists()
            elif kind == 'hotkey':
                problem = ('That key is taken by another app (NVIDIA overlay uses Alt+F10). Pick another one.'
                           if WIN else 'The hotkey needs an X11 session (Linux Mint XFCE is one). Voice and the '
                                       'buttons still work.')
                self.hotkey_note.configure(text='' if val else problem)
            elif kind == 'show':
                self.show()
            elif kind == 'toast' and self.settings['popup']:
                self.toast(val)
        self.root.after(150, self.pump)

    def toast(self, ok):
        """NVIDIA-style notice in the top-right corner: never takes focus, clicks go through it, fades away."""
        if getattr(self, 'popup', None):
            self.popup.destroy()
        t = self.popup = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes('-topmost', True)
        t.attributes('-alpha', 0.0)
        box = tk.Frame(t, bg=CARD, highlightbackground=ACCENT if ok else '#f31260', highlightthickness=2)
        box.pack()
        tk.Label(box, text='✔' if ok else '✖', bg=CARD, fg='#3ecf8e' if ok else '#f31260',
                 font=('Segoe UI', 20)).pack(side='left', padx=(16, 10), pady=12)
        words = tk.Frame(box, bg=CARD)
        words.pack(side='left', padx=(0, 20), pady=12)
        tk.Label(words, text='Clipped!' if ok else 'Clip failed', bg=CARD, fg=FG,
                 font=('Segoe UI Semibold', 12)).pack(anchor='w')
        tk.Label(words, text=f'Last {self.settings["clip_seconds"]} seconds saved' if ok else 'Open Clip Ça to see why',
                 bg=CARD, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w')
        t.update_idletasks()
        t.geometry(f'+{t.winfo_screenwidth() - t.winfo_reqwidth() - 24}+24')
        if WIN:  # no focus steal, no taskbar button, click-through (on X11 an override-redirect window already
            try:  # never takes focus nor shows in the taskbar)
                hwnd = int(t.wm_frame(), 16)
                ex = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex | 0x08000000 | 0x80 | 0x20)
            except (OSError, ValueError):
                pass
        def fade(step=0):
            if not t.winfo_exists():
                return
            if step < 8:  # fade in
                t.attributes('-alpha', 0.95 * (step + 1) / 8)
                t.after(18, fade, step + 1)
            elif step == 8:  # hold
                t.after(2200, fade, 9)
            elif step < 20:  # fade out
                t.attributes('-alpha', 0.95 * (20 - step) / 11)
                t.after(25, fade, step + 1)
            else:
                t.destroy()
        fade()

    # ---- look ----
    def style(self):
        st = ttk.Style(self.root)
        st.theme_use('clam')
        st.configure('.', background=BG, foreground=FG, fieldbackground=CARD, font=('Segoe UI', 10),
                     bordercolor='#2a2f3a', lightcolor='#2a2f3a', darkcolor='#2a2f3a')
        st.configure('TNotebook', background=BG, borderwidth=0)
        st.configure('TNotebook.Tab', background=BG, foreground=MUTED, padding=(14, 8), borderwidth=0)
        st.map('TNotebook.Tab', background=[('selected', CARD)], foreground=[('selected', FG)])
        st.configure('Card.TFrame', background=CARD)
        st.configure('TLabel', background=CARD, foreground=FG)
        st.configure('Muted.TLabel', background=CARD, foreground=MUTED, font=('Segoe UI', 9))
        st.configure('H.TLabel', background=CARD, foreground=FG, font=('Segoe UI Semibold', 11))
        st.configure('TCheckbutton', background=CARD, foreground=FG)
        st.map('TCheckbutton', background=[('active', CARD)])
        st.configure('TButton', background=CARD, foreground=FG, borderwidth=1, padding=(12, 6))
        st.map('TButton', background=[('active', '#2a2f3a')])
        st.configure('Accent.TButton', background=ACCENT, foreground='white', font=('Segoe UI Semibold', 10))
        st.map('Accent.TButton', background=[('active', '#6a4be0')])
        st.configure('TCombobox', fieldbackground=BG, background=CARD, foreground=FG, arrowcolor=FG)
        st.map('TCombobox', fieldbackground=[('readonly', BG)], foreground=[('readonly', FG)])
        self.root.option_add('*TCombobox*Listbox.background', CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', FG)
        st.configure('Horizontal.TScale', background=CARD, troughcolor=BG)
        st.configure('Treeview', background=BG, fieldbackground=BG, foreground=FG, rowheight=26, borderwidth=0)
        st.configure('Treeview.Heading', background=CARD, foreground=MUTED, borderwidth=0)
        st.map('Treeview', background=[('selected', ACCENT)])

    def page(self, nb, title):
        f = ttk.Frame(nb, style='Card.TFrame', padding=18)
        nb.add(f, text=title)
        f.columnconfigure(1, weight=1)
        return f

    def row(self, parent, r, label, widget, hint=None):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky='w', pady=6, padx=(0, 16))
        widget.grid(row=r, column=1, sticky='ew', pady=6)
        if hint:
            ttk.Label(parent, text=hint, style='Muted.TLabel', wraplength=380).grid(row=r + 1, column=1, sticky='w')

    def combo(self, parent, key, values, cast=str):
        var = tk.StringVar(value=str(self.settings[key]))
        cb = ttk.Combobox(parent, textvariable=var, values=[str(v) for v in values], state='readonly')
        cb.bind('<<ComboboxSelected>>', lambda e: self.changed(key, cast(var.get())))
        self.vars[key] = var
        return cb

    def check(self, parent, key, text):
        var = tk.BooleanVar(value=self.settings[key])
        self.vars[key] = var
        return ttk.Checkbutton(parent, text=text, variable=var, command=lambda: self.changed(key, var.get()))

    def slider(self, parent, key, lo, hi):
        box = ttk.Frame(parent, style='Card.TFrame')
        var = tk.DoubleVar(value=self.settings[key])
        label = ttk.Label(box, width=7)
        show = lambda *_: label.configure(text=f'{var.get():+.0f} dB')
        sc = ttk.Scale(box, from_=lo, to=hi, variable=var, command=show)
        sc.bind('<ButtonRelease-1>', lambda e: self.changed(key, round(var.get())))
        sc.pack(side='left', fill='x', expand=True)
        label.pack(side='left', padx=(8, 0))
        show()
        return box

    def build(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill='x', padx=18, pady=(16, 8))
        tk.Label(head, text=APP, bg=BG, fg=FG, font=('Segoe UI Semibold', 16)).pack(side='left')
        ttk.Button(head, text='Save clip now', style='Accent.TButton',
                   command=lambda: self.save_clip('button')).pack(side='right')
        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=18, pady=(0, 18))

        home = self.page(nb, 'Home')
        top = ttk.Frame(home, style='Card.TFrame')
        top.grid(row=0, column=0, columnspan=2, sticky='ew')
        self.dot = tk.Label(top, text='●', bg=CARD, fg='#f5a524', font=('Segoe UI', 14))
        self.dot.pack(side='left', anchor='n')
        txt = ttk.Frame(top, style='Card.TFrame')
        txt.pack(side='left', fill='x', expand=True, padx=(8, 0))
        self.status_text = ttk.Label(txt, text='Starting…', wraplength=480)
        self.status_text.pack(anchor='w', pady=(3, 0))
        self.install_btn = ttk.Button(txt, text='Install OBS Studio', command=self.install_obs)
        self.how = ttk.Label(home, style='Muted.TLabel')
        self.how.grid(row=1, column=0, columnspan=2, sticky='w', pady=(10, 12))
        cols = ttk.Frame(home, style='Card.TFrame')
        cols.grid(row=2, column=0, columnspan=2, sticky='nsew')
        home.rowconfigure(2, weight=1)
        self.clips = ttk.Treeview(cols, columns=('when', 'size'), show='headings', height=8)
        self.clips.heading('when', text='Recent clips (double-click to play)')
        self.clips.heading('size', text='Size')
        self.clips.column('size', width=80, anchor='e', stretch=False)
        self.clips.bind('<Double-1>', self.open_clip)
        self.clips.pack(fill='both', expand=True)
        ttk.Button(home, text='Open clips folder', command=lambda: open_path(self.settings["folder"])) \
            .grid(row=3, column=0, sticky='w', pady=(10, 0))

        video = self.page(nb, 'Video')
        self.screen_cb = ttk.Combobox(video, state='readonly')
        self.screen_cb.bind('<<ComboboxSelected>>', lambda e: self.pick_device('screen', self.screen_cb, self.obs.screens))
        self.row(video, 0, 'Screen', self.screen_cb)
        self.row(video, 2, 'Resolution', self.combo(video, 'resolution', RESOLUTIONS),
                 'Native records at your screen size. Lower = smaller files.')
        self.row(video, 4, 'Frame rate', self.combo(video, 'fps', FPS_CHOICES, int))
        self.row(video, 5, 'Quality', self.combo(video, 'quality', list(QUALITY)),
                 '"Very high" looks the same as your screen but makes big files.')
        self.row(video, 7, 'Clip length', self.combo(video, 'clip_seconds', [15, 30, 45, 60, 90, 120, 180, 300], int),
                 'Seconds saved each time you clip.')
        self.encoder_note = ttk.Label(video, style='Muted.TLabel')
        self.encoder_note.grid(row=9, column=0, columnspan=2, sticky='w', pady=(14, 0))

        audio = self.page(nb, 'Audio')
        self.speaker_cb = ttk.Combobox(audio, state='readonly')
        self.speaker_cb.bind('<<ComboboxSelected>>',
                             lambda e: self.pick_device('desktop_device', self.speaker_cb, self.obs.speakers))
        self.row(audio, 0, 'PC sound from', self.speaker_cb)
        self.row(audio, 1, 'PC sound volume', self.slider(audio, 'desktop_db', -30, 0))
        self.mic_cb = ttk.Combobox(audio, state='readonly')
        self.mic_cb.bind('<<ComboboxSelected>>', lambda e: self.pick_device(
            'mic_device', self.mic_cb, self.obs.mics + [('Off (no mic in clips)', 'off')]))
        self.row(audio, 2, 'Microphone', self.mic_cb)
        self.row(audio, 3, 'Mic level', self.slider(audio, 'mic_db', -30, 30), 'Above 0 boosts a quiet mic.')
        ttk.Label(audio, text='Mic effects', style='H.TLabel').grid(row=5, column=0, sticky='w', pady=(16, 4))
        for i, (key, text) in enumerate([('fx_noise', 'Noise suppression: removes fans, hum and keyboard noise'),
                                         ('fx_gate', "Noise gate: silences the mic when you're not talking"),
                                         ('fx_comp', 'Compressor: evens out shouting and whispering'),
                                         ('fx_limit', 'Limiter: stops loud moments from distorting')]):
            self.check(audio, key, text).grid(row=6 + i, column=0, columnspan=2, sticky='w', pady=2)

        ctl = self.page(nb, 'Controls')
        hk = ttk.Frame(ctl, style='Card.TFrame')
        self.hotkey_btn = ttk.Button(hk, text=self.settings['hotkey'], command=self.capture_hotkey)
        self.hotkey_btn.pack(side='left')
        ttk.Label(hk, text='click, then press your keys', style='Muted.TLabel').pack(side='left', padx=10)
        self.row(ctl, 0, 'Clip hotkey', hk)
        self.hotkey_note = ttk.Label(ctl, style='Muted.TLabel', foreground='#f31260', wraplength=380)
        self.hotkey_note.grid(row=1, column=1, sticky='w')
        ttk.Label(ctl, text='Voice', style='H.TLabel').grid(row=2, column=0, sticky='w', pady=(16, 4))
        self.check(ctl, 'voice_fr', 'Say "clip ça" (French)').grid(row=3, column=0, columnspan=2, sticky='w')
        self.check(ctl, 'voice_en', 'Say "clip that" (English)').grid(row=4, column=0, columnspan=2, sticky='w')
        ttk.Label(ctl, text='Voice listens on your default microphone, offline. Nothing leaves your PC.',
                  style='Muted.TLabel').grid(row=5, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.check(ctl, 'chime', 'Play a sound when a clip is saved').grid(row=6, column=0, columnspan=2,
                                                                         sticky='w', pady=(16, 0))
        self.check(ctl, 'popup', 'Show a "Clipped!" popup in the corner').grid(row=7, column=0, columnspan=2,
                                                                              sticky='w')

        gen = self.page(nb, 'General')
        folder = ttk.Frame(gen, style='Card.TFrame')
        self.folder_label = ttk.Label(folder, text=self.settings['folder'], wraplength=300)
        self.folder_label.pack(side='left', fill='x', expand=True)
        ttk.Button(folder, text='Change…', command=self.pick_folder).pack(side='right')
        self.row(gen, 0, 'Clips folder', folder)
        self.startup_var = tk.BooleanVar(value=self.starts_with_windows())
        ttk.Checkbutton(gen, text=f'Start {"with Windows" if WIN else "when you log in"} (recommended, so you '
                                  'never miss a moment)',
                        variable=self.startup_var, command=self.toggle_startup).grid(row=1, column=0, columnspan=2,
                                                                                     sticky='w', pady=(12, 0))
        self.check(gen, 'compress_clips', 'Compress clips after saving to save space (no visible loss)') \
            .grid(row=2, column=0, columnspan=2, sticky='w', pady=(4, 0))
        ttk.Label(gen, text=f'{APP} {VERSION} · records with OBS Studio in its own "Clipper" profile, so your other '
                            'OBS scenes and settings stay as they are. Log: ' + LOG,
                  style='Muted.TLabel', wraplength=500).grid(row=3, column=0, columnspan=2, sticky='w', pady=(24, 0))
        ttk.Button(gen, text=f'Quit {APP}', command=self.quit).grid(row=4, column=0, sticky='w', pady=(16, 0))
        self.refresh_how()
        self.refresh_clips()

    # ---- actions ----
    def changed(self, key, value):
        self.update_setting(key, value)
        if key in ('voice_fr', 'voice_en', 'chime', 'compress_clips'):  # no OBS restart needed
            self.refresh_how()
            return
        self.obs.apply_needed.set()
        self.obs.wake.set()

    def pick_device(self, key, cb, options):
        i = cb.current()
        if 0 <= i < len(options):
            self.changed(key, options[i][1])

    def refresh_lists(self):
        for cb, key, opts in ((self.screen_cb, 'screen', self.obs.screens),
                              (self.speaker_cb, 'desktop_device', self.obs.speakers),
                              (self.mic_cb, 'mic_device', self.obs.mics + [('Off (no mic in clips)', 'off')])):
            cb['values'] = [n for n, _ in opts]
            ids = [v for _, v in opts]
            cur = self.settings[key]
            if cur in ids:
                cb.current(ids.index(cur))
            elif key == 'screen':
                cb.current(next((i for i, (n, _) in enumerate(opts) if 'Primary' in n), 0)) if opts else None
        enc = {'nvenc': 'NVIDIA', 'amd': 'AMD', 'qsv': 'Intel', 'x264': 'CPU'}.get(self.settings['encoder'], '?')
        self.encoder_note.configure(text=f'Encoding on your {enc} {"processor" if enc == "CPU" else "graphics card"}.')

    def refresh_how(self):
        ways = [f'press {self.settings["hotkey"]}']
        ways += [f'say "{PHRASES[k][1]}"' for k in PHRASES if self.settings[k]]
        self.how.configure(text='To clip: ' + ', or '.join(ways) + '.')

    def refresh_clips(self):
        self.clips.delete(*self.clips.get_children())
        try:
            files = sorted((e for e in os.scandir(self.settings['folder']) if e.name.lower().endswith('.mp4')),
                           key=lambda e: e.stat().st_mtime, reverse=True)[:50]
        except OSError:
            files = []
        for e in files:
            self.clips.insert('', 'end', iid=e.path, values=(time.strftime('%a %d %b, %H:%M:%S',
                                                                           time.localtime(e.stat().st_mtime)),
                                                             f'{e.stat().st_size / 1e6:.0f} MB'))

    def open_clip(self, _):
        sel = self.clips.selection()
        if sel:
            open_path(sel[0])

    def capture_hotkey(self):
        self.hotkey_btn.configure(text='Press keys… (Esc cancels)')
        armed = [False]  # wait until every key is up, so the key that pressed the button isn't taken
        seen = [None, 0]  # the same combo 3 polls running: apps that tap Ctrl to tame Alt can't sneak one in
        esc = (lambda: ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000) if WIN else lambda: self.hotkey.esc
        held = keys_down if WIN else self.hotkey.combo
        def poll():
            if esc():
                self.hotkey_btn.configure(text=self.settings['hotkey'])
                return
            combo = held()
            seen[:] = [combo, seen[1] + 1 if combo == seen[0] else 1]
            if not armed[0]:
                armed[0] = combo is None
            elif combo and seen[1] >= 3 and parse_hotkey(combo):
                self.hotkey_btn.configure(text=combo)
                self.update_setting('hotkey', combo)
                self.hotkey.changed()
                self.refresh_how()
                return
            self.root.after(20, poll)
        poll()

    def pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.settings['folder'])
        if d:
            d = os.path.normpath(d)
            self.folder_label.configure(text=d)
            self.changed('folder', d)
            self.refresh_clips()

    def starts_with_windows(self):
        if not WIN:
            return os.path.exists(AUTOSTART)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP)
                return True
        except OSError:
            return False

    def toggle_startup(self):
        if not WIN:  # a login item, the freedesktop way (XFCE: Session and Startup > Application Autostart)
            if self.startup_var.get():
                os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
                with open(AUTOSTART, 'w', encoding='utf-8') as f:
                    f.write(f'[Desktop Entry]\nType=Application\nName={APP}\nIcon={os.path.join(BASE, "icon.png")}\n'
                            f'Exec="{sys.executable}" "{os.path.abspath(__file__)}" --background\n'
                            'X-GNOME-Autostart-enabled=true\n')
            elif os.path.exists(AUTOSTART):
                os.remove(AUTOSTART)
            return
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if self.startup_var.get():
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, f'"{sys.executable}" --background')
            else:
                try:
                    winreg.DeleteValue(k, APP)
                except OSError:
                    pass

    def install_obs(self):
        if not messagebox.askyesno(APP, 'Install OBS Studio (free, about 150 MB) with Windows Package Manager? '
                                        'Windows may ask for permission.' if WIN else
                                        'Install OBS Studio (free) from its official PPA? Linux will ask for your '
                                        'password.'):
            return
        self.install_btn.configure(text='Installing…', state='disabled')
        def go():
            # Linux: the official PPA, because Ubuntu/Mint's own obs-studio package lacks the websocket we drive OBS with
            cmd = ['winget', 'install', '--id', 'OBSProject.OBSStudio', '-e', '--silent', '--accept-package-agreements',
                   '--accept-source-agreements'] if WIN else \
                ['pkexec', 'sh', '-c', 'add-apt-repository -y ppa:obsproject/obs-studio && apt-get install -y obs-studio']
            r = subprocess.run(cmd, creationflags=NOWIN)
            log(f'OBS install exit {r.returncode}')
            self.root.after(0, lambda: self.install_btn.configure(text='Install OBS Studio', state='normal'))
            if r.returncode != 0:
                self.root.after(0, lambda: messagebox.showerror(APP, 'Installing OBS failed. Get it from '
                                                                    'obsproject.com, then reopen this app.'))
            self.obs.wake.set()
        threading.Thread(target=go, daemon=True).start()

    # ---- window / tray / single instance ----
    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.refresh_clips()

    def hide(self):
        self.root.withdraw()

    def tray(self):
        import pystray
        from PIL import Image
        img = Image.open(os.path.join(BASE, 'icon.png'))
        menu = pystray.Menu(pystray.MenuItem('Open', lambda: self.ui.put(('show', None)), default=True),
                            pystray.MenuItem('Save clip now', lambda: self.save_clip('tray')),
                            pystray.MenuItem('Quit', lambda: self.root.after(0, self.quit)))
        self.icon = pystray.Icon('ClipCa', img, APP, menu)
        self.icon.run_detached()

    def serve_show(self):
        while True:
            conn, _ = self.server.accept()
            conn.close()
            self.ui.put(('show', None))

    def quit(self):
        self.icon.stop()
        self.root.destroy()
        os._exit(0)  # OBS keeps running on purpose: only this app's helpers stop


def selftest():
    assert parse_hotkey('Alt+F10') == (1, 0x79)
    assert parse_hotkey('Ctrl+Shift+S') == (6, ord('S'))
    assert parse_hotkey('S') is None and parse_hotkey('Hyper+F1') is None
    assert parse_hotkey('Alt+1') == (1, 0x31) and VK_NAMES[0x31] == '1' and VK_NAMES[0x79] == 'F10'
    assert out_size(1920, 1080, '720p') == (1280, 720) and out_size(1920, 1080, '1440p') == (1920, 1080)
    assert out_size(2560, 1080, '720p') == (1706, 720)
    assert parse_hotkey(DEFAULTS['hotkey'])
    h = LinuxHotkey(lambda: 'Ctrl+Alt+C', None, None)
    h.mods, h.key = {'Alt', 'Ctrl'}, 'C'
    assert h.combo() == 'Ctrl+Alt+C' and parse_hotkey(h.combo()) == (3, ord('C'))
    import vosk
    vosk.SetLogLevel(-1)
    for model, phrase in PHRASES.values():
        r = vosk.KaldiRecognizer(vosk.Model(os.path.join(BASE, 'models', model)), 16000,
                                 json.dumps([phrase, '[unk]'], ensure_ascii=False))
        r.AcceptWaveform(b'\0' * 32000)
        assert json.loads(r.FinalResult()).get('text', '') == '', 'silence triggered a clip'
    return 'selftest ok'


def main():
    os.makedirs(DATA, exist_ok=True)
    if '--selftest' in sys.argv:
        with open(os.path.join(DATA, 'selftest.txt'), 'w') as f:
            f.write(selftest())
        return
    server = socket.socket()
    try:
        server.bind(('127.0.0.1', PORT))
    except OSError:  # already running: bring that window up instead
        try:
            socket.create_connection(('127.0.0.1', PORT), timeout=2).close()
        except OSError:
            pass
        return
    server.listen()
    if WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text, and real screen sizes
        except OSError:
            pass
    log(f'{APP} {VERSION} starting')
    App('--background' in sys.argv, server).root.mainloop()


if __name__ == '__main__':
    main()
