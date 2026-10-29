"""GujiGuji desktop overlay for DeepSeek Harness.

The dsh Host writes state.json. This independent process polls that file,
plays the matching sprite row, and shows a Codex-style task bubble only while
the agent is busy.
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont, ImageTk

import tkinter as tk

from pet_physics import (
    BodyGeometry,
    DragTracker,
    Rect,
    ThrowBody,
    clamp_window_to_monitor,
    landing_scale,
    landing_strength as landing_strength_for_impact,
    monitor_index_at_point,
    monitor_index_for_rect,
    step_throw,
)


CELL_W = 192
CELL_H = 208
POSE_CELL_W = 320
POSE_CELL_H = 320
POSE_BASELINE = 274
POSE_PADDING = 6
SHEET_BASELINE = 194
DEFAULT_SCALE = 0.62
DEFAULT_SIZE_PERCENT = 65
MIN_SIZE_PERCENT = 30
MAX_SIZE_PERCENT = 180
DEFAULT_OPACITY_PERCENT = 75
MIN_OPACITY_PERCENT = 20
MAX_OPACITY_PERCENT = 100
DEFAULT_THROW_POWER_PERCENT = 100
MIN_THROW_POWER_PERCENT = 50
MAX_THROW_POWER_PERCENT = 150
DEFAULT_IDLE_INTERVAL_PERCENT = 100
MIN_IDLE_INTERVAL_PERCENT = 50
MAX_IDLE_INTERVAL_PERCENT = 200
MIN_SETTINGS_WIDTH = 320
MIN_SETTINGS_HEIGHT = 300
DEFAULT_SETTINGS_WIDTH = 420
DEFAULT_SETTINGS_HEIGHT = 330
POSE_NAMES = ("idle", "head-tilt", "head-stretch", "cheer", "wave")
GESTURE_POSES = ("head-tilt", "head-stretch", "cheer", "wave")
CLICK_POSES = ("head-tilt", "head-stretch", "cheer", "wave")
IDLE_POSES = CLICK_POSES
DOUBLE_CLICK_POSES = ("head-tilt", "head-stretch")
IDLE_GESTURE_MIN_DELAY_MS = 30_000
IDLE_GESTURE_MAX_DELAY_MS = 75_000
STAND_FRAME_MS = 80
POSE_FRAME_MS = {
    "idle": 1000,
    "head-tilt": 220,
    "head-stretch": 180,
    "cheer": 190,
    "wave": 190,
}
POSE_FRAME_COUNTS = {
    "idle": 6,
    "head-tilt": 7,
    "head-stretch": 7,
    "cheer": 7,
    "wave": 7,
}
RUNNING_JUMP_SCALE = 0.4
COMPLETION_JUMP_SCALE = 0.4
COMPLETION_JUMP_COUNT = 2
COMPLETION_JUMP_GAP_MS = 220
FLIGHT_ROW = "jumping"
FLIGHT_TAKEOFF_FRAMES = (2,)
FLIGHT_TAKEOFF_START_FRAME = FLIGHT_TAKEOFF_FRAMES[0]
FLIGHT_GLIDE_POSE = "cheer"
FLIGHT_GLIDE_FRAME = 3
FLIGHT_LANDING_POSE = "cheer"
FLIGHT_LANDING_FRAMES = (1, 2, 3, 4, 5)
FLIGHT_LANDING_GAP_RATIO = 0.22
FLIGHT_LANDING_GAP_MIN = 20

ROWS = [
    ("idle", 6),
    ("running-right", 8),
    ("running-left", 8),
    ("waving", 4),
    ("jumping", 5),
    ("failed", 8),
    ("waiting", 6),
    ("running", 6),
    ("review", 6),
]
ROW_INDEX = {name: index for index, (name, _) in enumerate(ROWS)}
ROW_FRAMES = [frames for _, frames in ROWS]

FRAME_MS = {
    "idle": 220,
    "running-right": 90,
    "running-left": 90,
    "waving": 200,
    "jumping": 130,
    "failed": 150,
    "waiting": 240,
    "running": 190,
    "review": 200,
}

STATUS_COLORS = {
    "running": (154, 216, 184, 255),
    "waiting": (242, 191, 92, 255),
    "failed": (247, 123, 123, 255),
    "review": (151, 192, 244, 255),
}

ROW_FOR_STATUS = {
    "running": "running",
    "waiting": "waiting",
    "failed": "failed",
    "review": "review",
    "idle": "idle",
}

TRANSPARENT_KEY = "#010203"
CARD_BG = "#242424"
CARD_RAISED = "#30343c"
TEXT = "#f2f4f8"
TEXT_MUTED = "#aeb4c0"
ACCENT = "#9ad8b8"
BUBBLE_WIDTH = 284
BUBBLE_HEIGHT = 65
BUBBLE_RADIUS = 18
BUBBLE_OPACITY = 0.88
BUBBLE_EDGE_MARGIN = 8
MARQUEE_STEP_MS = 38
OVERLAY_HEALTH_CHECK_MS = 2000
PHYSICS_FRAME_MS = 16
DRAG_THRESHOLD_PX = 5
DRAG_FLIGHT_HOLD_MS = 120
LANDING_DURATION_MS = 170
LANDING_FRAME_MS = 33
GRAB_SCALE_X = 0.985
GRAB_SCALE_Y = 1.018

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def load_font(size: int, bold: bool = False):
    candidates = FONT_CANDIDATES
    if bold and os.path.exists(r"C:\Windows\Fonts\msyhbd.ttc"):
        candidates = [r"C:\Windows\Fonts\msyhbd.ttc", *FONT_CANDIDATES]
    for candidate in candidates:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def keyed_photo(image: Image.Image) -> ImageTk.PhotoImage:
    """Flatten alpha onto Tk's colour key without dark anti-alias fringes."""
    rgba = image.convert("RGBA")
    mask = rgba.getchannel("A").point(lambda alpha: 255 if alpha >= 128 else 0)
    keyed = Image.new("RGB", rgba.size, TRANSPARENT_KEY)
    keyed.paste(rgba.convert("RGB"), (0, 0), mask)
    return ImageTk.PhotoImage(keyed)




def rounded_card(
    width: int,
    height: int,
    radius: int = 14,
    fill=(34, 37, 43, 255),
    outline=None,
) -> Image.Image:
    scale = 4
    image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=radius * scale,
        fill=fill,
        outline=outline,
        width=0 if outline is None else scale,
    )
    return image.resize((width, height), Image.Resampling.LANCZOS)


def fit_text(draw, text: str, font, max_width: int) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    clipped = text
    while clipped:
        candidate = clipped + "\u2026"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            return candidate
        clipped = clipped[:-1]
    return "\u2026"


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def parse_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text: str, command, width: int, primary=False):
        super().__init__(
            parent,
            width=width,
            height=32,
            bg=CARD_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.command = command
        self.primary = primary
        self.hovered = False
        self.text = text
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda _event: self.command())

    def _draw(self):
        self.delete("all")
        width = int(self.cget("width"))
        height = int(self.cget("height"))
        if self.primary:
            fill = "#edf9f2" if self.hovered else "#d9f1e5"
            fg = "#17251e"
            outline = fill
        else:
            fill = "#3a3f49" if self.hovered else CARD_RAISED
            fg = TEXT
            outline = "#454b56"
        self.create_rectangle(1, 1, width - 1, height - 1, fill=fill, outline=outline)
        self.create_text(
            width // 2,
            height // 2 + 1,
            text=self.text,
            fill=fg,
            font=("Microsoft YaHei UI", 9),
        )

    def _on_enter(self, _event):
        self.hovered = True
        self._draw()

    def _on_leave(self, _event):
        self.hovered = False
        self._draw()


