# -*- coding: utf-8 -*-
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import requests
import os, re, base64, hashlib, time, threading, json, subprocess, sys, platform, random, tempfile
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    import winsound
    WINSOUND = True
except ImportError:
    WINSOUND = False

from bs4 import BeautifulSoup
import cv2
import urllib3
from PIL import Image, ImageOps, ImageTk, ImageFilter
import math

# ==================== HEIC ПІДТРИМКА ====================
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

# ==================== ПЕРЕКЛАДАЧ (опціонально) ====================
try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ГЛОБАЛЬНІ ШЛЯХИ (Mac .app bundle aware) ---
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if platform.system() == 'Darwin':
        # .app bundle read-only — пишемо дані в ~/Library/Application Support/
        APP_DIR  = os.path.join(os.path.expanduser('~'), 'Library',
                                'Application Support', 'CharmDateBot')
        os.makedirs(APP_DIR, exist_ok=True)
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
# Тимчасові файли в /tmp — APP_DIR може бути read-only на macOS
_TMP        = tempfile.gettempdir()
TEMP_IMAGE  = os.path.join(_TMP, 'cd_temp.jpg')
TEMP_VIDEO  = os.path.join(_TMP, 'cd_video.mp4')
TEMP_THUMB  = os.path.join(_TMP, 'cd_thumb.jpg')

ctk.set_appearance_mode('Dark')

