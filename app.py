#!/usr/bin/env python3
"""
Study Planner — unified GUI.
pip install customtkinter
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import math
from datetime import date, timedelta
from typing import Optional, List, Dict

import database as db
import scheduler
from models import Task, Subtask, Quadrant, QUADRANT_LABELS, SplitMode

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#F7F5F0"
CARD     = "#FFFFFF"
SIDE     = "#161616"
SIDE_SEL = "#2C2C2C"
T1       = "#1A1A1A"
T2       = "#888880"
BORDER   = "#E8E3DB"
OK_CLR   = "#2C7A45"
ERR_CLR  = "#B84040"
TIMER_BG = "#F2EFE9"
ARC_BG   = "#DDD9D2"
ARC_FG   = "#1A1A1A"
ARC_BRK  = "#5A9470"

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

DAYS_S = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
          "Jul","Aug","Sep","Oct","Nov","Dec"]


# ── Utility ───────────────────────────────────────────────────────────────────
def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())

def fmt_sec(s: int) -> str:
    return f"{s // 60:02d}:{s % 60:02d}"

def next_21_days(from_date: Optional[date] = None) -> List[date]:
    base = from_date or date.today()
    return [base + timedelta(days=i) for i in range(21)]

def date_label(d: date) -> str:
    return f"{DAYS_S[d.weekday()]}  {d.strftime('%b %d')}"


# ── Reusable widgets ──────────────────────────────────────────────────────────

def card_frame(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                        border_width=1, border_color=BORDER, **kw)

def section_label(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text,
                        font=ctk.CTkFont(size=11, weight="bold"),
                        text_color=T2)

def heading(parent, text: str, size: int = 18) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text,
                        font=ctk.CTkFont(size=size, weight="bold"),
                        text_color=T1)

def body_label(parent, text: str, color=T1, size=13) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text,
                        font=ctk.CTkFont(size=size), text_color=color)

class SideBtn(ctk.CTkButton):
    def __init__(self, master, text, cmd):
        super().__init__(master, text=text, command=cmd,
                         fg_color="transparent", text_color="#BBBBBB",
                         hover_color=SIDE_SEL, anchor="w",
                         font=ctk.CTkFont(size=13), height=42,
                         corner_radius=8)

class Divider(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        super().__init__(parent, height=1, fg_color=BORDER, **kw)


# ── Arc Timer Canvas ──────────────────────────────────────────────────────────

class TimerCanvas(tk.Canvas):
    """Off-white canvas with a progress arc and centred time text."""

    SIZE   = 260
    CX, CY = 130, 130
    R      = 100
    THICK  = 10

    def __init__(self, parent):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=TIMER_BG, highlightthickness=0)
        self._draw_idle()

    def _xy(self, r=None):
        r = r or self.R
        x0 = self.CX - r
        y0 = self.CY - r
        x1 = self.CX + r
        y1 = self.CY + r
        return x0, y0, x1, y1

    def _draw_idle(self):
        self.delete("all")
        x0, y0, x1, y1 = self._xy()
        self.create_arc(x0, y0, x1, y1, start=90, extent=359.99,
                        outline=ARC_BG, width=self.THICK, style="arc")
        self.create_text(self.CX, self.CY - 8,
                         text="--:--",
                         font=("Courier New", 42, "bold"), fill=T2)
        self.create_text(self.CX, self.CY + 30,
                         text="ready",
                         font=("Courier New", 13), fill=T2)

    def update(self, remaining_s: int, progress: float,
               label: str, is_break: bool):
        self.delete("all")
        arc_color = ARC_BRK if is_break else ARC_FG
        x0, y0, x1, y1 = self._xy()

        # Background ring
        self.create_arc(x0, y0, x1, y1, start=90, extent=359.99,
                        outline=ARC_BG, width=self.THICK, style="arc")

        # Progress ring (shrinks as time passes)
        extent = max(0.0, (1.0 - progress) * 359.99)
        if extent > 0:
            self.create_arc(x0, y0, x1, y1, start=90, extent=extent,
                            outline=arc_color, width=self.THICK, style="arc")

        # Time text
        self.create_text(self.CX, self.CY - 10,
                         text=fmt_sec(remaining_s),
                         font=("Courier New", 42, "bold"), fill=T1)
        self.create_text(self.CX, self.CY + 28,
                         text=label,
                         font=("Courier New", 12), fill=T2)

    def reset(self):
        self._draw_idle()


# ── Completion dialog ─────────────────────────────────────────────────────────

class CompletionDialog(ctk.CTkToplevel):
    """Modal: ask which tasks/subtasks were finished in this block."""

    def __init__(self, parent_app, block, task_map: Dict,
                 today: date, on_done):
        super().__init__(parent_app)
        self.title("Block Complete")
        self.geometry("460x500")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app     = parent_app
        self._block   = block
        self._task_map = task_map
        self._today   = today
        self._on_done = on_done
        self._checks: Dict[int, tk.BooleanVar] = {}  # subtask_id / task_id → var
        self._build()

    def _build(self):
        heading(self, "Block finished — what did you complete?",
                size=14).pack(pady=(20, 4), padx=20, anchor="w")
        body_label(self, "Check everything you finished in this block.",
                   color=T2, size=12).pack(padx=20, anchor="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG, height=300)
        scroll.pack(fill="both", expand=True, padx=20, pady=12)

        for sl in self._block.task_slices:
            t = self._task_map.get(sl["task_id"])
            if not t or t.completed:
                continue
            body_label(scroll, f"  {t.name}",
                       size=13).pack(anchor="w", pady=(8, 2))
            if t.subtasks:
                for st in t.subtasks:
                    if st.completed:
                        continue
                    var = tk.BooleanVar()
                    self._checks[("sub", st.id, t.id)] = var
                    ctk.CTkCheckBox(scroll, text=f"    {st.name}  "
                                    f"({st.estimated_minutes:.0f}m)",
                                    variable=var,
                                    font=ctk.CTkFont(size=12),
                                    text_color=T1,
                                    fg_color=T1).pack(anchor="w", padx=8)
            else:
                var = tk.BooleanVar()
                self._checks[("task", t.id, t.id)] = var
                ctk.CTkCheckBox(scroll, text=f"    Fully done",
                                variable=var,
                                font=ctk.CTkFont(size=12),
                                text_color=T1,
                                fg_color=T1).pack(anchor="w", padx=8)

        ctk.CTkButton(self, text="Save & Continue",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=40,
                      command=self._save).pack(pady=16, padx=20, fill="x")

    def _save(self):
        for key, var in self._checks.items():
            if not var.get():
                continue
            kind, item_id, task_id = key
            t = self._task_map.get(task_id)
            if not t:
                continue
            if kind == "sub":
                st = next((s for s in t.subtasks if s.id == item_id), None)
                if st:
                    db.mark_subtask_complete(st.id, st.estimated_minutes)
                    st.completed = True
                    t.remaining_minutes = max(0.0,
                        t.remaining_minutes - st.estimated_minutes)
                    db.update_remaining_minutes(t.id, t.remaining_minutes)
                if all(s.completed for s in t.subtasks):
                    scheduler.recalculate_after_completion(t.id, self._today)
                    t.completed = True
            else:
                scheduler.recalculate_after_completion(t.id, self._today)
                t.completed = True

        self.destroy()
        self._on_done()


# ── Report window ─────────────────────────────────────────────────────────────

class ReportWindow(ctk.CTkToplevel):
    def __init__(self, app, today: date, focus_min: int):
        super().__init__(app)
        self.title("End-of-Day Report")
        self.geometry("440x520")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app     = app
        self._today   = today
        self._focus   = focus_min
        self._carried: List[int] = []
        self._build()

    def _build(self):
        tasks      = db.get_tasks_for_date(self._today)
        done       = [t for t in tasks if t.completed]
        incomplete = [t for t in tasks if not t.completed]

        all_done = not incomplete
        mascot   = "( ^ᴗ^)" if all_done else "( ò_ó)"
        msg      = "All done! Great work!" if all_done else "Some tasks remain..."

        heading(self, mascot, size=36).pack(pady=(24, 4))
        heading(self, msg, size=15).pack(pady=(0, 16))
        Divider(self).pack(fill="x", padx=20, pady=4)

        if done:
            section_label(self, f"COMPLETED  ({len(done)})").pack(
                anchor="w", padx=20, pady=(8, 2))
            for t in done:
                body_label(self, f"  ✓  {t.name}", color=OK_CLR).pack(
                    anchor="w", padx=20)

        if incomplete:
            section_label(self, f"INCOMPLETE  ({len(incomplete)})").pack(
                anchor="w", padx=20, pady=(12, 2))
            for t in incomplete:
                body_label(self, f"  ○  {t.name}  "
                           f"({t.remaining_minutes:.0f}m left)",
                           color=ERR_CLR).pack(anchor="w", padx=20)

            self._carry_var = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(self, text="Carry incomplete tasks to tomorrow",
                            variable=self._carry_var,
                            font=ctk.CTkFont(size=12), text_color=T1,
                            fg_color=T1).pack(pady=(14, 4), padx=20, anchor="w")

        body_label(self, f"Total focus today:  {focus_min}m",
                   color=T2, size=12).pack(pady=(8, 0))

        ctk.CTkButton(self, text="Close & Advance to Tomorrow",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=42,
                      command=lambda: self._close(incomplete)).pack(
                          pady=20, padx=20, fill="x")

    def _close(self, incomplete):
        carry = getattr(self, "_carry_var", None)
        carried: List[int] = []
        if carry and carry.get() and incomplete:
            tomorrow   = self._today + timedelta(days=1)
            tom_monday = tomorrow - timedelta(days=tomorrow.weekday())
            for t in incomplete:
                db.insert_schedule_entry(tom_monday, tomorrow, t.id,
                                         t.remaining_minutes)
                carried.append(t.id)
        db.save_daily_report(self._today, 0, len(incomplete),
                             self._focus, carried)
        self.destroy()
        self._app.advance_day()


# ── Timer Panel ───────────────────────────────────────────────────────────────

class TimerPanel(ctk.CTkFrame):
    """Right panel of DailyView: session config + arc timer + controls."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=BG)
        self._app = app
        self._build()

    def _build(self):
        # ── Session config card ───────────────────────────────────────────
        cfg = card_frame(self)
        cfg.pack(fill="x", padx=0, pady=(0, 14))

        section_label(cfg, "SESSION CONFIG").pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(cfg, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(0, 8))

        # Focus slider
        focus_col = ctk.CTkFrame(row1, fg_color="transparent")
        focus_col.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self._focus_lbl = body_label(focus_col, "Focus: 50m", size=12, color=T2)
        self._focus_lbl.pack(anchor="w")
        self._focus_var = tk.IntVar(value=50)
        ctk.CTkSlider(focus_col, from_=5, to=120, number_of_steps=23,
                      variable=self._focus_var, button_color=T1,
                      progress_color=T1, button_hover_color=SIDE_SEL,
                      command=self._on_focus_change).pack(fill="x")

        # Break slider
        brk_col = ctk.CTkFrame(row1, fg_color="transparent")
        brk_col.pack(side="left", expand=True, fill="x")
        self._brk_lbl = body_label(brk_col, "Break: 10m", size=12, color=T2)
        self._brk_lbl.pack(anchor="w")
        self._brk_var = tk.IntVar(value=10)
        ctk.CTkSlider(brk_col, from_=1, to=30, number_of_steps=29,
                      variable=self._brk_var, button_color=T1,
                      progress_color=T1, button_hover_color=SIDE_SEL,
                      command=self._on_brk_change).pack(fill="x")

        row2 = ctk.CTkFrame(cfg, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 12))
        body_label(row2, "Mode:", size=12, color=T2).pack(side="left", padx=(0, 8))
        self._mode_var = tk.StringVar(value="Chunk")
        ctk.CTkSegmentedButton(row2, values=["Chunk", "Sandwich"],
                               variable=self._mode_var,
                               font=ctk.CTkFont(size=12),
                               selected_color=T1, selected_hover_color=SIDE_SEL,
                               unselected_color=BORDER,
                               text_color="#FFF",
                               unselected_hover_color=ARC_BG).pack(side="left")

        # ── Timer card ────────────────────────────────────────────────────
        timer_card = card_frame(self)
        timer_card.configure(fg_color=TIMER_BG)
        timer_card.pack(fill="x", padx=0, pady=(0, 14))

        self._canvas = TimerCanvas(timer_card)
        self._canvas.pack(pady=(20, 8))

        # Block / task info
        self._block_lbl = body_label(timer_card, "", color=T2, size=12)
        self._block_lbl.pack()
        self._task_lbl = body_label(timer_card, "", color=T1, size=13)
        self._task_lbl.pack(pady=(2, 16))

        # Controls
        btn_row = ctk.CTkFrame(timer_card, fg_color="transparent")
        btn_row.pack(pady=(0, 20))

        self._start_btn = ctk.CTkButton(
            btn_row, text="▶  Start", width=120, height=38,
            fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
            font=ctk.CTkFont(size=13), corner_radius=20,
            command=self._on_start)
        self._start_btn.pack(side="left", padx=6)

        self._pause_btn = ctk.CTkButton(
            btn_row, text="⏸  Pause", width=100, height=38,
            fg_color=CARD, hover_color=ARC_BG, text_color=T1,
            font=ctk.CTkFont(size=13), corner_radius=20,
            border_width=1, border_color=BORDER,
            command=self._on_pause, state="disabled")
        self._pause_btn.pack(side="left", padx=6)

        self._stop_btn = ctk.CTkButton(
            btn_row, text="■  Stop", width=90, height=38,
            fg_color=CARD, hover_color="#FDEAEA", text_color=ERR_CLR,
            font=ctk.CTkFont(size=13), corner_radius=20,
            border_width=1, border_color="#E8CECE",
            command=self._on_stop, state="disabled")
        self._stop_btn.pack(side="left", padx=6)

    # ── Slider callbacks ──────────────────────────────────────────────────
    def _on_focus_change(self, v):
        v = int(v)
        self._focus_lbl.configure(text=f"Focus: {v}m")
        auto_brk = max(5, v // 5)
        self._brk_var.set(auto_brk)
        self._brk_lbl.configure(text=f"Break: {auto_brk}m")

    def _on_brk_change(self, v):
        self._brk_lbl.configure(text=f"Break: {int(v)}m")

    # ── Button callbacks ──────────────────────────────────────────────────
    def _on_start(self):
        tasks = db.get_tasks_for_date(self._app.today)
        if not tasks:
            messagebox.showinfo("No Tasks",
                "No tasks scheduled for today.\n"
                "Add tasks in the Weekly or Daily planner first.")
            return

        task_map = {t.id: t for t in tasks}
        schedule = db.get_schedule_for_date(self._app.today)
        slices   = [
            {"task_id": e["task_id"], "minutes": e["allocated_minutes"]}
            for e in schedule
            if not task_map.get(e["task_id"],
               Task(None,"",1,1,0,0,self._app.today,Quadrant.N,0)).completed
        ]
        if not slices:
            messagebox.showinfo("All Done", "All of today's tasks are complete!")
            return

        focus  = int(self._focus_var.get())
        brk    = int(self._brk_var.get())
        mode   = (SplitMode.CHUNK if self._mode_var.get() == "Chunk"
                  else SplitMode.SANDWICH)
        blocks = scheduler.build_daily_blocks(slices, focus, brk, mode)
        for i, b in enumerate(blocks):
            b.block_date  = self._app.today
            b.block_index = i
            b.id = db.insert_pomodoro_block(b)

        self._start_btn.configure(state="disabled")
        self._pause_btn.configure(state="normal")
        self._stop_btn.configure(state="normal")
        self._app.timer_start(blocks, task_map, focus, brk)

    def _on_pause(self):
        self._app.timer_pause_toggle()
        paused = self._app._timer_paused
        self._pause_btn.configure(text="▶  Resume" if paused else "⏸  Pause")

    def _on_stop(self):
        self._app.timer_stop()
        self._start_btn.configure(state="normal")
        self._pause_btn.configure(state="disabled", text="⏸  Pause")
        self._stop_btn.configure(state="disabled")

    # ── Called by App timer engine ────────────────────────────────────────
    def update_display(self, remaining_s: int, progress: float, is_break: bool):
        label = "break" if is_break else "focus"
        self._canvas.update(remaining_s, progress, label, is_break)

    def on_block_start(self, idx: int, total: int, block, task_map: Dict,
                       is_break: bool):
        self._block_lbl.configure(
            text=f"{'Break' if is_break else 'Block'} {idx+1} / {total}")
        if not is_break:
            names = ", ".join(
                task_map[s["task_id"]].name
                for s in block.task_slices
                if s["task_id"] in task_map)
            self._task_lbl.configure(text=names)
        else:
            self._task_lbl.configure(text="Rest up  ☕")

    def on_block_end(self, block, task_map: Dict, today: date, on_done):
        CompletionDialog(self._app, block, task_map, today, on_done)

    def reset_display(self):
        self._canvas.reset()
        self._block_lbl.configure(text="")
        self._task_lbl.configure(text="")
        self._start_btn.configure(state="normal")
        self._pause_btn.configure(state="disabled", text="⏸  Pause")
        self._stop_btn.configure(state="disabled")


# ── Daily View ────────────────────────────────────────────────────────────────

class DailyView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=BG, corner_radius=0)
        self._app = app
        self.timer_panel: Optional[TimerPanel] = None
        self._build()

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hdr.pack(fill="x", padx=28, pady=(22, 0))
        self._date_heading = heading(hdr, "", size=22)
        self._date_heading.pack(side="left")

        # Adhoc button
        ctk.CTkButton(hdr, text="+ Ad-hoc task", width=140, height=32,
                      fg_color=CARD, hover_color=ARC_BG, text_color=T1,
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      border_width=1, border_color=BORDER,
                      command=self._add_adhoc).pack(side="right")

        Divider(self).pack(fill="x", padx=28, pady=12)

        # Two-column body
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)

        # Left: task list
        left = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._task_scroll = ctk.CTkScrollableFrame(left, fg_color=BG,
                                                    scrollbar_button_color=BORDER)
        self._task_scroll.pack(fill="both", expand=True)

        # Right: timer
        right = ctk.CTkScrollableFrame(body, fg_color=BG,
                                        scrollbar_button_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew")
        self.timer_panel = TimerPanel(right, self._app)
        self.timer_panel.pack(fill="both", expand=True)

    def refresh(self):
        today = self._app.today
        self._date_heading.configure(
            text=today.strftime("%A, %B %d, %Y"))

        # Clear task list
        for w in self._task_scroll.winfo_children():
            w.destroy()

        # Classes
        classes = db.get_classes_for_day(today)
        if classes:
            section_label(self._task_scroll,
                          "TODAY'S CLASSES").pack(anchor="w", pady=(4, 4))
            for c in classes:
                hrs = db._time_diff_hours(c["start_time"], c["end_time"])
                row = ctk.CTkFrame(self._task_scroll, fg_color=CARD,
                                   corner_radius=8, border_width=1,
                                   border_color=BORDER)
                row.pack(fill="x", pady=3)
                body_label(row, f"📚  {c['course_name']}",
                           size=13).pack(side="left", padx=12, pady=8)
                body_label(row, f"{c['start_time']}–{c['end_time']}  "
                           f"({hrs:.1f}h)",
                           color=T2, size=12).pack(side="right", padx=12)

        # Weekly tasks
        tasks = db.get_tasks_for_date(today)
        weekly = [t for t in tasks if t.source == "weekly"]
        adhoc  = [t for t in tasks if t.source == "adhoc"]

        if not tasks and not classes:
            msg = card_frame(self._task_scroll)
            msg.pack(fill="x", pady=20)
            body_label(msg, "No tasks from Weekly Planner today.",
                       color=T2).pack(pady=20)
            body_label(msg, "→ Go to Weekly tab to add tasks.",
                       color=T2, size=12).pack(pady=(0, 20))
            return

        if weekly:
            section_label(self._task_scroll,
                          "FROM WEEKLY PLANNER").pack(anchor="w",
                                                       pady=(12, 4))
            for t in weekly:
                self._task_row(t)

        if adhoc:
            section_label(self._task_scroll,
                          "AD-HOC").pack(anchor="w", pady=(12, 4))
            for t in adhoc:
                self._task_row(t)

    def _task_row(self, t: Task):
        row = card_frame(self._task_scroll)
        row.pack(fill="x", pady=3)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)

        mark = "✓" if t.completed else "○"
        color = OK_CLR if t.completed else T1
        body_label(inner, f"{mark}  {t.name}", color=color,
                   size=13).pack(side="left")

        right_info = ctk.CTkFrame(inner, fg_color="transparent")
        right_info.pack(side="right")
        body_label(right_info,
                   f"{t.remaining_minutes:.0f}m  ·  "
                   f"dl {t.deadline.strftime('%b %d')}",
                   color=T2, size=11).pack(side="right")

        # Subtasks
        if t.subtasks:
            for st in t.subtasks:
                sc = OK_CLR if st.completed else T2
                sm = "✓" if st.completed else "·"
                body_label(row, f"     {sm}  {st.name}  "
                           f"({st.estimated_minutes:.0f}m)",
                           color=sc, size=11).pack(anchor="w",
                                                    padx=16, pady=1)
            ctk.CTkFrame(row, height=6, fg_color="transparent").pack()

    def _add_adhoc(self):
        AdhocDialog(self._app, self._app.today, self.refresh)


