"""Small Tkinter UI helpers for AI Server Manager.

The rounded button uses a Canvas so it keeps the dark theme and has a very
small Windows-11-like corner radius without making the buttons look pill-shaped.
"""

import sys
import tkinter as tk
import webbrowser

try:
    import ctypes
except Exception:  # pragma: no cover
    ctypes = None


def open_url(url):
    if not url:
        return
    url = str(url).strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    webbrowser.open(url)


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent,
        text,
        command=None,
        bg="#234f9c",
        fg="white",
        hover_bg=None,
        disabled_bg="#303030",
        width=140,
        height=36,
        radius=4,
        font=("Segoe UI", 10, "bold"),
        **kwargs,
    ):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg") if hasattr(parent, "cget") else "#101010",
            highlightthickness=0,
            bd=0,
            relief=tk.FLAT,
            cursor="hand2",
            **kwargs,
        )
        self.command = command
        self.text = text
        self.fg = fg
        self.normal_bg = bg
        self.hover_bg = hover_bg or _lighten(bg, 0.10)
        self.disabled_bg = disabled_bg
        self.radius = radius
        self.font = font
        self.enabled = True
        self._draw(self.normal_bg)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _draw_round_rect(self, x1, y1, x2, y2, r, fill):
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)
        self.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, fill=fill, outline=fill)
        self.create_oval(x2 - 2 * r, y1, x2, y1 + 2 * r, fill=fill, outline=fill)
        self.create_oval(x1, y2 - 2 * r, x1 + 2 * r, y2, fill=fill, outline=fill)
        self.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2, fill=fill, outline=fill)

    def _draw(self, color):
        self.delete("all")
        w = int(self.cget("width"))
        h = int(self.cget("height"))
        self._draw_round_rect(1, 1, w - 1, h - 1, self.radius, color)
        self.create_text(w // 2, h // 2, text=self.text, fill=self.fg if self.enabled else "#9ca3af", font=self.font)

    def _on_enter(self, _event=None):
        if self.enabled:
            self._draw(self.hover_bg)

    def _on_leave(self, _event=None):
        self._draw(self.normal_bg if self.enabled else self.disabled_bg)

    def _on_click(self, _event=None):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled=True, text=None, bg=None):
        self.enabled = bool(enabled)
        if text is not None:
            self.text = text
        if bg is not None:
            self.normal_bg = bg
            self.hover_bg = _lighten(bg, 0.10)
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self._draw(self.normal_bg if self.enabled else self.disabled_bg)

    def config(self, cnf=None, **kwargs):  # compatibility with tk.Button config calls used by panels
        if cnf:
            kwargs.update(cnf)
        if "text" in kwargs:
            self.text = kwargs.pop("text")
        if "bg" in kwargs:
            self.normal_bg = kwargs.pop("bg")
            self.hover_bg = _lighten(self.normal_bg, 0.10)
        if "state" in kwargs:
            self.enabled = kwargs.pop("state") != tk.DISABLED
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        super().config(**kwargs)
        self._draw(self.normal_bg if self.enabled else self.disabled_bg)

    configure = config


def rounded_button(parent, text, command=None, bg="#234f9c", width=150, height=38, **kwargs):
    return RoundedButton(parent, text=text, command=command, bg=bg, width=width, height=height, **kwargs)


def make_link(label_or_widget, url):
    label_or_widget.configure(cursor="hand2")
    try:
        label_or_widget.configure(fg="#ffd36a")
    except Exception:
        pass
    label_or_widget.bind("<Button-1>", lambda _e, u=url: open_url(u))


def enable_dark_toplevel_titlebar(win):
    if sys.platform != "win32" or ctypes is None:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass



def _hex_to_rgb(hex_color):
    h = str(hex_color or "#000000").lstrip("#")
    if len(h) != 6:
        h = "000000"
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return 0, 0, 0


def blend_colors(color_a, color_b, amount=0.50):
    """Blend two #rrggbb colors. amount=0 returns A, amount=1 returns B."""
    try:
        amount = max(0.0, min(1.0, float(amount)))
        ar, ag, ab = _hex_to_rgb(color_a)
        br, bg, bb = _hex_to_rgb(color_b)
        r = int(ar + (br - ar) * amount)
        g = int(ag + (bg - ag) * amount)
        b = int(ab + (bb - ab) * amount)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return color_a


def soft_row_bg(colors, index=0):
    """Return gentle alternating row colors for Services/Service manager.

    V65 keeps the alternating rows, but removes the purple tint. The second
    row now stays on the grey/blue side and is deliberately lighter/softer.
    """
    base = colors.get("panel_bg", "#181b22")
    text = colors.get("text_bg", base)
    fg = colors.get("fg", "#ffffff")
    if str(fg).lower() in ("#111827", "#000000") or colors.get("root_bg", "").startswith("#f"):
        return blend_colors(base, "#dbeafe" if index % 2 == 0 else "#e5e7eb", 0.24)
    tint = "#8fb7e8" if index % 2 == 0 else "#91a4bd"
    return blend_colors(text if index % 2 == 0 else base, tint, 0.11)


def show_modal_backdrop(manager, bg=None):
    """Backdrop disabled.

    V67 removes the modal blur/overlay entirely to keep window handling simple.
    The function remains as a no-op so older callers stay safe.
    """
    try:
        manager._modal_backdrop_force = False
        old = getattr(manager, "_modal_backdrop", None)
        if old is not None and old.winfo_exists():
            old.destroy()
        manager._modal_backdrop = None
    except Exception:
        pass
    return None


def hide_modal_backdrop(manager):
    try:
        manager._modal_backdrop_force = False
        frame = getattr(manager, "_modal_backdrop", None)
        if frame is not None and frame.winfo_exists():
            frame.destroy()
        manager._modal_backdrop = None
    except Exception:
        pass


def _lighten(hex_color, amount=0.10):
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color