# ── Drag & Drop support (optional) ──
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

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

        # Activate TkinterDnD on this CTk window if available
        if _DND_AVAILABLE:
            try:
                TkinterDnD._require(self)
            except Exception:
                pass

        # FIX MAC: знімаємо quarantine та ставимо права на ffmpeg/ffprobe —
        # без цього macOS блокує запуск бінарників з .app
        if platform.system() == 'Darwin':
            for _name in ('ffmpeg', 'ffprobe'):
                for _d in [_BIN_DIR,
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
                            subprocess.run(['xattr', '-rd', 'com.apple.quarantine', _p],
                                           capture_output=True)
                        except Exception:
                            pass

        self._create_ui()
        self.load_config()
        # Auto-scan if profile credentials already filled
        self.after(800, self._auto_scan_if_ready)

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
        # FIX MAC: на Retina 960x720 виглядає крихітним + вікно не розтягувалось
        if platform.system() == 'Darwin':
            self.geometry('1100x820')
        else:
            self.geometry('960x720')
        self.resizable(True, True)

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

        log_hdr = tk.Frame(left, bg=C['bg'])
        log_hdr.pack(fill='x', pady=(8,3))
        tk.Label(log_hdr, text='◈ ЛОГ', bg=C['bg'], fg=C['dim'],
                 font=('Segoe UI',9,'bold')).pack(side='left')
        tk.Button(log_hdr, text='💾', bg=C['bg'], fg=C['dim'], relief='flat',
                  font=('Segoe UI',9), cursor='hand2', bd=0,
                  command=self.save_log).pack(side='right', padx=(4,0))
        tk.Button(log_hdr, text='🗑', bg=C['bg'], fg=C['dim'], relief='flat',
                  font=('Segoe UI',9), cursor='hand2', bd=0,
                  command=self.clear_log).pack(side='right')
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
        step_row.pack(fill='x', pady=(0,6))
        self.btn_fetch  = self._mk_btn(step_row, '1 СКАН',    self.fetch_albums_thread)
        self.btn_select = self._mk_btn(step_row, '2 ВИБРАТИ', self.select_media)
        self.btn_add    = self._mk_btn(step_row, '+ ДОДАТИ',  self.add_media)
        self.btn_titles = self._mk_btn(step_row, '3 НАЗВИ',   self.load_and_erase_titles)
        for b in (self.btn_fetch, self.btn_select, self.btn_add, self.btn_titles):
            b.pack(side='left', fill='x', expand=True, padx=2)

        # ── AI strip toggle ──
        ai_row = tk.Frame(right, bg=C['bg'])
        ai_row.pack(fill='x', pady=(4,2))
        self.strip_ai_var = tk.BooleanVar(value=False)
        self.strip_ai_chk = ctk.CTkCheckBox(
            ai_row, text='🧹 Стерти ІІ сліди (метадані + шум)',
            variable=self.strip_ai_var,
            fg_color=C['accent'], hover_color=C['accent2'],
            text_color=C['mid'], font=('Segoe UI',10),
            border_color=C['border2'], corner_radius=4,
            checkbox_width=20, checkbox_height=20)
        self.strip_ai_chk.pack(side='left')

        self.translate_var = tk.BooleanVar(value=False)
        self.translate_chk = ctk.CTkCheckBox(
            ai_row, text='🌐 Авто-переклад назв → EN',
            variable=self.translate_var,
            fg_color=C['accent'], hover_color=C['accent2'],
            text_color=C['mid'], font=('Segoe UI',10),
            border_color=C['border2'], corner_radius=4,
            checkbox_width=20, checkbox_height=20)
        self.translate_chk.pack(side='left', padx=(16,0))
        # ── Progress bar with counter ──
        prog_row = tk.Frame(right, bg=C['bg'])
        prog_row.pack(fill='x', pady=(0,6))
        self._prog_bg   = tk.Frame(prog_row, bg=C['border2'], height=4)
        self._prog_bg.pack(side='left', fill='x', expand=True)
        self._prog_fill = tk.Frame(self._prog_bg, bg=C['accent'], height=4)
        self._prog_fill.place(x=0, y=0, relwidth=0, height=4)
        self._prog_lbl = tk.Label(prog_row, text='', bg=C['bg'], fg=C['dim'],
                                  font=('Consolas',9), width=7)
        self._prog_lbl.pack(side='left', padx=(6,0))

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
        # ── Drag & Drop ──
        self._setup_dnd(self.scroll)
        self._setup_dnd(qo)

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
        _show = lambda e: menu.tk_popup(e.x_root, e.y_root)
        w.bind('<Button-3>', _show)
        if platform.system() == 'Darwin':
            w.bind('<Button-2>', _show)   # Control+click на трекпаді macOS

        def _ctrl_any(event):
            kc = event.keycode
            if kc == 86:   # V — Paste
                inner.event_generate('<<Paste>>');     return 'break'
            if kc == 67:   # C — Copy
                inner.event_generate('<<Copy>>');      return 'break'
            if kc == 88:   # X — Cut
                inner.event_generate('<<Cut>>');       return 'break'
            if kc == 65:   # A — Select All
                inner.event_generate('<<SelectAll>>'); return 'break'

        inner.bind('<Control-KeyPress>', _ctrl_any, add=True)
        if platform.system() == 'Darwin':
            # macOS: буфер обміну — Command, а не Control
            w.bind('<Command-v>', lambda e: (inner.event_generate('<<Paste>>'),     'break')[1])
            w.bind('<Command-c>', lambda e: (inner.event_generate('<<Copy>>'),      'break')[1])
            w.bind('<Command-x>', lambda e: (inner.event_generate('<<Cut>>'),       'break')[1])
            w.bind('<Command-a>', lambda e: (inner.event_generate('<<SelectAll>>'), 'break')[1])

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

    def _auto_scan_if_ready(self):
        a = self.entry_agency.get().strip()
        s = self.entry_staff.get().strip()
        p = self.entry_pass.get().strip()
        w = self.entry_woman_id.get().strip()
        if a and s and p and w:
            self.log('Автозапуск сканування...')
            self.fetch_albums_thread()

    def toast(self, msg, color='#00C97A'):
        t = tk.Toplevel(self)
        t.overrideredirect(True)
        t.attributes('-topmost', True)
        t.attributes('-alpha', 0.92)
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        w2 = 320; h2 = 48
        t.geometry(f'{w2}x{h2}+{sw-w2-20}+{sh-h2-60}')
        tk.Label(t, text=msg, bg=color, fg='white',
                 font=('Segoe UI',12,'bold'), padx=20).pack(expand=True, fill='both')
        t.after(3000, t.destroy)

    # ── Album creation offer ─────────────────────────────────────────────────
    def _offer_create_album(self, wid, mode):
        d = ctk.CTkInputDialog(
            text='Альбомів не знайдено. Введіть назву для створення першого:',
            title='Створити альбом')
        new_name = d.get_input()
        if not new_name:
            return
        cs = {'Short Video':    'short_video_album_update.php',
              'Private Photos': 'private_album_update.php',
              'Mail Photos':    'album_update.php'}.get(mode, 'album_update.php')
        try:
            self.session.post(
                f'https://www.charmdate.com/clagt/woman/{cs}',
                data={'womanid': wid, 'update': 'createAlbum', 'albumid': 'A',
                      'albumName': new_name, 'albumDesc': '', 'Submit': 'Confirm '},
                verify=False, timeout=30)
            self.log(f'→ Альбом "{new_name}" створено. Повторний скан...')
            self.after(4000, self.fetch_albums_thread)
        except Exception as e:
            self.log(f'Помилка створення: {e}')

    # ── Sound ─────────────────────────────────────────────────────────────────
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

    # ── Drag & Drop ──────────────────────────────────────────────────────────
    def _setup_dnd(self, widget):
        if not _DND_AVAILABLE:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>', self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        raw = event.data
        # Parse space-separated paths, handle {path with spaces}
        paths = []
        import shlex
        try:
            paths = shlex.split(raw.replace('\\', '/'))
        except Exception:
            paths = raw.split()
        mode = self.mode_var.get()
        video_ext = ('.mp4','.mov','.hevc','.mkv','.avi')
        img_ext   = ('.jpg','.jpeg','.png','.heic','.heif')
        accepted = 0
        for p in paths:
            p = p.strip('{}')
            ext = os.path.splitext(p)[1].lower()
            if mode == 'Short Video' and ext in video_ext:
                self._add_queue_item(p); accepted += 1
            elif mode != 'Short Video' and ext in img_ext:
                self._add_queue_item(p); accepted += 1
        if accepted:
            self.update_queue_count()
            self.scroll.update()
            self.log(f'→ DnD: додано {accepted} файлів')

    def clear_log(self):
        self.log_box.configure(state='normal')
        self.log_box.delete('1.0', 'end')
        self.log_box.configure(state='disabled')

    def save_log(self):
        p = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('Текст','*.txt')],
            initialfile=f'log_{time.strftime("%Y%m%d_%H%M%S")}.txt')
        if p:
            with open(p, 'w', encoding='utf-8') as fout:
                fout.write(self.log_box.get('1.0', 'end'))

    def add_media(self):
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
        for p in paths:
            self._add_queue_item(p)
        self.update_queue_count()
        self.scroll.update()

    def _add_queue_item(self, p):
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
        status_lbl = tk.Label(ctrl, text='', bg='#181818',
                              font=('Segoe UI',14), width=2)
        status_lbl.pack()
        item = {'path': p, 'entry': None, 'status_lbl': status_lbl, 'frame': f}
        tk.Button(f, text='✕', bg='#181818', fg='#555', relief='flat',
                  font=('Segoe UI',11), cursor='hand2', bd=0,
                  activebackground='#181818', activeforeground='#FF1060',
                  command=lambda fr=f, it=item: self._remove_queue_item(fr, it)
                  ).pack(side='right', padx=6)
        e = ctk.CTkEntry(f, font=('Segoe UI Semibold',13),
                         border_width=0, fg_color='#0D0D0D', height=38,
                         placeholder_text='Ввести назву...')
        e.pack(side='right', padx=(0,6), pady=10, fill='x', expand=True)
        self._bind_clipboard(e)
        item['entry'] = e
        self.photo_title_pairs.append(item)

    def _remove_queue_item(self, frame, item):
        if item in self.photo_title_pairs:
            self.photo_title_pairs.remove(item)
        frame.destroy()
        self.update_queue_count()

    # ── config ───────────────────────────────────────────────────────────────
    def load_config(self):
        try:
            with open(CONFIG_FILE,'r') as f:
                data = json.load(f)
            self.profiles = data.get('profiles', {'Default':{'a':'','s':'','p':'','w':''}})
            self.current_profile_name = data.get('last_profile','Default')
            self.strip_ai_var.set(data.get('strip_ai', False))
            self.translate_var.set(data.get('translate', False))
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
                       'last_profile':self.current_profile_name,
                       'strip_ai':self.strip_ai_var.get(),
                       'translate':self.translate_var.get()}, f)

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
        # FIX MAC: на macOS бінарник зветься 'ffmpeg' без .exe, і лежить
        # усередині .app — перевіряємо всі можливі місця
        candidates = [os.path.join(_BIN_DIR, 'ffmpeg'),
                      os.path.join(APP_DIR,  'ffmpeg')]
        if getattr(sys, 'frozen', False):
            _exe = os.path.dirname(sys.executable)
            candidates += [
                os.path.join(_exe, 'bin', 'ffmpeg'),
                os.path.normpath(os.path.join(_exe, '..', 'Resources', 'bin', 'ffmpeg')),
            ]
        candidates += [os.path.join(_BIN_DIR, 'ffmpeg.exe'),
                       os.path.join(APP_DIR,  'ffmpeg.exe')]
        for c in candidates:
            if os.path.exists(c):
                return c
        return 'ffmpeg'

    def _get_ffprobe(self):
        # FIX: не replace() — зламався б шлях, де 'ffmpeg' є в назві папки
        ff = self._get_ffmpeg()
        d  = os.path.dirname(ff)
        for n in ('ffprobe', 'ffprobe.exe'):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
        return 'ffprobe'

    # ── Параметри під правила сайту ──────────────────────────────────────────
    # Duration 8-15s | Pixels 720-1280 | Bitrate >10000kbps | Size <=40MB
    VID_SECS   = 14        # -t: ріже довгі до 14с (в межах 8-15)
    VID_MIN_S  = 8.0       # коротше — сайт відхилить
    VID_KBPS   = 12000     # цільовий бітрейт (з запасом над 10000)
    VID_MAX_MB = 40

    def _detect_hw_encoder(self, ff):
        # CBR-параметри для кожного енкодера — БЕЗ них бітрейт провалюється
        # нижче 10000kbps на статичних сценах (перевірено: 85kbps!)
        K = self.VID_KBPS
        if platform.system() == 'Darwin':
            encs = [('h264_videotoolbox',
                     ['-realtime','true','-b:v',f'{K}k','-maxrate',f'{K}k',
                      '-bufsize',f'{K}k'])]
        else:
            encs = [('h264_nvenc',
                     ['-preset','p4','-rc','cbr','-b:v',f'{K}k',
                      '-maxrate',f'{K}k','-bufsize',f'{K}k']),
                    ('h264_amf',
                     ['-usage','transcoding','-rc','cbr','-b:v',f'{K}k',
                      '-maxrate',f'{K}k','-bufsize',f'{K}k']),
                    ('h264_qsv',
                     ['-preset','veryfast','-b:v',f'{K}k',
                      '-maxrate',f'{K}k','-bufsize',f'{K}k'])]
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
        return 'libx264', self._cpu_enc_args()

    def _cpu_enc_args(self):
        # nal-hrd=cbr ГАРАНТУЄ бітрейт (доповнює filler-даними).
        # Без нього libx264 віддає 85kbps на статичному відео.
        K = self.VID_KBPS
        return ['-preset','veryfast','-b:v',f'{K}k','-minrate',f'{K}k',
                '-maxrate',f'{K}k','-bufsize',f'{K}k',
                '-x264-params','nal-hrd=cbr:force-cfr=1']

    def _ff_root_error(self, stderr_bytes):
        # Витягує ПЕРШУ справжню помилку. Раніше бралися останні 800 символів —
        # там лише статистика енкодера, а причина губилась.
        txt = stderr_bytes.decode(errors='ignore')
        skip = ('task finished with error code', 'terminating thread',
                'conversion failed', 'nothing was written')
        keys = ('error', 'invalid', 'unsupported', 'not supported', 'could not',
                'unable to', 'no such', 'failed', 'cannot', 'incorrect',
                'does not contain', 'no decoder')
        hits = []
        for ln in txt.splitlines():
            low = ln.lower()
            if any(s in low for s in skip):
                continue
            if any(k in low for k in keys):
                ln = ln.strip()
                if ln and ln not in hits:
                    hits.append(ln)
            if len(hits) >= 3:
                break
        return ' | '.join(hits) if hits else txt.strip()[-300:]

    def _probe(self, path, ffprobe):
        """(w, h, codec, duration, pix_fmt). duration читаємо з format —
        у MKV та частині MOV поля stream=duration просто немає."""
        w = h = 0; codec = ''; pix = ''; dur = 0.0
        try:
            r = subprocess.run(
                [ffprobe,'-v','error','-select_streams','v:0',
                 '-show_entries','stream=width,height,codec_name,pix_fmt',
                 '-of','json', path],
                capture_output=True, timeout=15)
            st = json.loads(r.stdout or '{}').get('streams', [])
            if st:
                s = st[0]
                w     = int(s.get('width')  or 0)
                h     = int(s.get('height') or 0)
                codec = s.get('codec_name') or ''
                pix   = s.get('pix_fmt')    or ''
        except Exception:
            pass
        try:
            r = subprocess.run(
                [ffprobe,'-v','error','-show_entries','format=duration',
                 '-of','json', path],
                capture_output=True, timeout=15)
            d = json.loads(r.stdout or '{}').get('format', {}).get('duration')
            if d and d != 'N/A':
                dur = float(d)
        except Exception:
            pass
        return w, h, codec, dur, pix

    def _bitrate_kbps(self, path, dur):
        try:
            if not dur:
                return 0
            return int(os.path.getsize(path) * 8 / dur / 1000)
        except Exception:
            return 0

    def process_video_dan(self, path):
        try:
            t0 = time.time()
            ff = self._get_ffmpeg(); fp = self._get_ffprobe()
            w, h, codec, dur, pix = self._probe(path, fp)
            self.log(f'→ Відео: {w}x{h} {codec} {pix or "?"} {dur:.1f}s')

            if not w or not h:
                self.log('[!] Не вдалося прочитати відеопотік. Файл пошкоджений?')
                return None, None

            # ПРАВИЛО 8-15с: -t ріже довгі, але коротке відео не подовжить
            if dur and dur < self.VID_MIN_S:
                self.log(f'[!] Тривалість {dur:.1f}с < {self.VID_MIN_S:.0f}с — '
                         f'сайт відхилить. Пропускаю.')
                return None, None

            enc, enc_args = self._detect_hw_encoder(ff)

            # format=yuv420p ОБОВ'ЯЗКОВИЙ: iPhone HDR = 10-бітний HEVC,
            # апаратні енкодери 10 біт на H.264 не приймають → "Invalid data"
            vf = ('scale=720:1280:force_original_aspect_ratio=increase,'
                  'crop=720:1280,format=yuv420p')

            def _run(encoder, eargs):
                cmd = [ff,'-y','-fflags','+genpts','-i',path,
                       '-map','0:v:0','-map','0:a:0?',
                       '-t',str(self.VID_SECS),
                       '-vf', vf,
                       '-c:v',encoder, *eargs,
                       '-pix_fmt','yuv420p',
                       '-c:a','aac','-b:a','128k','-ac','2',
                       '-movflags','+faststart', TEMP_VIDEO]
                return subprocess.run(cmd, capture_output=True, timeout=240)

            self.log('→ Конвертація...')
            r = _run(enc, enc_args)

            # Апаратний енкодер впав → CPU (libx264 їсть будь-який формат)
            if r.returncode != 0 and enc != 'libx264':
                self.log(f'[!] {enc}: {self._ff_root_error(r.stderr)}')
                self.log('→ Повтор через CPU (libx264)...')
                enc = 'libx264'
                r = _run('libx264', self._cpu_enc_args())

            if r.returncode != 0:
                self.log(f'FFmpeg помилка: {self._ff_root_error(r.stderr)}')
                return None, None
            if not os.path.exists(TEMP_VIDEO) or os.path.getsize(TEMP_VIDEO) < 2048:
                self.log('[!] Вихідний файл порожній.')
                return None, None

            ow, oh, _oc, odur, _op = self._probe(TEMP_VIDEO, fp)
            kbps = self._bitrate_kbps(TEMP_VIDEO, odur)

            # Апаратний енкодер не дотягнув бітрейт → CPU з CBR (гарантує)
            if kbps and kbps < 10000 and enc != 'libx264':
                self.log(f'[!] {enc} дав {kbps}kbps < 10000. Повтор через CPU...')
                r = _run('libx264', self._cpu_enc_args())
                if r.returncode == 0 and os.path.exists(TEMP_VIDEO):
                    ow, oh, _oc, odur, _op = self._probe(TEMP_VIDEO, fp)
                    kbps = self._bitrate_kbps(TEMP_VIDEO, odur)

            sz = os.path.getsize(TEMP_VIDEO)
            self.log(f'→ Готово: {ow}x{oh}, {odur:.1f}с, ~{kbps}kbps, '
                     f'{sz//1024}KB (за {time.time()-t0:.1f}с)')

            # Фінальна перевірка по правилах сайту
            if odur and odur < self.VID_MIN_S:
                self.log(f'[!] На виході {odur:.1f}с < {self.VID_MIN_S:.0f}с — відхилять.')
                return None, None
            if kbps and kbps < 10000:
                self.log(f'[!] УВАГА: {kbps}kbps < 10000 — сайт може відхилити.')
            if sz > self.VID_MAX_MB * 1024 * 1024:
                self.log(f'[!] {sz//1024//1024}МБ > {self.VID_MAX_MB}МБ ліміт!')
                return None, None

            # Прев'ю — з середини ролика + ПЕРЕВІРКА (раніше результат не
            # перевірявся → міг піти старий кадр від попереднього відео)
            try: os.remove(TEMP_THUMB)
            except: pass
            mid = max(0.5, (odur or 2.0) / 2)
            rt = subprocess.run(
                [ff,'-y','-ss',f'{mid:.2f}','-i',TEMP_VIDEO,'-frames:v','1',
                 '-vf','scale=720:1080:force_original_aspect_ratio=disable',
                 '-q:v','2', TEMP_THUMB],
                capture_output=True, timeout=30)
            if rt.returncode != 0 or not os.path.exists(TEMP_THUMB) \
                    or os.path.getsize(TEMP_THUMB) < 512:
                self.log('[!] Прев\'ю не створено (сайт вимагає кадр з відео).')
                return None, None

            return TEMP_VIDEO, TEMP_THUMB
        except subprocess.TimeoutExpired:
            self.log('Таймаут конвертації!'); return None, None
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
    # FIX: fetch_albums — robust Mail Photos album count parsing
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

            # =================================================================
            # UNIFIED tile parser — works for ALL modes.
            # All three list pages use <table width="150"> album tiles:
            #   • <a href="...?albumid=XXXX&...">          → albumid
            #   • <td class="albumfont">Name</td>          → album name
            #   • "N photo(s)" or "N videos" in tile text  → count
            #
            # We skip tiles that have &flag= in the link (pending approval).
            # =================================================================
            seen_aids = set()
            for tbl in soup_li.find_all('table', width='150'):
                link = tbl.find('a', href=re.compile(r'albumid='))
                if not link:
                    continue
                href = link.get('href', '')
                # Skip "pending approval" tiles (flag=2 etc.)
                if 'flag=' in href and 'flag=&' not in href and not href.endswith('flag='):
                    continue
                m = re.search(r'albumid=([A-Z0-9]+)', href)
                if not m:
                    continue
                aid = m.group(1)
                if aid in seen_aids:
                    continue
                seen_aids.add(aid)

                # ── album name ────────────────────────────────────────────────
                name_td = tbl.find('td', class_='albumfont')
                if name_td:
                    pn = name_td.get_text(strip=True)
                else:
                    first_h40 = tbl.find('td', height='40')
                    pn = first_h40.get_text(strip=True) if first_h40 else ''
                pn = pn or f'Album-{aid}'

                # ── count: "N photo(s)" OR "N videos" ────────────────────────
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

            # Fallback to <select> if tile parsing found nothing
            if len(album_list) == 1:
                self.log('Тайли не знайдено, пробую select...')
                sel = soup_up.find('select', {'name': 'albumid'}) or soup_up.find('select')
                if not sel:
                    self.log('Список альбомів не знайдено.')
                    # Offer to create first album immediately
                    self.after(0, lambda: self._offer_create_album(wid, mode))
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

            # If still no albums found at all — offer to create one
            if len(album_list) == 1:
                self.log('Альбомів немає. Пропоную створити...')
                self.after(0, lambda: self._offer_create_album(wid, mode))
                self.btn_fetch.configure(state='normal', text='СКАН')
                return False

            self.album_dropdown.configure(values=album_list)
            # Auto-select best album: prefer partially filled (>0 and <30)
            best_disp = album_list[0]
            best_cnt  = -1
            for disp, aid2 in self.available_albums.items():
                if aid2 == 'NEW':
                    continue
                c2 = self.album_counts.get(aid2, 0)
                if c2 < 30 and c2 > best_cnt:
                    best_cnt  = c2
                    best_disp = disp
            self.album_var.set(best_disp)
            self.selected_album_id = self.available_albums.get(best_disp, 'NEW')
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
        # Clear existing queue
        for w in self.scroll.winfo_children():
            w.destroy()
        self.photo_title_pairs.clear()
        self.image_refs.clear()
        for p in paths:
            self._add_queue_item(p)
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

    def _translate_to_en(self, text):
        """Перекладає текст на англійську. Кеш + м'який fallback на оригінал."""
        text = (text or '').strip()
        if not text:
            return text
        # якщо переклад вимкнено — повертаємо як є
        if not self.translate_var.get():
            return text
        # якщо бібліотека не встановлена
        if not TRANSLATOR_AVAILABLE:
            self.log('→ Переклад недоступний (pip install deep-translator)')
            return text
        # якщо текст вже латиницею (ASCII) — не перекладаємо
        if all(ord(c) < 128 for c in text):
            return text
        # кеш
        if not hasattr(self, '_tr_cache'):
            self._tr_cache = {}
        if text in self._tr_cache:
            return self._tr_cache[text]
        try:
            result = GoogleTranslator(source='auto', target='en').translate(text)
            result = (result or text).strip()
            self._tr_cache[text] = result
            self.log(f'→ Переклад: "{text}" → "{result}"')
            return result
        except Exception as e:
            self.log(f'→ Помилка перекладу ({e}), залишаю оригінал')
            self._tr_cache[text] = text
            return text

    def _extract_html_body_text(self, text):
        """Витягує видимий текст з <body>, обрізає CSS/скрипти."""
        try:
            soup = BeautifulSoup(text, 'html.parser')
            for tag in soup(['style','script','head']):
                tag.decompose()
            body_text = soup.get_text(' ', strip=True)
            return body_text[:800] if body_text else '(порожня відповідь)'
        except:
            # fallback: наївне очищення
            import re as _re
            clean = _re.sub(r'<style[^>]*>.*?</style>', '', text, flags=_re.DOTALL|_re.I)
            clean = _re.sub(r'<script[^>]*>.*?</script>', '', clean, flags=_re.DOTALL|_re.I)
            clean = _re.sub(r'<head[^>]*>.*?</head>', '', clean, flags=_re.DOTALL|_re.I)
            clean = _re.sub(r'<[^>]+>', ' ', clean)
            clean = _re.sub(r'\s+', ' ', clean).strip()
            return clean[:800] if clean else '(порожня відповідь)'

    def _is_success(self, text, status_code):
        if status_code == 302:
            return True
        t = text.lower()
        # explicit success markers
        for marker in ('successful','success','upload ok','uploadok','上传成功',
                        'uploaded','完成','album_update','photo has been'):
            if marker in t:
                return True
        # Mail Photos success: server redirects to Lady Profile page
        if 'lady profile' in t or 'lady_profile' in t:
            return True
        # Private Photos success: same profile page pattern
        if '<title>lady' in t:
            return True
        # Short Video success: page with album list or confirmation form
        if 'short_video_album' in t and 'error' not in t:
            return True
        # Generic: HTML page returned without error keywords = likely OK
        if status_code == 200 and '<html' in t:
            err_markers = ('error','fail','denied','reject','invalid','expired',
                           'помилка','ошибка','відхилено')
            if not any(e in t for e in err_markers):
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

      # ── Strip AI traces if enabled (Bypass SynthID) ──
        if self.strip_ai_var.get():
            self.log('→ Жорстке знищення SynthID та метаданих...')
            
            # 1) Абсолютное удаление метаданных
            clean = Image.new('RGB', img.size)
            clean.putdata(list(img.getdata()))
            img = clean

            w, h = img.size
            
            # 2) Масштабирование (туда-сюда) — убивает высокочастотные водяные знаки
            down_size = (int(w * 0.85), int(h * 0.85))
            img = img.resize(down_size, Image.Resampling.BILINEAR)
            img = img.resize((w, h), Image.Resampling.BICUBIC)
            
            # 3) Микро-ротация — ломает пространственную сетку SynthID
            angle = random.uniform(-0.4, 0.4)
            img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
            
            # 4) Субпиксельный блюр + жесткий Unsharp Mask — переписывает пиксельные градиенты
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
            img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))

            # 5) Динамический Гауссовский шум (лучше обычного random)
            arr = np.array(img, dtype=np.int16)
            noise = np.random.normal(0, 3.0, arr.shape).astype(np.int16)
            arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)

            # 6) Жесткая микро-обрезка со сдвигом — сбивает якоря детектора
            crop_amount = random.randint(3, 6)
            img = img.crop((crop_amount, crop_amount, w - crop_amount, h - crop_amount))
            img = img.resize((w, h), Image.Resampling.LANCZOS)

            self.log('→ SynthID та ІІ відбитки випалено')

        w, h = img.size
        min_side = min(w, h)
        max_side = max(w, h)
        self.log(f'→ Розмір оригіналу: {w}x{h} (min={min_side}, max={max_side})')
        # Сайт вимагає ОБИДВІ сторони в діапазоні 800-3200
        if max_side > 3200:
            img.thumbnail((3200,3200), Image.Resampling.LANCZOS)
            self.log(f'→ Зменшено: {w}x{h} → {img.size[0]}x{img.size[1]}')
            w, h = img.size
            min_side = min(w, h)
        if min_side < 800:
            scale = 800 / min_side
            new_w, new_h = int(w*scale), int(h*scale)
            # перевіряємо щоб не вийти за 3200
            if max(new_w, new_h) > 3200:
                scale = 3200 / max(w, h)
                new_w, new_h = int(w*scale), int(h*scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            self.log(f'→ Збільшено: {w}x{h} → {img.size[0]}x{img.size[1]}')
        w, h = img.size
        self.log(f'→ Фінальний розмір: {w}x{h}')

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
                # === REFRESH TOKEN перед кожним відео ===
                self.log('→ Оновлення токена...')
                try:
                    _upu = f'https://www.charmdate.com/clagt/woman/short_video_upload.php?womanid={wid}'
                    _rup = self.session.get(_upu, verify=False, timeout=15)
                    _vk  = re.search(r'videoKey["\']?\s*[:=]\s*["\']?([a-fA-F0-9]{32})', _rup.text)
                    _ut  = re.search(r'uploadToken["\']?\s*[:=]\s*["\']?([a-fA-F0-9]{32})', _rup.text)
                    if not _ut:
                        _ut = re.search(r'uploadToken.*?value=["\'](.*?)(?=["\'])', _rup.text)
                    if _vk: self.video_key    = _vk.group(1)
                    if _ut: self.upload_token = _ut.group(1)
                    self.log(f'→ Token: ...{self.upload_token[-8:] if self.upload_token else "НЕ ЗНАЙДЕНО"}')
                    self.session.headers.update({'Referer': _upu})
                except Exception as _e:
                    self.log(f'→ Не вдалось оновити токен: {_e}')
                # ========================================

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
                CHUNK_SIZE = 2 * 1024 * 1024  # 2MB chunks
                PARALLEL   = 6
                chunks     = (v_s + CHUNK_SIZE - 1) // CHUNK_SIZE
                fid        = ''
                upload_ok  = True
                _upload_url = base64.b64decode(
                    b'aHR0cHM6Ly9pbS5lc2gtY29ycC5jb20vRmlsZVVwbG9hZC9maWxldXBsb2FkZXIucGhwP2FjdD11cGxvYWQ='
                ).decode()
                self.log(f'→ Чанків: {chunks} ({v_s//1024}KB, паралельно: {PARALLEL})')

                # Pre-read all chunks into memory to avoid file seek races
                _chunks_data = []
                with open(v_f, 'rb') as _f:
                    for c in range(chunks):
                        _f.seek(c * CHUNK_SIZE)
                        _chunks_data.append(_f.read(min(CHUNK_SIZE, v_s - c * CHUNK_SIZE)))

                # Build a proper session copy per thread (shares cookies snapshot)
                def _make_sess():
                    s = requests.Session()
                    s.headers.update(dict(self.session.headers))
                    s.cookies.update(requests.utils.dict_from_cookiejar(self.session.cookies))
                    s.verify = False
                    return s

                _fid_lock = threading.Lock()

                def upload_chunk(c):
                    sess = _make_sess()
                    for _retry in range(3):
                        if _retry > 0:
                            time.sleep(5 * _retry)
                        try:
                            res = sess.post(
                                _upload_url,
                                files={'filedata': ('v.mp4', _chunks_data[c], 'application/octet-stream')},
                                data={'filename': 'v.mp4', 'trunkIndex': str(c),
                                      'uploadInfo': json.dumps(info, separators=(',', ':'))},
                                timeout=120)
                            rj = res.json()
                            if rj.get('errno') == 200:
                                with _fid_lock:
                                    nonlocal fid
                                    if rj.get('final_file'):
                                        fid = rj['final_file']
                                self.log(f'→ Чанк {c+1}/{chunks}: OK')
                                return True
                            else:
                                self.log(f'→ Чанк {c+1} errno={rj.get("errno")}, повтор...')
                        except Exception as e:
                            self.log(f'→ Чанк {c+1} помилка (спроба {_retry+1}/3): {e}')
                    self.log(f'[!] Чанк {c+1} не завантажено після 3 спроб')
                    return False

                with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
                    futures = {pool.submit(upload_chunk, c): c for c in range(chunks)}
                    for fut in as_completed(futures):
                        if not fut.result():
                            upload_ok = False
                            pool.shutdown(wait=False, cancel_futures=True)
                            break

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
                              ('short_video_desc',(None,self._translate_to_en(item['entry'].get()) or 'Beauty')),
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
                                self.log(f'→ Відповідь: {self._extract_html_body_text(r.text)}')
                        except Exception as e:
                            self.log(f'Помилка реєстрації: {e}')
                else:
                    self.log(f'final_fid порожній! jr={jr}')
                try: os.remove(v_f); os.remove(t_f)   # temp video/thumb — завжди видаляємо
                except: pass

            else:
                # PHOTOS (Mail Photos + Private Photos)
                # === REFRESH REFERER перед кожним фото ===
                try:
                    _up_map = {
                        'Mail Photos':    'women_album_upload',
                        'Private Photos': 'private_photo_upload',
                    }
                    _upu = f'https://www.charmdate.com/clagt/woman/{_up_map[mode]}.php?womanid={wid}'
                    self.session.get(_upu, verify=False, timeout=15)
                    self.session.headers.update({'Referer': _upu})
                except Exception as _e:
                    self.log(f'→ Referer не оновлено: {_e}')
                # =========================================

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
                    # спочатку переклад (якщо увімкнено), потім прибираємо спецсимволи
                    raw_caption = self._translate_to_en(item['entry'].get()) or 'Photo'
                    cl = re.sub(r'[^\w\s]', '', raw_caption, flags=re.UNICODE).strip()[:30]
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
                            self.log(f'→ Відповідь: {self._extract_html_body_text(res.text)}')
                    except requests.exceptions.Timeout:
                        self.log(f'Таймаут! Файл {file_kb}KB, ліміт {upload_timeout}с')
                    except Exception as e:
                        self.log(f'Помилка завантаження: {e}')

                # TEMP_IMAGE — завжди видаляємо після спроби (успіх чи ні)
                try: os.remove(TEMP_IMAGE)
                except: pass

            if success:
                self.album_counts[aid] += 1
                cnt = self.album_counts[aid]
                self.after(0, lambda d=f"{self.album_names[aid]} ({cnt}/30)":
                               self.album_var.set(d))
                self.log(f'УСПІХ ({cnt}/30)')
                if item.get('status_lbl'):
                    self.after(0, lambda lbl=item['status_lbl']: (
                        lbl.configure(text='✓', fg='#00C97A')))
                try: os.remove(item['path'])
                except: pass
            else:
                self.log(f'[!] ПОМИЛКА {i+1}')
                if item.get('status_lbl'):
                    self.after(0, lambda lbl=item['status_lbl']: (
                        lbl.configure(text='✗', fg='#FF1060')))

            self.after(0, lambda done=i+1, total=len(tasks):
                           self.set_progress(done, total))
            time.sleep(1)

        ok_count  = sum(1 for it in tasks if it.get('status_lbl') and it['status_lbl'].cget('text') == '✓')
        err_count = sum(1 for it in tasks if it.get('status_lbl') and it['status_lbl'].cget('text') == '✗')
        self.log(f'ГОТОВО. Успіх: {ok_count}, Помилки: {err_count}')
        msg = f'✓ {ok_count} завантажено'
        if err_count:
            msg += f'  ✗ {err_count} помилок'
        clr = '#00C97A' if not err_count else '#D06000'
        self.after(0, lambda: self.toast(msg, clr))
        self.after(0, self._play_done_sound)
        self.btn_start.configure(state='normal')
        self.btn_stop.configure(state='disabled')


if __name__ == '__main__':
    app = PhotoUploaderApp()
    app.mainloop()