# ── Adhoc Dialog ──────────────────────────────────────────────────────────────

class AdhocDialog(ctk.CTkToplevel):
    def __init__(self, app, today: date, on_done):
        super().__init__(app)
        self.title("Add Ad-Hoc Task")
        self.geometry("420x460")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app     = app
        self._today   = today
        self._on_done = on_done
        self._build()

    def _build(self):
        heading(self, "New Ad-Hoc Task", size=16).pack(
            pady=(20, 4), padx=20, anchor="w")
        body_label(self, "Added directly to today's schedule.",
                   color=T2, size=12).pack(padx=20, anchor="w")
        Divider(self).pack(fill="x", padx=20, pady=12)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=20)

        section_label(form, "TASK NAME").pack(anchor="w")
        self._name = ctk.CTkEntry(form, height=36, font=ctk.CTkFont(size=13),
                                   fg_color=CARD, border_color=BORDER,
                                   text_color=T1)
        self._name.pack(fill="x", pady=(2, 10))

        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        col1 = ctk.CTkFrame(row, fg_color="transparent")
        col1.pack(side="left", expand=True, fill="x", padx=(0, 8))
        section_label(col1, "HOURS").pack(anchor="w")
        self._hours = ctk.CTkEntry(col1, height=36, font=ctk.CTkFont(size=13),
                                    placeholder_text="e.g. 1.5",
                                    fg_color=CARD, border_color=BORDER,
                                    text_color=T1)
        self._hours.pack(fill="x", pady=(2, 0))

        col2 = ctk.CTkFrame(row, fg_color="transparent")
        col2.pack(side="left", expand=True, fill="x")
        section_label(col2, "URGENCY").pack(anchor="w")
        self._urg_var = tk.IntVar(value=3)
        self._urg_lbl = body_label(col2, "3 / 5", color=T2, size=11)
        self._urg_lbl.pack(anchor="w")
        ctk.CTkSlider(col2, from_=1, to=5, number_of_steps=4,
                      variable=self._urg_var, button_color=T1,
                      progress_color=T1,
                      command=lambda v: self._urg_lbl.configure(
                          text=f"{int(v)} / 5")).pack(fill="x")

        section_label(form, "IMPORTANCE").pack(anchor="w", pady=(6, 0))
        self._imp_var = tk.IntVar(value=3)
        self._imp_lbl = body_label(form, "3 / 5", color=T2, size=11)
        self._imp_lbl.pack(anchor="w")
        ctk.CTkSlider(form, from_=1, to=5, number_of_steps=4,
                      variable=self._imp_var, button_color=T1,
                      progress_color=T1,
                      command=lambda v: self._imp_lbl.configure(
                          text=f"{int(v)} / 5")).pack(fill="x",
                                                       pady=(0, 12))

        ctk.CTkButton(self, text="Add Task",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=40,
                      command=self._save).pack(pady=16, padx=20, fill="x")

    def _save(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning("Missing", "Task name is required.", parent=self)
            return
        try:
            hours = float(self._hours.get())
        except ValueError:
            messagebox.showwarning("Invalid", "Hours must be a number.", parent=self)
            return

        week_start = self._today - timedelta(days=self._today.weekday())
        existing   = db.task_in_week_by_name(name, week_start)
        if existing:
            if not messagebox.askyesno(
                    "Duplicate",
                    f"'{name}' already exists this week.\n"
                    "Add as a separate task anyway?", parent=self):
                self.destroy()
                return

        urg  = int(self._urg_var.get())
        imp  = int(self._imp_var.get())
        q    = scheduler.classify_quadrant(urg, imp)
        sc   = scheduler.compute_priority_score(urg, imp, q, self._today)
        task = Task(id=None, name=name, urgency=urg, importance=imp,
                    time_allocation=hours, remaining_minutes=hours * 60,
                    deadline=self._today, quadrant=q, priority_score=sc,
                    source="adhoc", week_start=week_start)
        tid  = db.insert_task(task)
        db.insert_schedule_entry(week_start, self._today, tid, hours * 60)
        self.destroy()
        self._on_done()


# ── Weekly View ───────────────────────────────────────────────────────────────

class WeeklyView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=BG, corner_radius=0)
        self._app = app
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hdr.pack(fill="x", padx=28, pady=(22, 0))
        heading(hdr, "Weekly Planner", size=22).pack(side="left")

        self._week_lbl = body_label(hdr, "", color=T2)
        self._week_lbl.pack(side="left", padx=16)

        ctk.CTkButton(hdr, text="⟳  Regenerate", width=130, height=32,
                      fg_color=CARD, hover_color=ARC_BG, text_color=T1,
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      border_width=1, border_color=BORDER,
                      command=self._regen).pack(side="right")

        ctk.CTkButton(hdr, text="+ Add Task", width=110, height=32,
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      command=self._add_task).pack(side="right", padx=8)

        Divider(self).pack(fill="x", padx=28, pady=12)

        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self._schedule_scroll = ctk.CTkScrollableFrame(
            body, fg_color=BG, scrollbar_button_color=BORDER)
        self._schedule_scroll.grid(row=0, column=0, sticky="nsew")

    def refresh(self):
        ws = self._app.week_start
        self._week_lbl.configure(
            text=f"Week of {ws.strftime('%b %d, %Y')}")

        for w in self._schedule_scroll.winfo_children():
            w.destroy()

        entries   = db.get_schedule_for_week(ws)
        all_tasks = {t.id: t for t in db.get_all_tasks(week_start=ws)}
        by_day: Dict = {}
        for e in entries:
            by_day.setdefault(e["day_date"], []).append(e)

        work_days = [ws + timedelta(days=i) for i in range(5)]

        if not entries:
            msg = card_frame(self._schedule_scroll)
            msg.pack(fill="x", pady=20)
            body_label(msg, "No schedule yet. Click '+ Add Task' to begin.",
                       color=T2).pack(pady=20)
            return

        for d in work_days:
            ds      = d.isoformat()
            ch      = db.get_class_hours_for_day(d)
            classes = db.get_classes_for_day(d)

            day_card = card_frame(self._schedule_scroll)
            day_card.pack(fill="x", pady=5)

            hdr_row = ctk.CTkFrame(day_card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=14, pady=(10, 4))
            body_label(hdr_row,
                       f"{d.strftime('%A, %b %d')}",
                       size=13).pack(side="left")
            if ch > 0:
                body_label(hdr_row,
                           f"−{ch:.1f}h classes",
                           color=T2, size=11).pack(side="right")

            for c in classes:
                body_label(day_card,
                           f"  📚 {c['course_name']}  "
                           f"{c['start_time']}–{c['end_time']}",
                           color=T2, size=11).pack(anchor="w", padx=14)

            if ds in by_day:
                for e in by_day[ds]:
                    t = all_tasks.get(e["task_id"])
                    if not t:
                        continue
                    trow = ctk.CTkFrame(day_card, fg_color="transparent")
                    trow.pack(fill="x", padx=14, pady=2)
                    mark  = "✓" if t.completed else "○"
                    color = OK_CLR if t.completed else T1
                    body_label(trow, f"{mark}  {t.name}",
                               color=color, size=12).pack(side="left")
                    body_label(trow,
                               f"{e['allocated_minutes']:.0f}m  "
                               f"[{t.quadrant.value}]  "
                               f"P={t.priority_score:.1f}",
                               color=T2, size=11).pack(side="right")

            ctk.CTkFrame(day_card, height=8,
                         fg_color="transparent").pack()

    def _add_task(self):
        AddTaskDialog(self._app, self._app.week_start, self.refresh)

    def _regen(self):
        tasks = db.get_all_tasks(week_start=self._app.week_start,
                                 completed=False)
        if not tasks:
            messagebox.showinfo("No Tasks",
                                "Add tasks before generating a schedule.")
            return
        work_days   = [self._app.week_start + timedelta(days=i) for i in range(5)]
        class_hours = {d: db.get_class_hours_for_day(d) for d in work_days}
        try:
            alloc = scheduler.allocate_weekly(
                tasks, self._app.week_start, 8.0, class_hours)
        except scheduler.PomodoroDebtError as e:
            messagebox.showerror("Schedule Impossible", str(e))
            return
        db.clear_schedule_for_week(self._app.week_start)
        for day_date, entries in alloc.items():
            for task_id, minutes in entries:
                db.insert_schedule_entry(
                    self._app.week_start, day_date, task_id, minutes)
        self.refresh()


