# -*- coding: utf-8 -*-
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import requests
import os, re, base64, hashlib, time, threading, json, subprocess, sys, platform, tempfile
from bs4 import BeautifulSoup
import cv2
import urllib3
from PIL import Image, ImageOps, ImageTk

# ==================== HEIC ПІДТРИМКА ====================
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== ЗВУК ====================
try:
    import winsound
    WINSOUND = True
except ImportError:
    WINSOUND = False

# --- ГЛОБАЛЬНІ ШЛЯХИ (Mac .app bundle aware) ---
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if platform.system() == 'Darwin':
        # FIX: .app bundle read-only — пишемо дані в ~/Library/Application Support/
        APP_DIR  = os.path.join(os.path.expanduser('~'), 'Library',
                                'Application Support', 'CharmDateBot')
        os.makedirs(APP_DIR, exist_ok=True)
        # FIX: bin/ знаходиться в _MEIPASS (поруч з виконуваним файлом)
        _BIN_DIR = os.path.join(_exe_dir, 'bin')
        if not os.path.isdir(_BIN_DIR):
            _BIN_DIR = os.path.normpath(
                os.path.join(_exe_dir, '..', 'Resources', 'bin'))
    else:
        APP_DIR  = _exe_dir
        _BIN_DIR = os.path.join(APP_DIR, 'bin')
else:
    APP_DIR  = os.path.dirname(os.path.abspath(__file__))
    _BIN_DIR = os.path.join(APP_DIR, 'bin')

os.chdir(APP_DIR)
CONFIG_FILE = os.path.join(APP_DIR, 'profiles_v99.json')

# FIX: тимчасові файли в системному /tmp — APP_DIR може бути недоступний для запису
_TMP       = tempfile.gettempdir()
TEMP_IMAGE = os.path.join(_TMP, 'cd_temp.jpg')
TEMP_VIDEO = os.path.join(_TMP, 'cd_video.mp4')
TEMP_THUMB = os.path.join(_TMP, 'cd_thumb.jpg')

ctk.set_appearance_mode('Dark')

class PhotoUploaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.COLOR_BG           = '#121212'
        self.COLOR_PANEL        = '#1E1E1E'
        self.COLOR_ACCENT       = '#D00050'
        self.COLOR_ACCENT_HOVER = '#FF0060'
        self.COLOR_INPUT        = '#0D0D0D'
        self.COLOR_TEXT         = '#F0F0F0'

        self.photo_title_pairs  = []
        self.image_refs         = []
        self.is_running         = False
        self.session            = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9'
        })
        self.available_albums    = {}
        self.album_counts        = {}
        self.album_names         = {}
        self.selected_album_id   = "NEW"
        self.video_key           = ""
        self.upload_token        = ""
        self.profiles            = {}
        self.current_profile_name = "Default"
        self.current_cap         = None
        self.video_label         = None
        self.video_after_id      = None
        self.current_playing_path = None

        # FIX MAC: chmod ffmpeg/ffprobe — файли всередині .app bundle
        # можуть не мати біту виконання після розпакування
        if platform.system() == 'Darwin':
            for _name in ('ffmpeg', 'ffprobe'):
                for _d in [_BIN_DIR,
                           APP_DIR,
                           os.path.join(os.path.dirname(sys.executable), 'bin')
                               if getattr(sys, 'frozen', False) else '',
                           os.path.normpath(os.path.join(
                               os.path.dirname(sys.executable), '..', 'Resources', 'bin'))
                               if getattr(sys, 'frozen', False) else '']:
                    if not _d:
                        continue
                    _p = os.path.join(_d, _name)
                    if os.path.exists(_p):
                        try:
                            os.chmod(_p, 0o755)
                        except:
                            pass

        self._create_ui()
        self.load_config()

    # =========================================================================
    # UI BUILD
    # =========================================================================
    def _create_ui(self):
        C = {
            'bg':'#0A0A0C', 'surface':'#111116', 'panel':'#16161D',
            'border':'#232330', 'border2':'#2E2E40',
            'accent':'#D00050', 'accent2':'#FF1060',
            'text':'#E8E8F0', 'dim':'#6B6B80', 'mid':'#9999AA',
            'input':'#0D0D10',
        }
        self._C = C
        self.configure(fg_color=C['bg'])
        self.title('CharmDate Media Center v99.0')
        self.geometry('960x720')
        self.resizable(False, False)

        # ── top bar ──
        topbar = tk.Frame(self, bg=C['surface'], height=48)
        topbar.pack(side='top', fill='x')
        topbar.pack_propagate(False)
        tk.Label(topbar, text='C', bg=C['accent'], fg='white',
                 font=('Segoe UI',12,'bold'), width=2).pack(side='left', padx=(14,6), pady=10)
        tk.Label(topbar, text='CharmDate', bg=C['surface'], fg=C['accent'],
                 font=('Segoe UI',13,'bold')).pack(side='left')
        tk.Label(topbar, text='Media Center', bg=C['surface'], fg=C['text'],
                 font=('Segoe UI',12)).pack(side='left')
        self._status_canvas = tk.Canvas(topbar, width=10, height=10,
                                        bg=C['surface'], highlightthickness=0)
        self._status_canvas.pack(side='right', padx=(0,8), pady=19)
        self._status_dot = self._status_canvas.create_oval(1,1,9,9, fill='#444', outline='')
        tk.Label(topbar, text='v99.0', bg=C['surface'], fg=C['dim'],
                 font=('Consolas',9)).pack(side='right', padx=(0,6))
        tk.Frame(self, bg=C['accent'], height=1).pack(fill='x')

        body = tk.Frame(self, bg=C['bg'])
        body.pack(expand=True, fill='both', padx=14, pady=14)

        # ── LEFT column ──
        left = tk.Frame(body, bg=C['bg'], width=290)
        left.pack(side='left', fill='y', padx=(0,12))
        left.pack_propagate(False)

        self._mk_card_header(left, '👤 ПРОФІЛІ')
        pf_card = self._mk_card(left)
        pf_row = tk.Frame(pf_card, bg=C['panel'])
        pf_row.pack(fill='x', padx=12, pady=(8,4))
        self.profile_var = tk.StringVar(value='Default')
        self.profile_menu = ctk.CTkOptionMenu(
            pf_row, variable=self.profile_var, values=['Default'],
            fg_color=C['input'], button_color='#252530',
            button_hover_color=C['accent'], text_color=C['text'],
            font=('Segoe UI',12), dropdown_fg_color=C['surface'],
            dropdown_text_color=C['text'], corner_radius=8,
            command=self.change_profile)
        self.profile_menu.pack(side='left', fill='x', expand=True, ipady=1)
        ctk.CTkButton(pf_row, text='+', width=30, height=30, fg_color='#252530',
                      hover_color=C['accent'], text_color=C['mid'], corner_radius=8,
                      command=self.add_profile).pack(side='left', padx=(5,3))
        ctk.CTkButton(pf_row, text='🗑', width=30, height=30, fg_color='#252530',
                      hover_color='#7A0000', text_color=C['mid'], corner_radius=8,
                      command=self.delete_profile).pack(side='left')

        self.entry_agency   = self._mk_field(pf_card, 'ID АГЕНТСТВА',  'C1358')
        self.entry_staff    = self._mk_field(pf_card, 'ID СПІВРОБІТНИКА','S67720')
        self.entry_pass     = self._mk_field(pf_card, 'ПАРОЛЬ',         '', show='*')
        self.entry_woman_id = self._mk_field(pf_card, 'ID ЖІНКИ',       'C260072')

        self._mk_card_header(left, '🎯 НАЛАШТУВАННЯ ЦІЛІ')
        tg_card = self._mk_card(left)
        tabs = tk.Frame(tg_card, bg='#0D0D10')
        tabs.pack(fill='x', padx=12, pady=(10,8))
        self.mode_var  = tk.StringVar(value='Short Video')
        self._mode_tabs = {}
        for mode, label in [('Mail Photos','Пошта'),
                             ('Private Photos','Приватні'),
                             ('Short Video','Відео')]:
            b = tk.Button(tabs, text=label, bg='#0D0D10', fg=C['dim'],
                          activebackground=C['accent'], activeforeground='white',
                          font=('Segoe UI',10,'bold'), relief='flat', bd=0,
                          padx=6, pady=5, cursor='hand2',
                          command=lambda m=mode: self._switch_mode(m))
            b.pack(side='left', fill='x', expand=True)
            self._mode_tabs[mode] = b
        self._update_mode_tabs('Short Video')

        tk.Label(tg_card, text='АЛЬБОМ', bg=C['panel'], fg=C['dim'],
                 font=('Segoe UI',9,'bold')).pack(anchor='w', padx=14, pady=(4,2))
        self.album_var = tk.StringVar(value='-- Не підключено --')
        self.album_dropdown = ctk.CTkOptionMenu(
            tg_card, variable=self.album_var,
            values=['-- Не підключено --'],
            fg_color=C['input'], button_color='#252530',
            button_hover_color=C['accent'], text_color=C['text'],
            font=('Segoe UI',11), dropdown_fg_color=C['surface'],
            dropdown_text_color=C['text'], corner_radius=8,
            command=self.on_album_ui_select)
        self.album_dropdown.pack(fill='x', padx=12, pady=(0,12), ipady=1)

        tk.Label(left, text='◈ ЛОГ', bg=C['bg'], fg=C['dim'],
                 font=('Segoe UI',9,'bold')).pack(anchor='w', pady=(8,3))
        log_outer = tk.Frame(left, bg=C['border'], bd=1)
        log_outer.pack(fill='both', expand=True)
        self.log_box = tk.Text(log_outer, font=('Consolas',10),
                               bg=C['surface'], fg=C['mid'], relief='flat',
                               bd=0, padx=10, pady=8, state='disabled',
                               wrap='word', cursor='arrow')
        self.log_box.pack(fill='both', expand=True)
        self.log_box.tag_config('ok',  foreground='#00C97A')
        self.log_box.tag_config('err', foreground='#FF1060')
        self.log_box.tag_config('inf', foreground='#5B8CFF')
        self.log_box.tag_config('dim', foreground=C['mid'])

        # ── RIGHT column ──
        right = tk.Frame(body, bg=C['bg'])
        right.pack(side='right', expand=True, fill='both')

        step_row = tk.Frame(right, bg=C['bg'])
        step_row.pack(fill='x', pady=(0,8))
        self.btn_fetch  = self._mk_btn(step_row, '1 СКАН',    self.fetch_albums_thread)
        self.btn_select = self._mk_btn(step_row, '2 ВИБРАТИ', self.select_media)
        self.btn_titles = self._mk_btn(step_row, '3 НАЗВИ',   self.load_and_erase_titles)
        for b in (self.btn_fetch, self.btn_select, self.btn_titles):
            b.pack(side='left', fill='x', expand=True, padx=3)

        self._prog_bg   = tk.Frame(right, bg=C['border2'], height=3)
        self._prog_bg.pack(fill='x', pady=(0,8))
        self._prog_fill = tk.Frame(self._prog_bg, bg=C['accent'], height=3)
        self._prog_fill.place(x=0, y=0, relwidth=0, height=3)

        qh = tk.Frame(right, bg=C['bg'])
        qh.pack(fill='x', pady=(0,4))
        tk.Label(qh, text='◈ ЧЕРГА ЗАВДАНЬ', bg=C['bg'], fg=C['dim'],
                 font=('Segoe UI',9,'bold')).pack(side='left')
        self._queue_count_lbl = tk.Label(qh, text='', bg=C['bg'], fg=C['accent'],
                                         font=('Consolas',9,'bold'))
        self._queue_count_lbl.pack(side='right')

        qo = tk.Frame(right, bg=C['border'], bd=1)
        qo.pack(fill='both', expand=True)
        self.scroll = ctk.CTkScrollableFrame(
            qo, fg_color=C['surface'],
            scrollbar_button_color=C['border2'],
            scrollbar_button_hover_color=C['accent'],
            corner_radius=0)
        self.scroll.pack(fill='both', expand=True)

        bottom = tk.Frame(right, bg=C['bg'])
        bottom.pack(fill='x', pady=(10,0))
        self.btn_start = ctk.CTkButton(
            bottom, text='▶ ПОЧАТИ', height=46,
            fg_color=C['accent'], hover_color=C['accent2'],
            text_color='white', font=('Segoe UI',14,'bold'),
            corner_radius=10, state='disabled', command=self.start_thread)
        self.btn_start.pack(side='left', fill='x', expand=True)
        self.btn_stop = ctk.CTkButton(
            bottom, text='■', width=46, height=46,
            fg_color='#1A1A22', hover_color='#3A0010',
            text_color=C['dim'], font=('Segoe UI',14),
            corner_radius=10, state='disabled', command=self.stop)
        self.btn_stop.pack(side='left', padx=(8,0))

    # ── helpers ──────────────────────────────────────────────────────────────
    def _mk_card_header(self, parent, title):
        tk.Label(parent, text=title, bg=self._C['bg'], fg=self._C['dim'],
                 font=('Segoe UI',9,'bold')).pack(anchor='w', pady=(10,3))

    def _mk_card(self, parent):
        outer = tk.Frame(parent, bg=self._C['border'], bd=1)
        outer.pack(fill='x', pady=(0,4))
        inner = tk.Frame(outer, bg=self._C['panel'])
        inner.pack(fill='both', expand=True, padx=1, pady=1)
        return inner

    def _mk_field(self, parent, label, placeholder, show=''):
        C = self._C
        tk.Label(parent, text=label, bg=C['panel'], fg=C['dim'],
                 font=('Segoe UI',8,'bold')).pack(anchor='w', padx=14, pady=(6,1))
        e = ctk.CTkEntry(parent, placeholder_text=placeholder, show=show,
                         height=32, corner_radius=8, font=('Segoe UI',12),
                         border_width=1, border_color=C['border2'],
                         fg_color=C['input'], text_color=C['text'],
                         placeholder_text_color=C['dim'])
        e.pack(fill='x', padx=12, pady=(0,4))
        self._bind_clipboard(e)
        return e

    def _mk_btn(self, parent, text, cmd):
        C = self._C
        return ctk.CTkButton(
            parent, text=text, height=38,
            fg_color=C['panel'], hover_color=C['border2'],
            text_color=C['mid'], font=('Segoe UI',10,'bold'),
            border_width=1, border_color=C['border2'],
            corner_radius=9, command=cmd)

    def _update_mode_tabs(self, active):
        C = self._C
        for m, b in self._mode_tabs.items():
            b.configure(bg=C['accent'] if m == active else '#0D0D10',
                        fg='white' if m == active else C['dim'])

    def _switch_mode(self, mode):
        self.mode_var.set(mode)
        self._update_mode_tabs(mode)
        self.on_mode_change(mode)

    def _bind_clipboard(self, w):
        menu = tk.Menu(w, tearoff=0, bg=self.COLOR_PANEL, fg=self.COLOR_TEXT,
                       relief='flat', font=('Segoe UI',10))
        inner = w._entry if hasattr(w, '_entry') else w
        menu.add_command(label='Вирізати',    command=lambda: inner.event_generate('<<Cut>>'))
        menu.add_command(label='Копіювати',   command=lambda: inner.event_generate('<<Copy>>'))
        menu.add_command(label='Вставити',    command=lambda: inner.event_generate('<<Paste>>'))
        menu.add_separator()
        menu.add_command(label='Вибрати все', command=lambda: inner.event_generate('<<SelectAll>>'))
        # Mac: правий клік — Button-2 (трекпад) та Button-3
        w.bind('<Button-2>', lambda e: menu.tk_popup(e.x_root, e.y_root))
        w.bind('<Button-3>', lambda e: menu.tk_popup(e.x_root, e.y_root))
        # Mac: Command+ (основний спосіб)
        w.bind('<Command-v>', lambda e: (inner.event_generate('<<Paste>>'),     'break')[1])
        w.bind('<Command-c>', lambda e: (inner.event_generate('<<Copy>>'),      'break')[1])
        w.bind('<Command-x>', lambda e: (inner.event_generate('<<Cut>>'),       'break')[1])
        w.bind('<Command-a>', lambda e: (inner.event_generate('<<SelectAll>>'), 'break')[1])
        # Control+ (на випадок підключеної Windows-клавіатури до Mac)
        w.bind('<Control-v>', lambda e: (inner.event_generate('<<Paste>>'),     'break')[1])
        w.bind('<Control-c>', lambda e: (inner.event_generate('<<Copy>>'),      'break')[1])
        w.bind('<Control-x>', lambda e: (inner.event_generate('<<Cut>>'),       'break')[1])
        w.bind('<Control-a>', lambda e: (inner.event_generate('<<SelectAll>>'), 'break')[1])

    def _edit(self, w, action):
        inner = w._entry if hasattr(w, '_entry') else w
        if action == 'paste':   inner.event_generate('<<Paste>>')
        elif action == 'copy':  inner.event_generate('<<Copy>>')
        elif action == 'cut':   inner.event_generate('<<Cut>>')

    # =========================================================================
    def set_status(self, ok):
        self._status_canvas.itemconfig(self._status_dot,
                                       fill='#00C97A' if ok else '#444')

    def set_progress(self, done, total):
        self._prog_fill.place(x=0, y=0,
                              relwidth=(done/total if total else 0), height=3)

    def update_queue_count(self):
        n = len(self.photo_title_pairs)
        self._queue_count_lbl.configure(text=f'{n} файлів' if n else '')

    # ── sound ─────────────────────────────────────────────────────────────────
    def _play_done_sound(self):
        if WINSOUND:
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        elif platform.system() == 'Darwin':
            try:
                subprocess.Popen(['afplay', '/System/Library/Sounds/Funk.aiff'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        else:
            try:
                subprocess.Popen(['paplay', '/usr/share/sounds/freedesktop/stereo/complete.oga'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    # ── config ───────────────────────────────────────────────────────────────
    def load_config(self):
        try:
            with open(CONFIG_FILE,'r') as f:
                data = json.load(f)
            self.profiles = data.get('profiles', {'Default':{'a':'','s':'','p':'','w':''}})
            self.current_profile_name = data.get('last_profile','Default')
        except:
            self.profiles = {'Default':{'a':'','s':'','p':'','w':''}}
        self._refresh_profile_ui()

    def save_config(self):
        self.profiles[self.current_profile_name] = {
            'a': self.entry_agency.get().strip(),
            's': self.entry_staff.get().strip(),
            'p': self.entry_pass.get().strip(),
            'w': self.entry_woman_id.get().strip()
        }
        with open(CONFIG_FILE,'w') as f:
            json.dump({'profiles':self.profiles,
                       'last_profile':self.current_profile_name}, f)

    def _refresh_profile_ui(self):
        self.profile_menu.configure(values=list(self.profiles.keys()))
        self.profile_var.set(self.current_profile_name)
        d = self.profiles.get(self.current_profile_name, {})
        for k, v in {'a':self.entry_agency,'s':self.entry_staff,
                     'p':self.entry_pass,'w':self.entry_woman_id}.items():
            v.delete(0,'end')
            v.insert(0, d.get(k,''))

    def change_profile(self, name):
        self.save_config()
        self.current_profile_name = name
        self._refresh_profile_ui()

    def add_profile(self):
        d = ctk.CTkInputDialog(text="Ім'я:", title='Новий профіль')
        n = d.get_input()
        if n and n not in self.profiles:
            self.save_config()
            self.profiles[n] = {'a':'','s':'','p':'','w':''}
            self.current_profile_name = n
            self._refresh_profile_ui()

    def delete_profile(self):
        if len(self.profiles) <= 1:
            return
        del self.profiles[self.current_profile_name]
        self.current_profile_name = list(self.profiles.keys())[0]
        self._refresh_profile_ui()
        self.save_config()

    # ── ffmpeg ───────────────────────────────────────────────────────────────
    def _get_ffmpeg(self):
        # FIX MAC: перевіряємо всі можливі місця всередині .app bundle
        candidates = [os.path.join(_BIN_DIR, 'ffmpeg'),
                      os.path.join(APP_DIR, 'ffmpeg')]
        if getattr(sys, 'frozen', False):
            _exe = os.path.dirname(sys.executable)
            candidates += [
                os.path.join(_exe, 'bin', 'ffmpeg'),
                os.path.normpath(os.path.join(_exe, '..', 'Resources', 'bin', 'ffmpeg')),
            ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return 'ffmpeg'

    def _get_ffprobe(self):
        # FIX: не використовуємо replace щоб не зламати шлях де є 'ffmpeg' в назві папки
        ff = self._get_ffmpeg()
        fp = os.path.join(os.path.dirname(ff), 'ffprobe')
        return fp if os.path.exists(fp) else 'ffprobe'

    def _detect_hw_encoder(self, ff):
        # FIX MAC: VideoToolbox — нативний Apple GPU encoder (M1/M2/Intel Mac)
        if platform.system() == 'Darwin':
            encs = [('h264_videotoolbox', ['-realtime', 'true'])]
        else:
            encs = [('h264_nvenc',['-preset','p1','-tune','ll']),
                    ('h264_amf',['-quality','speed']),
                    ('h264_qsv',['-preset','veryfast'])]
        for enc, args in encs:
            try:
                r = subprocess.run(
                    [ff,'-y','-f','lavfi','-i','nullsrc=s=128x128:d=1',
                     '-c:v',enc,'-f','null','-'],
                    capture_output=True, timeout=8)
                if r.returncode == 0:
                    self.log(f'→ GPU: {enc}')
                    return enc, args
            except:
                pass
        self.log('→ CPU: libx264')
        return 'libx264', ['-preset','ultrafast']

    def _probe(self, path, ffprobe):
        try:
            r = subprocess.run(
                [ffprobe,'-v','error','-select_streams','v:0',
                 '-show_entries','stream=width,height,codec_name,duration',
                 '-of','json', path],
                capture_output=True, timeout=10)
            s = json.loads(r.stdout).get('streams',[{}])[0]
            return (int(s.get('width',0)), int(s.get('height',0)),
                    s.get('codec_name',''), float(s.get('duration',99)))
        except:
            return 0, 0, '', 99

    def process_video_dan(self, path):
        try:
            t0 = time.time()
            ff = self._get_ffmpeg(); fp = self._get_ffprobe()
            w, h, codec, dur = self._probe(path, fp)
            self.log(f'→ Відео: {w}x{h} {codec} {dur:.1f}s')
            enc, enc_args = self._detect_hw_encoder(ff)
            self.log('→ Конвертація...')
            cmd = [ff,'-y','-i',path,'-t','14',
                   '-vf','scale=-2:1280,crop=720:ih',
                   '-c:v',enc, *enc_args,
                   '-b:v','12000k','-minrate','10000k',
                   '-maxrate','15000k','-bufsize','20000k',
                   '-c:a','aac','-b:a','128k','-threads','0', TEMP_VIDEO]
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            if r.returncode != 0:
                self.log(f'FFmpeg помилка: {r.stderr.decode(errors="ignore")[-300:]}')
                return None, None
            sz = os.path.getsize(TEMP_VIDEO)
            self.log(f'→ Готово: {sz//1024}KB ({time.time()-t0:.1f}с)')
            if sz > 40 * 1024 * 1024:
                self.log(f'Файл {sz//1024//1024}МБ > 40МБ ліміт!')
                return None, None
            subprocess.run(
                [ff,'-y','-i',TEMP_VIDEO,'-ss','1','-vframes','1',
                 '-vf','scale=720:1080:force_original_aspect_ratio=disable',
                 TEMP_THUMB],
                capture_output=True, timeout=30)
            return TEMP_VIDEO, TEMP_THUMB
        except subprocess.TimeoutExpired:
            self.log('Таймаут!'); return None, None
        except Exception as e:
            self.log(f'Помилка: {e}'); return None, None

    # ── video preview ─────────────────────────────────────────────────────────
    def stop_video(self):
        if self.video_after_id:
            self.after_cancel(self.video_after_id)
            self.video_after_id = None
        if self.current_cap:
            self.current_cap.release()
            self.current_cap = None
        self.current_playing_path = None

    def play_video_inline(self, path, lbl):
        if self.current_playing_path == path:
            self.stop_video(); return
        self.stop_video()
        self.current_playing_path = path
        self.video_label = lbl
        self.current_cap = cv2.VideoCapture(path)
        self.update_video_frame()

    def update_video_frame(self):
        if self.current_cap and self.current_cap.isOpened():
            ret, frame = self.current_cap.read()
            if not ret:
                self.current_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.current_cap.read()
            if ret:
                frame = cv2.resize(frame, (80,80))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = ImageTk.PhotoImage(image=Image.fromarray(frame))
                self.video_label.configure(image=img)
                self.video_label.image = img
            self.video_after_id = self.after(33, self.update_video_frame)

    def generate_preview(self, path):
        try:
            if str(path).lower().endswith(('.mp4','.mov','.avi','.mkv','.hevc','.h265')):
                cap = cv2.VideoCapture(path)
                ret, frame = cap.read()
                cap.release()
                if not ret:
                    return None
                pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            else:
                pil = ImageOps.exif_transpose(Image.open(path))
            pil.thumbnail((80,80), Image.Resampling.LANCZOS)
            return pil
        except:
            return None

    def log(self, msg):
        self.log_box.configure(state='normal')
        ts = time.strftime('%H:%M:%S')
        if any(w in msg for w in ('УСПІХ','SUCCESS','OK','захоплено')):
            tag = 'ok'
        elif any(w in msg for w in ('помилка','Помилка','FAILED','Error','FAIL','Таймаут')):
            tag = 'err'
        elif any(w in msg for w in ('Автентифікація','Конвертація')):
            tag = 'inf'
        else:
            tag = 'dim'
        self.log_box.insert('end', f'[{ts}] {msg}\n', tag)
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    # ── mode / album ──────────────────────────────────────────────────────────
    def on_mode_change(self, mode):
        self.stop_video()
        for w in self.scroll.winfo_children():
            w.destroy()
        self.photo_title_pairs.clear()
        self.image_refs.clear()
        self.set_progress(0, 0)
        self.available_albums = {}
        self.selected_album_id = 'NEW'
        self.album_dropdown.configure(values=['-- Потрібен повторний скан --'])
        self.album_var.set('-- Потрібен повторний скан --')
        self.btn_start.configure(state='disabled')

    def on_album_ui_select(self, choice):
        self.selected_album_id = self.available_albums.get(choice, 'NEW')
        self.log(f'Ціль: {self.selected_album_id}')

    # =========================================================================
    # FETCH ALBUMS
    # =========================================================================
    def fetch_albums_thread(self):
        self.save_config()
        self.btn_fetch.configure(state='disabled', text='СКАНУВАННЯ...')
        threading.Thread(target=self.do_fetch, daemon=True).start()

    def do_fetch(self):
        self.log('Автентифікація...')
        lp = {
            'agentid':   self.entry_agency.get().strip(),
            'staff_id':  self.entry_staff.get().strip(),
            'passwd':    self.entry_pass.get().strip(),
            'agentlogin':'Login'
        }
        try:
            u1 = base64.b64decode(b'aHR0cHM6Ly93d3cuY2hhcm1kYXRlLmNvbS9jbGFndC9sb2dpbmIuaHRt').decode()
            u2 = base64.b64decode(b'aHR0cHM6Ly93d3cuY2hhcm1kYXRlLmNvbS9jbGFndC9sb2dpbi5waHA=').decode()
            self.session.get(u1, verify=False, timeout=10)
            self.session.headers.update({'Referer': u1})
            rp = self.session.post(u2, data=lp, verify=False,
                                   allow_redirects=True, timeout=15)
            if 'loginb.htm' in rp.url:
                self.log('Вхід НЕ УСПІШНИЙ.')
                self.btn_fetch.configure(state='normal', text='СКАН')
                return False

            wid  = self.entry_woman_id.get().strip()
            mode = self.mode_var.get()

            up_m = {'Mail Photos':    'women_album_upload',
                    'Private Photos': 'private_photo_upload',
                    'Short Video':    'short_video_upload'}
            li_m = {'Mail Photos':    'women_album',
                    'Private Photos': 'private_photo_list',
                    'Short Video':    'short_video_list'}

            upu = f'https://www.charmdate.com/clagt/woman/{up_m[mode]}.php?womanid={wid}'
            liu = f'https://www.charmdate.com/clagt/woman/{li_m[mode]}.php?womanid={wid}'

            self.session.headers.update({'Referer': rp.url})
            rli = self.session.get(liu, verify=False, timeout=15)
            self.session.headers.update({'Referer': rli.url})
            rup = self.session.get(upu, verify=False, timeout=15)

            vk = re.search(r'videoKey["\']?\s*[:=]\s*["\']?([a-fA-F0-9]{32})', rup.text)
            ut = re.search(r'uploadToken["\']?\s*[:=]\s*["\']?([a-fA-F0-9]{32})', rup.text)
            if not ut:
                ut = re.search(r'uploadToken.*?value=["\'](.*?)(?=["\'])', rup.text)
            self.video_key    = vk.group(1) if vk else ''
            self.upload_token = ut.group(1) if ut else ''

            soup_li = BeautifulSoup(rli.text, 'html.parser')
            soup_up = BeautifulSoup(rup.text, 'html.parser')

            album_list = ['--- СТВОРИТИ НОВИЙ АЛЬБОМ ---']
            self.available_albums = {'--- СТВОРИТИ НОВИЙ АЛЬБОМ ---': 'NEW'}
            self.album_counts = {}
            self.album_names  = {}

            seen_aids = set()
            for tbl in soup_li.find_all('table', width='150'):
                link = tbl.find('a', href=re.compile(r'albumid='))
                if not link:
                    continue
                href = link.get('href', '')
                if 'flag=' in href and 'flag=&' not in href and not href.endswith('flag='):
                    continue
                m = re.search(r'albumid=([A-Z0-9]+)', href)
                if not m:
                    continue
                aid = m.group(1)
                if aid in seen_aids:
                    continue
                seen_aids.add(aid)

                name_td = tbl.find('td', class_='albumfont')
                if name_td:
                    pn = name_td.get_text(strip=True)
                else:
                    first_h40 = tbl.find('td', height='40')
                    pn = first_h40.get_text(strip=True) if first_h40 else ''
                pn = pn or f'Album-{aid}'

                cnt = 0
                txt = tbl.get_text(' ', strip=True)
                cm = re.search(r'(\d+)\s*(?:photo(?:\(s\)|s)?|videos?)', txt, re.IGNORECASE)
                if cm:
                    cnt = int(cm.group(1))

                unit = 'відео' if mode == 'Short Video' else 'фото'
                disp = f'{pn} ({cnt}/30)'
                self.available_albums[disp] = aid
                self.album_counts[aid]       = cnt
                self.album_names[aid]        = pn
                album_list.append(disp)
                self.log(f'→ Альбом: {pn} [{aid}] = {cnt} {unit}')

            if len(album_list) == 1:
                self.log('Тайли не знайдено, пробую select...')
                sel = soup_up.find('select', {'name': 'albumid'}) or soup_up.find('select')
                if not sel:
                    self.log('Список альбомів не знайдено.')
                    self.btn_fetch.configure(state='normal', text='СКАН')
                    return False
                for opt in sel.find_all('option'):
                    aid = opt.get('value')
                    if not aid:
                        continue
                    pn = opt.text.split('(')[0].strip() or f'Album-{aid}'
                    cnt = 0
                    lnk = soup_li.find('a', href=re.compile(rf'albumid={re.escape(aid)}'))
                    if lnk:
                        node = lnk
                        for _ in range(5):
                            node = node.parent
                            if node is None:
                                break
                            t = node.get_text(' ', strip=True)
                            cm = re.search(r'(\d+)\s*(?:photo(?:\(s\)|s)?|videos?)', t, re.IGNORECASE)
                            if cm:
                                cnt = int(cm.group(1))
                                break
                    disp = f'{pn} ({cnt}/30)'
                    self.available_albums[disp] = aid
                    self.album_counts[aid]       = cnt
                    self.album_names[aid]        = pn
                    album_list.append(disp)

            self.album_dropdown.configure(values=album_list)
            self.album_var.set(album_list[0])
            self.btn_start.configure(state='normal')
            self.btn_fetch.configure(state='normal', text='СКАН')
            self.after(0, lambda: self.set_status(True))
            self.log(f'Ціль захоплено. Альбомів: {len(album_list)-1}')
            return True

        except requests.exceptions.RequestException:
            self.log('Мережа втрачена.')
        except Exception as e:
            self.log(f'Помилка: {e}')
        self.btn_fetch.configure(state='normal', text='СКАН')
        return False

    # ── media selection ───────────────────────────────────────────────────────
    def select_media(self):
        self.stop_video()
        mode = self.mode_var.get()
        if mode == 'Short Video':
            exts = [('Відео','*.mp4 *.mov *.hevc *.mkv *.avi')]
        else:
            h = ' *.heic *.heif' if HEIC_SUPPORTED else ''
            exts = [('Зображення', ('*.jpg *.jpeg *.png' + h).strip())]
        paths = filedialog.askopenfilenames(filetypes=exts)
        if not paths:
            return

        for w in self.scroll.winfo_children():
            w.destroy()
        self.photo_title_pairs.clear()
        self.image_refs.clear()

        for p in paths:
            f = ctk.CTkFrame(self.scroll, fg_color='#181818',
                             corner_radius=8, border_width=1, border_color='#222')
            f.pack(fill='x', pady=3, padx=5)
            il = tk.Label(f, bg='#181818', width=80, height=80)
            il.pack(side='left', padx=10, pady=5)
            pi = self.generate_preview(p)
            if pi:
                ti = ImageTk.PhotoImage(pi)
                self.image_refs.append(ti)
                il.configure(image=ti)
            ctrl = ctk.CTkFrame(f, fg_color='transparent')
            ctrl.pack(side='left', padx=5)
            if str(p).lower().endswith(('.mp4','.mov','.hevc','.mkv','.avi')):
                ctk.CTkButton(ctrl, text='PLAY', width=45, height=22,
                              font=('Segoe UI Bold',9),
                              fg_color=self.COLOR_ACCENT,
                              hover_color=self.COLOR_ACCENT_HOVER,
                              command=lambda pp=p, ll=il:
                                  self.play_video_inline(pp, ll)).pack(pady=2)
            e = ctk.CTkEntry(f, font=('Segoe UI Semibold',13),
                             border_width=0, fg_color='#0D0D0D', height=38,
                             placeholder_text='Ввести назву...')
            e.pack(side='right', padx=15, pady=10, fill='x', expand=True)
            self._bind_clipboard(e)
            self.photo_title_pairs.append({'path': p, 'entry': e})

        self.update_queue_count()
        self.scroll.update()

    def load_and_erase_titles(self):
        p = filedialog.askopenfilename(filetypes=[('Текст','*.txt')])
        if not p:
            return
        try:
            with open(p,'r',encoding='utf-8') as f:
                lines = [l.strip() for l in f if l.strip()]
            for i, item in enumerate(self.photo_title_pairs):
                if i < len(lines):
                    item['entry'].delete(0,'end')
                    item['entry'].insert(0, lines[i])
        except:
            pass

    # =========================================================================
    # UPLOAD WORKER
    # =========================================================================
    def start_thread(self):
        self.stop_video()
        self.is_running = True
        self.btn_start.configure(state='disabled')
        self.btn_stop.configure(state='normal')
        threading.Thread(target=self.work, daemon=True).start()

    def stop(self):
        self.is_running = False

    def _is_success(self, text, status_code):
        if status_code == 302:
            return True
        t = text.lower()
        for marker in ('successful','success','upload ok','uploadok','上传成功'):
            if marker in t:
                return True
        if 'lady profile' in t or 'lady_profile' in t:
            return True
        if '<title>lady' in t:
            return True
        if '<title></title>' in t and 'font-family' in t:
            return True
        if status_code == 200 and 'font-family: "arial"' in t and 'error' not in t and 'fail' not in t:
            return True
        return False

    def _prepare_photo(self, path):
        img = Image.open(path)
        try:
            img = ImageOps.exif_transpose(img)
        except:
            pass
        if img.mode != 'RGB':
            img = img.convert('RGB')
        w, h = img.size
        max_side = max(w, h)
        if max_side > 3200:
            img.thumbnail((3200,3200), Image.Resampling.LANCZOS)
            self.log(f'→ Зменшено: {w}x{h} → {img.size[0]}x{img.size[1]}')
        elif max_side < 800:
            scale = 800 / max_side
            img = img.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
            self.log(f'→ Збільшено: {w}x{h} → {img.size[0]}x{img.size[1]}')

        quality = 95
        img.save(TEMP_IMAGE, 'JPEG', quality=quality)
        file_kb = os.path.getsize(TEMP_IMAGE) // 1024
        while file_kb > 5000 and quality > 50:
            quality -= 10
            img.save(TEMP_IMAGE, 'JPEG', quality=quality)
            file_kb = os.path.getsize(TEMP_IMAGE) // 1024
            self.log(f'→ Стиснення quality={quality}: {file_kb}KB')
        if file_kb < 100:
            img.save(TEMP_IMAGE, 'JPEG', quality=99)
            file_kb = os.path.getsize(TEMP_IMAGE) // 1024
        self.log(f'→ Temp збережено: {file_kb}KB')
        if not (100 <= file_kb <= 5000):
            self.log(f'Розмір {file_kb}KB поза межами 100KB-5MB!')
            return False
        return True

    def work(self):
        wid   = self.entry_woman_id.get().strip()
        tasks = self.photo_title_pairs
        mode  = self.mode_var.get()
        self.save_config()

        for i, item in enumerate(tasks):
            if not self.is_running:
                break
            aid   = self.selected_album_id
            count = self.album_counts.get(aid, 0)

            if aid == 'NEW' or count >= 30:
                self.log('Альбом повний. Потрібен новий...')
                d = ctk.CTkInputDialog(text='Назва нового альбому:', title='Створити альбом')
                new_name = d.get_input()
                if new_name:
                    cs = {'Short Video':'short_video_album_update.php',
                          'Private Photos':'private_album_update.php',
                          'Mail Photos':'album_update.php'}.get(mode,'album_update.php')
                    self.session.post(
                        f'https://www.charmdate.com/clagt/woman/{cs}',
                        data={'womanid':wid,'update':'createAlbum','albumid':'A',
                              'albumName':new_name,'albumDesc':'','Submit':'Confirm '},
                        verify=False, timeout=30)
                    time.sleep(5)
                    self.do_fetch()
                    if not self.album_counts:
                        self.log('Не вдалося отримати новий альбом.')
                        break
                    aid = list(self.album_counts.keys())[-1]
                    self.selected_album_id = aid
                    count = 0

            self.log(f'Завантаження {i+1}/{len(tasks)}...')
            success = False

            if mode == 'Short Video':
                if not self.upload_token:
                    self.log('Токен відсутній.'); break
                v_f, t_f = self.process_video_dan(item['path'])
                if not v_f:
                    continue
                v_s = os.path.getsize(v_f)
                v_m = hashlib.md5(open(v_f,'rb').read()).hexdigest()
                info = {'videoType':'shortVideo','womanid':wid,
                        'agentid':self.entry_agency.get().strip(),
                        'siteid':'4','num':'1','videoKey':self.video_key,
                        'serverType':'0','uploadToken':self.upload_token}
                chunks     = (v_s // 2048000) + 1
                fid        = ''
                upload_ok  = True
                self.log(f'→ Чанків: {chunks} ({v_s//1024}KB)')

                for c in range(chunks):
                    start = c * 2048000; end = min(v_s, start + 2048000)
                    with open(v_f,'rb') as f:
                        f.seek(start); chunk = f.read(end - start)
                    self.log(f'→ Чанк {c+1}/{chunks}...')
                    try:
                        res = self.session.post(
                            base64.b64decode(
                                b'aHR0cHM6Ly9pbS5lc2gtY29ycC5jb20vRmlsZVVwbG9hZC9maWxldXBsb2FkZXIucGhwP2FjdD11cGxvYWQ='
                            ).decode(),
                            files={'filedata':('v.mp4',chunk,'application/octet-stream')},
                            data={'filename':'v.mp4','trunkIndex':str(c),
                                  'uploadInfo':json.dumps(info, separators=(',',':'))},
                            verify=False, timeout=60)
                        rj = res.json()
                        self.log(f'→ Чанк {c+1}: errno={rj.get("errno")}')
                        if rj.get('errno') == 200:
                            fid = rj.get('final_file', fid)
                    except Exception as e:
                        self.log(f'Помилка чанку {c+1}: {e}')
                        upload_ok = False; break

                if not upload_ok:
                    try: os.remove(v_f); os.remove(t_f)
                    except: pass
                    continue

                self.log('→ JOIN...')
                info.update({'fileExt':'mp4','trunkTotal':str(chunks)})
                try:
                    jr = self.session.post(
                        base64.b64decode(
                            b'aHR0cHM6Ly9pbS5lc2gtY29ycC5jb20vRmlsZVVwbG9hZC9maWxldXBsb2FkZXIucGhwP2FjdD1qb2lu'
                        ).decode(),
                        data=info, verify=False, timeout=60).json()
                    self.log(f'→ JOIN: {jr}')
                except Exception as e:
                    self.log(f'JOIN помилка: {e}')
                    try: os.remove(v_f); os.remove(t_f)
                    except: pass
                    continue

                final_fid = jr.get('final_file', fid)
                if final_fid:
                    self.log('→ Реєстрація...')
                    with open(t_f,'rb') as ft:
                        pd = [('hidFileID',(None,final_fid)),
                              ('hidFileSizeID',(None,str(v_s))),
                              ('hidFileMd5ID',(None,jr.get('file_md5',v_m))),
                              ('hidVideoKey',(None,self.video_key)),
                              ('womanid',(None,wid)),('albumid',(None,aid)),
                              ('short_video_desc',(None,item['entry'].get() or 'Beauty')),
                              ('short_video_img',('t.jpg',ft,'image/jpeg')),
                              ('photoIndex',(None,'5')),('actionto',(None,'onlyUpload')),
                              ('update',(None,'uploadPhoto')),('Submit',(None,' Upload '))]
                        try:
                            r = self.session.post(
                                'https://www.charmdate.com/clagt/woman/short_video_album_update.php',
                                files=pd, verify=False, timeout=60)
                            self.log(f'→ Статус: {r.status_code}')
                            success = self._is_success(r.text, r.status_code)
                            if not success:
                                self.log(f'→ Відповідь: {r.text.replace(chr(10)," ")[:300]}')
                        except Exception as e:
                            self.log(f'Помилка реєстрації: {e}')
                else:
                    self.log(f'final_fid порожній! jr={jr}')
                try: os.remove(v_f); os.remove(t_f)
                except: pass

            else:
                try:
                    ok = self._prepare_photo(item['path'])
                except Exception as e:
                    ext = os.path.splitext(item['path'])[1].lower()
                    if ext in ('.heic','.heif') and not HEIC_SUPPORTED:
                        self.log('HEIC не підтримується! pip install pillow-heif')
                    else:
                        self.log(f'Не вдалося відкрити файл: {e}')
                    continue
                if not ok:
                    continue

                file_kb        = os.path.getsize(TEMP_IMAGE) // 1024
                upload_timeout = max(120, file_kb // 50)
                self.log(f'→ Таймаут: {upload_timeout}с')

                with open(TEMP_IMAGE,'rb') as fh:
                    cl = re.sub(r'[^\w\s]', '', item['entry'].get() or 'Photo', flags=re.UNICODE).strip()[:30]
                    p  = [('womanid',(None,wid)),('albumid',(None,aid)),
                          ('photoIndex',(None,'5')),('actionto',(None,'onlyUpload')),
                          ('photo1',(os.path.basename(item['path']),fh,'image/jpeg')),
                          ('update',(None,'uploadPhoto')),('Submit',(None,' Upload '))]
                    if mode == 'Mail Photos':
                        p.append(('photodesc[]',(None,cl)))
                    else:
                        p.append(('photodesc1',(None,cl)))
                    sc = 'album_update.php' if mode == 'Mail Photos' else 'private_album_update.php'
                    try:
                        res = self.session.post(
                            f'https://www.charmdate.com/clagt/woman/{sc}'
                            f'?albumid={aid}&womanid={wid}',
                            files=p, verify=False, timeout=upload_timeout)
                        self.log(f'→ Статус: {res.status_code}')
                        success = self._is_success(res.text, res.status_code)
                        if not success:
                            self.log(f'→ Відповідь: {res.text.replace(chr(10)," ")[:300]}')
                    except requests.exceptions.Timeout:
                        self.log(f'Таймаут! Файл {file_kb}KB, ліміт {upload_timeout}с')
                    except Exception as e:
                        self.log(f'Помилка завантаження: {e}')

                try: os.remove(TEMP_IMAGE)
                except: pass

            if success:
                self.album_counts[aid] += 1
                cnt = self.album_counts[aid]
                self.after(0, lambda d=f"{self.album_names[aid]} ({cnt}/30)":
                               self.album_var.set(d))
                self.log(f'УСПІХ ({cnt}/30)')
                try: os.remove(item['path'])
                except: pass
            else:
                self.log(f'[!] ПОМИЛКА {i+1}')

            self.after(0, lambda done=i+1, total=len(tasks):
                           self.set_progress(done, total))
            time.sleep(1)

        self.log('ГОТОВО.')
        self._play_done_sound()
        self.btn_start.configure(state='normal')
        self.btn_stop.configure(state='disabled')


if __name__ == '__main__':
    app = PhotoUploaderApp()
    app.mainloop()