class SettingSlider:
    """Label, hint, track, thumb, editable value and reset action."""

    def __init__(
        self,
        parent,
        y: int,
        title: str,
        hint: str,
        value: int,
        minimum: int,
        maximum: int,
        default: int,
        command,
        on_reset,
        layout,
    ):
        self.parent = parent
        self.y = y
        self.minimum = minimum
        self.maximum = maximum
        self.command = command
        self.on_reset = on_reset
        self.layout_callback = layout
        self.value = clamp(value, minimum, maximum)

        self.title_label = tk.Label(
            parent,
            text=title,
            bg=CARD_BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.hint_label = tk.Label(
            parent,
            text=hint,
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 8),
        )

        self.track = tk.Canvas(
            parent,
            width=1,
            height=28,
            bg=CARD_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.track.place(
            x=0,
            y=0,
            width=1,
            height=28,
        )
        self.track.bind("<Button-1>", self._on_track_press)
        self.track.bind("<B1-Motion>", self._on_track_drag)
        self.track.bind("<ButtonRelease-1>", self._on_track_release)
        self.track.bind("<Configure>", lambda _event: self.parent.after_idle(self._draw_track))
        self.track_press = None

        self.value_var = tk.StringVar(value=str(self.value))
        self.entry = tk.Entry(
            parent,
            textvariable=self.value_var,
            width=4,
            justify="right",
            bg=CARD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#3a3a3a",
            highlightcolor="#6f6f6f",
            font=("Microsoft YaHei UI", 9),
        )
        self.entry.place(x=0, y=0, width=43, height=25)
        self.percent_label = tk.Label(
            parent,
            text="%",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 8),
        )

        self.reset_label = tk.Label(
            parent,
            text="\u91cd\u7f6e",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.reset_label.bind("<Button-1>", lambda _event: self.on_reset())
        self.reset_label.bind(
            "<Enter>", lambda _event: self.reset_label.configure(fg=TEXT)
        )
        self.reset_label.bind(
            "<Leave>", lambda _event: self.reset_label.configure(fg=TEXT_MUTED)
        )

        self._entry_job = None
        self.entry.bind("<Return>", self._apply_entry)
        self.entry.bind("<FocusOut>", self._apply_entry)
        self.entry.bind("<KeyRelease>", self._schedule_entry)
        self.layout()
        self._draw_track()

    @property
    def height(self) -> int:
        return 80

    def layout(self):
        left, width = self.layout_callback()
        label_width = 150 if width >= 380 else 132
        value_left = left + width - 82
        track_left = left + label_width
        track_right = value_left - 12
        track_width = max(54, track_right - track_left)
        self.title_label.place(x=left, y=self.y)
        self.hint_label.place(x=left, y=self.y + 21)
        self.track.place(
            x=track_left,
            y=self.y + 11,
            width=track_width,
            height=28,
        )
        self.entry.place(x=value_left, y=self.y + 3, width=43, height=25)
        self.percent_label.place(x=value_left + 46, y=self.y + 8)
        self.reset_label.place(x=value_left + 4, y=self.y + 34)
        self._draw_track()

    def set_visible(self, visible: bool):
        widgets = (
            self.title_label,
            self.hint_label,
            self.track,
            self.entry,
            self.percent_label,
            self.reset_label,
        )
        if visible:
            self.layout()
        else:
            for widget in widgets:
                widget.place_forget()

    def _thumb_x(self, width: int) -> int:
        fraction = (self.value - self.minimum) / (self.maximum - self.minimum)
        return round(9 + fraction * max(0, width - 18))

    def _draw_track(self):
        width = max(20, self.track.winfo_width())
        thumb = self._thumb_x(width)
        self.track.delete("all")
        self.track.create_line(
            9,
            14,
            width - 9,
            14,
            fill="#4b4b4b",
            width=2,
        )
        self.track.create_line(
            9,
            14,
            thumb,
            14,
            fill="#d9d9d9",
            width=2,
        )
        self.track.create_oval(
            thumb - 8,
            6,
            thumb + 8,
            22,
            fill="#f0f0f0",
            outline="#f0f0f0",
        )

    def _set_from_x(self, x: int, notify: bool):
        width = max(20, self.track.winfo_width())
        fraction = (x - 9) / max(1, width - 18)
        value = round(self.minimum + fraction * (self.maximum - self.minimum))
        self.set_value(value, notify)

    def _on_track_press(self, event):
        # Grabbing the track or thumb moves it immediately; a background click
        # outside the thumb does not jump the value unexpectedly.
        thumb = self._thumb_x(max(20, self.track.winfo_width()))
        if abs(event.x - thumb) <= 14:
            self.track_press = event.x
            self._set_from_x(event.x, True)
        else:
            self.track_press = None

    def _on_track_drag(self, event):
        if self.track_press is None:
            return
        self._set_from_x(event.x, True)

    def _on_track_release(self, _event):
        self.track_press = None

    def set_value(self, value: int, notify: bool):
        value = clamp(round(value), self.minimum, self.maximum)
        changed = value != self.value
        self.value = value
        self.value_var.set(str(value))
        self._draw_track()
        if notify and changed:
            self.command(value)

    def _schedule_entry(self, _event=None):
        if self._entry_job:
            try:
                self.parent.after_cancel(self._entry_job)
            except tk.TclError:
                pass
        self._entry_job = self.parent.after(300, self._apply_entry)

    def _apply_entry(self, _event=None):
        self._entry_job = None
        try:
            value = round(float(self.value_var.get().strip()))
        except ValueError:
            self.value_var.set(str(self.value))
            return
        self.set_value(value, True)


class SettingToggle:
    """Compact labelled switch used for interaction preferences."""

    def __init__(
        self,
        parent,
        y: int,
        title: str,
        hint: str,
        value: bool,
        command,
        layout,
    ):
        self.parent = parent
        self.y = y
        self.command = command
        self.layout_callback = layout
        self.value = bool(value)
        self.title_label = tk.Label(
            parent,
            text=title,
            bg=CARD_BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.hint_label = tk.Label(
            parent,
            text=hint,
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 8),
        )
        self.state_label = tk.Label(
            parent,
            text="",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 9),
        )
        self.switch = tk.Canvas(
            parent,
            width=44,
            height=24,
            bg=CARD_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.switch.bind("<Button-1>", self._toggle)
        self._draw_switch()
        self.layout()

    def layout(self):
        left, width = self.layout_callback()
        self.title_label.place(x=left, y=self.y)
        self.hint_label.place(x=left, y=self.y + 21)
        self.state_label.place(x=left + width - 98, y=self.y + 5)
        self.switch.place(x=left + width - 48, y=self.y + 5)

    def set_visible(self, visible: bool):
        if visible:
            self.layout()
        else:
            for widget in (
                self.title_label,
                self.hint_label,
                self.state_label,
                self.switch,
            ):
                widget.place_forget()

    def _draw_switch(self):
        self.switch.delete("all")
        fill = "#9ad8b8" if self.value else "#4b4b4b"
        self.switch.create_oval(2, 2, 24, 24, fill=fill, outline=fill)
        self.switch.create_oval(20, 2, 42, 24, fill=fill, outline=fill)
        self.switch.create_rectangle(12, 3, 32, 23, fill=fill, outline=fill)
        knob_x = 23 if self.value else 1
        self.switch.create_oval(
            knob_x,
            2,
            knob_x + 20,
            22,
            fill="#f0f0f0",
            outline="#f0f0f0",
        )
        self.state_label.configure(text="\u5f00\u542f" if self.value else "\u5173\u95ed")

    def _toggle(self, _event=None):
        self.value = not self.value
        self._draw_switch()
        self.command(self.value)


class SettingAction:
    """Compact rounded action used by the behaviour settings page."""

    WIDTH = 150
    HEIGHT = 30

    def __init__(self, parent, y: int, text: str, command, layout):
        self.parent = parent
        self.y = y
        self.command = command
        self.layout_callback = layout
        self.hovered = False
        self.photo = None
        self.canvas = tk.Canvas(
            parent,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=CARD_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.canvas.bind("<Button-1>", lambda _event: self.command())
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.text = text
        self.layout()

    def layout(self):
        left, _width = self.layout_callback()
        self.canvas.place(
            x=left,
            y=self.y,
            width=self.WIDTH,
            height=self.HEIGHT,
        )
        self._draw()

    def set_visible(self, visible: bool):
        if visible:
            self.layout()
        else:
            self.canvas.place_forget()

    def _on_enter(self, _event):
        self.hovered = True
        self._draw()

    def _on_leave(self, _event):
        self.hovered = False
        self._draw()

    def _draw(self):
        fill = (58, 64, 74, 255) if self.hovered else (48, 52, 60, 255)
        image = rounded_card(
            self.WIDTH,
            self.HEIGHT,
            radius=8,
            fill=fill,
            outline=(255, 255, 255, 20),
        )
        self.photo = keyed_photo(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_text(
            self.WIDTH // 2,
            self.HEIGHT // 2,
            text=self.text,
            fill=TEXT,
            font=("Microsoft YaHei UI", 9),
        )


def enable_dpi_awareness():
    """Keep Tk coordinates aligned with physical pixels across mixed-DPI screens."""
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [wintypes.HANDLE]
        set_context.restype = wintypes.BOOL
        if set_context(wintypes.HANDLE(-4)):
            return
    except (AttributeError, OSError, OverflowError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def reassert_overlay(window: tk.Misc, redraw: bool = True) -> bool:
    """Recover a Tk overlay that Windows stopped compositing.

    ``overrideredirect`` + ``-topmost`` windows can keep WS_EX_TOPMOST while
    DWM temporarily stops presenting their pixels, especially after a
    full-screen app or display change. Re-applying topmost without activation
    makes the compositor present the already-correct Tk surface again.
    """
    if sys.platform != "win32":
        return False
    try:
        window.update_idletasks()
        client_hwnd = int(window.winfo_id())
        if not window.winfo_ismapped():
            return False
    except (tk.TclError, ValueError, TypeError):
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    hwnd = user32.GetAncestor(client_hwnd, 2) or client_hwnd  # GA_ROOT
    flags = (
        0x0001  # SWP_NOSIZE
        | 0x0002  # SWP_NOMOVE
        | 0x0010  # SWP_NOACTIVATE
        | 0x0040  # SWP_SHOWWINDOW
        | 0x0200  # SWP_NOOWNERZORDER
    )
    if not user32.SetWindowPos(
        hwnd,
        wintypes.HWND(-1),
        0,
        0,
        0,
        0,
        flags,
    ):
        return False
    if redraw:
        user32.RedrawWindow.argtypes = [
            wintypes.HWND,
            ctypes.c_void_p,
            wintypes.HBRUSH,
            ctypes.c_uint,
        ]
        user32.RedrawWindow.restype = wintypes.BOOL
        user32.RedrawWindow(
            hwnd,
            None,
            None,
            0x0001 | 0x0004 | 0x0080 | 0x0100,
        )  # INVALIDATE | UPDATENOW | ALLCHILDREN | FRAME
    return True


class StatusBubble:
    """Separate translucent rounded task bubble above the pet."""

    def __init__(self, pet):
        self.pet = pet
        self.pet_hovered = False
        self.minimize_hovered = False
        self.window = tk.Toplevel(pet.root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.window.attributes("-alpha", BUBBLE_OPACITY)
        self.window.configure(bg=TRANSPARENT_KEY)
        self.canvas = tk.Canvas(
            self.window,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.photo = None
        self.width = 0
        self.height = 0
        self.task_font = load_font(13, bold=True)
        self.activity_font = load_font(11)
        self.status = "idle"
        self.task = ""
        self.activity = ""
        self.activity_width = 0
        self.visible = False
        self.collapsed = False
        self.motion_hidden = False
        self.minimize_pressed = False
        self.scroll_offset = 0
        self.marquee_job = None
        self.last_width = BUBBLE_WIDTH

        for widget in (self.window, self.canvas):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self.pet._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)
            widget.bind("<Double-Button-1>", self._on_double_click)
            widget.bind("<Button-3>", self.pet._on_right_click)
            widget.bind("<Motion>", self._on_motion)
            widget.bind("<Leave>", self._on_leave)

    def update(self, status: str, task: str, activity: str = ""):
        self.status = status
        self.task = task.strip()
        self.activity = activity.strip()
        self.visible = status in ("running", "waiting", "failed", "review")
        if not self.visible or self.collapsed or self.motion_hidden:
            self._stop_marquee()
            self.window.withdraw()
            return
        self.scroll_offset = 0
        self._render()
        self.window.deiconify()
        self.window.lift()
        self.place()
        reassert_overlay(self.window)
        self._start_marquee()

    def toggle_collapsed(self):
        self.collapsed = not self.collapsed
        if self.collapsed or not self.visible or self.motion_hidden:
            self._stop_marquee()
            self.window.withdraw()
            return
        self.scroll_offset = 0
        self._render()
        self.window.deiconify()
        self.window.lift()
        self.place()
        reassert_overlay(self.window)
        self._start_marquee()

    def minimize(self):
        if not self.collapsed:
            self.toggle_collapsed()

    def hide_temporarily(self):
        self.collapsed = True
        self._stop_marquee()
        self.window.withdraw()

    def restore(self):
        if self.collapsed:
            self.toggle_collapsed()

    def set_motion_hidden(self, hidden: bool):
        if hidden == self.motion_hidden:
            return
        self.motion_hidden = hidden
        if hidden or not self.visible or self.collapsed:
            self._stop_marquee()
            self.window.withdraw()
            return
        self._render()
        self.window.deiconify()
        self.window.lift()
        self.place()
        reassert_overlay(self.window)
        self._start_marquee()

    def _render(self):
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        width = BUBBLE_WIDTH
        height = BUBBLE_HEIGHT
        title_text = fit_text(probe, self.task, self.task_font, width - 52)
        card = rounded_card(
            width,
            height,
            radius=BUBBLE_RADIUS,
            fill=(31, 32, 37, 255),
            outline=None,
        )
        draw = ImageDraw.Draw(card)
        dot_color = STATUS_COLORS.get(self.status, TEXT_MUTED)
        draw.ellipse((17, 15, 21, 19), fill=dot_color)
        draw.text((29, 8), title_text, font=self.task_font, fill=TEXT)
        self._draw_minimize_button(card, self.minimize_hovered)
        activity_text = self.activity
        self.activity_width = probe.textbbox(
            (0, 0),
            activity_text,
            font=self.activity_font,
        )[2]
        activity_area = width - 46
        if self.activity_width <= activity_area:
            self.scroll_offset = 0
            draw.text(
                (29, 37),
                activity_text,
                font=self.activity_font,
                fill=TEXT_MUTED,
            )
        else:
            gap = 48
            cycle = self.activity_width + gap
            start_x = width - 10
            x = start_x - self.scroll_offset
            strip = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            strip_draw = ImageDraw.Draw(strip)
            strip_draw.text(
                (x, 37),
                activity_text,
                font=self.activity_font,
                fill=TEXT_MUTED,
            )
            strip_draw.text(
                (x + cycle, 37),
                activity_text,
                font=self.activity_font,
                fill=TEXT_MUTED,
            )
            # Keep the card intact and mask only the independently drawn text.
            mask = Image.new("L", (width, height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rectangle((27, 32, width - 18, height - 8), fill=255)
            alpha = Image.composite(
                strip.getchannel("A"),
                Image.new("L", (width, height), 0),
                mask,
            )
            strip.putalpha(alpha)
            card.alpha_composite(strip)
        self.width = width
        self.height = height
        self.photo = keyed_photo(card)
        self.canvas.configure(width=width, height=height)
        self.canvas.delete("all")
        self.image_item = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        # Repaints (minimize-button hover, marquee ticks, status updates) must
        # only change the size. Including coordinates here snapped the bubble
        # to the desktop origin whenever it repainted.
        self.window.geometry(f"{width}x{height}")

    def _on_press(self, event):
        if self._inside_minimize(event.x, event.y):
            self.minimize_pressed = True
            return "break"
        return self.pet._on_press(event)

    def _on_release(self, event):
        if self.minimize_pressed:
            should_minimize = self._inside_minimize(event.x, event.y)
            self.minimize_pressed = False
            if should_minimize:
                self.minimize()
            return "break"
        return self.pet._on_release(event)

    def _on_double_click(self, event):
        if self._inside_minimize(event.x, event.y):
            return "break"
        return self.pet._on_double_click(event)

    @staticmethod
    def _inside_minimize(x, y):
        return BUBBLE_WIDTH - 37 <= x <= BUBBLE_WIDTH - 8 and 7 <= y <= 34

    def _on_motion(self, event):
        hovered = self._inside_minimize(event.x, event.y)
        if hovered != self.minimize_hovered:
            self.minimize_hovered = hovered
            self.canvas.configure(cursor="hand2" if hovered else "")
            self._render()

    def _on_leave(self, _event):
        self.minimize_pressed = False
        if self.minimize_hovered:
            self.minimize_hovered = False
            self.canvas.configure(cursor="")
            self._render()

    @staticmethod
    def _draw_minimize_button(card, hovered=False):
        button = Image.new("RGBA", card.size, (0, 0, 0, 0))
        button_draw = ImageDraw.Draw(button)
        button_draw.line(
            (BUBBLE_WIDTH - 29, 18, BUBBLE_WIDTH - 18, 18),
            fill=(235, 238, 242, 255 if hovered else 210),
            width=2,
        )
        card.alpha_composite(button)

    def _start_marquee(self):
        self._stop_marquee()
        if (
            self.visible
            and not self.collapsed
            and not self.motion_hidden
            and self.activity_width > BUBBLE_WIDTH - 46
        ):
            self.marquee_job = self.window.after(
                MARQUEE_STEP_MS,
                self._advance_marquee,
            )

    def _advance_marquee(self):
        self.marquee_job = None
        if not self.visible or self.collapsed or self.motion_hidden:
            return
        cycle = self.activity_width + 42
        self.scroll_offset = (self.scroll_offset + 1) % max(1, cycle)
        self._render()
        self.marquee_job = self.window.after(
            MARQUEE_STEP_MS,
            self._advance_marquee,
        )

    def _stop_marquee(self):
        if self.marquee_job is not None:
            try:
                self.window.after_cancel(self.marquee_job)
            except tk.TclError:
                pass
            self.marquee_job = None

    def place(self):
        if not self.visible or self.collapsed or self.motion_hidden:
            return
        try:
            self.window.update_idletasks()
            pet_w = self.pet.root.winfo_width()
            pet_h = self.pet.root.winfo_height()
        except tk.TclError:
            return
        if pet_w <= 1 or pet_h <= 1:
            return
        pet_x = self.pet.root.winfo_x()
        pet_y = self.pet.root.winfo_y()
        x = pet_x + pet_w // 2 - self.width // 2
        work_left, work_top, work_right, work_bottom = (
            self.pet._work_area_for_rect(pet_x, pet_y, pet_w, pet_h)
        )
        x = clamp(
            x,
            work_left + BUBBLE_EDGE_MARGIN,
            max(
                work_left + BUBBLE_EDGE_MARGIN,
                work_right - self.width - BUBBLE_EDGE_MARGIN,
            ),
        )
        above_y = pet_y + self.pet._bubble_anchor_top() - self.height - 7
        below_y = pet_y + pet_h + 4
        if (
            above_y >= work_top + BUBBLE_EDGE_MARGIN
            and above_y + self.height <= work_bottom - BUBBLE_EDGE_MARGIN
        ):
            y = above_y
        elif (
            below_y >= work_top + BUBBLE_EDGE_MARGIN
            and below_y + self.height <= work_bottom - BUBBLE_EDGE_MARGIN
        ):
            y = below_y
        else:
            y = clamp(
                above_y,
                work_top + BUBBLE_EDGE_MARGIN,
                max(
                    work_top + BUBBLE_EDGE_MARGIN,
                    work_bottom - self.height - BUBBLE_EDGE_MARGIN,
                ),
            )
        self.window.geometry(f"+{x}+{y}")

    def destroy(self):
        self._stop_marquee()
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class ContextMenu:
    """Codex-style rounded menu opened by right-clicking the pet."""

    WIDTH = 180
    PAD = 7
    ROW_H = 38

    def __init__(self, pet, x_root: int, y_root: int):
        self.pet = pet
        self.items = [
            ("\u8bbe\u7f6e", pet.open_settings),
            ("\u9690\u85cf\u5ba0\u7269", pet.hide),
        ]
        self.hover = -1
        self.height = self.PAD * 2 + self.ROW_H * len(self.items)
        self.window = tk.Toplevel(pet.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.window.attributes("-alpha", 0.96 * pet.opacity_percent / 100)
        self.window.configure(bg=TRANSPARENT_KEY)
        self.canvas = tk.Canvas(
            self.window,
            width=self.WIDTH,
            height=self.height,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.canvas.pack()
        self.photo = None
        self.font = load_font(11)
        self._render()
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_click)
        self.window.bind("<Escape>", lambda _event: self.close())

        desktop_left, desktop_top, desktop_right, desktop_bottom = (
            pet.virtual_desktop()
        )
        x = clamp(x_root, desktop_left, max(desktop_left, desktop_right - self.WIDTH))
        y = clamp(y_root, desktop_top, max(desktop_top, desktop_bottom - self.height))
        self.window.geometry(f"{self.WIDTH}x{self.height}+{x}+{y}")
        self.window.lift()
        try:
            self.window.focus_force()
        except tk.TclError:
            pass

    def _row_at(self, y: int) -> int:
        index = (y - self.PAD) // self.ROW_H
        return index if 0 <= index < len(self.items) else -1

    def _render(self):
        image = rounded_card(self.WIDTH, self.height, radius=12)
        draw = ImageDraw.Draw(image)
        for index, (label, _command) in enumerate(self.items):
            top = self.PAD + index * self.ROW_H
            if index == self.hover:
                draw.rounded_rectangle(
                    (6, top + 2, self.WIDTH - 6, top + self.ROW_H - 2),
                    radius=8,
                    fill=(58, 63, 73, 255),
                )
            draw.text((18, top + 10), label, font=self.font, fill=TEXT)
        self.photo = keyed_photo(image)
        self.canvas.delete("all")
        self.background_item = self.canvas.create_image(
            0,
            0,
            image=self.photo,
            anchor="nw",
        )

    def _on_motion(self, event):
        row = self._row_at(event.y)
        if row != self.hover:
            self.hover = row
            self._render()

    def _on_click(self, event):
        row = self._row_at(event.y)
        if row < 0:
            return
        command = self.items[row][1]
        self.close()
        command()

    def close(self):
        if getattr(self.pet, "menu", None) is self:
            self.pet.menu = None
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class SettingsWindow:
    PAD = 24
    MIN_WIDTH = MIN_SETTINGS_WIDTH
    MIN_HEIGHT = MIN_SETTINGS_HEIGHT
    GRIP = 16

    def __init__(self, pet):
        self.pet = pet
        self.width, self.height = self._load_size()
        self.page = "general"
        self.resize_origin = None
        self.resize_start = None
        self.window = tk.Toplevel(pet.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.window.attributes("-alpha", pet.opacity_percent / 100)
        self.window.configure(bg=TRANSPARENT_KEY)
        self.window.withdraw()
        self.canvas = tk.Canvas(
            self.window,
            width=self.width,
            height=self.height,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.photo = None
        self.background_item = self.canvas.create_image(0, 0, anchor="nw")

        desktop_left, desktop_top, desktop_right, desktop_bottom = (
            pet.virtual_desktop()
        )
        x = clamp(
            pet.root.winfo_x() + pet.root.winfo_width() // 2 - self.width // 2,
            desktop_left,
            max(desktop_left, desktop_right - self.width),
        )
        y = clamp(
            pet.root.winfo_y() - self.height - 14,
            desktop_top,
            max(desktop_top, desktop_bottom - self.height),
        )
        if y <= desktop_top:
            y = clamp(
                pet.root.winfo_y() + pet.root.winfo_height() + 14,
                desktop_top,
                max(desktop_top, desktop_bottom - self.height),
            )
        self.window.update_idletasks()
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")

        self.title = tk.Label(
            self.window,
            text="\u81ea\u5b9a\u4e49\u865a\u62df\u5ba0\u7269",
            bg=CARD_BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        self.title.place(x=self.PAD, y=17)

        self.general_tab = tk.Label(
            self.window,
            text="\u901a\u7528",
            bg=CARD_BG,
            fg=TEXT,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.general_tab.bind(
            "<Button-1>",
            lambda _event: self._set_page("general"),
        )
        self.interaction_tab = tk.Label(
            self.window,
            text="\u4ea4\u4e92",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.interaction_tab.bind(
            "<Button-1>",
            lambda _event: self._set_page("interaction"),
        )
        self.behavior_tab = tk.Label(
            self.window,
            text="\u884c\u4e3a",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        self.behavior_tab.bind(
            "<Button-1>",
            lambda _event: self._set_page("behavior"),
        )

        self.close_button = tk.Canvas(
            self.window,
            width=28,
            height=28,
            bg=CARD_BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.close_button.create_line(9, 9, 19, 19, fill=TEXT_MUTED, width=1)
        self.close_button.create_line(19, 9, 9, 19, fill=TEXT_MUTED, width=1)
        self.close_button.bind("<Button-1>", lambda _event: self.close())

        self.size_slider = SettingSlider(
            self.window,
            y=98,
            title="\u865a\u62df\u5ba0\u7269\u5927\u5c0f",
            hint="\u8c03\u6574\u865a\u62df\u5ba0\u7269\u5927\u5c0f",
            value=pet.size_percent,
            minimum=MIN_SIZE_PERCENT,
            maximum=MAX_SIZE_PERCENT,
            default=DEFAULT_SIZE_PERCENT,
            command=pet.set_size_percent,
            on_reset=lambda: self.size_slider.set_value(
                DEFAULT_SIZE_PERCENT, notify=True
            ),
            layout=self._content_layout,
        )
        self.opacity_slider = SettingSlider(
            self.window,
            y=182,
            title="\u5ba0\u7269\u900f\u660e\u5ea6",
            hint="\u8c03\u6574\u5ba0\u7269\u548c\u6c14\u6ce1\u7684\u900f\u660e\u5ea6",
            value=pet.opacity_percent,
            minimum=MIN_OPACITY_PERCENT,
            maximum=MAX_OPACITY_PERCENT,
            default=DEFAULT_OPACITY_PERCENT,
            command=pet.set_opacity_percent,
            on_reset=lambda: self.opacity_slider.set_value(
                DEFAULT_OPACITY_PERCENT, notify=True
            ),
            layout=self._content_layout,
        )
        self.throw_slider = SettingSlider(
            self.window,
            y=98,
            title="\u7529\u51fa\u529b\u5ea6",
            hint="\u8c03\u6574\u5feb\u901f\u62d6\u62fd\u540e\u7684\u98de\u884c\u529b\u5ea6",
            value=pet.throw_power_percent,
            minimum=MIN_THROW_POWER_PERCENT,
            maximum=MAX_THROW_POWER_PERCENT,
            default=DEFAULT_THROW_POWER_PERCENT,
            command=pet.set_throw_power_percent,
            on_reset=lambda: self.throw_slider.set_value(
                DEFAULT_THROW_POWER_PERCENT,
                notify=True,
            ),
            layout=self._content_layout,
        )
        self.reduced_motion_toggle = SettingToggle(
            self.window,
            y=190,
            title="\u51cf\u5c11\u52a8\u6001\u6548\u679c",
            hint="\u5173\u95ed\u81ea\u52a8\u5f85\u673a\u3001\u5de5\u4f5c\u8df3\u52a8\u548c\u843d\u5730\u6324\u538b",
            value=pet.reduced_motion,
            command=pet.set_reduced_motion,
            layout=self._content_layout,
        )
        self.idle_interval_slider = SettingSlider(
            self.window,
            y=98,
            title="\u7a7a\u95f2\u52a8\u4f5c\u95f4\u9694",
            hint="100% = 30\u201375 \u79d2\uff0c\u8d8a\u5927\u8d8a\u5b89\u9759",
            value=pet.idle_interval_percent,
            minimum=MIN_IDLE_INTERVAL_PERCENT,
            maximum=MAX_IDLE_INTERVAL_PERCENT,
            default=DEFAULT_IDLE_INTERVAL_PERCENT,
            command=pet.set_idle_interval_percent,
            on_reset=lambda: self.idle_interval_slider.set_value(
                DEFAULT_IDLE_INTERVAL_PERCENT,
                notify=True,
            ),
            layout=self._content_layout,
        )
        self.lock_position_toggle = SettingToggle(
            self.window,
            y=190,
            title="\u9501\u5b9a\u4f4d\u7f6e",
            hint="\u6253\u5f00\u540e\u62d6\u62fd\u53ea\u4f1a\u89e6\u53d1\u52a8\u4f5c\uff0c\u4e0d\u4f1a\u79fb\u52a8\u5ba0\u7269",
            value=pet.lock_position,
            command=pet.set_lock_position,
            layout=self._content_layout,
        )
        self.reset_position_button = SettingAction(
            self.window,
            y=246,
            text="\u6062\u590d\u9ed8\u8ba4\u4f4d\u7f6e",
            command=pet.reset_position,
            layout=self._content_layout,
        )
        self.grip = tk.Canvas(
            self.window,
            width=self.GRIP,
            height=self.GRIP,
            bg=CARD_BG,
            highlightthickness=0,
            bd=0,
            cursor="bottom_right_corner",
        )
        self.grip.bind("<ButtonPress-1>", self._resize_press)
        self.grip.bind("<B1-Motion>", self._resize_drag)
        self.grip.bind("<ButtonRelease-1>", self._resize_release)

        self.window.bind("<Configure>", self._on_configure)
        self.window.bind("<Escape>", lambda _event: self.close())
        self._layout()
        self.window.deiconify()

    def _load_size(self):
        if not self.pet.settings_path or not self.pet.settings_path.exists():
            return DEFAULT_SETTINGS_WIDTH, DEFAULT_SETTINGS_HEIGHT
        try:
            data = json.loads(self.pet.settings_path.read_text("utf-8"))
            width = round(float(data.get("settingsWidth", DEFAULT_SETTINGS_WIDTH)))
            height = round(float(data.get("settingsHeight", DEFAULT_SETTINGS_HEIGHT)))
            return (
                clamp(width, self.MIN_WIDTH, 720),
                clamp(height, self.MIN_HEIGHT, 560),
            )
        except (OSError, ValueError, TypeError):
            return DEFAULT_SETTINGS_WIDTH, DEFAULT_SETTINGS_HEIGHT

    def _content_layout(self):
        return self.PAD, max(1, self.width - self.PAD * 2)

    def _layout(self):
        self._render_background()
        self.close_button.place(x=self.width - 42, y=14)
        self.general_tab.place(x=self.PAD, y=53)
        self.interaction_tab.place(x=self.PAD + 52, y=53)
        self.behavior_tab.place(x=self.PAD + 104, y=53)
        general = self.page == "general"
        interaction = self.page == "interaction"
        behavior = self.page == "behavior"
        self.general_tab.configure(
            fg=TEXT if general else TEXT_MUTED,
            font=("Microsoft YaHei UI", 9, "bold" if general else "normal"),
        )
        self.interaction_tab.configure(
            fg=TEXT if interaction else TEXT_MUTED,
            font=("Microsoft YaHei UI", 9, "bold" if interaction else "normal"),
        )
        self.behavior_tab.configure(
            fg=TEXT if behavior else TEXT_MUTED,
            font=("Microsoft YaHei UI", 9, "bold" if behavior else "normal"),
        )
        self.size_slider.set_visible(general)
        self.opacity_slider.set_visible(general)
        self.throw_slider.set_visible(interaction)
        self.reduced_motion_toggle.set_visible(interaction)
        self.idle_interval_slider.set_visible(behavior)
        self.lock_position_toggle.set_visible(behavior)
        self.reset_position_button.set_visible(behavior)
        self.grip.place(x=self.width - self.GRIP - 5, y=self.height - self.GRIP - 4)
        self._draw_grip()

    def _set_page(self, page: str):
        if page == self.page:
            return
        self.page = page
        self._layout()

    def _draw_grip(self):
        self.grip.delete("all")
        for offset in (4, 8, 12):
            self.grip.create_line(
                offset,
                self.GRIP - 1,
                self.GRIP - 1,
                offset,
                fill=TEXT_MUTED,
                width=1,
            )

    def _render_background(self):
        image = rounded_card(
            self.width,
            self.height,
            radius=20,
            fill=(36, 36, 36, 255),
            outline=(255, 255, 255, 18),
        )
        self.photo = keyed_photo(image)
        self.canvas.itemconfigure(self.background_item, image=self.photo)

    def _on_configure(self, event):
        if event.widget is not self.window:
            return
        width = max(self.MIN_WIDTH, event.width)
        height = max(self.MIN_HEIGHT, event.height)
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        self._layout()

    def _resize_press(self, event):
        self.resize_origin = (event.x_root, event.y_root)
        self.resize_start = (self.width, self.height)

    def _resize_drag(self, event):
        if not self.resize_origin or not self.resize_start:
            return
        dx = event.x_root - self.resize_origin[0]
        dy = event.y_root - self.resize_origin[1]
        width = clamp(self.resize_start[0] + dx, self.MIN_WIDTH, 720)
        height = clamp(self.resize_start[1] + dy, self.MIN_HEIGHT, 560)
        self.window.geometry(f"{width}x{height}+{self.window.winfo_x()}+{self.window.winfo_y()}")

    def _resize_release(self, _event):
        self.resize_origin = None
        self.resize_start = None
        self._save_settings()

    def _save_settings(self):
        if not self.pet.settings_path:
            return
        try:
            data = {}
            if self.pet.settings_path.exists():
                data = json.loads(self.pet.settings_path.read_text("utf-8"))
            data["settingsWidth"] = self.width
            data["settingsHeight"] = self.height
            temp = self.pet.settings_path.with_suffix(".tmp")
            temp.write_text(json.dumps(data), "utf-8")
            temp.replace(self.pet.settings_path)
        except (OSError, ValueError, TypeError):
            pass

    def close(self):
        if getattr(self.pet, "settings_window", None) is self:
            self.pet.settings_window = None
        self._save_settings()
        self.pet._save_settings()
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class PetWindow:
    def __init__(
        self,
        sprite_path: Path,
        state_path: Path,
        position_path,
        settings_path,
    ):
        self.sprite_path = sprite_path
        self.state_path = state_path
        self.position_path = position_path
        self.settings_path = settings_path
        self.last_state = None
        self.task = ""
        self.status = "idle"
        self.row = "idle"
        self.pose = "idle"
        self.gesture_token = 0
        self.gesture_after_job = None
        self.last_click_pose = None
        self.click_pose_bag = []
        self.last_double_click_pose = None
        self.last_idle_pose = None
        self.idle_gesture_job = None
        self.single_click_job = None
        self.last_completion_seq = None
        self.completion_jumps_remaining = 0
        self.completion_frame = 0
        self.completion_between_jumps = False
        self.completion_pending = False
        self.overlay_health_job = None
        self.physics_after_job = None
        self.physics_body = None
        self.physics_last_tick = None
        self.physics_work_areas = []
        self.landing_after_job = None
        self.landing_started = None
        self.landing_strength = 0.0
        self.frame = 0
        self.flight_frame = FLIGHT_TAKEOFF_START_FRAME
        self.flight_landing_frame = FLIGHT_LANDING_FRAMES[0]
        self.flight_phase = "takeoff"
        self.drag_tracker = DragTracker(threshold=DRAG_THRESHOLD_PX)
        self.drag_work_areas = []
        self.drag_position = None
        self.monitor_index = 0
        self.dragged = False
        self.drag_flight_active = False
        self.drag_flight_job = None
        self.anchor_pid = 0
        self.dsh_pid_path = state_path.with_name("dsh.pid")
        self.hidden_path = state_path.with_name("hidden.flag")
        self.log_path = state_path.with_name("pet-window.log")
        (
            self.size_percent,
            self.opacity_percent,
            self.throw_power_percent,
            self.reduced_motion,
            self.lock_position,
            self.idle_interval_percent,
        ) = self._load_settings()
        self.menu = None
        self.settings_window = None
        self.grab_active = False

        self.sheet = Image.open(sprite_path).convert("RGBA")
        pose_root = sprite_path.parent / "poses"
        self.poses = {}
        for pose_name in POSE_NAMES:
            frames = []
            for frame_index in range(POSE_FRAME_COUNTS[pose_name]):
                pose_path = pose_root / f"{pose_name}_{frame_index}.png"
                if not pose_path.exists():
                    frames = []
                    break
                frames.append(Image.open(pose_path).convert("RGBA"))
            if not frames:
                fallback = pose_root / f"{pose_name}.png"
                if fallback.exists():
                    frames = [Image.open(fallback).convert("RGBA")]
            if frames:
                self.poses[pose_name] = frames
        self.pose_top = 100
        for frames in self.poses.values():
            for frame in frames:
                bbox = self._pose_cell(frame).getchannel("A").getbbox()
                if bbox:
                    self.pose_top = min(self.pose_top, bbox[1])
        self.row_bounds = {}
        self.gesture_bounds = {}
        self.pose_bounds = self._measure_pose_bounds()
        self.root = tk.Tk()
        self.root.title("GujiGuji Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.attributes("-alpha", self.opacity_percent / 100)
        self.root.configure(bg=TRANSPARENT_KEY)

        width, height = self._window_size()
        self.root.geometry(f"{width}x{height}+0+0")
        self.canvas = tk.Canvas(
            self.root,
            width=width,
            height=height,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.image_item = self.canvas.create_image(
            width // 2,
            self._sprite_top() + self._display_height() // 2,
            anchor="center",
        )
        self.photo = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.root.bind("<Configure>", self._on_configure)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        self.bubble = StatusBubble(self)
        self._render_frame()
        self.root.geometry(self._initial_geometry(width, height))
        self.root.after(120, self._tick_state)
        self.root.after(60, self._tick_animation)
        self.root.after(600, self._maintain_overlay)

    def _load_settings(self) -> tuple[int, int, int, bool, bool, int]:
        if not self.settings_path or not self.settings_path.exists():
            return (
                DEFAULT_SIZE_PERCENT,
                DEFAULT_OPACITY_PERCENT,
                DEFAULT_THROW_POWER_PERCENT,
                False,
                False,
                DEFAULT_IDLE_INTERVAL_PERCENT,
            )
        try:
            data = json.loads(self.settings_path.read_text("utf-8"))
            size = round(float(data.get("sizePercent", DEFAULT_SIZE_PERCENT)))
            opacity = round(
                float(data.get("opacityPercent", DEFAULT_OPACITY_PERCENT))
            )
            throw_power = round(
                float(
                    data.get(
                        "throwPowerPercent",
                        DEFAULT_THROW_POWER_PERCENT,
                    )
                )
            )
            reduced_motion = parse_bool(data.get("reducedMotion"), False)
            lock_position = parse_bool(data.get("lockPosition"), False)
            idle_interval = round(
                float(
                    data.get(
                        "idleIntervalPercent",
                        DEFAULT_IDLE_INTERVAL_PERCENT,
                    )
                )
            )
            return (
                clamp(size, MIN_SIZE_PERCENT, MAX_SIZE_PERCENT),
                clamp(opacity, MIN_OPACITY_PERCENT, MAX_OPACITY_PERCENT),
                clamp(
                    throw_power,
                    MIN_THROW_POWER_PERCENT,
                    MAX_THROW_POWER_PERCENT,
                ),
                reduced_motion,
                lock_position,
                clamp(
                    idle_interval,
                    MIN_IDLE_INTERVAL_PERCENT,
                    MAX_IDLE_INTERVAL_PERCENT,
                ),
            )
        except (OSError, ValueError, TypeError):
            return (
                DEFAULT_SIZE_PERCENT,
                DEFAULT_OPACITY_PERCENT,
                DEFAULT_THROW_POWER_PERCENT,
                False,
                False,
                DEFAULT_IDLE_INTERVAL_PERCENT,
            )

    def _save_settings(self):
        if not self.settings_path:
            return
        try:
            data = {}
            if self.settings_path.exists():
                try:
                    data = json.loads(self.settings_path.read_text("utf-8"))
                except (OSError, ValueError, TypeError):
                    data = {}
            data["sizePercent"] = self.size_percent
            data["opacityPercent"] = self.opacity_percent
            data["throwPowerPercent"] = self.throw_power_percent
            data["reducedMotion"] = self.reduced_motion
            data["lockPosition"] = self.lock_position
            data["idleIntervalPercent"] = self.idle_interval_percent
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.settings_path.with_suffix(".tmp")
            temp.write_text(json.dumps(data), "utf-8")
            temp.replace(self.settings_path)
        except OSError:
            pass

    def _load_position(self):
        if not self.position_path or not self.position_path.exists():
            return None
        try:
            saved = json.loads(self.position_path.read_text("utf-8"))
            if isinstance(saved.get("left"), int) and isinstance(saved.get("top"), int):
                return saved["left"], saved["top"]
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _initial_geometry(self, width: int, height: int) -> str:
        saved = self._load_position()
        left, top = saved or self._default_position(width, height)
        areas = self._work_area_rects()
        geometry = self._body_geometry()
        self.monitor_index = monitor_index_for_rect(
            geometry.bounds_at(left, top),
            areas,
            self.monitor_index,
        )
        left, top = clamp_window_to_monitor(
            left,
            top,
            geometry,
            areas[self.monitor_index],
        )
        return f"{width}x{height}+{round(left)}+{round(top)}"

    def _default_position(self, width: int, height: int):
        left, top, right, bottom = self.virtual_desktop()
        return right - width - 24, bottom - height - 72

    @staticmethod
    def virtual_desktop():
        """Return the complete multi-monitor Windows desktop rectangle."""
        if sys.platform != "win32":
            return 0, 0, 1920, 1080
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        return (
            user32.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
            user32.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
            user32.GetSystemMetrics(76) + user32.GetSystemMetrics(78),
            user32.GetSystemMetrics(77) + user32.GetSystemMetrics(79),
        )

    @staticmethod
    def monitor_work_areas():
        """Return each monitor's usable rectangle in virtual-screen pixels."""
        if sys.platform != "win32":
            return []

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", Rect),
                ("rcWork", Rect),
                ("dwFlags", wintypes.DWORD),
            ]

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetMonitorInfoW.argtypes = [
                wintypes.HMONITOR,
                ctypes.POINTER(MonitorInfo),
            ]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            callback_type = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HMONITOR,
                wintypes.HDC,
                ctypes.POINTER(Rect),
                wintypes.LPARAM,
            )
            result = []

            @callback_type
            def collect(hmonitor, _hdc, _rect, _data):
                info = MonitorInfo()
                info.cbSize = ctypes.sizeof(info)
                if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                    work = info.rcWork
                    result.append((work.left, work.top, work.right, work.bottom))
                return True

            user32.EnumDisplayMonitors.argtypes = [
                wintypes.HDC,
                ctypes.POINTER(Rect),
                callback_type,
                wintypes.LPARAM,
            ]
            user32.EnumDisplayMonitors.restype = wintypes.BOOL
            if not user32.EnumDisplayMonitors(None, None, collect, 0):
                return []
            return result
        except (AttributeError, OSError, TypeError, ValueError):
            return []

    @classmethod
    def _work_area_for_rect(
        cls,
        left: int,
        top: int,
        width: int,
        height: int,
    ):
        """Pick the monitor containing the pet, then use only its work area."""
        right = left + width
        bottom = top + height
        center_x = left + width // 2
        center_y = top + height // 2
        work_areas = cls.monitor_work_areas()
        if not work_areas:
            return cls.virtual_desktop()
        for area in work_areas:
            if area[0] <= center_x < area[2] and area[1] <= center_y < area[3]:
                return area

        def overlap(area):
            overlap_width = max(
                0,
                min(right, area[2]) - max(left, area[0]),
            )
            overlap_height = max(
                0,
                min(bottom, area[3]) - max(top, area[1]),
            )
            return overlap_width * overlap_height

        return max(work_areas, key=overlap)

    @classmethod
    def _work_area_rects(cls):
        raw_areas = cls.monitor_work_areas()
        if not raw_areas:
            raw_areas = [cls.virtual_desktop()]
        return [Rect(*area) for area in raw_areas]

    def _clamp_to_screen(self, left: int, top: int, width: int, height: int):
        work_left, work_top, work_right, work_bottom = self._work_area_for_rect(
            left,
            top,
            width,
            height,
        )
        left = max(
            work_left,
            min(left, max(work_left, work_right - width)),
        )
        top = max(
            work_top,
            min(top, max(work_top, work_bottom - height)),
        )
        return left, top

    def _display_width(self) -> int:
        return round(POSE_CELL_W * DEFAULT_SCALE * self.size_percent / 100)

    def _display_height(self) -> int:
        return round(POSE_CELL_H * DEFAULT_SCALE * self.size_percent / 100)

    def _window_size(self):
        # Every state uses the same 320x320 pose canvas so the standing frame
        # and gesture frames keep the same apparent size when switching.
        margin = 8
        return self._display_width() + margin * 2, self._display_height() + margin * 2

    def _body_geometry(self) -> BodyGeometry:
        width, _ = self._window_size()
        display_w = self._display_width()
        display_h = self._display_height()
        scale_x = display_w / POSE_CELL_W
        scale_y = display_h / POSE_CELL_H
        origin_x = (width - display_w) // 2
        origin_y = self._sprite_top()
        left, top, right, bottom = self._active_body_bounds()
        # _pose_cell lifts frames that overshoot the shared foot line, so this
        # visible bottom is also the exact floor contact used by physics.
        return BodyGeometry(
            origin_x + left * scale_x,
            origin_y + top * scale_y,
            origin_x + right * scale_x,
            origin_y + bottom * scale_y,
        )

    def _active_body_bounds(self):
        if self.physics_body is not None or self.drag_flight_active:
            return self.row_bounds.get(FLIGHT_ROW, self.pose_bounds)
        if self._completion_active():
            return self.row_bounds.get(FLIGHT_ROW, self.pose_bounds)
        if self.pose in GESTURE_POSES and self.pose in self.poses:
            return self.gesture_bounds.get(self.pose, self.pose_bounds)
        if self.status == "idle" and self.pose == "idle":
            return self.row_bounds.get("idle", self.pose_bounds)
        animation_row = self._current_animation_row()
        return self.row_bounds.get(animation_row, self.pose_bounds)

    def _current_animation_row(self):
        if self._completion_active():
            return FLIGHT_ROW
        if self.row == "running" and not self.reduced_motion:
            return "jumping"
        return self.row

    def _clamp_current_window_to_monitor(self):
        areas = self._work_area_rects()
        if not areas:
            return
        geometry = self._body_geometry()
        left, top = self.root.winfo_x(), self.root.winfo_y()
        self.monitor_index = monitor_index_for_rect(
            geometry.bounds_at(left, top),
            areas,
            self.monitor_index,
        )
        clamped = clamp_window_to_monitor(
            left,
            top,
            geometry,
            areas[self.monitor_index],
        )
        left, top = round(clamped[0]), round(clamped[1])
        if left != self.root.winfo_x() or top != self.root.winfo_y():
            self.root.geometry(f"+{left}+{top}")

    def _bubble_anchor_top(self) -> int:
        """Keep the task bubble just above the tallest possible pose."""
        scale = self._display_height() / POSE_CELL_H
        return self._sprite_top() + round(self.pose_top * scale)

    @staticmethod
    def _sprite_top() -> int:
        return 8

    @staticmethod
    def _pose_cell(cell: Image.Image) -> Image.Image:
        """Place a sheet cell on the same canvas used by generated poses."""
        if cell.size == (POSE_CELL_W, POSE_CELL_H):
            return cell
        bbox = cell.getchannel("A").getbbox()
        if not bbox:
            return Image.new("RGBA", (POSE_CELL_W, POSE_CELL_H), (0, 0, 0, 0))
        content = cell.crop(bbox)
        if cell.size == (CELL_W, CELL_H):
            # Preserve the sheet's motion and horizontal placement while
            # mapping its foot baseline into the gesture canvas.
            left = (POSE_CELL_W - CELL_W) // 2 + bbox[0]
            top = (POSE_BASELINE - SHEET_BASELINE) + bbox[1]
            canvas = Image.new("RGBA", (POSE_CELL_W, POSE_CELL_H), (0, 0, 0, 0))
            canvas.alpha_composite(content, (left, top))
            placed_bbox = canvas.getchannel("A").getbbox()
            if placed_bbox and placed_bbox[3] > POSE_BASELINE:
                # Keep rare source frames from hanging below the shared floor.
                lifted = Image.new(
                    "RGBA",
                    (POSE_CELL_W, POSE_CELL_H),
                    (0, 0, 0, 0),
                )
                lifted.alpha_composite(
                    canvas,
                    (0, POSE_BASELINE - placed_bbox[3]),
                )
                return lifted
            return canvas
        max_width = POSE_CELL_W - POSE_PADDING * 2
        max_height = POSE_BASELINE - POSE_PADDING
        if content.width > max_width or content.height > max_height:
            scale = min(max_width / content.width, max_height / content.height)
            content = content.resize(
                (
                    max(1, round(content.width * scale)),
                    max(1, round(content.height * scale)),
                ),
                Image.Resampling.NEAREST,
            )
        canvas = Image.new("RGBA", (POSE_CELL_W, POSE_CELL_H), (0, 0, 0, 0))
        left = (POSE_CELL_W - content.width) // 2
        top = POSE_BASELINE - content.height
        canvas.alpha_composite(content, (left, top))
        return canvas

    def _measure_pose_bounds(self):
        """Measure every rendered pose so no transparent edge is treated as body."""
        boxes = []
        for row_index, (row_name, frame_count) in enumerate(ROWS):
            row_boxes = []
            for frame_index in range(frame_count):
                left = frame_index * CELL_W
                top = row_index * CELL_H
                cell = self.sheet.crop(
                    (left, top, left + CELL_W, top + CELL_H)
                )
                bbox = self._pose_cell(cell).getchannel("A").getbbox()
                if bbox:
                    boxes.append(bbox)
                    row_boxes.append(bbox)
            if row_boxes:
                self.row_bounds[row_name] = (
                    min(box[0] for box in row_boxes),
                    min(box[1] for box in row_boxes),
                    max(box[2] for box in row_boxes),
                    max(box[3] for box in row_boxes),
                )
        for pose_name in GESTURE_POSES:
            pose_boxes = []
            for frame in self.poses.get(pose_name, ()):
                bbox = self._pose_cell(frame).getchannel("A").getbbox()
                if bbox:
                    boxes.append(bbox)
                    pose_boxes.append(bbox)
            if pose_boxes:
                self.gesture_bounds[pose_name] = (
                    min(box[0] for box in pose_boxes),
                    min(box[1] for box in pose_boxes),
                    max(box[2] for box in pose_boxes),
                    max(box[3] for box in pose_boxes),
                )
        if not boxes:
            return (POSE_PADDING, POSE_PADDING, POSE_CELL_W, POSE_BASELINE)
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    @staticmethod
    def _scaled_jump(cell: Image.Image, travel_scale: float) -> Image.Image:
        bbox = cell.getchannel("A").getbbox()
        if not bbox:
            return cell
        _, _, _, bottom = bbox
        target_bottom = round(
            POSE_BASELINE - (POSE_BASELINE - bottom) * travel_scale
        )
        shift = target_bottom - bottom
        if shift <= 0:
            return cell
        reduced = Image.new("RGBA", cell.size, (0, 0, 0, 0))
        reduced.alpha_composite(cell, (0, shift))
        return reduced

    def _scaled_running_jump(self, cell: Image.Image) -> Image.Image:
        """Keep the work bob, but reduce its vertical travel."""
        if self.reduced_motion or self.row != "running":
            return cell
        return self._scaled_jump(cell, RUNNING_JUMP_SCALE)

    def _scaled_completion_jump(self, cell: Image.Image) -> Image.Image:
        if self.reduced_motion:
            return cell
        return self._scaled_jump(cell, COMPLETION_JUMP_SCALE)

    def set_size_percent(self, percent: int):
        percent = clamp(round(percent), MIN_SIZE_PERCENT, MAX_SIZE_PERCENT)
        if percent == self.size_percent:
            return
        self._cancel_physics(save_position=False)
        old_w = max(1, self.root.winfo_width())
        old_h = max(1, self.root.winfo_height())
        old_x = self.root.winfo_x()
        old_y = self.root.winfo_y()
        center_x = old_x + old_w // 2
        bottom = old_y + old_h

        self.size_percent = percent
        width, height = self._window_size()
        left = round(center_x - width / 2)
        top = bottom - height
        areas = self._work_area_rects()
        geometry = self._body_geometry()
        self.monitor_index = monitor_index_for_rect(
            geometry.bounds_at(left, top),
            areas,
            self.monitor_index,
        )
        left, top = clamp_window_to_monitor(
            left,
            top,
            geometry,
            areas[self.monitor_index],
        )
        left, top = round(left), round(top)
        self.root.geometry(f"{width}x{height}+{left}+{top}")
        self.canvas.configure(width=width, height=height)
        self._render_frame()
        self.root.after_idle(self.bubble.place)
        self.root.after_idle(lambda: reassert_overlay(self.root))
        self._save_settings()

    def set_opacity_percent(self, percent: int):
        percent = clamp(
            round(percent),
            MIN_OPACITY_PERCENT,
            MAX_OPACITY_PERCENT,
        )
        if percent == self.opacity_percent:
            return
        self.opacity_percent = percent
        alpha = percent / 100
        self.root.attributes("-alpha", alpha)
        self.bubble.window.attributes("-alpha", BUBBLE_OPACITY * alpha)
        if self.menu is not None:
            try:
                self.menu.window.attributes("-alpha", 0.96 * alpha)
            except tk.TclError:
                pass
        if self.settings_window is not None:
            try:
                self.settings_window.window.attributes("-alpha", alpha)
            except tk.TclError:
                pass
        self._save_settings()

    def set_throw_power_percent(self, percent: int):
        percent = clamp(
            round(percent),
            MIN_THROW_POWER_PERCENT,
            MAX_THROW_POWER_PERCENT,
        )
        if percent == self.throw_power_percent:
            return
        self.throw_power_percent = percent
        self._save_settings()

    def set_idle_interval_percent(self, percent: int):
        percent = clamp(
            round(percent),
            MIN_IDLE_INTERVAL_PERCENT,
            MAX_IDLE_INTERVAL_PERCENT,
        )
        if percent == self.idle_interval_percent:
            return
        self.idle_interval_percent = percent
        if self.status == "idle" and self.pose not in GESTURE_POSES:
            self._schedule_idle_gesture()
        self._save_settings()

    def set_lock_position(self, locked: bool):
        locked = bool(locked)
        if locked == self.lock_position:
            return
        self.lock_position = locked
        if locked:
            self._cancel_physics(save_position=True)
        self._save_settings()

    def reset_position(self):
        self._cancel_physics(save_position=False)
        width, height = self._window_size()
        left, top = self._default_position(width, height)
        areas = self._work_area_rects()
        geometry = self._body_geometry()
        self.monitor_index = monitor_index_for_rect(
            geometry.bounds_at(left, top),
            areas,
            self.monitor_index,
        )
        left, top = clamp_window_to_monitor(
            left,
            top,
            geometry,
            areas[self.monitor_index],
        )
        left, top = round(left), round(top)
        self.root.geometry(f"{width}x{height}+{left}+{top}")
        self._save_position(left, top)
        self.root.after_idle(self.bubble.place)

    def set_reduced_motion(self, reduced: bool):
        reduced = bool(reduced)
        if reduced == self.reduced_motion:
            return
        self.reduced_motion = reduced
        if reduced:
            self._cancel_drag_flight_hold()
            self._cancel_idle_gesture()
            self._cancel_completion_jumps(redraw=False)
            self.grab_active = False
            self._set_drag_flight_active(False, redraw=False)
            self._cancel_landing(redraw=False)
        elif self.status == "idle" and self.pose not in GESTURE_POSES:
            self._schedule_idle_gesture()
        self._render_frame()
        self._save_settings()

    def _set_grab_feedback(self, active: bool):
        active = bool(
            active
            and not self.reduced_motion
            and not self.lock_position
        )
        if active == self.grab_active:
            return
        self.grab_active = active
        self._render_frame()

    def _set_drag_flight_active(self, active: bool, redraw: bool = True):
        active = bool(
            active
            and not self.reduced_motion
            and not self.lock_position
        )
        if active == self.drag_flight_active:
            return
        self.drag_flight_active = active
        self.flight_phase = "takeoff"
        if active:
            self.flight_frame = FLIGHT_TAKEOFF_START_FRAME
        self._log(
            f"drag flight active={self.drag_flight_active} "
            f"frame={self.flight_frame} phase={self.flight_phase}"
        )
        if redraw:
            self._render_frame()

    def _schedule_drag_flight_hold(self):
        self._cancel_drag_flight_hold()
        if self.reduced_motion or self.lock_position:
            return
        self.drag_flight_job = self.root.after(
            DRAG_FLIGHT_HOLD_MS,
            self._activate_drag_flight_from_hold,
        )

    def _activate_drag_flight_from_hold(self):
        self.drag_flight_job = None
        press_pointer = self.drag_tracker.press_pointer
        if press_pointer is None:
            return
        try:
            pointer = self.root.winfo_pointerxy()
        except tk.TclError:
            return
        dx = pointer[0] - press_pointer[0]
        dy = pointer[1] - press_pointer[1]
        if dx * dx + dy * dy >= DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX:
            self._set_drag_flight_active(True)

    def _cancel_drag_flight_hold(self):
        if self.drag_flight_job is None:
            return
        try:
            self.root.after_cancel(self.drag_flight_job)
        except tk.TclError:
            pass
        self.drag_flight_job = None

    def _on_press(self, event):
        self._cancel_completion_jumps()
        self._log(
            f"pet press x={event.x_root} y={event.y_root} "
            f"status={self.status} pose={self.pose} frame={self.frame}"
        )
        if self.menu is not None:
            self.menu.close()
        self._cancel_physics(save_position=True)
        self._set_drag_flight_active(False, redraw=False)
        self._set_grab_feedback(True)
        self.drag_work_areas = self._work_area_rects()
        self.monitor_index = monitor_index_for_rect(
            self._body_geometry().bounds_at(
                self.root.winfo_x(),
                self.root.winfo_y(),
            ),
            self.drag_work_areas,
            self.monitor_index,
        )
        self.drag_tracker.press(
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
            time.perf_counter(),
        )
        self.drag_position = (self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False
        self._schedule_drag_flight_hold()

    def _move_drag_to(self, pointer_x: float, pointer_y: float) -> bool:
        if self.lock_position:
            return False
        dragged = self.drag_tracker.move(
            pointer_x,
            pointer_y,
            time.perf_counter(),
        )
        if dragged and not self.drag_flight_active:
            self._set_drag_flight_active(True)
        self.dragged = self.dragged or dragged
        if not dragged or not self.drag_work_areas:
            return dragged
        position = self.drag_tracker.window_position(pointer_x, pointer_y)
        if position is None:
            return dragged
        self.monitor_index = monitor_index_at_point(
            self.drag_work_areas,
            pointer_x,
            pointer_y,
            self.monitor_index,
        )
        left, top = clamp_window_to_monitor(
            position[0],
            position[1],
            self._body_geometry(),
            self.drag_work_areas[self.monitor_index],
        )
        left, top = round(left), round(top)
        self.drag_position = (left, top)
        if left != self.root.winfo_x() or top != self.root.winfo_y():
            self.root.geometry(f"+{left}+{top}")
        return dragged

    def _on_drag(self, event):
        self._move_drag_to(event.x_root, event.y_root)
        if self.drag_tracker.dragged:
            self._set_drag_flight_active(True)

    def _on_release(self, event):
        self._cancel_drag_flight_hold()
        self._set_grab_feedback(False)
        if self.lock_position:
            self.drag_tracker.reset()
            release_dragged = False
            release_velocity = None
        else:
            self._move_drag_to(event.x_root, event.y_root)
            release = self.drag_tracker.release(
                event.x_root,
                event.y_root,
                time.perf_counter(),
                self.throw_power_percent / 100,
            )
            release_dragged = release.dragged
            release_velocity = release.velocity
        self.drag_work_areas = []
        self._log(
            f"pet release dragged={release_dragged} "
            f"velocity={0 if release_velocity is None else round(release_velocity.speed)} "
            f"status={self.status} pose={self.pose} frame={self.frame}"
        )
        drag_position = self.drag_position or (
            self.root.winfo_x(),
            self.root.winfo_y(),
        )
        self.drag_position = None
        if not release_dragged:
            self._set_drag_flight_active(False)
            if self.dragged:
                return
            self._schedule_single_click()
            return

        self.dragged = True
        velocity = release_velocity
        self._start_physics(
            drag_position[0],
            drag_position[1],
            0.0 if velocity is None else velocity.vx,
            0.0 if velocity is None else velocity.vy,
        )

    def _start_physics(self, left: float, top: float, vx: float, vy: float):
        continue_takeoff = self.drag_flight_active
        takeoff_frame = self.flight_frame
        self.drag_flight_active = False
        self._cancel_completion_jumps(redraw=False)
        self._cancel_physics(save_position=False)
        self.physics_work_areas = self._work_area_rects()
        self.monitor_index = monitor_index_for_rect(
            self._body_geometry().bounds_at(left, top),
            self.physics_work_areas,
            self.monitor_index,
        )
        self.physics_body = ThrowBody(
            float(left),
            float(top),
            float(vx),
            float(vy),
            self.monitor_index,
        )
        self.flight_phase = "takeoff"
        if continue_takeoff and takeoff_frame in FLIGHT_TAKEOFF_FRAMES:
            self.flight_frame = takeoff_frame
        else:
            self.flight_frame = FLIGHT_TAKEOFF_START_FRAME
        self.flight_landing_frame = FLIGHT_LANDING_FRAMES[0]
        self.physics_last_tick = time.perf_counter()
        if vy >= 0 and self._flight_floor_gap(self.physics_body) <= self._flight_landing_gap_limit():
            self.flight_phase = "landing"
        self.bubble.set_motion_hidden(True)
        self._log(
            f"physics start x={left} y={top} "
            f"vx={round(vx)} vy={round(vy)} monitor={self.monitor_index}"
        )
        self._render_frame()
        self.physics_after_job = self.root.after(
            PHYSICS_FRAME_MS,
            self._tick_physics,
        )

    def _flight_floor_gap(self, body) -> float:
        if body is None or not self.physics_work_areas:
            return float("inf")
        monitor_index = min(
            max(0, body.monitor_index),
            len(self.physics_work_areas) - 1,
        )
        monitor = self.physics_work_areas[monitor_index]
        bounds = self._body_geometry().bounds_at(body.x, body.y)
        return max(0.0, monitor.bottom - bounds.bottom)

    def _flight_landing_gap_limit(self) -> float:
        return max(
            FLIGHT_LANDING_GAP_MIN,
            self._display_height() * FLIGHT_LANDING_GAP_RATIO,
        )

    def _update_flight_phase(self, body, landed: bool):
        if landed:
            self.flight_phase = "landed"
            return
        if self.flight_phase != "takeoff" or body.vy < 0:
            return
        gap = self._flight_floor_gap(body)
        if gap > self._flight_landing_gap_limit():
            return
        self.flight_phase = "landing"
        self.flight_landing_frame = FLIGHT_LANDING_FRAMES[0]
        self._log(f"flight landing approach gap={round(gap)}")

    @staticmethod
    def _next_flight_frame(current: int, frames: tuple[int, ...]) -> int:
        try:
            index = frames.index(current)
        except ValueError:
            index = 0
        return frames[(index + 1) % len(frames)]

    def _start_landing(self, impact_speed: float):
        self._cancel_landing(redraw=False)
        self.landing_started = time.perf_counter()
        self.landing_strength = landing_strength_for_impact(impact_speed)
        self._render_frame()
        self.landing_after_job = self.root.after(
            LANDING_FRAME_MS,
            self._tick_landing,
        )

    def _tick_landing(self):
        self.landing_after_job = None
        if self.landing_started is None:
            return
        elapsed = time.perf_counter() - self.landing_started
        if elapsed * 1000 >= LANDING_DURATION_MS:
            self._cancel_landing(redraw=True)
            return
        self._render_frame()
        self.landing_after_job = self.root.after(
            LANDING_FRAME_MS,
            self._tick_landing,
        )

    def _cancel_landing(self, redraw: bool):
        if self.landing_after_job is not None:
            try:
                self.root.after_cancel(self.landing_after_job)
            except tk.TclError:
                pass
            self.landing_after_job = None
        active = self.landing_started is not None
        self.landing_started = None
        self.landing_strength = 0.0
        if redraw and active:
            self._render_frame()

    def _tick_physics(self):
        self.physics_after_job = None
        if self.physics_body is None:
            return
        now = time.perf_counter()
        delta = now - (self.physics_last_tick or now)
        self.physics_last_tick = now
        result = step_throw(
            self.physics_body,
            delta,
            self._body_geometry(),
            self.physics_work_areas,
        )
        self.physics_body = result.body
        self.monitor_index = result.body.monitor_index
        self._update_flight_phase(result.body, result.landed)
        left = round(result.body.x)
        top = round(result.body.y)
        if left != self.root.winfo_x() or top != self.root.winfo_y():
            self.root.geometry(f"+{left}+{top}")
        if result.landed:
            self._log(
                f"physics landed impact={round(result.impact_speed)} "
                f"x={left} y={top} monitor={self.monitor_index}"
            )
            self._start_landing(result.impact_speed)
        if result.at_rest:
            self._finish_physics()
            return
        self.physics_after_job = self.root.after(
            PHYSICS_FRAME_MS,
            self._tick_physics,
        )

    def _finish_physics(self):
        body = self.physics_body
        self.physics_body = None
        self.drag_flight_active = False
        self.flight_phase = "takeoff"
        self.flight_frame = FLIGHT_TAKEOFF_START_FRAME
        self.flight_landing_frame = FLIGHT_LANDING_FRAMES[0]
        self.physics_last_tick = None
        self.physics_work_areas = []
        if body is not None:
            left, top = round(body.x), round(body.y)
            self.root.geometry(f"+{left}+{top}")
        if body is not None:
            self._save_position(round(body.x), round(body.y))
        else:
            self._save_position()
        self._render_frame()
        self.bubble.set_motion_hidden(False)
        self._log("physics rest")
        if self.completion_pending:
            self._start_completion_jumps()

    def _cancel_physics(self, save_position: bool):
        active = (
            self.physics_body is not None
            or self.physics_after_job is not None
            or self.landing_started is not None
            or self.grab_active
            or self.drag_flight_active
        )
        self._cancel_landing(redraw=False)
        if self.physics_after_job is not None:
            try:
                self.root.after_cancel(self.physics_after_job)
            except tk.TclError:
                pass
            self.physics_after_job = None
        body = self.physics_body
        self.physics_body = None
        self.drag_flight_active = False
        self.flight_phase = "takeoff"
        self.flight_frame = FLIGHT_TAKEOFF_START_FRAME
        self.flight_landing_frame = FLIGHT_LANDING_FRAMES[0]
        self.grab_active = False
        self.physics_last_tick = None
        self.physics_work_areas = []
        if body is not None and save_position:
            left, top = round(body.x), round(body.y)
            self.root.geometry(f"+{left}+{top}")
            self._save_position(left, top)
        if active:
            self._render_frame()
        self.bubble.set_motion_hidden(False)

    def _save_position(self, left=None, top=None):
        if not self.position_path:
            return
        payload = {
            "left": self.root.winfo_x() if left is None else left,
            "top": self.root.winfo_y() if top is None else top,
        }
        try:
            self.position_path.write_text(json.dumps(payload), "utf-8")
        except OSError:
            pass

    def _schedule_single_click(self):
        self._cancel_single_click()
        # Delay the single-click gesture so a recognized double-click can
        # replace it cleanly instead of briefly starting another pose.
        self.single_click_job = self.root.after(180, self._run_single_click)

    def _run_single_click(self):
        self.single_click_job = None
        pose = self._next_click_gesture()
        self._log(f"single-click gesture pose={pose}")
        self._start_gesture(pose)

    def _schedule_idle_gesture(self):
        self._cancel_idle_gesture()
        if (
            self.reduced_motion
            or self.status != "idle"
            or self.pose in GESTURE_POSES
            or self._completion_active()
        ):
            return
        minimum, maximum = self._idle_delay_bounds()
        delay = random.randint(minimum, maximum)
        self._log(f"idle gesture scheduled delay={delay}ms")
        self.idle_gesture_job = self.root.after(delay, self._run_idle_gesture)

    def _idle_delay_bounds(self) -> tuple[int, int]:
        scale = self.idle_interval_percent / 100
        return (
            max(1_000, round(IDLE_GESTURE_MIN_DELAY_MS * scale)),
            max(1_000, round(IDLE_GESTURE_MAX_DELAY_MS * scale)),
        )

    def _run_idle_gesture(self):
        self.idle_gesture_job = None
        if (
            self.reduced_motion
            or self.status != "idle"
            or self.pose in GESTURE_POSES
            or self._completion_active()
        ):
            return
        pose = self._next_idle_gesture()
        self._log(f"idle gesture pose={pose}")
        self._start_gesture(pose)

    def _next_idle_gesture(self):
        available = [
            pose
            for pose in IDLE_POSES
            if pose in self.poses and pose != self.last_idle_pose
        ]
        if not available:
            available = [pose for pose in IDLE_POSES if pose in self.poses]
        pose = random.choice(available) if available else IDLE_POSES[0]
        self.last_idle_pose = pose
        return pose

    def _cancel_idle_gesture(self):
        if self.idle_gesture_job is None:
            return
        try:
            self.root.after_cancel(self.idle_gesture_job)
        except tk.TclError:
            pass
        self.idle_gesture_job = None

    def _next_click_gesture(self):
        if not self.click_pose_bag:
            bag = list(CLICK_POSES)
            random.shuffle(bag)
            # Avoid repeating the previous action across bag boundaries.
            if self.last_click_pose in bag and bag[0] == self.last_click_pose:
                bag[0], bag[-1] = bag[-1], bag[0]
            self.click_pose_bag = bag
        pose = self.click_pose_bag.pop(0)
        self.last_click_pose = pose
        return pose

    def _next_double_click_gesture(self):
        available = [
            pose
            for pose in DOUBLE_CLICK_POSES
            if pose in self.poses and pose != self.last_double_click_pose
        ]
        if not available:
            available = [
                pose for pose in DOUBLE_CLICK_POSES if pose in self.poses
            ]
        pose = random.choice(available) if available else DOUBLE_CLICK_POSES[0]
        self.last_double_click_pose = pose
        return pose

    def _cancel_single_click(self):
        if self.single_click_job is None:
            return
        try:
            self.root.after_cancel(self.single_click_job)
        except tk.TclError:
            pass
        self.single_click_job = None

    def _start_gesture(self, pose: str):
        if pose not in GESTURE_POSES or pose not in self.poses:
            self._log(f"gesture skipped pose={pose}: pose unavailable")
            return
        self._cancel_completion_jumps(redraw=False)
        self._cancel_idle_gesture()
        self._cancel_gesture_timer()
        self.pose = pose
        self.gesture_token += 1
        token = self.gesture_token
        self.frame = 0
        self._clamp_current_window_to_monitor()
        self._log(
            f"gesture start pose={self.pose} frame={self.frame} "
            f"frames={len(self.poses[self.pose])} token={token}"
        )
        self._render_frame()
        self.gesture_after_job = self.root.after(
            self._gesture_frame_delay(self.pose, self.frame),
            lambda: self._advance_gesture(token),
        )

    def _advance_gesture(self, token=None):
        if token is not None and token != self.gesture_token:
            return
        if self.pose not in GESTURE_POSES or self.pose not in self.poses:
            return
        self.frame += 1
        if self.frame >= len(self.poses[self.pose]):
            self._finish_gesture()
            return
        self._render_frame()
        self.gesture_after_job = self.root.after(
            self._gesture_frame_delay(self.pose, self.frame),
            lambda: self._advance_gesture(token),
        )

    def _gesture_frame_delay(self, pose: str, frame: int) -> int:
        frames = self.poses.get(pose, ())
        if frame <= 0 or frame >= len(frames) - 1:
            return STAND_FRAME_MS
        return POSE_FRAME_MS.get(pose, 240)

    def _finish_gesture(self):
        self._cancel_gesture_timer()
        self.gesture_token += 1
        self._log(
            f"gesture finish pose={self.pose} frame={self.frame}"
        )
        self.pose = "idle"
        self.frame = 0
        self._render_frame()
        if not self.reduced_motion and self.status == "idle":
            self._schedule_idle_gesture()

    def _cancel_gesture_timer(self):
        if self.gesture_after_job is None:
            return
        try:
            self.root.after_cancel(self.gesture_after_job)
        except tk.TclError:
            pass
        self.gesture_after_job = None

    def _completion_active(self) -> bool:
        return int(getattr(self, "completion_jumps_remaining", 0)) > 0

    def _start_completion_jumps(self):
        if self.reduced_motion:
            self._log("completion jumps skipped: reduced motion")
            return
        if getattr(self, "physics_body", None) is not None:
            self.completion_pending = True
            self._log("completion jumps queued until landing")
            return
        self.completion_pending = False
        self._cancel_idle_gesture()
        self._cancel_single_click()
        self._cancel_gesture_timer()
        self.gesture_token += 1
        self.pose = "idle"
        self.frame = 0
        self.completion_jumps_remaining = COMPLETION_JUMP_COUNT
        self.completion_frame = 0
        self.completion_between_jumps = False
        self._log(f"completion jumps start count={COMPLETION_JUMP_COUNT}")
        self._render_frame()

    def _advance_completion_jump(self) -> int:
        if not self._completion_active():
            return 1000
        if self.completion_between_jumps:
            self.completion_between_jumps = False
            self.completion_frame = 0
            self._render_frame()
            return FRAME_MS[FLIGHT_ROW]

        frame_count = ROW_FRAMES[ROW_INDEX[FLIGHT_ROW]]
        self.completion_frame += 1
        if self.completion_frame < frame_count:
            self._render_frame()
            return FRAME_MS[FLIGHT_ROW]

        self.completion_jumps_remaining -= 1
        self.completion_frame = 0
        if self.completion_jumps_remaining > 0:
            self.completion_between_jumps = True
            self._render_frame()
            return COMPLETION_JUMP_GAP_MS

        self._finish_completion_jumps()
        return 1000 if self.status == "idle" else 160

    def _finish_completion_jumps(self):
        self.completion_jumps_remaining = 0
        self.completion_frame = 0
        self.completion_between_jumps = False
        self.completion_pending = False
        self.pose = "idle"
        self.frame = 0
        self._log("completion jumps finish")
        self._render_frame()
        if not self.reduced_motion and self.status == "idle":
            self._schedule_idle_gesture()

    def _cancel_completion_jumps(self, redraw: bool = True):
        was_active = self._completion_active()
        self.completion_pending = False
        self.completion_jumps_remaining = 0
        self.completion_frame = 0
        self.completion_between_jumps = False
        if (
            was_active
            and redraw
            and getattr(self, "physics_body", None) is None
        ):
            self._render_frame()

    def _on_configure(self, event):
        if event.widget is self.root and self.bubble.visible:
            self.bubble.place()

    def _on_double_click(self, _event):
        self._cancel_drag_flight_hold()
        if self.dragged:
            return "break"
        self._cancel_single_click()
        restore_bubble = self._bubble_should_restore()
        self._log(
            "double-click toggle dsh window"
            f" restore_bubble={restore_bubble}"
        )
        self.dragged = True
        pose = self._next_double_click_gesture()
        self._log(f"double-click gesture pose={pose}")
        self._start_gesture(pose)
        # Paint the first gesture frame before doing Win32 window work. Opening
        # or focusing DSH can temporarily block Tk's event loop, which made the
        # feedback appear only after the window had already opened.
        self.root.update_idletasks()
        self.root.after(
            0,
            lambda: self._finish_double_click_toggle(restore_bubble),
        )
        return "break"

    def _finish_double_click_toggle(self, restore_bubble: bool):
        self._toggle_dsh_window()
        if restore_bubble:
            self.bubble.restore()

    def _bubble_should_restore(self) -> bool:
        """Restore a collapsed task bubble only while the task is active."""
        if not self.bubble.collapsed or not self.bubble.visible:
            return False
        return self.status in ("running", "waiting", "failed", "review")

    def _on_right_click(self, event):
        self._cancel_drag_flight_hold()
        self._cancel_completion_jumps()
        self._cancel_physics(save_position=True)
        if self.menu is not None:
            self.menu.close()
        self.menu = ContextMenu(self, event.x_root, event.y_root)
        return "break"

    def open_settings(self):
        if self.settings_window is not None:
            try:
                self.settings_window.window.lift()
                self.settings_window.window.focus_force()
            except tk.TclError:
                self.settings_window = None
            if self.settings_window is not None:
                return
        self.settings_window = SettingsWindow(self)

    def _dsh_pid(self) -> int:
        try:
            return int(self.dsh_pid_path.read_text("utf-8").strip())
        except (OSError, ValueError):
            return self.anchor_pid

    def _log(self, message: str):
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            pass

    @staticmethod
    def _process_path(pid: int) -> str:
        if pid <= 0:
            return ""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(length)
            ):
                return ""
            return buffer.value
        finally:
            kernel32.CloseHandle(handle)

    def _find_dsh_window(self, preferred_pid: int) -> int:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
            wintypes.LPARAM,
        ]
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            executable = self._process_path(pid.value)
            title_length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(hwnd, title, title_length + 1)
            executable_matches = executable.lower().endswith("deepseek harness.exe")
            title_matches = "DeepSeek Harness" in title.value
            if not executable_matches and not title_matches:
                return True
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            visible = bool(user32.IsWindowVisible(hwnd))
            score = 0
            if pid.value == preferred_pid:
                score += 50
            if title_matches:
                score += 100
            elif title.value:
                score += 35
            if class_name.value == "Chrome_WidgetWin_1":
                score += 40
            if visible:
                score += 20
            if score >= 40:
                self._window_candidates.append(
                    (score, hwnd, pid.value, title.value)
                )
            return True

        self._window_candidates = []
        user32.EnumWindows(collect, 0)
        if not self._window_candidates:
            return 0
        self._window_candidates.sort(key=lambda item: item[0], reverse=True)
        _score, hwnd, pid, title = self._window_candidates[0]
        self._log(f"dsh window hwnd={hwnd} pid={pid} title={title}")
        try:
            self.dsh_pid_path.write_text(str(pid), "utf-8")
        except OSError:
            pass
        return hwnd

    def _focus_dsh_window(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.FlashWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.FlashWindow.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        else:
            user32.ShowWindow(hwnd, 5)
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        attached = False
        if target_thread and target_thread != current_thread:
            attached = bool(
                user32.AttachThreadInput(current_thread, target_thread, True)
            )
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            focused = bool(user32.SetForegroundWindow(hwnd))
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, target_thread, False)
        if not focused:
            user32.FlashWindow(hwnd, True)
        return True

    def _launch_dsh(self) -> bool:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", ""))
        candidates = [
            local_app_data / "Programs" / "DeepSeek Harness" / "DeepSeek Harness.exe",
            program_files / "DeepSeek Harness" / "DeepSeek Harness.exe",
        ]
        for executable in candidates:
            if executable.exists():
                try:
                    subprocess.Popen(
                        [str(executable)],
                        cwd=str(executable.parent),
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    self._log(f"dsh launched: {executable}")
                    return True
                except OSError as error:
                    self._log(f"dsh launch error: {error}")
        return False

    def _open_dsh(self):
        if sys.platform != "win32":
            return
        self._log("double-click open dsh")
        hwnd = self._find_dsh_window(self._dsh_pid())
        if hwnd:
            self._focus_dsh_window(hwnd)
            return
        if self._launch_dsh():
            self.root.after(450, lambda: self._poll_dsh_focus(0))

    def _toggle_dsh_window(self):
        if sys.platform != "win32":
            return
        hwnd = self._find_dsh_window(self._dsh_pid())
        if hwnd and self._dsh_window_visible(hwnd):
            self._hide_dsh_window(hwnd)
            return
        self._open_dsh()

    def _dsh_window_visible(self, hwnd: int) -> bool:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        return bool(user32.IsWindowVisible(hwnd))

    def _hide_dsh_window(self, hwnd: int):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
        self._log(f"dsh window hidden hwnd={hwnd}")

    def _poll_dsh_focus(self, attempt: int):
        hwnd = self._find_dsh_window(self._dsh_pid())
        if hwnd:
            self._focus_dsh_window(hwnd)
            return
        if attempt < 20:
            self.root.after(500, lambda: self._poll_dsh_focus(attempt + 1))

    def hide(self):
        self._cancel_physics(save_position=True)
        try:
            self.hidden_path.write_text("", "utf-8")
        except OSError:
            pass
        if self.overlay_health_job is not None:
            try:
                self.root.after_cancel(self.overlay_health_job)
            except tk.TclError:
                pass
            self.overlay_health_job = None
        if self.menu is not None:
            self.menu.close()
        if self.settings_window is not None:
            self.settings_window.close()
        self.bubble.destroy()
        self.root.destroy()

    def _read_state(self) -> dict:
        candidates = [self.state_path]
        app_data = os.environ.get("APPDATA")
        if app_data:
            candidates.extend(
                Path(app_data) / name / "state.json"
                for name in ("dsh-light-feather", "dsh-mint-budgie")
            )

        newest = None
        newest_mtime = float("-inf")
        seen = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            try:
                mtime = path.stat().st_mtime
                state = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if mtime > newest_mtime and isinstance(state, dict):
                newest = state
                newest_mtime = mtime
        return newest or {}

    @staticmethod
    def _completion_sequence(state: dict) -> int:
        value = state.get("completionSeq") if isinstance(state, dict) else 0
        if isinstance(value, bool):
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _tick_state(self):
        state = self._read_state()
        status = state.get("status")
        task = state.get("task") if isinstance(state.get("task"), str) else ""
        activity = state.get("activity") if isinstance(state.get("activity"), str) else ""
        working = state.get("working") is True
        completion_seq = self._completion_sequence(state)
        state_key = (status, task, activity, working, completion_seq)
        if state_key != self.last_state:
            self.last_state = state_key
            self.task = task.strip()
            if isinstance(status, str):
                self.status = status
                self.row = ROW_FOR_STATUS.get(status, "idle")
                if self.status == "idle" and self.pose not in GESTURE_POSES:
                    self.gesture_token += 1
                    self.pose = "idle"
                    self.frame = 0
            if not working and self.status == "running":
                self.status = "idle"
                self.row = "idle"
                if self.pose not in GESTURE_POSES:
                    self.frame = 0
            visible_status = self.status
            if visible_status == "running" and self.pose not in GESTURE_POSES:
                self.row = "running"
                self.frame = 0
            self.bubble.update(visible_status, self.task, activity)
            if self.last_completion_seq is None:
                self.last_completion_seq = completion_seq
            elif completion_seq > self.last_completion_seq:
                self.last_completion_seq = completion_seq
                self._start_completion_jumps()
            elif completion_seq < self.last_completion_seq:
                # A restarted Host resets its process-local sequence.
                self.last_completion_seq = completion_seq
            self._render_frame()
            if self.status == "idle":
                if self.idle_gesture_job is None:
                    self._schedule_idle_gesture()
            else:
                self._cancel_idle_gesture()
            reassert_overlay(self.root)
        self.root.after(120, self._tick_state)

    def _maintain_overlay(self):
        """Keep desktop windows visible without taking focus from the user."""
        reassert_overlay(self.root)
        if (
            self.bubble.visible
            and not self.bubble.collapsed
            and self.bubble.window.winfo_ismapped()
        ):
            reassert_overlay(self.bubble.window)
        if self.menu is not None:
            reassert_overlay(self.menu.window, redraw=False)
        if self.settings_window is not None:
            reassert_overlay(self.settings_window.window, redraw=False)
        self.overlay_health_job = self.root.after(
            OVERLAY_HEALTH_CHECK_MS,
            self._maintain_overlay,
        )

    def _tick_animation(self):
        if self.physics_body is not None:
            if self.flight_phase == "landing":
                self.flight_landing_frame = self._next_flight_frame(
                    self.flight_landing_frame,
                    FLIGHT_LANDING_FRAMES,
                )
                delay = POSE_FRAME_MS.get(FLIGHT_LANDING_POSE, 190)
            elif self.flight_phase == "landed":
                delay = 1000
            else:
                self.flight_frame = self._next_flight_frame(
                    self.flight_frame,
                    FLIGHT_TAKEOFF_FRAMES,
                )
                delay = FRAME_MS[FLIGHT_ROW]
            self._render_frame()
        elif self.drag_flight_active:
            self.flight_frame = self._next_flight_frame(
                self.flight_frame,
                FLIGHT_TAKEOFF_FRAMES,
            )
            delay = FRAME_MS[FLIGHT_ROW]
            self._render_frame()
        elif self._completion_active():
            delay = self._advance_completion_jump()
        elif self.pose in GESTURE_POSES and self.pose in self.poses:
            # The gesture timer owns the frame while a click animation plays.
            # Do not advance or redraw the work row, or the standing frame would
            # briefly be replaced by an unrelated animation frame at the end.
            delay = 160
        elif self.status != "idle":
            # The supplied running row is nearly indistinguishable from
            # standing. Use the more legible jump cycle while work is active.
            animation_row = self._current_animation_row()
            row_index = ROW_INDEX.get(animation_row, 0)
            frames = ROW_FRAMES[row_index]
            self.frame = (self.frame + 1) % frames
            delay = FRAME_MS.get(animation_row, 200)
            self._render_frame()
        elif self.pose == "idle":
            # Standing is static. Repaint only when another state change asks
            # for it instead of running a hidden idle animation in the background.
            delay = 1000
        else:
            delay = 160
        self.root.after(delay, self._tick_animation)

    def _current_pose_cell(self, display_w: int, display_h: int):
        if self.physics_body is not None:
            glide_frames = self.poses.get(FLIGHT_GLIDE_POSE)
            if (
                self.flight_phase in ("takeoff", "landing")
                and glide_frames
            ):
                frame_index = (
                    self.flight_landing_frame
                    if self.flight_phase == "landing"
                    else FLIGHT_GLIDE_FRAME
                )
                cell = glide_frames[frame_index % len(glide_frames)]
            elif self.flight_phase == "landed":
                cell = self.sheet.crop((0, 0, CELL_W, CELL_H))
            else:
                row_index = ROW_INDEX[FLIGHT_ROW]
                left = self.flight_frame * CELL_W
                top = row_index * CELL_H
                cell = self.sheet.crop(
                    (left, top, left + CELL_W, top + CELL_H)
                )
            cell = self._pose_cell(cell)
            return cell.resize(
                (display_w, display_h),
                Image.Resampling.NEAREST,
            )
        if self.drag_flight_active:
            glide_frames = self.poses.get(FLIGHT_GLIDE_POSE)
            if glide_frames:
                cell = glide_frames[
                    FLIGHT_GLIDE_FRAME % len(glide_frames)
                ]
            else:
                row_index = ROW_INDEX[FLIGHT_ROW]
                left = self.flight_frame * CELL_W
                top = row_index * CELL_H
                cell = self.sheet.crop(
                    (left, top, left + CELL_W, top + CELL_H)
                )
            cell = self._pose_cell(cell)
            return cell.resize(
                (display_w, display_h),
                Image.Resampling.NEAREST,
            )
        if self._completion_active():
            if self.completion_between_jumps:
                cell = self.sheet.crop((0, 0, CELL_W, CELL_H))
                cell = self._pose_cell(cell)
            else:
                row_index = ROW_INDEX[FLIGHT_ROW]
                left = self.completion_frame * CELL_W
                top = row_index * CELL_H
                cell = self.sheet.crop(
                    (left, top, left + CELL_W, top + CELL_H)
                )
                cell = self._pose_cell(cell)
                cell = self._scaled_completion_jump(cell)
            return cell.resize(
                (display_w, display_h),
                Image.Resampling.NEAREST,
            )
        if self.pose in GESTURE_POSES and self.pose in self.poses:
            frames = self.poses[self.pose]
            cell = self._pose_cell(frames[self.frame % len(frames)])
            return cell.resize(
                (display_w, display_h),
                Image.Resampling.NEAREST,
            )
        if self.status == "idle" and self.pose == "idle":
            # The pose folders contain edited close-up frames. The top-left
            # sheet cell is the original upright standing frame used by Codex.
            cell = self.sheet.crop((0, 0, CELL_W, CELL_H))
            cell = self._pose_cell(cell)
            return cell.resize(
                (display_w, display_h),
                Image.Resampling.NEAREST,
            )
        animation_row = self._current_animation_row()
        row_index = ROW_INDEX.get(animation_row, 0)
        left = self.frame * CELL_W
        top = row_index * CELL_H
        cell = self.sheet.crop((left, top, left + CELL_W, top + CELL_H))
        cell = self._pose_cell(cell)
        cell = self._scaled_running_jump(cell)
        return cell.resize(
            (display_w, display_h),
            Image.Resampling.NEAREST,
        )

    def _current_landing_scale(self) -> tuple[float, float]:
        if self.reduced_motion or self.landing_started is None:
            return (1.0, 1.0)
        elapsed = time.perf_counter() - self.landing_started
        progress = elapsed * 1000 / LANDING_DURATION_MS
        if progress >= 1.0:
            return (1.0, 1.0)
        return landing_scale(progress, self.landing_strength)

    def _current_pose_scale(self) -> tuple[float, float]:
        scale_x, scale_y = self._current_landing_scale()
        if self.grab_active and not self.reduced_motion:
            scale_x *= GRAB_SCALE_X
            scale_y *= GRAB_SCALE_Y
        return (scale_x, scale_y)

    @staticmethod
    def _squash_pose_cell(cell, scale_x: float, scale_y: float):
        if abs(scale_x - 1.0) < 0.001 and abs(scale_y - 1.0) < 0.001:
            return cell
        bbox = cell.getchannel("A").getbbox()
        if not bbox:
            return cell
        content = cell.crop(bbox)
        new_w = max(1, round(content.width * scale_x))
        new_h = max(1, round(content.height * scale_y))
        resized = content.resize(
            (new_w, new_h),
            Image.Resampling.NEAREST,
        )
        center_x = (bbox[0] + bbox[2]) / 2
        left = round(center_x - new_w / 2)
        top = bbox[3] - new_h
        canvas = Image.new("RGBA", cell.size, (0, 0, 0, 0))
        canvas.alpha_composite(resized, (max(0, left), max(0, top)))
        return canvas

    def _render_frame(self):
        width, height = self._window_size()
        display_w = self._display_width()
        display_h = self._display_height()
        cell = self._current_pose_cell(display_w, display_h)
        scale_x, scale_y = self._current_pose_scale()
        cell = self._squash_pose_cell(cell, scale_x, scale_y)
        composed = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        composed.alpha_composite(
            cell,
            ((width - display_w) // 2, self._sprite_top()),
        )
        self.photo = keyed_photo(composed)
        self.canvas.configure(width=width, height=height)
        self.canvas.coords(
            self.image_item,
            width // 2,
            self._sprite_top() + display_h // 2,
        )
        self.canvas.itemconfigure(self.image_item, image=self.photo)

    def run(self):
        self.root.mainloop()


def watch_parent(pid: int, root: tk.Tk):
    """Close the overlay when the dsh application shell exits."""
    if sys.platform != "win32" or pid <= 0:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return

    def poll():
        if kernel32.WaitForSingleObject(handle, 0) == 0:
            kernel32.CloseHandle(handle)
            try:
                root.destroy()
            except tk.TclError:
                pass
            return
        root.after(1000, poll)

    root.after(1000, poll)


def main() -> int:
    enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    parser.add_argument("--sprite", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--position", default="")
    parser.add_argument("--settings", default="")
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--anchor-pid", type=int, default=0)
    args = parser.parse_args()

    position_path = Path(args.position) if args.position else None
    settings_path = Path(args.settings) if args.settings else None
    pet = PetWindow(
        Path(args.sprite),
        Path(args.state),
        position_path,
        settings_path,
    )
    pet.anchor_pid = args.anchor_pid or args.parent_pid
    watcher_pid = args.anchor_pid or args.parent_pid
    if watcher_pid > 0:
        watch_parent(watcher_pid, pet.root)
    pet.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