# ── Add Task Dialog ───────────────────────────────────────────────────────────

class AddTaskDialog(ctk.CTkToplevel):
    def __init__(self, app, week_start: date, on_done):
        super().__init__(app)
        self.title("Add Weekly Task")
        self.geometry("480x640")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app        = app
        self._week_start = week_start
        self._on_done    = on_done
        self._subtasks: List[Dict] = []
        self._build()

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        heading(scroll, "New Task", size=16).pack(anchor="w", pady=(0, 4))
        Divider(scroll).pack(fill="x", pady=8)

        # Name
        section_label(scroll, "TASK NAME").pack(anchor="w")
        self._name = ctk.CTkEntry(scroll, height=36, font=ctk.CTkFont(size=13),
                                   fg_color=CARD, border_color=BORDER,
                                   text_color=T1)
        self._name.pack(fill="x", pady=(2, 10))

        # Urgency
        section_label(scroll, "URGENCY").pack(anchor="w")
        self._urg_lbl = body_label(scroll, "3 / 5", color=T2, size=11)
        self._urg_lbl.pack(anchor="w")
        self._urg_var = tk.IntVar(value=3)
        ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4,
                      variable=self._urg_var, button_color=T1,
                      progress_color=T1,
                      command=lambda v: self._urg_lbl.configure(
                          text=f"{int(v)} / 5")).pack(fill="x",
                                                       pady=(0, 10))

        # Importance
        section_label(scroll, "IMPORTANCE").pack(anchor="w")
        self._imp_lbl = body_label(scroll, "3 / 5", color=T2, size=11)
        self._imp_lbl.pack(anchor="w")
        self._imp_var = tk.IntVar(value=3)
        ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4,
                      variable=self._imp_var, button_color=T1,
                      progress_color=T1,
                      command=lambda v: self._imp_lbl.configure(
                          text=f"{int(v)} / 5")).pack(fill="x",
                                                       pady=(0, 10))

        # Hours
        section_label(scroll, "ESTIMATED HOURS").pack(anchor="w")

        # Try to pull difficulty suggestion
        last_week  = week_start - timedelta(weeks=1)
        prev_tasks = db.get_tasks_from_week(last_week)
        self._prev_map = {t.name.lower(): t for t in prev_tasks}
        self._name.bind("<FocusOut>", self._on_name_blur)

        self._hours_hint = body_label(scroll, "", color=T2, size=11)
        self._hours_hint.pack(anchor="w")
        self._hours = ctk.CTkEntry(scroll, height=36,
                                    font=ctk.CTkFont(size=13),
                                    placeholder_text="e.g. 2.5",
                                    fg_color=CARD, border_color=BORDER,
                                    text_color=T1)
        self._hours.pack(fill="x", pady=(2, 10))

        # Deadline
        section_label(scroll, "DEADLINE").pack(anchor="w")
        days      = next_21_days()
        day_strs  = [date_label(d) for d in days]
        self._day_map = dict(zip(day_strs, days))
        self._deadline_var = tk.StringVar(value=day_strs[4])
        ctk.CTkOptionMenu(scroll, values=day_strs,
                          variable=self._deadline_var,
                          font=ctk.CTkFont(size=12),
                          fg_color=CARD, button_color=T1,
                          button_hover_color=SIDE_SEL,
                          text_color=T1, dropdown_text_color=T1,
                          dropdown_fg_color=CARD).pack(fill="x",
                                                        pady=(2, 10))

        # Notes
        section_label(scroll, "NOTES (optional)").pack(anchor="w")
        self._notes = ctk.CTkEntry(scroll, height=36,
                                    font=ctk.CTkFont(size=12),
                                    fg_color=CARD, border_color=BORDER,
                                    text_color=T1)
        self._notes.pack(fill="x", pady=(2, 10))

        # Subtasks
        section_label(scroll, "SUB-TASKS").pack(anchor="w", pady=(4, 0))
        self._sub_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._sub_frame.pack(fill="x")

        sub_row = ctk.CTkFrame(scroll, fg_color="transparent")
        sub_row.pack(fill="x", pady=(4, 0))
        self._sub_entry = ctk.CTkEntry(sub_row, height=32,
                                        font=ctk.CTkFont(size=12),
                                        placeholder_text="Sub-task name",
                                        fg_color=CARD, border_color=BORDER,
                                        text_color=T1)
        self._sub_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._sub_mins = ctk.CTkEntry(sub_row, width=80, height=32,
                                       font=ctk.CTkFont(size=12),
                                       placeholder_text="min",
                                       fg_color=CARD, border_color=BORDER,
                                       text_color=T1)
        self._sub_mins.pack(side="left", padx=(0, 6))
        ctk.CTkButton(sub_row, text="+", width=32, height=32,
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=14),
                      command=self._add_subtask).pack(side="left")

        ctk.CTkButton(self, text="Save Task",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=42,
                      command=self._save).pack(pady=16, padx=20, fill="x")

    def _on_name_blur(self, _event=None):
        name = self._name.get().strip().lower()
        prev = self._prev_map.get(name)
        if prev:
            diff = db.get_latest_difficulty(prev.name)
            if diff is not None:
                mult = db.DIFFICULTY_MULTIPLIER[diff]
                adj  = round(prev.time_allocation * mult, 1)
                self._hours_hint.configure(
                    text=f"ℹ  Last week: {prev.time_allocation}h  "
                         f"· difficulty {diff}/5  →  suggested {adj}h")
                if not self._hours.get():
                    self._hours.insert(0, str(adj))
            else:
                self._hours_hint.configure(
                    text=f"ℹ  Last week you used {prev.time_allocation}h")
                if not self._hours.get():
                    self._hours.insert(0, str(prev.time_allocation))

    def _add_subtask(self):
        name = self._sub_entry.get().strip()
        mins_raw = self._sub_mins.get().strip()
        if not name:
            return
        try:
            mins = float(mins_raw)
        except ValueError:
            mins = 30.0
        self._subtasks.append({"name": name, "minutes": mins})
        body_label(self._sub_frame,
                   f"  ·  {name}  ({mins:.0f}m)",
                   color=T2, size=11).pack(anchor="w")
        self._sub_entry.delete(0, "end")
        self._sub_mins.delete(0, "end")

    def _save(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning("Missing", "Task name is required.", parent=self)
            return
        try:
            hours = float(self._hours.get())
        except ValueError:
            messagebox.showwarning("Invalid", "Hours must be a number.", parent=self)
            return

        if db.task_in_week_by_name(name, self._week_start):
            messagebox.showwarning("Duplicate",
                f"'{name}' already exists this week.", parent=self)
            return

        dl  = self._day_map.get(self._deadline_var.get(), date.today())
        urg = int(self._urg_var.get())
        imp = int(self._imp_var.get())
        q   = scheduler.classify_quadrant(urg, imp)
        sc  = scheduler.compute_priority_score(urg, imp, q, dl)

        task = Task(id=None, name=name, urgency=urg, importance=imp,
                    time_allocation=hours, remaining_minutes=hours * 60,
                    deadline=dl, quadrant=q, priority_score=sc,
                    source="weekly", week_start=self._week_start,
                    notes=self._notes.get().strip())
        tid  = db.insert_task(task)
        task.id = tid

        for i, s in enumerate(self._subtasks):
            db.insert_subtask(Subtask(id=None, task_id=tid,
                                      name=s["name"],
                                      estimated_minutes=s["minutes"],
                                      order_index=i))

        # Auto-generate schedule
        tasks = db.get_all_tasks(week_start=self._week_start, completed=False)
        work_days   = [self._week_start + timedelta(days=i) for i in range(5)]
        class_hours = {d: db.get_class_hours_for_day(d) for d in work_days}
        try:
            alloc = scheduler.allocate_weekly(tasks, self._week_start,
                                              8.0, class_hours)
            db.clear_schedule_for_week(self._week_start)
            for day_date, entries in alloc.items():
                for task_id, minutes in entries:
                    db.insert_schedule_entry(
                        self._week_start, day_date, task_id, minutes)
        except scheduler.PomodoroDebtError as e:
            messagebox.showwarning("Schedule Warning", str(e), parent=self)

        self.destroy()
        self._on_done()


# ── Term View ─────────────────────────────────────────────────────────────────

class TermView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=BG, corner_radius=0)
        self._app = app
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        hdr.pack(fill="x", padx=28, pady=(22, 0))
        heading(hdr, "Term Schedule", size=22).pack(side="left")
        ctk.CTkButton(hdr, text="+ Add Class", width=120, height=32,
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      command=self._add_class).pack(side="right")
        Divider(self).pack(fill="x", padx=28, pady=12)

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=BG, scrollbar_button_color=BORDER)
        self._scroll.pack(fill="both", expand=True, padx=28, pady=(0, 20))

    def refresh(self):
        for w in self._scroll.winfo_children():
            w.destroy()

        classes = db.get_term_classes()
        if not classes:
            msg = card_frame(self._scroll)
            msg.pack(fill="x", pady=20)
            body_label(msg, "No term classes saved yet.",
                       color=T2).pack(pady=20)
            body_label(msg, "Add your recurring class schedule once "
                       "and it applies every week.",
                       color=T2, size=12).pack(pady=(0, 20))
            return

        days_full = ["Monday","Tuesday","Wednesday","Thursday",
                     "Friday","Saturday","Sunday"]
        by_day: Dict = {}
        for c in classes:
            by_day.setdefault(c["day_of_week"], []).append(c)

        for dow in sorted(by_day):
            section_label(self._scroll, days_full[dow].upper()).pack(
                anchor="w", pady=(12, 4))
            for c in by_day[dow]:
                row = card_frame(self._scroll)
                row.pack(fill="x", pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=14, pady=10)

                body_label(inner, f"📚  {c['course_name']}",
                           size=13).pack(side="left")

                right = ctk.CTkFrame(inner, fg_color="transparent")
                right.pack(side="right")
                hrs = db._time_diff_hours(c["start_time"], c["end_time"])
                body_label(right,
                           f"{c['start_time']}–{c['end_time']}  "
                           f"({hrs:.1f}h)   "
                           f"{c['term_start']} → {c['term_end']}",
                           color=T2, size=11).pack(side="left", padx=8)

                ctk.CTkButton(right, text="✕", width=28, height=28,
                              fg_color="transparent",
                              hover_color="#FDEAEA",
                              text_color=ERR_CLR,
                              font=ctk.CTkFont(size=12),
                              command=lambda cid=c["id"]: self._delete(cid)
                              ).pack(side="left")

                if c["location"]:
                    body_label(row, f"   {c['location']}",
                               color=T2, size=11).pack(anchor="w",
                                                        padx=14, pady=(0, 6))

    def _delete(self, cid: int):
        if messagebox.askyesno("Remove", "Remove this class?"):
            db.delete_term_class(cid)
            self.refresh()

    def _add_class(self):
        AddClassDialog(self._app, self.refresh)


