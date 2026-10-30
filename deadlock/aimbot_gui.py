from __future__ import annotations

"""Modern Tkinter GUI for configuring and running the aimbot.

This module provides a lightweight, modernised interface using ttk
widgets, a custom dark theme, and an improved layout with a header,
tabbed content, and a status bar. Functionality remains the same while
presenting a cleaner, more professional experience.
"""

import logging
import os
import queue
import threading
import tkinter as tk
from copy import deepcopy
from dataclasses import replace
from tkinter import messagebox, scrolledtext, ttk

from .aimbot import Aimbot, AimbotSettings, FALLBACK_ZONE_HEIGHTS
from .heroes import HeroIds
from .memory import DeadlockMemory
from .overlay_process import OverlayProcess
from .gui_utils import (
    GUILogHandler,
    load_saved_settings,
    save_settings,
    get_build_sha,
)




class AimbotApp:
    """Main application controller for the DeadUnlock GUI."""

    def __init__(self, root: tk.Tk, *, combined: bool = False) -> None:
        self.root = root
        self.combined = combined
        self.overlay: OverlayProcess | None = None
        self.root.title("DeadUnlock")
        self.root.geometry("860x580")
        self.root.minsize(720, 520)

        # Set window icon (best-effort)
        try:
            icon_path = os.path.join(
                os.path.dirname(__file__), "..", "img", "deadunlock_icon.png"
            )
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception:
            pass

        self.settings = load_saved_settings()
        self._live_save_job: str | None = None
        self.bot: Aimbot | None = None
        self.bot_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.is_running = False
        self.is_paused = False

        # Set up logging
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_handler = GUILogHandler(self.log_queue)
        self.log_handler.setFormatter(
            logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        )

        # Attach loggers
        aimbot_logger = logging.getLogger('deadlock.aimbot')
        aimbot_logger.addHandler(self.log_handler)
        aimbot_logger.setLevel(logging.INFO)

        offset_finder_logger = logging.getLogger('offset_finder')
        offset_finder_logger.addHandler(self.log_handler)
        offset_finder_logger.setLevel(logging.INFO)

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._process_log_queue()

    def _build_widgets(self) -> None:
        """Create and arrange the GUI widgets."""
        self._configure_style()

        # Root grid: header, notebook, statusbar
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self._build_statusbar()
        self._setup_live_save()

    def _configure_style(self) -> None:
        """Create a clean dark ttk theme with accent buttons and sliders."""
        style = ttk.Style(self.root)
        base_theme = "clam" if "clam" in style.theme_names() else style.theme_use()
        if "deadunlock" not in style.theme_names():
            # Palette
            bg = "#0f1115"
            surface = "#151923"
            border = "#2a2f3a"
            fg = "#e5e7eb"
            muted = "#9ca3af"
            accent = "#2563eb"
            accent_active = "#1d4ed8"
            danger = "#ef4444"
            danger_active = "#dc2626"

            style.theme_create(
                "deadunlock",
                parent=base_theme,
                settings={
                    ".": {
                        "configure": {
                            "background": bg,
                            "foreground": fg,
                        }
                    },
                    "TFrame": {
                        "configure": {"background": bg}
                    },
                    "TLabelframe": {
                        "configure": {
                            "background": surface,
                            "bordercolor": border,
                            "relief": "groove",
                            "padding": 10,
                        }
                    },
                    "TLabelframe.Label": {
                        "configure": {"foreground": muted, "font": ("Segoe UI", 10, "bold")}
                    },
                    "TLabel": {
                        "configure": {"background": bg, "foreground": fg}
                    },
                    "TButton": {
                        "configure": {
                            "padding": 8,
                            "background": surface,
                            "foreground": fg,
                            "bordercolor": border,
                            "relief": "flat",
                        },
                        "map": {
                            "background": [
                                ("active", "#1f2430"),
                                ("disabled", surface),
                            ],
                            "foreground": [("disabled", muted)],
                        },
                    },
                    "Accent.TButton": {
                        "configure": {
                            "background": accent,
                            "foreground": "#ffffff",
                        },
                        "map": {
                            "background": [("active", accent_active)],
                            "foreground": [("disabled", "#c7d2fe")],
                        },
                    },
                    "Danger.TButton": {
                        "configure": {
                            "background": danger,
                            "foreground": "#ffffff",
                        },
                        "map": {
                            "background": [("active", danger_active)],
                            "foreground": [("disabled", "#fecaca")],
                        },
                    },
                    "TCheckbutton": {
                        "configure": {"background": bg, "foreground": fg, "padding": (2, 2)},
                        "map": {"foreground": [("disabled", muted)]},
                    },
                    "TEntry": {
                        "configure": {"fieldbackground": surface, "foreground": fg},
                        "map": {"foreground": [("disabled", muted)]},
                    },
                    "TSpinbox": {
                        "configure": {"fieldbackground": surface, "foreground": fg},
                        "map": {"foreground": [("disabled", muted)]},
                    },
                    "TCombobox": {
                        "configure": {
                            "selectbackground": surface,
                            "fieldbackground": surface,
                            "foreground": fg,
                        }
                    },
                    "Horizontal.TScale": {
                        "configure": {"background": bg},
                    },
                    "TNotebook": {
                        "configure": {"background": bg}
                    },
                    "TNotebook.Tab": {
                        "configure": {"padding": (12, 6)}
                    },
                },
            )
        style.theme_use("deadunlock" if "deadunlock" in style.theme_names() else base_theme)

        default_font = ("Segoe UI", 10)
        self.root.option_add("*Font", default_font)
        try:
            self.root.configure(bg="#0f1115")
        except Exception:
            pass

    def _build_header(self) -> None:
        """Create the top header with title and primary controls."""
        header = ttk.Frame(self.root, padding=(12, 12, 12, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)

        # Title + icon
        title_frame = ttk.Frame(header)
        title_frame.grid(row=0, column=0, sticky="w")
        try:
            icon_path = os.path.join(
                os.path.dirname(__file__), "..", "img", "deadunlock_icon.png"
            )
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(file=icon_path)
                icon_label = ttk.Label(title_frame, image=icon)
                icon_label.image = icon  # keep reference
                icon_label.grid(row=0, column=0, padx=(0, 8))
        except Exception:
            pass
        ttk.Label(
            title_frame, text="DeadUnlock", font=("Segoe UI", 14, "bold")
        ).grid(row=0, column=1, sticky="w")

        # Spacer
        ttk.Frame(header).grid(row=0, column=1, padx=10)

        # Controls: single Start/Stop toggle for clarity
        controls = ttk.Frame(header)
        controls.grid(row=0, column=2, sticky="e")
        self.toggle_button = ttk.Button(
            controls,
            text="Start",
            style="Accent.TButton",
            command=self.toggle_run,
            width=14,
        )
        self.toggle_button.grid(row=0, column=0, padx=(0, 0))
        self.live_save_var = tk.BooleanVar(value=self.settings.live_save)
        ttk.Checkbutton(controls, text="Live Save", variable=self.live_save_var).grid(
            row=0, column=1, padx=(10, 0)
        )
        if self.combined:
            self.esp_enabled = tk.BooleanVar(value=self.settings.esp_enabled)
            self.esp_check = ttk.Checkbutton(
                controls, text="ESP overlay", variable=self.esp_enabled
            )
            self.esp_check.grid(row=0, column=2, padx=(10, 0))

    def _build_tabs(self) -> None:
        """Create the main notebook and its tabs."""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        settings_tab = ttk.Frame(self.notebook, padding=10)
        zones_tab = ttk.Frame(self.notebook, padding=10)
        heights_tab = ttk.Frame(self.notebook, padding=10)
        log_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(settings_tab, text="Settings")
        self.notebook.add(zones_tab, text="Aim Zones")
        self.notebook.add(heights_tab, text="Hero Heights")
        self.notebook.add(log_tab, text="Logs")

        self._build_settings_frame(settings_tab)
        self._build_zones_frame(zones_tab)
        self._build_hero_heights_frame(heights_tab)
        self._build_log_frame(log_tab)

    def _build_statusbar(self) -> None:
        """Create a slim status bar at the bottom."""
        bar = ttk.Frame(self.root, padding=(12, 6))
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(bar, text="Status: Stopped", foreground="red")
        self.status_label.grid(row=0, column=0, sticky="w")
        if self.combined:
            self.esp_status_label = ttk.Label(bar, text="ESP: stopped", foreground="#9ca3af")
            self.esp_status_label.grid(row=0, column=1, sticky="e", padx=(0, 16))

        sha = get_build_sha()
        ttk.Label(
            bar, text=f"build {sha}", font=("Segoe UI", 9)
        ).grid(row=0, column=2, sticky="e")

    def _build_settings_frame(self, parent: ttk.Frame) -> None:
        """Build the settings tab content."""
        # Aim settings
        frame = ttk.LabelFrame(parent, text="Aim Settings")
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(frame, text="Target selection").grid(row=row, column=0, sticky="w")
        self.target_var = tk.StringVar(value=self.settings.target_select_type)
        ttk.Combobox(
            frame,
            textvariable=self.target_var,
            values=["fov", "distance"],
            width=10,
            state="readonly",
        ).grid(row=row, column=1, sticky="w", padx=8)
        ttk.Label(frame, text="Aim button").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.aim_button_var = tk.StringVar(value=f"Mouse {self.settings.aim_button - 4}")
        ttk.Combobox(
            frame, textvariable=self.aim_button_var, values=("Mouse 4", "Mouse 5"),
            width=10, state="readonly",
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))
        self.live_save_status = ttk.Label(frame, text="Live Save: off", foreground="#9ca3af")
        self.live_save_status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Hero settings
        row += 1
        hero_frame = ttk.LabelFrame(parent, text="Hero Ability Locks")
        hero_frame.grid(row=row, column=0, sticky="ew", pady=(10, 0))

        hero_row = 0
        ttk.Label(hero_frame, text="Hero").grid(row=hero_row, column=0, sticky="w")
        ttk.Label(hero_frame, text="Key 1").grid(row=hero_row, column=1, sticky="w")
        ttk.Label(hero_frame, text="Key 2").grid(row=hero_row, column=2, sticky="w")
        hero_row += 1

        self.grey_enabled = tk.BooleanVar(value=self.settings.grey_talon_lock_enabled)
        ttk.Checkbutton(
            hero_frame, text="Grey Talon", variable=self.grey_enabled
        ).grid(row=hero_row, column=0, sticky="w")
        self.grey_key = tk.StringVar(value=chr(self.settings.grey_talon_key))
        ttk.Entry(hero_frame, textvariable=self.grey_key, width=4).grid(
            row=hero_row, column=1, sticky="w"
        )
        hero_row += 1

        self.yamato_enabled = tk.BooleanVar(value=self.settings.yamato_lock_enabled)
        ttk.Checkbutton(hero_frame, text="Yamato", variable=self.yamato_enabled).grid(
            row=hero_row, column=0, sticky="w"
        )
        self.yamato_key = tk.StringVar(value=chr(self.settings.yamato_key))
        ttk.Entry(hero_frame, textvariable=self.yamato_key, width=4).grid(
            row=hero_row, column=1, sticky="w"
        )
        hero_row += 1

        self.vindicta_enabled = tk.BooleanVar(
            value=self.settings.vindicta_lock_enabled
        )
        ttk.Checkbutton(
            hero_frame, text="Vindicta", variable=self.vindicta_enabled
        ).grid(row=hero_row, column=0, sticky="w")
        self.vindicta_key = tk.StringVar(value=chr(self.settings.vindicta_key))
        ttk.Entry(hero_frame, textvariable=self.vindicta_key, width=4).grid(
            row=hero_row, column=1, sticky="w"
        )
        hero_row += 1

        self.paradox_enabled = tk.BooleanVar(value=self.settings.paradox_shortcut_enabled)
        ttk.Checkbutton(hero_frame, text="Paradox", variable=self.paradox_enabled).grid(
            row=hero_row, column=0, sticky="w"
        )
        self.paradox_r_key = tk.StringVar(value=chr(self.settings.paradox_r_key))
        ttk.Entry(hero_frame, textvariable=self.paradox_r_key, width=4).grid(
            row=hero_row, column=1, sticky="w"
        )
        self.paradox_e_key = tk.StringVar(value=chr(self.settings.paradox_e_key))
        ttk.Entry(hero_frame, textvariable=self.paradox_e_key, width=4).grid(
            row=hero_row, column=2, sticky="w"
        )

    def _build_zones_frame(self, parent: ttk.Frame) -> None:
        """Build the weighted aim-zone controls."""
        parent.columnconfigure(0, weight=1)
        frame = ttk.LabelFrame(parent, text="Aim zones")
        frame.grid(row=0, column=0, sticky="ew")
        self.random_zones_var = tk.BooleanVar(value=self.settings.random_zones)
        ttk.Checkbutton(
            frame, text="Random weights (all zones)", variable=self.random_zones_var,
            command=self._update_zone_controls,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame, text="Random generates new weights at each Start. Manual weights are relative."
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Label(frame, text="Zone").grid(row=2, column=0, sticky="w")
        ttk.Label(frame, text="Weight (0–100)").grid(row=2, column=1, sticky="w")
        self.zone_enabled_vars = {}
        self.zone_weight_vars = {}
        self.zone_checks = {}
        self.zone_entries = {}
        for row, zone in enumerate(("head", "body", "legs"), start=3):
            enabled = tk.BooleanVar(value=getattr(self.settings, f"{zone}_enabled"))
            weight = tk.StringVar(value=str(getattr(self.settings, f"{zone}_weight")))
            self.zone_enabled_vars[zone] = enabled
            self.zone_weight_vars[zone] = weight
            check = ttk.Checkbutton(
                frame, text=zone.title(), variable=enabled, command=self._update_zone_controls
            )
            check.grid(row=row, column=0, sticky="w")
            entry = ttk.Spinbox(frame, from_=0, to=100, textvariable=weight, width=8)
            entry.grid(row=row, column=1, sticky="w", padx=(8, 0))
            self.zone_checks[zone] = check
            self.zone_entries[zone] = entry
        ttk.Label(frame, text="Head height adjustment (game units)").grid(
            row=6, column=0, sticky="w", pady=(12, 0)
        )
        self.head_vertical_var = tk.StringVar(value=str(self.settings.head_vertical_offset))
        ttk.Spinbox(frame, from_=-100, to=100, textvariable=self.head_vertical_var, width=8).grid(
            row=6, column=1, sticky="w", padx=(8, 0), pady=(12, 0)
        )
        ttk.Label(
            frame,
            text="Negative moves head aim down. Stop and Start to apply changes. "
                 "Head/leg estimates are unverified; check Logs.",
            wraplength=680,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._update_zone_controls()

    def _build_hero_heights_frame(self, parent: ttk.Frame) -> None:
        """Build per-target fallback-height controls without assuming hero measurements."""
        frame = ttk.LabelFrame(parent, text="Fallback heights by target hero")
        frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            frame,
            text="Used only when a bone is unavailable or implausible. Heights are game units "
                 "above the scene origin, not verified hitboxes.",
            wraplength=650,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        heroes = sorted(hero.name for hero in HeroIds)
        self.hero_height_vars = {
            hero: {
                zone: tk.StringVar(value=str(
                    self.settings.hero_zone_heights.get(hero, {}).get(zone, default)
                ))
                for zone, default in FALLBACK_ZONE_HEIGHTS.items()
            }
            for hero in heroes
        }
        ttk.Label(frame, text="Target hero").grid(row=1, column=0, sticky="w")
        self.height_hero_var = tk.StringVar(value="Abrams")
        ttk.Combobox(
            frame, textvariable=self.height_hero_var, values=heroes, state="readonly", width=16
        ).grid(row=1, column=1, sticky="w", padx=8)
        self.height_entries = {}
        for column, zone in enumerate(FALLBACK_ZONE_HEIGHTS):
            ttk.Label(frame, text=zone.title()).grid(row=2, column=column, sticky="w", pady=(10, 0))
            entry = ttk.Spinbox(frame, from_=0, to=200, width=8)
            entry.grid(row=3, column=column, sticky="w", padx=(0, 12))
            self.height_entries[zone] = entry
        ttk.Label(
            frame,
            text="Defaults (100 / 70 / 30) are uncalibrated for most heroes. "
                 "Global head adjustment also applies. Stop and Start to apply edits.",
            wraplength=650,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(12, 0))
        self.height_hero_var.trace_add("write", self._show_hero_heights)
        self._show_hero_heights()

    def _show_hero_heights(self, *_args: object) -> None:
        """Switch the editor to the selected hero without discarding unsaved edits."""
        hero = self.height_hero_var.get()
        if hero in self.hero_height_vars:
            for zone, entry in self.height_entries.items():
                entry.configure(textvariable=self.hero_height_vars[hero][zone])

    def _update_zone_controls(self) -> None:
        """Dim manual controls in random mode and disable unselected weights."""
        random_mode = self.random_zones_var.get()
        for zone in self.zone_enabled_vars:
            self.zone_checks[zone].state(["disabled"] if random_mode else ["!disabled"])
            disabled = random_mode or not self.zone_enabled_vars[zone].get()
            self.zone_entries[zone].state(["disabled"] if disabled else ["!disabled"])

    def _build_status_frame(self, parent: ttk.Frame) -> None:
        """Deprecated: status is now in the status bar."""
        # Kept for backward compatibility if referenced elsewhere.
        pass

    def _build_log_frame(self, parent: ttk.Frame) -> None:
        """Build the log tab with a dark console-like view."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(
            parent, width=50, height=20, state="disabled"
        )
        self.log_text.configure(
            background="#111318",
            foreground="#dcdcdc",
            insertbackground="#ffffff",
            borderwidth=0,
            relief="flat",
            padx=8,
            pady=8,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        ttk.Button(parent, text="Clear Log", command=self.clear_log).grid(
            row=1, column=0, sticky="e", pady=(8, 0)
        )

    def _add_build_label(self, parent: ttk.Frame) -> None:
        """Deprecated: build label is shown in status bar."""
        # Preserved to avoid accidental removal; no-op now.
        pass
    def _process_log_queue(self) -> None:
        """Process log messages from queue and display them."""
        try:
            while True:
                log_message = self.log_queue.get_nowait()
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, log_message + '\n')
                self.log_text.see(tk.END)
                self.log_text.config(state='disabled')
        except queue.Empty:
            pass
        finally:
            # Schedule next check
            self.root.after(100, self._process_log_queue)
    
    def clear_log(self) -> None:
        """Clear the log display."""
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')
    
    def _update_status(self, status: str, color: str = "black") -> None:
        """Update the status label in the status bar."""
        self.status_label.config(text=f"Status: {status}", foreground=color)
    
    def _update_button_states(self) -> None:
        """Update controls to reflect running state."""
        if self.combined:
            self.esp_check.state(["disabled"] if self.is_running else ["!disabled"])
        if not self.is_running:
            self.toggle_button.config(
                text="Start",
                style="Accent.TButton",
                state="normal",
            )
        else:
            self.toggle_button.config(
                text="Stop",
                style="Danger.TButton",
                state="normal",
            )

    def toggle_run(self) -> None:
        """Toggle between starting and stopping the aimbot."""
        if self.is_running:
            self.stop()
        else:
            self.start()

    def _apply_widget_values(self) -> None:
        """Validate and update settings from widget values."""
        settings = replace(self.settings)
        aim_buttons = {"Mouse 4": 8, "Mouse 5": 9}
        if self.aim_button_var.get() not in aim_buttons:
            raise ValueError("Select Mouse 4 or Mouse 5 as the aim button")
        settings.aim_button = aim_buttons[self.aim_button_var.get()]
        heights = {}
        for hero, zone_vars in self.hero_height_vars.items():
            configured = {}
            for zone, variable in zone_vars.items():
                try:
                    height = int(variable.get())
                    if not 0 <= height <= 200:
                        raise ValueError
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"{hero} {zone} fallback height must be an integer from 0 to 200"
                    ) from exc
                if height != FALLBACK_ZONE_HEIGHTS[zone]:
                    configured[zone] = height
            if configured:
                heights[hero] = configured
        settings.hero_zone_heights = heights
        random_zones = self.random_zones_var.get()
        try:
            head_offset = int(self.head_vertical_var.get())
            if not -100 <= head_offset <= 100:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Head height adjustment must be an integer from -100 to 100") from exc
        weights = {}
        for zone, variable in self.zone_weight_vars.items():
            try:
                value = int(variable.get())
                if not 0 <= value <= 100:
                    raise ValueError
            except ValueError as exc:
                if not random_zones:
                    raise ValueError(
                        f"{zone.title()} weight must be an integer from 0 to 100"
                    ) from exc
                # Invalid inactive edits do not affect random mode or overwrite saved values.
                value = getattr(settings, f"{zone}_weight")
            weights[zone] = value
        if not random_zones and not any(
            self.zone_enabled_vars[zone].get() and weights[zone] for zone in weights
        ):
            raise ValueError("Select at least one zone with a positive weight")
        for zone, weight in weights.items():
            setattr(settings, f"{zone}_weight", weight)
            setattr(settings, f"{zone}_enabled", self.zone_enabled_vars[zone].get())
        settings.random_zones = random_zones
        settings.head_vertical_offset = head_offset
        settings.target_select_type = self.target_var.get()

        settings.live_save = self.live_save_var.get()
        if self.combined:
            settings.esp_enabled = self.esp_enabled.get()

        for enabled_name, enabled_var, key_name, key_var in (
            ("grey_talon_lock_enabled", self.grey_enabled, "grey_talon_key", self.grey_key),
            ("yamato_lock_enabled", self.yamato_enabled, "yamato_key", self.yamato_key),
            ("vindicta_lock_enabled", self.vindicta_enabled, "vindicta_key", self.vindicta_key),
            ("paradox_shortcut_enabled", self.paradox_enabled, "paradox_r_key", self.paradox_r_key),
            ("paradox_shortcut_enabled", self.paradox_enabled, "paradox_e_key", self.paradox_e_key),
        ):
            key = key_var.get().upper()
            if len(key) != 1 or not key.isascii() or not key.isalnum():
                raise ValueError("Ability keys must each be a single ASCII letter or digit")
            setattr(settings, enabled_name, enabled_var.get())
            setattr(settings, key_name, ord(key))
        self.settings = settings

    def _setup_live_save(self) -> None:
        """Watch all persisted panel fields after the widgets are initialized."""
        variables = [
            self.target_var, self.aim_button_var, self.random_zones_var, self.head_vertical_var,
            self.grey_enabled, self.grey_key, self.yamato_enabled, self.yamato_key,
            self.vindicta_enabled, self.vindicta_key, self.paradox_enabled,
            self.paradox_r_key, self.paradox_e_key,
            *self.zone_enabled_vars.values(), *self.zone_weight_vars.values(),
        ]
        variables.extend(
            variable for zones in self.hero_height_vars.values() for variable in zones.values()
        )
        if self.combined:
            variables.append(self.esp_enabled)
        for variable in variables:
            variable.trace_add("write", self._schedule_live_save)
        self.live_save_var.trace_add("write", self._toggle_live_save)
        self._set_save_status("Live Save: on" if self.live_save_var.get() else "Live Save: off")

    def _set_save_status(self, text: str, *, error: bool = False) -> None:
        """Display whether settings have been saved or require attention."""
        self.live_save_status.config(text=text, foreground="#ef4444" if error else "#9ca3af")

    def _write_settings(self, settings: AimbotSettings) -> bool:
        """Save settings and report any failure without blocking the control panel."""
        try:
            save_settings(settings)
        except (OSError, TypeError, ValueError) as exc:
            self.log_queue.put(f"Settings save failed: {exc}")
            self._set_save_status("Settings not saved; see Logs", error=True)
            return False
        return True

    def _cancel_live_save(self) -> None:
        """Cancel a pending debounced save."""
        if self._live_save_job is not None:
            self.root.after_cancel(self._live_save_job)
            self._live_save_job = None

    def _schedule_live_save(self, *_args: object) -> None:
        """Debounce edits so typing does not rewrite the JSON on every keystroke."""
        if not self.live_save_var.get():
            return
        self._cancel_live_save()
        self._set_save_status("Live Save: pending")
        self._live_save_job = self.root.after(350, self._save_live_values)

    def _save_live_values(self) -> None:
        """Save the latest valid panel snapshot, or keep the previous valid JSON."""
        self._live_save_job = None
        if not self.live_save_var.get():
            return
        try:
            self._apply_widget_values()
        except ValueError as exc:
            self._set_save_status(f"Live Save: invalid settings — {exc}", error=True)
            return
        if self._write_settings(self.settings):
            self._set_save_status("Live Save: saved")

    def _toggle_live_save(self, *_args: object) -> None:
        """Persist the preference and flush any valid edits when it is toggled."""
        self._cancel_live_save()
        enabled = self.live_save_var.get()
        try:
            self._apply_widget_values()
        except ValueError:
            # Retain the last valid snapshot while still remembering the preference.
            self.settings = replace(self.settings, live_save=enabled)
            if self._write_settings(self.settings):
                self._set_save_status("Live Save: invalid edits not saved", error=True)
            return
        if self._write_settings(self.settings):
            self._set_save_status("Live Save: saved" if enabled else "Live Save: off")

    def _start_overlay(self) -> None:
        """Start and monitor the Qt overlay in its own process."""
        overlay = OverlayProcess(self.log_queue.put)
        self.overlay = overlay
        overlay.start()
        self.esp_status_label.config(text="ESP: starting", foreground="#60a5fa")
        self.log_queue.put("ESP process started; check Logs for startup errors.")
        self.root.after(500, lambda: self._poll_overlay(overlay))

    def _poll_overlay(self, overlay: OverlayProcess) -> None:
        """Report unexpected overlay exit without blocking the Tk event loop."""
        if self.overlay is not overlay:
            return
        exit_code = overlay.poll()
        if exit_code is None:
            self.esp_status_label.config(text="ESP: process active", foreground="#10b981")
            self.root.after(500, lambda: self._poll_overlay(overlay))
            return
        overlay.stop()
        self.overlay = None
        self.esp_status_label.config(text="ESP: exited", foreground="red")
        self.log_queue.put(f"ESP exited (code {exit_code}); see earlier ESP messages in Logs.")

    def _stop_overlay(self) -> None:
        """Stop a managed overlay when the aimbot is stopped or fails."""
        overlay, self.overlay = self.overlay, None
        if overlay is not None:
            overlay.stop()
            self.log_queue.put("ESP stopped.")
        if self.combined:
            self.esp_status_label.config(text="ESP: stopped", foreground="#9ca3af")

    def start(self) -> None:
        """Start the aimbot and, if enabled, its ESP overlay."""
        if self.is_running:
            return
            
        self._cancel_live_save()
        try:
            self._apply_widget_values()
        except ValueError as exc:
            if self.live_save_var.get():
                self._set_save_status(f"Live Save: invalid settings — {exc}", error=True)
            messagebox.showerror("Invalid settings", str(exc))
            return
        if self._write_settings(self.settings):
            self._set_save_status(
                "Live Save: saved" if self.settings.live_save else "Live Save: off"
            )

        try:
            if self.bot_thread and self.bot_thread.is_alive():
                messagebox.showinfo("Please wait", "The previous aimbot is still stopping.")
                return
            if self.combined and self.esp_enabled.get():
                self._start_overlay()
            self.stop_event.clear()
            self.bot = None
            self.is_running = True
            self.is_paused = False
            self._update_status("Starting...", "#60a5fa")
            self._update_button_states()

            # Start initialisation and aimbot in a separate thread
            self.bot_thread = threading.Thread(
                target=self._initialise_and_run, args=(deepcopy(self.settings),), daemon=True
            )
            self.bot_thread.start()

        except Exception as e:
            self._stop_overlay()
            self._update_status("Error", "red")
            self.is_running = False
            self._update_button_states()
            messagebox.showerror("Error", f"Failed to start aimbot or ESP: {str(e)}")

    def _initialise_and_run(self, settings: AimbotSettings) -> None:
        """Initialise and run with a snapshot of the settings at Start."""
        try:
            mem = DeadlockMemory()
            if self.stop_event.is_set():
                mem.pm.close()
                return
            try:
                self.bot = Aimbot(mem, settings)
            except Exception:
                mem.pm.close()
                raise
            if self.stop_event.is_set():
                self.bot.input.close()
                mem.pm.close()
                return
            self.log_queue.put("Aimbot started successfully.")
            self.root.after(0, lambda: (
                self._update_status("Running", "#10b981") if self.is_running else None,
                self._update_button_states()
            ))
            try:
                self._run_aimbot()
            finally:
                mem.pm.close()
        except Exception as exc:
            msg = str(exc)
            self.log_queue.put(f"Aimbot error: {msg}")
            if not self.stop_event.is_set():
                self.root.after(0, lambda: self._handle_bot_error(msg))

    def _handle_bot_error(self, message: str) -> None:
        """Stop the overlay and report a bot error from the Tk thread."""
        if self.stop_event.is_set():
            return
        self._stop_overlay()
        self.is_running = False
        self._update_status("Error", "red")
        self._update_button_states()
        messagebox.showerror("Error", f"Aimbot failed: {message}")

    def _run_aimbot(self) -> None:
        """Run the aimbot loop with pause support."""
        if self.bot:
            self.bot.run()
    
    def toggle_pause(self) -> None:
        """Toggle pause state of the aimbot."""
        if not self.is_running or not self.bot:
            return
            
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.bot.pause()
            self._update_status("Paused", "#f59e0b")
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, "Aimbot paused.\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        else:
            self.bot.resume()
            self._update_status("Running", "#10b981")
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, "Aimbot resumed.\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        
        self._update_button_states()
    
    def stop(self) -> None:
        """Stop the aimbot."""
        if not self.is_running:
            return
            
        self.stop_event.set()
        if self.bot:
            self.bot.stop()
        self._stop_overlay()
            
        self.is_running = False
        self.is_paused = False
        
        self._update_status("Stopped", "red")
        self._update_button_states()
        
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, "Aimbot stopped.\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def on_close(self) -> None:
        """Handle window close event."""
        self._cancel_live_save()
        try:
            self._apply_widget_values()
        except ValueError as exc:
            messagebox.showwarning("Settings not saved", f"Invalid edits were not saved: {exc}")
        else:
            if not self._write_settings(self.settings):
                messagebox.showwarning("Settings not saved", "See Logs for the save error.")
        
        if self.is_running:
            self.stop()
        else:
            self._stop_overlay()
        
        # Clean up logging handler
        if hasattr(self, 'log_handler'):
            aimbot_logger = logging.getLogger('deadlock.aimbot')
            aimbot_logger.removeHandler(self.log_handler)
            
            # Also clean up offset finder logger
            offset_finder_logger = logging.getLogger('offset_finder')
            offset_finder_logger.removeHandler(self.log_handler)
            
        self.root.destroy()


def main(*, combined: bool = False) -> None:
    """Run the GUI, optionally enabling managed ESP control."""
    app = None
    try:
        root = tk.Tk()
        root.resizable(True, True)
        app = AimbotApp(root, combined=combined)
        root.mainloop()
    finally:
        if app is not None:
            app.stop_event.set()
            if app.bot is not None:
                app.bot.stop()
            if app.overlay is not None:
                app.overlay.stop()
            if app.bot_thread is not None and app.bot_thread.is_alive():
                app.bot_thread.join(timeout=2)


if __name__ == "__main__":
    main()