# ── Add Class Dialog ──────────────────────────────────────────────────────────

class AddClassDialog(ctk.CTkToplevel):
    def __init__(self, app, on_done):
        super().__init__(app)
        self.title("Add Term Class")
        self.geometry("420x540")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._on_done = on_done
        self._build()

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        heading(scroll, "New Term Class", size=16).pack(anchor="w",
                                                         pady=(0, 4))
        Divider(scroll).pack(fill="x", pady=8)

        section_label(scroll, "COURSE NAME").pack(anchor="w")
        self._name = ctk.CTkEntry(scroll, height=36,
                                   font=ctk.CTkFont(size=13),
                                   fg_color=CARD, border_color=BORDER,
                                   text_color=T1)
        self._name.pack(fill="x", pady=(2, 10))

        section_label(scroll, "DAY OF WEEK").pack(anchor="w")
        days = ["Monday","Tuesday","Wednesday","Thursday",
                "Friday","Saturday","Sunday"]
        self._dow_var = tk.StringVar(value="Monday")
        ctk.CTkOptionMenu(scroll, values=days, variable=self._dow_var,
                          font=ctk.CTkFont(size=12),
                          fg_color=CARD, button_color=T1,
                          button_hover_color=SIDE_SEL,
                          text_color=T1,
                          dropdown_text_color=T1,
                          dropdown_fg_color=CARD).pack(fill="x",
                                                        pady=(2, 10))

        time_row = ctk.CTkFrame(scroll, fg_color="transparent")
        time_row.pack(fill="x", pady=(0, 10))
        col1 = ctk.CTkFrame(time_row, fg_color="transparent")
        col1.pack(side="left", expand=True, fill="x", padx=(0, 8))
        section_label(col1, "START (HH:MM)").pack(anchor="w")
        self._start = ctk.CTkEntry(col1, height=36,
                                    font=ctk.CTkFont(size=13),
                                    placeholder_text="09:00",
                                    fg_color=CARD, border_color=BORDER,
                                    text_color=T1)
        self._start.pack(fill="x", pady=(2, 0))

        col2 = ctk.CTkFrame(time_row, fg_color="transparent")
        col2.pack(side="left", expand=True, fill="x")
        section_label(col2, "END (HH:MM)").pack(anchor="w")
        self._end = ctk.CTkEntry(col2, height=36,
                                  font=ctk.CTkFont(size=13),
                                  placeholder_text="10:30",
                                  fg_color=CARD, border_color=BORDER,
                                  text_color=T1)
        self._end.pack(fill="x", pady=(2, 0))

        days21    = next_21_days()
        day_strs  = [date_label(d) for d in days21]
        self._day_map = dict(zip(day_strs, days21))

        section_label(scroll, "TERM START").pack(anchor="w", pady=(8, 0))
        self._tstart_var = tk.StringVar(value=day_strs[0])
        ctk.CTkOptionMenu(scroll, values=day_strs,
                          variable=self._tstart_var,
                          font=ctk.CTkFont(size=12),
                          fg_color=CARD, button_color=T1,
                          button_hover_color=SIDE_SEL,
                          text_color=T1, dropdown_text_color=T1,
                          dropdown_fg_color=CARD).pack(fill="x",
                                                        pady=(2, 10))

        section_label(scroll, "TERM END").pack(anchor="w")
        self._tend_var = tk.StringVar(value=day_strs[-1])
        ctk.CTkOptionMenu(scroll, values=day_strs,
                          variable=self._tend_var,
                          font=ctk.CTkFont(size=12),
                          fg_color=CARD, button_color=T1,
                          button_hover_color=SIDE_SEL,
                          text_color=T1, dropdown_text_color=T1,
                          dropdown_fg_color=CARD).pack(fill="x",
                                                        pady=(2, 10))

        section_label(scroll, "LOCATION (optional)").pack(anchor="w")
        self._loc = ctk.CTkEntry(scroll, height=36,
                                  font=ctk.CTkFont(size=12),
                                  fg_color=CARD, border_color=BORDER,
                                  text_color=T1)
        self._loc.pack(fill="x", pady=(2, 0))

        ctk.CTkButton(self, text="Save Class",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=42,
                      command=self._save).pack(pady=16, padx=20, fill="x")

    def _save(self):
        name  = self._name.get().strip()
        start = self._start.get().strip()
        end   = self._end.get().strip()
        if not name or not start or not end:
            messagebox.showwarning("Missing", "Name, start and end are required.",
                                   parent=self)
            return
        for t in (start, end):
            parts = t.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                messagebox.showwarning("Invalid",
                                       "Time must be HH:MM (e.g. 09:30).",
                                       parent=self)
                return
        if end <= start:
            messagebox.showwarning("Invalid",
                                   "End time must be after start.", parent=self)
            return

        days_full = ["Monday","Tuesday","Wednesday","Thursday",
                     "Friday","Saturday","Sunday"]
        dow   = days_full.index(self._dow_var.get())
        ts    = self._day_map.get(self._tstart_var.get(), date.today())
        te    = self._day_map.get(self._tend_var.get(), date.today())
        loc   = self._loc.get().strip()
        db.insert_term_class(name, dow, start, end, ts, te, loc)
        self.destroy()
        self._on_done()


# ── App ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        db.init_db()
        self.title("Study Planner")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)

        self.today      = date.today()
        self.week_start = week_start_of(self.today)

        # Timer state
        self._timer_active  = False
        self._timer_paused  = False
        self._in_break      = False
        self._elapsed_s     = 0
        self._total_s       = 0
        self._focus_min     = 50
        self._break_min     = 10
        self._blocks: List  = []
        self._block_idx     = 0
        self._task_map: Dict = {}
        self._after_id      = None
        self._total_focus_min = 0

        self._build_ui()
        self._show_daily()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Sidebar
        self._sidebar = ctk.CTkFrame(self, width=210,
                                      fg_color=SIDE, corner_radius=0)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        ctk.CTkLabel(self._sidebar, text="Study\nPlanner",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#FFFFFF").pack(pady=(28, 8), padx=20)

        ctk.CTkFrame(self._sidebar, height=1,
                     fg_color="#333").pack(fill="x", padx=16, pady=(0, 12))

        self._btn_daily  = SideBtn(self._sidebar, "  📆  Daily",
                                    self._show_daily)
        self._btn_weekly = SideBtn(self._sidebar, "  📅  Weekly",
                                    self._show_weekly)
        self._btn_term   = SideBtn(self._sidebar, "  📚  Term Schedule",
                                    self._show_term)
        for b in (self._btn_daily, self._btn_weekly, self._btn_term):
            b.pack(fill="x", padx=12, pady=2)

        self._date_lbl = ctk.CTkLabel(
            self._sidebar,
            text=self.today.strftime("%a, %b %d"),
            font=ctk.CTkFont(size=11), text_color="#555555")
        self._date_lbl.pack(side="bottom", pady=16)

        # Content
        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self._content.pack(side="left", fill="both", expand=True)

        self._daily_view  = DailyView(self._content, self)
        self._weekly_view = WeeklyView(self._content, self)
        self._term_view   = TermView(self._content, self)

    def _hide_all(self):
        for v in (self._daily_view, self._weekly_view, self._term_view):
            v.place_forget()

    def _set_active(self, btn):
        for b in (self._btn_daily, self._btn_weekly, self._btn_term):
            b.configure(fg_color=SIDE_SEL if b is btn else "transparent",
                        text_color="#FFFFFF" if b is btn else "#BBBBBB")

    def _show_daily(self):
        self._hide_all()
        self._daily_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._daily_view.refresh()
        self._set_active(self._btn_daily)

    def _show_weekly(self):
        self._hide_all()
        self._weekly_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._weekly_view.refresh()
        self._set_active(self._btn_weekly)

    def _show_term(self):
        self._hide_all()
        self._term_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._term_view.refresh()
        self._set_active(self._btn_term)

    def advance_day(self):
        self.today      = self.today + timedelta(days=1)
        self.week_start = week_start_of(self.today)
        self._total_focus_min = 0
        self._date_lbl.configure(text=self.today.strftime("%a, %b %d"))
        self._show_daily()

    # ── Timer engine ──────────────────────────────────────────────────────

    def timer_start(self, blocks, task_map, focus_min, break_min):
        self._blocks    = blocks
        self._task_map  = task_map
        self._focus_min = focus_min
        self._break_min = break_min
        self._block_idx = 0
        self._total_focus_min = 0
        self._start_block()

    def _start_block(self):
        while self._block_idx < len(self._blocks):
            if not self._blocks[self._block_idx].completed:
                break
            self._block_idx += 1
        if self._block_idx >= len(self._blocks):
            self._finish()
            return
        self._in_break      = False
        self._elapsed_s     = 0
        self._total_s       = self._focus_min * 60
        self._timer_active  = True
        self._timer_paused  = False
        b = self._blocks[self._block_idx]
        self._daily_view.timer_panel.on_block_start(
            self._block_idx, len(self._blocks), b, self._task_map, False)
        self._after_id = self.after(1000, self._tick)

    def _start_break(self):
        self._in_break  = True
        self._elapsed_s = 0
        self._total_s   = self._break_min * 60
        b = self._blocks[self._block_idx]
        self._daily_view.timer_panel.on_block_start(
            self._block_idx, len(self._blocks), b, self._task_map, True)
        self._after_id = self.after(1000, self._tick)

    def _tick(self):
        if not self._timer_active or self._timer_paused:
            return
        self._elapsed_s += 1
        remaining = self._total_s - self._elapsed_s
        progress  = (self._elapsed_s / self._total_s) if self._total_s else 1.0
        self._daily_view.timer_panel.update_display(remaining, progress,
                                                     self._in_break)
        if remaining <= 0:
            if not self._in_break:
                self._total_focus_min += self._focus_min
                b = self._blocks[self._block_idx]
                db.mark_block_complete(b.id, self._focus_min)
                self._daily_view.timer_panel.on_block_end(
                    b, self._task_map, self.today,
                    self._after_block_completion)
            else:
                self._block_idx += 1
                self._start_block()
        else:
            self._after_id = self.after(1000, self._tick)

    def _after_block_completion(self):
        if self._block_idx < len(self._blocks) - 1:
            self._start_break()
        else:
            self._block_idx += 1
            self._finish()

    def timer_pause_toggle(self):
        if not self._timer_active:
            return
        self._timer_paused = not self._timer_paused
        if not self._timer_paused:
            self._after_id = self.after(1000, self._tick)

    def timer_stop(self):
        self._timer_active = False
        if self._after_id:
            self.after_cancel(self._after_id)

    def _finish(self):
        self._timer_active = False
        all_blocks = db.get_blocks_for_date(self.today)
        if all_blocks and all(b.completed for b in all_blocks):
            self._daily_view.timer_panel.reset_display()
            ReportWindow(self, self.today, self._total_focus_min)
        else:
            self._daily_view.timer_panel.reset_display()
            self._daily_view.refresh()


if __name__ == "__main__":
    app = App()
    app.mainloop()
