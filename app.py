#!/usr/bin/env python3
"""
Study Planner — unified GUI.
pip install customtkinter
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from tkcalendar import DateEntry
import math
from datetime import date, timedelta
import time
from typing import Optional, List, Dict

import database as db
import scheduler
from models import Task, Subtask, Quadrant, QUADRANT_LABELS, SplitMode
from mascots import DEAD_MASCOT  #Claude修正

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
ARC_PAUSE = "#E3B341"

# Eisenhower-quadrant card tints (Feature 5：依象限為任務卡上色).  #Claude修正
QUAD_CLR = {                                                       #Claude修正
    "UI":  "#FDEAEA",   # Urgent & Important       → light red     #Claude修正
    "UU":  "#FDECD9",   # Urgent but Unimportant   → light orange  #Claude修正
    "INU": "#FEF9E0",   # Important but Not Urgent → light yellow  #Claude修正
    "N":   "#E8F5EC",   # Neither                  → light green   #Claude修正
}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

DAYS_S = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
          "Jul","Aug","Sep","Oct","Nov","Dec"]


# ── Utility ───────────────────────────────────────────────────────────────────
def week_start_of(d: date) -> date:
    return date.today()  # 改成永遠從「今天」開始

def format_hm(minutes: float) -> str:
    """將分鐘數轉換為 Xh Ym 的直覺格式"""
    if minutes <= 0:
        return "0m"
    h = int(minutes // 60)
    m = int(minutes % 60)
    if h > 0 and m > 0:
        return f"{h}h {m}m"
    elif h > 0:
        return f"{h}h"
    else:
        return f"{m}m"

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
               label: str, is_break: bool, is_paused: bool = False):
        self.delete("all")
        
        # --- [優化：加入暫停顏色的判斷] ---
        if is_paused:
            arc_color = ARC_PAUSE
        elif is_break:
            arc_color = ARC_BRK
        else:
            arc_color = ARC_FG
        # --------------------------------
        
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

# ── Completion dialog ─────────────────────────────────────────────────────────

# ── Completion dialog ─────────────────────────────────────────────────────────

class CompletionDialog(ctk.CTkToplevel):
    """
    Block 結束後的進度回報 dialog。
    ─ 每個 task 顯示：
        • 主任務整體完成度 slider（拖動只影響主任務 remaining_minutes）
        • 主任務剩餘時間即時顯示
        • 各子任務 checkbox → 勾選後展開該子任務的進度 slider
          子任務 slider 同時更新子任務本身與主任務的剩餘時間
    """

    def __init__(self, parent_app, block, task_map: Dict, today: date, on_done):
        super().__init__(parent_app)
        self.title("Block Complete")
        self.geometry("500x620")
        self.resizable(False, True)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app      = parent_app
        self._block    = block
        self._task_map = task_map
        self._today    = today
        self._on_done  = on_done

        # task_id -> (pct_var, total_mins, rem_lbl)
        self._task_sliders: Dict[int, tuple] = {}
        # subtask_id -> (check_var, pct_var, frame, rem_lbl, estimated_mins, task_id)
        self._sub_sliders: Dict[int, tuple] = {}
        # subtask_id -> 本次 dialog 開啟時的初始完成 %（取消勾選時還原用）
        self._sub_init_pct: Dict[int, float] = {}

        self._build()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _task_remaining(self, t_id: int) -> float:
        """主任務目前的剩餘分鐘（由 slider % 換算）。"""
        pct_var, total_mins, _ = self._task_sliders[t_id]
        return round(total_mins * (1.0 - pct_var.get() / 100.0), 1)

    def _sub_remaining(self, st_id: int) -> float:
        """子任務目前的剩餘分鐘（由 slider % 換算）。"""
        _, pct_var, _, _, est_mins, _ = self._sub_sliders[st_id]
        return round(est_mins * (1.0 - pct_var.get() / 100.0), 1)

    def _refresh_task_rem_label(self, t_id: int):
        pct_var, total_mins, info_lbl = self._task_sliders[t_id]
        rem = self._task_remaining(t_id)
        info_lbl.configure(text=f"  ({total_mins:.0f}m / {rem:.0f}m)")

    def _refresh_sub_rem_label(self, st_id: int):
        _, _, _, rem_lbl, est_mins, _ = self._sub_sliders[st_id]
        rem = self._sub_remaining(st_id)
        rem_lbl.configure(text=f"({est_mins:.0f}m / {rem:.0f}m)")

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self):
        heading(self, "Block finished — Update your progress",
                size=15).pack(pady=(20, 4), padx=20, anchor="w")
        body_label(self,
                   "Main slider: overall task progress.  "
                   "Check a sub-task to set its individual progress.",
                   color=T2, size=12).pack(padx=20, anchor="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=12)

        for sl in self._block.task_slices:
            t = self._task_map.get(sl["task_id"])
            if not t or t.completed:
                continue

            total_mins = max(1.0, t.time_allocation * 60)
            # 預設：把這個 block 分配的時間當作已花掉，換算成完成 %
            new_rem = max(0.0, t.remaining_minutes - sl["minutes"])
            init_pct = min(100.0, (total_mins - new_rem) / total_mins * 100)

            # ── 任務標題（顯示 總時間 / 剩餘時間）─────────────────────────
            title_row = ctk.CTkFrame(scroll, fg_color="transparent")
            title_row.pack(fill="x", pady=(16, 2))
            ctk.CTkLabel(title_row, text=t.name,
                         font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=T1).pack(side="left")
            time_info_lbl = body_label(
                title_row,
                f"  ({t.time_allocation*60:.0f}m / {new_rem:.0f}m)",
                color=T2, size=12)
            time_info_lbl.pack(side="left")

            # ── 主任務 slider 列 ──────────────────────────────────────────
            task_row = ctk.CTkFrame(scroll, fg_color="transparent")
            task_row.pack(fill="x", padx=8, pady=(0, 2))

            pct_var = tk.DoubleVar(value=init_pct)
            pct_lbl = body_label(task_row, f"{int(init_pct)}%", color=T1, size=12)
            pct_lbl.pack(side="right", padx=(6, 0))

            # rem_lbl 同步更新 title_row 的時間顯示
            self._task_sliders[t.id] = (pct_var, total_mins, time_info_lbl)

            def _make_task_cmd(t_id, p_lbl):
                def cmd(v):
                    p_lbl.configure(text=f"{int(float(v))}%")
                    self._refresh_task_rem_label(t_id)
                return cmd

            ctk.CTkSlider(task_row, from_=0, to=100,
                          variable=pct_var, button_color=T1,
                          progress_color=T1,
                          command=_make_task_cmd(t.id, pct_lbl)
                          ).pack(side="left", fill="x", expand=True)

            # ── 子任務區 ──────────────────────────────────────────────────
            if not t.subtasks:
                continue

            sub_container = ctk.CTkFrame(scroll, fg_color="transparent")
            sub_container.pack(fill="x", padx=16, pady=(4, 8))

            for st in t.subtasks:
                if st.completed:
                    continue

                st_est    = max(1.0, st.estimated_minutes)
                check_var = tk.BooleanVar(value=False)

                # 子任務外層 row（checkbox + 名稱 + 總時間/剩餘時間）
                st_row = ctk.CTkFrame(sub_container, fg_color="transparent")
                st_row.pack(fill="x", pady=(6, 0))

                # 用已存在 DB 的 remaining_minutes 換算初始進度
                st_cur_rem = st.remaining_minutes if st.remaining_minutes >= 0 else st_est
                st_init_pct = min(100.0, max(0.0, (1.0 - st_cur_rem / st_est) * 100))

                st_rem_lbl = body_label(st_row,
                                        f"({st_est:.0f}m / {st_cur_rem:.0f}m)",
                                        color=T2, size=11)
                st_rem_lbl.pack(side="right")

                st_pct_var = tk.DoubleVar(value=st_init_pct)

                # slider frame（初始隱藏）—— 緊接在 st_row 正下方
                sl_frame = ctk.CTkFrame(sub_container,
                                        fg_color=TIMER_BG, corner_radius=8)

                # 記錄到 dict
                self._sub_sliders[st.id] = (
                    check_var, st_pct_var, sl_frame, st_rem_lbl, st_est, t.id)
                self._sub_init_pct[st.id] = st_init_pct

                def _make_check_cmd(st_id, sl_fr, st_rw):
                    def on_toggle():
                        if self._sub_sliders[st_id][0].get():
                            # 展開：插入在 st_row 正下方
                            sl_fr.pack(in_=sub_container, fill="x",
                                       pady=(2, 4), padx=4,
                                       after=st_rw)
                        else:
                            sl_fr.pack_forget()
                            # 取消勾選 → slider 回到本次 dialog 的初始進度
                            init_pct = self._sub_init_pct.get(st_id, 0.0)
                            self._sub_sliders[st_id][1].set(init_pct)
                            self._refresh_sub_rem_label(st_id)
                            
                        # 🛡️ 修正：不論勾選或取消，都要重新計算「本次新增消耗的 Delta」並重推主任務
                        t_id2 = self._sub_sliders[st_id][5]
                        delta_consumed = 0.0
                        for sid2, data2 in self._sub_sliders.items():
                            c2, p2, _, _, se2, tid2b = data2
                            if tid2b == t_id2 and c2.get():
                                init_p = self._sub_init_pct.get(sid2, 0.0)
                                delta_consumed += se2 * ((p2.get() - init_p) / 100.0)
                                
                        t2 = self._task_map.get(t_id2)
                        if t2:
                            _, t_tot3, _ = self._task_sliders[t_id2]
                            new_rem3 = max(0.0, t2.remaining_minutes - delta_consumed)
                            new_pct3 = min(100.0, (t_tot3 - new_rem3) / t_tot3 * 100)
                            self._task_sliders[t_id2][0].set(new_pct3)
                            self._refresh_task_rem_label(t_id2)
                    return on_toggle
                
                cb = ctk.CTkCheckBox(
                    st_row,
                    text=f"{st.name}",
                    variable=check_var,
                    command=_make_check_cmd(st.id, sl_frame, st_row),
                    font=ctk.CTkFont(size=12), text_color=T1, fg_color=T1)
                cb.pack(side="left")

                # slider frame 內容（% 標籤 + slider）
                sl_inner = ctk.CTkFrame(sl_frame, fg_color="transparent")
                sl_inner.pack(fill="x", padx=8, pady=6)

                st_pct_lbl = body_label(sl_inner, f"{int(st_init_pct)}%", color=T1, size=11)
                st_pct_lbl.pack(side="right", padx=(6, 0))

                def _make_sub_pct_cmd(st_id, p_lbl, t_id, s_est, t_tot):
                    def cmd(v):
                        p_lbl.configure(text=f"{int(float(v))}%")
                        self._refresh_sub_rem_label(st_id)
                        
                        # 🛡️ 修正：重推主任務 (計算本次新增消耗的 Delta)
                        delta_consumed = 0.0
                        for sid2, data2 in self._sub_sliders.items():
                            c2, p2, _, _, se2, tid2 = data2
                            if tid2 == t_id and c2.get():
                                init_p = self._sub_init_pct.get(sid2, 0.0)
                                delta_consumed += se2 * ((p2.get() - init_p) / 100.0)
                                
                        t_obj = self._task_map.get(t_id)
                        if t_obj:
                            new_rem2 = max(0.0, t_obj.remaining_minutes - delta_consumed)
                            new_pct2 = min(100.0, (t_tot - new_rem2) / t_tot * 100)
                            self._task_sliders[t_id][0].set(new_pct2)
                            self._refresh_task_rem_label(t_id)
                    return cmd
                
                ctk.CTkSlider(
                    sl_inner, from_=0, to=100,
                    variable=st_pct_var,
                    button_color=T1, progress_color=T1,
                    command=_make_sub_pct_cmd(
                        st.id, st_pct_lbl, t.id, st_est, total_mins)
                ).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(self, text="Save & Continue",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=40,
                      command=self._save).pack(pady=16, padx=20, fill="x")

    # ── save ──────────────────────────────────────────────────────────────────

    def _save(self):
        for sl in self._block.task_slices:
            t = self._task_map.get(sl["task_id"])
            if not t or t.completed:
                continue

            has_checked_subs = any(
                data[0].get() and data[5] == t.id
                for data in self._sub_sliders.values()
            )

            if has_checked_subs:
                # ── 🛡️ 修正：子任務優先，依各子任務 slider 計算「本次新增消耗 Delta」，扣主任務 ──────
                delta_consumed = 0.0
                for st_id, data in self._sub_sliders.items():
                    check_var, pct_var, _, _, est_mins, t_id = data
                    if t_id != t.id or not check_var.get():
                        continue
                    
                    init_p = self._sub_init_pct.get(st_id, 0.0)
                    delta_consumed += est_mins * ((pct_var.get() - init_p) / 100.0)
                    
                    done_mins = est_mins * (pct_var.get() / 100.0)
                    st_rem = max(0.0, est_mins - done_mins)
                    st_obj = next((s for s in t.subtasks if s.id == st_id), None)
                    
                    if pct_var.get() >= 99.0:
                        # 完成：標記完成，remaining 歸零
                        if st_obj:
                            db.mark_subtask_complete(st_id, est_mins)
                            st_obj.completed = True
                            st_obj.remaining_minutes = 0.0
                    else:
                        # 部分完成：寫入剩餘時間
                        db.update_subtask_remaining(st_id, st_rem)
                        if st_obj:
                            st_obj.remaining_minutes = st_rem

                new_rem = max(0.0, t.remaining_minutes - delta_consumed)
            else:
                # ── 無子任務勾選：直接用主任務 slider ────────────────────
                pct_var, total_mins, _ = self._task_sliders[t.id]
                new_rem = total_mins * (1.0 - pct_var.get() / 100.0)

            # 🛡️ 防呆修正：降低強制歸零門檻，避免測試時微小任務(如5分鐘)提早被結案
            if new_rem < 0.1:
                new_rem = 0.0

            t.remaining_minutes = new_rem
            db.update_remaining_minutes(t.id, new_rem)

            # 判斷主任務是否全部完成: 必須是「有子任務且全做完」或「剩餘時間歸零」
            all_subs_done = bool(t.subtasks) and all(s.completed for s in t.subtasks)
            if new_rem == 0.0 or all_subs_done:
                t.remaining_minutes = 0.0
                db.update_remaining_minutes(t.id, 0.0)
                scheduler.recalculate_after_completion(t.id, self._today)
                t.completed = True

        self.destroy()
        self._on_done()


# ── Dead-mascot dialog (impossible schedule) ───────────────────────────────────

class DeadMascotDialog(ctk.CTkToplevel):  #Claude修正
    """GUI counterpart of the terminal planner's DEAD_MASCOT screen.  #Claude修正

    Shown when scheduler.allocate_weekly() raises PomodoroDebtError — i.e. the
    requested work physically cannot fit before its deadline. This mirrors
    weekly_planner.py's terminal behaviour (clear screen + print DEAD_MASCOT)
    inside the customtkinter GUI so the desktop app reacts the same way.
    """

    def __init__(self, app, message: str):  #Claude修正
        super().__init__(app)
        self.title("Pomodoro Debt Exceeded")
        self.geometry("600x600")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.grab_set()
        self._build(message)

    def _build(self, message: str):
        wrap = ctk.CTkScrollableFrame(self, fg_color=BG,
                                      scrollbar_button_color=BORDER)
        wrap.pack(fill="both", expand=True, padx=24, pady=(22, 12))

        heading(wrap, "Schedule Impossible", size=20).pack(anchor="center",
                                                            pady=(2, 10))

        # ASCII mascot rendered in a monospace font so the art stays aligned.
        ctk.CTkLabel(wrap, text=DEAD_MASCOT, justify="left",
                     font=ctk.CTkFont(family="Courier New", size=12),
                     text_color=ERR_CLR).pack(anchor="center", pady=(0, 14))

        card = card_frame(wrap)
        card.pack(fill="x")
        body_label(card,
                   "This workload cannot be finished before the deadline.",
                   color=T1, size=13).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(card, text=message, font=ctk.CTkFont(size=12),
                     text_color=ERR_CLR, wraplength=500,
                     justify="left").pack(anchor="w", padx=16, pady=(0, 6))
        body_label(card,
                   "Tip: push the deadline back, lower the estimated hours, "
                   "or spread the task across more days.",
                   color=T2, size=11).pack(anchor="w", padx=16, pady=(0, 14))

        ctk.CTkButton(self, text="Got it — let me adjust",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=42,
                      command=self.destroy).pack(pady=(0, 18), padx=24, fill="x")


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
                           f"({t.time_allocation*60:.0f}m / {t.remaining_minutes:.0f}m)",
                           color=ERR_CLR).pack(anchor="w", padx=20)

            self._carry_var = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(self, text="Carry incomplete tasks to tomorrow",
                            variable=self._carry_var,
                            font=ctk.CTkFont(size=12), text_color=T1,
                            fg_color=T1).pack(pady=(14, 4), padx=20, anchor="w")

        body_label(self, f"Total focus today:  {self._focus}m",
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
        # 移除 IntVar，直接將 Slider 存成變數
        self._focus_slider = ctk.CTkSlider(
            focus_col, from_=5, to=120, number_of_steps=23,
            button_color=T1, progress_color=T1, button_hover_color=SIDE_SEL,
            command=self._on_focus_change
        )
        self._focus_slider.set(50)  # 手動設定預設值為 50
        self._focus_slider.pack(fill="x")

        # Break slider
        brk_col = ctk.CTkFrame(row1, fg_color="transparent")
        brk_col.pack(side="left", expand=True, fill="x")
        self._brk_lbl = body_label(brk_col, "Break: 10m", size=12, color=T2)
        self._brk_lbl.pack(anchor="w")
        # 移除 IntVar，直接將 Slider 存成變數
        self._brk_slider = ctk.CTkSlider(
            brk_col, from_=1, to=30, number_of_steps=29,
            button_color=T1, progress_color=T1, button_hover_color=SIDE_SEL,
            command=self._on_brk_change
        )
        self._brk_slider.set(10)  # 手動設定預設值為 10
        self._brk_slider.pack(fill="x")

        row2 = ctk.CTkFrame(cfg, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 12))
        body_label(row2, "Mode:", size=12, color=T2).pack(side="left", padx=(0, 8))
        
        self._mode_var = ctk.StringVar(value="Chunk")
        self._mode_btn = ctk.CTkSegmentedButton(
            row2, values=["Chunk", "Sandwich"],
            variable=self._mode_var,
            font=ctk.CTkFont(size=12),
            selected_color=T1, selected_hover_color=SIDE_SEL,
            unselected_color=BORDER, text_color="#FFF",
            unselected_hover_color=ARC_BG
        )
        self._mode_btn.pack(side="left")

        # ---- 最小切片時間元件 ----
        min_slice_label = ctk.CTkLabel(cfg, text="Min Slice (min):", font=ctk.CTkFont(family="Arial", size=12), text_color=T2)
        min_slice_label.pack(side="left", padx=(15, 5))
        
        # 🛡️ 移除 StringVar，直接對 Entry 操作
        self._min_slice_entry = ctk.CTkEntry(cfg, width=50, justify="center")
        self._min_slice_entry.insert(0, "10")  # 手動填入預設值
        self._min_slice_entry.pack(side="left", padx=5)

        # ── Timer card ────────────────────────────────────────────────────
        timer_card = card_frame(self)
        timer_card.configure(fg_color=TIMER_BG)
        timer_card.pack(fill="both", expand=True, padx=0, pady=(0, 14))

        # 1. 計時器圖形排在最上方
        self._canvas = TimerCanvas(timer_card)
        self._canvas.pack(pady=(24, 8))

        self._block_lbl = body_label(timer_card, "", color=T2, size=12)
        self._block_lbl.pack(pady=(0, 16))

        # 2. 把按鈕移到計時器正下方，保證絕對不會被擠出畫面
        btn_row = ctk.CTkFrame(timer_card, fg_color="transparent")
        btn_row.pack(pady=(0, 16))

        self._start_btn = ctk.CTkButton(
            btn_row, text=">  Start", width=120, height=38,
            fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
            font=ctk.CTkFont(size=13), corner_radius=20,
            command=self._on_start)
        self._start_btn.pack(side="left", padx=6)

        self._pause_btn = ctk.CTkButton(
            btn_row, text="||  Pause", width=100, height=38,
            fg_color=CARD, hover_color=ARC_BG, text_color=T1,
            font=ctk.CTkFont(size=13), corner_radius=20,
            border_width=1, border_color=BORDER,
            command=self._on_pause, state="disabled")
        self._pause_btn.pack(side="left", padx=6)

        self._stop_btn = ctk.CTkButton(
            btn_row, text="x  Stop", width=90, height=38,
            fg_color=CARD, hover_color="#FDEAEA", text_color=ERR_CLR,
            font=ctk.CTkFont(size=13), corner_radius=20,
            border_width=1, border_color="#E8CECE",
            command=self._on_stop, state="disabled")
        self._stop_btn.pack(side="left", padx=6)

        # 3. 任務卡片容器排在最後面，填滿剩餘空間
        self._task_list_frame = ctk.CTkFrame(timer_card, fg_color="transparent")
        self._task_list_frame.pack(fill="both", expand=True, padx=30, pady=(0, 16))

    # ── Slider callbacks ──────────────────────────────────────────────────
    def _on_focus_change(self, v):
        v = int(v)
        self._focus_lbl.configure(text=f"Focus: {v}m")
        auto_brk = max(5, v // 5)
        # 🛡️ 效能防火牆：只有當休息時間「真的改變時」，才去操作另一個拉桿
        current_brk = int(self._brk_slider.get())
        if current_brk != auto_brk:
            self._brk_slider.set(auto_brk)
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
        
        # 修正：精準過濾，只允許「還存在於未完成清單 (task_map) 中」的任務進入排程
        slices = [
            {"task_id": e["task_id"], "minutes": e["allocated_minutes"]}
            for e in schedule
            if e["task_id"] in task_map
        ]
        
        # 依據 priority_score 由高到低進行排序，確保緊急任務優先排入區塊
        slices.sort(key=lambda s: task_map[s["task_id"]].priority_score, reverse=True)

        if not slices:
            messagebox.showinfo("All Done", "All of today's tasks are complete!")
            return
        
        # 改為向 slider 直接要數字
        focus  = int(self._focus_slider.get())
        brk    = int(self._brk_slider.get())
        
        mode_val = self._mode_var.get()
        mode = SplitMode.CHUNK if mode_val == "Chunk" else SplitMode.SANDWICH
        
        # 🛡️ 改為向 Entry 元件直接要字串
        try:
            min_slice = int(self._min_slice_entry.get().strip())
            if min_slice <= 0:
                min_slice = 10
        except ValueError:
            min_slice = 10
        
        # 🛡️ 終極無條件攔截：只要 Min Slice 大於 Focus，管你什麼模式一律當場逮捕！
        if min_slice > focus:
            messagebox.showwarning(
                "設定衝突", 
                f"最小切片 (Min Slice: {min_slice}m) 不能大於 專注時間 (Focus: {focus}m)！\n"
                f"💡 請調整設定，確保 Focus 必須大於或等於 Min Slice。"
            )
            return

        blocks = scheduler.build_daily_blocks(slices, focus, brk, mode, min_slice_minutes=min_slice)
        
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

        # ── 新增：提早結束時，跳出結算畫面讓你儲存進度 ──
        if getattr(self._app, "_in_break", False) == False:
            try:
                b = self._app._blocks[self._app._block_idx]
                
                # 將這回合的時間換算成「實際經過的時間」
                # (為了方便測試，就算秒按 Stop 也給個保底 1 分鐘，讓你看到拉桿效果)
                actual_mins = max(1, self._app._elapsed_s // 60)
                for sl in b.task_slices:
                    sl["minutes"] = actual_mins

                # 跳出結算視窗，結算完後直接重置畫面 (不再進入休息時間)
                def _after_completion():
                    self.reset_display()
                    self._app._daily_view.refresh()
                    self._app._weekly_view.refresh()
                self.on_block_end(b, self._app._task_map, self._app.today, _after_completion)
            except Exception:
                self.reset_display()
        else:
            self.reset_display()

    # ── Called by App timer engine ────────────────────────────────────────
    def update_display(self, remaining_s: int, progress: float, is_break: bool, is_paused: bool = False):
        label = "break" if is_break else "focus"
        self._canvas.update(remaining_s, progress, label, is_break, is_paused)

    def on_block_start(self, idx: int, total: int, block, task_map: Dict,
                       is_break: bool):
        self._block_lbl.configure(
            text=f"{'Break' if is_break else 'Block'} {idx+1} / {total}")
            
        # 清除舊的任務卡片
        for w in self._task_list_frame.winfo_children():
            w.destroy()
            
        if not is_break:
            # 動態生成與 Daily/Weekly 風格一致的塊狀卡片
            for s in block.task_slices:
                if s["task_id"] in task_map:
                    t = task_map[s["task_id"]]
                    mins = s["minutes"]
                    
                    # 建立卡片，帶入艾森豪矩陣的優先序顏色
                    card = card_frame(self._task_list_frame)
                    card.configure(fg_color=QUAD_CLR.get(t.quadrant.value, CARD))
                    card.pack(fill="x", pady=3)
                    
                    inner = ctk.CTkFrame(card, fg_color="transparent")
                    inner.pack(fill="x", padx=12, pady=6)
                    
                    body_label(inner, t.name, size=12, color=T1).pack(side="left")
                    body_label(inner, f"{mins:.0f}m", size=12, color=T2).pack(side="right")
        else:
            # 休息時間顯示
            lbl = body_label(self._task_list_frame, "Rest up", justify="center")
            lbl.pack(pady=10)

    def on_block_end(self, block, task_map: Dict, today: date, on_done):
        CompletionDialog(self._app, block, task_map, today, on_done)

    def reset_display(self):
        self._canvas.reset()
        self._block_lbl.configure(text="")
        
        # 清空卡片容器
        for w in self._task_list_frame.winfo_children():
            w.destroy()
            
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

        # Right: timer (🛡️ 終極解法：改成普通 Frame，徹底阻斷無限迴圈)
        right = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ② 修改 DailyView._task_row()
#    完整取代原本第 598–625 行的 _task_row 方法。
#    唯一改動：右側加一個「⋯」按鈕，點擊後開啟 EditTaskDialog。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _task_row(self, t: Task):
        row = card_frame(self._task_scroll)
        row.configure(fg_color=QUAD_CLR.get(t.quadrant.value, CARD))  #Claude修正
        row.pack(fill="x", pady=3)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)

        mark  = "✓" if t.completed else "○"
        color = OK_CLR if t.completed else T1
        body_label(inner, f"{mark}  {t.name}", color=color,
                   size=13).pack(side="left")

        right_info = ctk.CTkFrame(inner, fg_color="transparent")
        right_info.pack(side="right")

        # ── 新增：編輯按鈕 ────────────────────────────────────────────────
        ctk.CTkButton(
            right_info, text="⋯", width=28, height=24,
            fg_color="transparent", hover_color=ARC_BG,
            text_color=T2, font=ctk.CTkFont(size=14),
            corner_radius=6,
            command=lambda task=t: EditTaskDialog(
                self._app, task, self.refresh),
        ).pack(side="right", padx=(6, 0))
        # ─────────────────────────────────────────────────────────────────

        body_label(right_info,
                   f"({format_hm(t.time_allocation*60)} / {format_hm(t.remaining_minutes)})  ·  "
                   f"dl {t.deadline.strftime('%b %d')}",
                   color=T2, size=11).pack(side="right")

        # Subtasks（原本邏輯不變）
        if t.subtasks:
            for st in t.subtasks:
                sc = OK_CLR if st.completed else T2
                sm = "✓" if st.completed else "·"
                body_label(row, f"     {sm}  {st.name}  "
                           f"({format_hm(st.estimated_minutes)} / {format_hm(st.remaining_minutes)})",
                           color=sc, size=11).pack(anchor="w",
                                                    padx=16, pady=1)
            ctk.CTkFrame(row, height=6, fg_color="transparent").pack()


    def _add_adhoc(self):
        AdhocDialog(self._app, self._app.today, self.refresh)


# ── Adhoc Dialog ──────────────────────────────────────────────────────────────

# ── Adhoc Dialog ──────────────────────────────────────────────────────────────

class AdhocDialog(ctk.CTkToplevel):
    def __init__(self, app, today: date, on_done):
        super().__init__(app)
        self.title("Add Ad-Hoc Task")
        self.geometry("460x580")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app     = app
        self._today   = today
        self._on_done = on_done
        self._subtasks: List[Dict] = []
        self._build()

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        heading(scroll, "New Ad-Hoc Task", size=16).pack(pady=(0, 4), anchor="w")
        body_label(scroll, "Added directly to today's schedule.", color=T2, size=12).pack(anchor="w")
        Divider(scroll).pack(fill="x", pady=12)

        section_label(scroll, "TASK NAME").pack(anchor="w")
        self._name = ctk.CTkEntry(scroll, height=36, font=ctk.CTkFont(size=13),
                                   fg_color=CARD, border_color=BORDER, text_color=T1)
        self._name.pack(fill="x", pady=(2, 10))

        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        col1 = ctk.CTkFrame(row, fg_color="transparent")
        col1.pack(side="left", expand=True, fill="x", padx=(0, 8))
        section_label(col1, "HOURS").pack(anchor="w")
        self._hours = ctk.CTkEntry(col1, height=36, font=ctk.CTkFont(size=13),
                                    placeholder_text="e.g. 1.5",
                                    fg_color=CARD, border_color=BORDER, text_color=T1)
        self._hours.pack(fill="x", pady=(2, 0))

        col2 = ctk.CTkFrame(row, fg_color="transparent")
        col2.pack(side="left", expand=True, fill="x")
        section_label(col2, "URGENCY").pack(anchor="w")
        self._urg_var = tk.IntVar(value=3)
        self._urg_lbl = body_label(col2, "3 / 5", color=T2, size=11)
        self._urg_lbl.pack(anchor="w")
        ctk.CTkSlider(col2, from_=1, to=5, number_of_steps=4, variable=self._urg_var, 
                      button_color=T1, progress_color=T1,
                      command=lambda v: self._urg_lbl.configure(text=f"{int(v)} / 5")).pack(fill="x")

        section_label(scroll, "IMPORTANCE").pack(anchor="w", pady=(6, 0))
        self._imp_var = tk.IntVar(value=3)
        self._imp_lbl = body_label(scroll, "3 / 5", color=T2, size=11)
        self._imp_lbl.pack(anchor="w")
        ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4, variable=self._imp_var, 
                      button_color=T1, progress_color=T1,
                      command=lambda v: self._imp_lbl.configure(text=f"{int(v)} / 5")).pack(fill="x", pady=(0, 12))

        # ── 子任務輸入區塊 ──
        section_label(scroll, "SUB-TASKS").pack(anchor="w", pady=(4, 0))
        sub_row = ctk.CTkFrame(scroll, fg_color="transparent")
        sub_row.pack(fill="x", pady=(4, 6))
        
        self._sub_entry = ctk.CTkEntry(sub_row, height=32, font=ctk.CTkFont(size=12),
                                        placeholder_text="Sub-task name",
                                        fg_color=CARD, border_color=BORDER, text_color=T1)
        self._sub_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._sub_mins = ctk.CTkEntry(sub_row, width=80, height=32, font=ctk.CTkFont(size=12),
                                       placeholder_text="min",
                                       fg_color=CARD, border_color=BORDER, text_color=T1)
        self._sub_mins.pack(side="left", padx=(0, 6))
        ctk.CTkButton(sub_row, text="+", width=32, height=32, fg_color=T1, hover_color=SIDE_SEL, 
                      text_color="#FFF", font=ctk.CTkFont(size=14),
                      command=self._add_subtask).pack(side="left")

        self._sub_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._sub_frame.pack(fill="x", pady=(0, 10))

        # Add Task 按鈕留在外層
        ctk.CTkButton(self, text="Add Task", fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=40,
                      command=self._save).pack(pady=16, padx=20, fill="x")
        
    def _add_subtask_row(self):
        """動態新增一行子任務輸入框"""
        row = ctk.CTkFrame(self._subtasks_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)

        # 子任務名稱
        name_ent = ctk.CTkEntry(row, placeholder_text="Subtask name",
                                height=30, fg_color=CARD, border_color=BORDER, text_color=T1)
        name_ent.pack(side="left", expand=True, fill="x", padx=(0, 5))

        # 子任務時間(分鐘)
        min_ent = ctk.CTkEntry(row, placeholder_text="Mins", width=60,
                               height=30, fg_color=CARD, border_color=BORDER, text_color=T1)
        min_ent.pack(side="left")

        # 把這兩個框框記下來，之後 _save 的時候要讀取
        self._subtask_widgets.append((name_ent, min_ent))

    def _auto_adjust_hours(self):
        """新增：自動偵測子任務時間並調高大任務時間的防呆機制"""
        total_sub_mins = sum(s["minutes"] for s in self._subtasks)
        try:
            current_hours = float(self._hours.get())
        except ValueError:
            current_hours = 0.0
            
        if total_sub_mins > current_hours * 60:
            new_hours = round(total_sub_mins / 60.0, 1)
            self._hours.delete(0, "end")
            self._hours.insert(0, str(new_hours))

    def _remove_subtask_new(self, index: int):
        """新增任務 dialog 中刪除尚未儲存的子任務。"""
        if 0 <= index < len(self._subtasks):
            self._subtasks.pop(index)
        self._refresh_sub_frame()

    def _refresh_sub_frame(self):
        for w in self._sub_frame.winfo_children():
            w.destroy()
        for i, s in enumerate(self._subtasks):
            row = ctk.CTkFrame(self._sub_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            body_label(row, f"  ·  {s['name']}  ({s['minutes']:.0f}m)",
                       color=T2, size=12).pack(side="left")
            ctk.CTkButton(
                row, text="✕", width=24, height=24,
                fg_color="transparent", hover_color=ERR_CLR,
                text_color=T2, font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._remove_subtask_new(idx)
            ).pack(side="right")

    def _add_subtask(self):
        name = self._sub_entry.get().strip()
        mins_raw = self._sub_mins.get().strip()
        if not name: return
        try: mins = float(mins_raw)
        except ValueError: mins = 30.0
            
        self._subtasks.append({"name": name, "minutes": mins})
        self._refresh_sub_frame()
        self._sub_entry.delete(0, "end")
        self._sub_mins.delete(0, "end")
        
        # 呼叫防呆
        self._auto_adjust_hours()

    def _save(self):
        name = self._name.get().strip()
        if not name:
            from tkinter import messagebox
            messagebox.showwarning("Missing", "Task name is required.", parent=self)
            return
            
        total_sub_mins = sum(s["minutes"] for s in self._subtasks)
        try:
            hours = float(self._hours.get())
        except ValueError:
            from tkinter import messagebox
            messagebox.showwarning("Invalid", "Hours must be a number.", parent=self)
            return

        # 子任務總時間驗證（儲存時阻擋）
        if total_sub_mins > hours * 60:
            messagebox.showwarning(
                "Sub-task Time Exceeded",
                f"Sub-task total ({total_sub_mins:.0f}m) exceeds task time ({hours*60:.0f}m).\n"
                f"Please increase task hours or reduce sub-task times.",
                parent=self)
            return

        week_start = self._app.week_start
        existing   = db.task_in_week_by_name(name, week_start)
        if existing:
            if not messagebox.askyesno("Duplicate", f"'{name}' already exists this week.\nAdd as a separate task anyway?", parent=self):
                self.destroy()
                return

        urg  = int(self._urg_var.get())
        imp  = int(self._imp_var.get())
        q    = scheduler.classify_quadrant(urg, imp)
        sc   = scheduler.compute_priority_score(urg, imp, q, self._today)
        
        # 💡 自動校正：如果子任務加起來超過原本設定的小時數，就以子任務為主
        final_minutes = hours * 60
        final_hours = hours
        if total_sub_mins > final_minutes:
            final_minutes = total_sub_mins
            final_hours = final_minutes / 60.0

        # 注意：這裡使用了 final_hours 和 final_minutes
        task = Task(id=None, name=name, urgency=urg, importance=imp,
                    time_allocation=final_hours, remaining_minutes=final_minutes,
                    deadline=self._today, quadrant=q, priority_score=sc,
                    source="adhoc", week_start=week_start, notes="")
        tid  = db.insert_task(task)
        
        for i, s in enumerate(self._subtasks):
            db.insert_subtask(Subtask(id=None, task_id=tid, name=s["name"],
                                      estimated_minutes=s["minutes"], order_index=i))

        db.insert_schedule_entry(week_start, self._today, tid, hours * 60)
        self.destroy()
        self._on_done()


# ── Edit Task Dialog ──────────────────────────────────────────────────────────

class EditTaskDialog(ctk.CTkToplevel):
    def __init__(self, app, task: Task, on_done):
        super().__init__(app)
        self.title("Edit Task")
        self.geometry("460x620")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app     = app
        self._task    = task
        self._on_done = on_done
        
        self._subtasks_state = []
        if self._task.subtasks:
            for st in self._task.subtasks:
                self._subtasks_state.append({
                    "id": st.id, "name": st.name, "minutes": st.estimated_minutes,
                    "completed": st.completed, "status": "keep"
                })
        self._build()

    def _build(self):
        heading(self, "Edit Task", size=16).pack(pady=(20, 2), padx=20, anchor="w")
        body_label(self, self._task.name, color=T2, size=12).pack(padx=20, anchor="w")
        Divider(self).pack(fill="x", padx=20, pady=(12, 0))

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=10)

        section_label(scroll, "TASK NAME").pack(anchor="w")
        self._name = ctk.CTkEntry(scroll, height=36, font=ctk.CTkFont(size=13),
                                   fg_color=CARD, border_color=BORDER, text_color=T1)
        self._name.insert(0, self._task.name)
        self._name.pack(fill="x", pady=(2, 12))

        section_label(scroll, "ESTIMATED HOURS").pack(anchor="w")
        self._hours = ctk.CTkEntry(scroll, height=36, font=ctk.CTkFont(size=13),
                                    fg_color=CARD, border_color=BORDER, text_color=T1)
        self._hours.insert(0, f"{self._task.time_allocation:g}")
        self._hours.pack(fill="x", pady=(2, 12))

        section_label(scroll, "URGENCY").pack(anchor="w")
        self._urg_var = tk.IntVar(value=self._task.urgency)
        self._urg_lbl = body_label(scroll, f"{self._task.urgency} / 5", color=T2, size=11)
        self._urg_lbl.pack(anchor="w")
        ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4, variable=self._urg_var, 
                      button_color=T1, progress_color=T1,
                      command=lambda v: self._urg_lbl.configure(text=f"{int(v)} / 5")).pack(fill="x", pady=(0, 12))

        section_label(scroll, "IMPORTANCE").pack(anchor="w")
        self._imp_var = tk.IntVar(value=self._task.importance)
        self._imp_lbl = body_label(scroll, f"{self._task.importance} / 5", color=T2, size=11)
        self._imp_lbl.pack(anchor="w")
        ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4, variable=self._imp_var, 
                      button_color=T1, progress_color=T1,
                      command=lambda v: self._imp_lbl.configure(text=f"{int(v)} / 5")).pack(fill="x", pady=(0, 16))

        # ── 子任務區塊 (修正排版避免空白撐大) ──
        section_label(scroll, "SUB-TASKS").pack(anchor="w", pady=(4, 0))

        sub_row = ctk.CTkFrame(scroll, fg_color="transparent")
        sub_row.pack(fill="x", pady=(4, 6))
        self._sub_entry = ctk.CTkEntry(sub_row, height=32, font=ctk.CTkFont(size=12),
                                        placeholder_text="Sub-task name",
                                        fg_color=CARD, border_color=BORDER, text_color=T1)
        self._sub_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._sub_mins = ctk.CTkEntry(sub_row, width=80, height=32, font=ctk.CTkFont(size=12),
                                       placeholder_text="min",
                                       fg_color=CARD, border_color=BORDER, text_color=T1)
        self._sub_mins.pack(side="left", padx=(0, 6))

        ctk.CTkButton(sub_row, text="+", width=32, height=32, fg_color=T1, hover_color=SIDE_SEL, 
                      text_color="#FFF", font=ctk.CTkFont(size=14),
                      command=self._add_subtask).pack(side="left")

        self._sub_list_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._sub_list_frame.pack(fill="x", pady=(0, 10))
        self._render_subtasks()

        # ── 底部按鈕 ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(4, 16))

        ctk.CTkButton(btn_row, text="Save Changes", fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=40, corner_radius=8,
                      command=self._save).pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(btn_row, text="Delete", fg_color=CARD, hover_color="#FDEAEA", text_color=ERR_CLR,
                      border_width=1, border_color="#E8CECE",
                      font=ctk.CTkFont(size=13), height=40, corner_radius=8,
                      command=self._delete).pack(side="left", expand=True, fill="x", padx=(6, 0))

    def _render_subtasks(self):
        for w in self._sub_list_frame.winfo_children():
            w.destroy()

        for idx, s in enumerate(self._subtasks_state):
            if s["status"] == "delete": continue
            row = ctk.CTkFrame(self._sub_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            sm = "✓" if s["completed"] else "·"
            color = OK_CLR if s["completed"] else T1
            body_label(row, f"  {sm}  {s['name']}  ({s['minutes']:.0f}m)", color=color, size=12).pack(side="left")

            if not s["completed"]:
                del_btn = ctk.CTkButton(row, text="✕", width=24, height=24,
                                        fg_color="transparent", hover_color="#FDEAEA", text_color=ERR_CLR,
                                        font=ctk.CTkFont(size=12), corner_radius=4,
                                        command=lambda i=idx: self._remove_subtask(i))
                del_btn.pack(side="right")

    def _auto_adjust_hours(self):
        """新增：自動偵測子任務時間並調高大任務時間的防呆機制"""
        total_sub_mins = sum(s["minutes"] for s in self._subtasks_state if s["status"] != "delete")
        try:
            current_hours = float(self._hours.get())
        except ValueError:
            current_hours = 0.0
            
        if total_sub_mins > current_hours * 60:
            new_hours = round(total_sub_mins / 60.0, 1)
            self._hours.delete(0, "end")
            self._hours.insert(0, str(new_hours))

    def _add_subtask(self):
        name = self._sub_entry.get().strip()
        mins_raw = self._sub_mins.get().strip()
        if not name: return
        try: mins = float(mins_raw)
        except ValueError: mins = 30.0

        self._subtasks_state.append({
            "id": None, "name": name, "minutes": mins,
            "completed": False, "status": "new"
        })
        self._sub_entry.delete(0, "end")
        self._sub_mins.delete(0, "end")
        self._render_subtasks()
        
        # 呼叫防呆
        self._auto_adjust_hours()

    def _remove_subtask(self, index):
        if self._subtasks_state[index]["id"] is None:
            self._subtasks_state.pop(index)
        else:
            self._subtasks_state[index]["status"] = "delete"
        self._render_subtasks()

    def _save(self):
        name = self._name.get().strip()
        if not name:
            messagebox.showwarning("Missing", "Task name is required.", parent=self)
            return

        total_sub_mins = sum(s["minutes"] for s in self._subtasks_state if s["status"] != "delete")
        try:
            hours = float(self._hours.get())
            if hours < 0.1: raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid", "Hours must be a number >= 0.1.", parent=self)
            return

        # 子任務總時間驗證（儲存時阻擋，不自動調整）
        if total_sub_mins > hours * 60:
            messagebox.showwarning(
                "Sub-task Time Exceeded",
                f"Sub-task total ({total_sub_mins:.0f}m) exceeds task time ({hours*60:.0f}m).\n"
                f"Please increase task hours or reduce sub-task times.",
                parent=self)
            return

        urg = int(self._urg_var.get())
        imp = int(self._imp_var.get())

        old_alloc = self._task.time_allocation
        if hours != old_alloc and old_alloc > 0:
            new_remaining = round(self._task.remaining_minutes * (hours / old_alloc), 1)
        else:
            new_remaining = self._task.remaining_minutes

        new_q     = scheduler.classify_quadrant(urg, imp)
        new_score = scheduler.compute_priority_score(urg, imp, new_q, self._task.deadline)

        db.update_task(task_id=self._task.id, name=name, urgency=urg, importance=imp,
                       time_allocation=hours, remaining_minutes=new_remaining,
                       quadrant=new_q, priority_score=new_score)

        try:
            with db._conn() as conn:
                for s in self._subtasks_state:
                    if s["status"] == "delete" and s["id"] is not None:
                        conn.execute("DELETE FROM subtasks WHERE id=?", (s["id"],))
                    elif s["status"] == "new":
                        db.insert_subtask(Subtask(id=None, task_id=self._task.id, 
                                                  name=s["name"], estimated_minutes=s["minutes"], order_index=0))
        except Exception as e:
            print(f"Error updating subtasks: {e}")

        self.destroy()
        self._on_done()

    def _delete(self):
        confirmed = messagebox.askyesno("Delete Task", f"Delete '{self._task.name}'?\n\nThis cannot be undone.", parent=self)
        if confirmed:
            db.delete_task(self._task.id)
            self.destroy()
            self._on_done()


# ── Difficulty Review Dialog ──────────────────────────────────────────────────

class DifficultyReviewDialog(ctk.CTkToplevel):
    LABELS = {
        0: "輕鬆 (trivially easy)",
        1: "容易 (easy)",
        2: "適中 (about right)",
        3: "稍難 (a bit tough)",
        4: "困難 (hard)",
        5: "極難 (brutal)",
    }

    def __init__(self, app, week_start: date, on_done=None):
        super().__init__(app)
        self.title("上週難度回顧 Difficulty Review")
        self.geometry("520x540")
        self.resizable(False, True)
        self.grab_set()
        self.configure(fg_color=BG)

        self._app        = app
        self._on_done    = on_done
        self._week_start = week_start

        last_week = week_start - timedelta(weeks=1)
        tasks_raw = db.get_tasks_from_week(last_week)

        seen: set = set()
        self._tasks: List[Task] = []
        for t in tasks_raw:
            key = t.name.strip().lower()
            if key not in seen:
                seen.add(key)
                self._tasks.append(t)

        self._vars: Dict[int, tk.IntVar] = {}
        self._build()

    def _build(self):
        if not self._tasks:
            heading(self, "上週沒有找到任務", size=15).pack(pady=40)
            ctk.CTkButton(self, text="關閉", fg_color=T1, hover_color=SIDE_SEL,
                          text_color="#FFF", height=38, command=self.destroy
                          ).pack(padx=24, pady=12, fill="x")
            return

        heading(self, "上週任務難度回顧", size=16).pack(anchor="w", padx=24, pady=(20, 2))
        body_label(self,
                   "替每個任務打一個難度分數，下次新增同名任務時系統會自動建議時數。",
                   color=T2, size=12).pack(anchor="w", padx=24, pady=(0, 4))
        body_label(self, "0 = 超輕鬆  ·  2 = 剛好  ·  5 = 超硬",
                   color=T2, size=11).pack(anchor="w", padx=24, pady=(0, 12))
        Divider(self).pack(fill="x", padx=24, pady=(0, 12))

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG,
                                        scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        for t in self._tasks:
            var = tk.IntVar(value=2)
            self._vars[t.id] = var

            card = card_frame(scroll)
            card.pack(fill="x", pady=5)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=(10, 4))

            name_row = ctk.CTkFrame(inner, fg_color="transparent")
            name_row.pack(fill="x")
            body_label(name_row, t.name, size=13).pack(side="left")
            body_label(name_row, f"  {t.time_allocation}h", color=T2, size=12).pack(side="left")

            diff_lbl = body_label(inner, self.LABELS[2], color=T2, size=11)
            diff_lbl.pack(anchor="w", pady=(2, 4))

            def _make_cmd(lbl, v):
                def cmd(val):
                    score = int(float(val))
                    lbl.configure(text=self.LABELS.get(score, ""))
                    v.set(score)
                return cmd

            ctk.CTkSlider(
                inner, from_=0, to=5, number_of_steps=5,
                variable=var, button_color=T1, progress_color=T1,
                command=_make_cmd(diff_lbl, var)
            ).pack(fill="x", pady=(0, 8))

        Divider(self).pack(fill="x", padx=24, pady=(4, 0))
        ctk.CTkButton(
            self, text="儲存難度回顧",
            fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
            font=ctk.CTkFont(size=13), height=42,
            command=self._save
        ).pack(padx=24, pady=16, fill="x")

    def _save(self):
        last_week = self._week_start - timedelta(weeks=1)
        for t in self._tasks:
            score = self._vars[t.id].get()
            db.log_difficulty(t.name, last_week, score)
        messagebox.showinfo(
            "已儲存",
            f"✓ 已記錄 {len(self._tasks)} 個任務的難度分數。\n"
            f"下次新增同名任務時，系統將自動建議時數。",
            parent=self,
        )
        self.destroy()
        if self._on_done:
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
        ctk.CTkButton(hdr, text="📊 Review", width=100, height=32,
                      fg_color=CARD, hover_color=ARC_BG, text_color=T1,
                      font=ctk.CTkFont(size=12), corner_radius=8,
                      border_width=1, border_color=BORDER,
                      command=self._difficulty_review).pack(side="right", padx=(0, 8))
                      
        self._hours_var = ctk.StringVar(value=f"{self._app.hours_per_day:g}")
        hours_entry = ctk.CTkEntry(hdr, width=55, textvariable=self._hours_var, justify="center")
        hours_entry.pack(side="right", padx=(0, 16))
        hours_label = body_label(hdr, "Default Hrs/Day:", color=T2, size=12)
        hours_label.pack(side="right", padx=4)
        # ── 新增：排程策略切換按鈕 ───────────────────────────────────────
        self._strategy_var = ctk.StringVar(value="Balanced")
        strategy_btn = ctk.CTkSegmentedButton(
            hdr, values=["Deep Work", "Balanced"],
            variable=self._strategy_var,
            font=ctk.CTkFont(size=12),
            selected_color=T1, selected_hover_color=SIDE_SEL,
            unselected_color=BORDER, text_color="#FFF",
            unselected_hover_color=ARC_BG
        )
        strategy_btn.pack(side="right", padx=(0, 16))
        strategy_label = body_label(hdr, "Strategy:", color=T2, size=12)
        strategy_label.pack(side="right", padx=4)

        Divider(self).pack(fill="x", padx=28, pady=12)

        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        body.columnconfigure(0, weight=3) 
        body.columnconfigure(1, weight=1) 
        body.rowconfigure(0, weight=1)

        self._schedule_scroll = ctk.CTkScrollableFrame(
            body, fg_color=BG, scrollbar_button_color=BORDER)
        self._schedule_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        self._task_list_scroll = ctk.CTkScrollableFrame(
            body, fg_color=BG, scrollbar_button_color=BORDER)
        self._task_list_scroll.grid(row=0, column=1, sticky="nsew")

    def _render_task_list(self, tasks):
        """專責繪製右側代辦事項清單，統一排版與視覺層級"""
        for w in self._task_list_scroll.winfo_children():
            w.destroy()
            
        section_label(self._task_list_scroll, "TASKS & DEADLINES").pack(anchor="w", pady=(12, 8))
        
        if not tasks:
            body_label(self._task_list_scroll, "No pending tasks.", color=T2).pack(pady=10)
            return

        tasks_sorted = sorted(tasks, key=lambda x: x.deadline)
        
        for t in tasks_sorted:
            t_card = card_frame(self._task_list_scroll)
            t_card.configure(fg_color=QUAD_CLR.get(t.quadrant.value, CARD))
            t_card.pack(fill="x", pady=4)
            
            # --- 第一列：名稱與靠右對齊的操作按鈕 ---
            top_row = ctk.CTkFrame(t_card, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(8, 2))
            
            body_label(top_row, t.name, size=13).pack(side="left")
            
            btn_frame = ctk.CTkFrame(top_row, fg_color="transparent")
            btn_frame.pack(side="right")
            
            ctk.CTkButton(btn_frame, text="⋯", width=28, height=24,
                          fg_color="transparent", hover_color=ARC_BG, text_color=T2,
                          font=ctk.CTkFont(size=14), corner_radius=6,
                          command=lambda task=t: EditTaskDialog(self._app, task, self.refresh)
            ).pack(side="right")

            toggle_btn = ctk.CTkButton(btn_frame, text="+", width=24, height=24,
                                       fg_color=BORDER, hover_color=ARC_BG, text_color=T1,
                                       font=ctk.CTkFont(size=14, weight="bold"), corner_radius=6)
            toggle_btn.pack(side="right", padx=(0, 4))
            
            # --- 第二列：動態死線顏色與轉換後的時數 ---
            info_row = ctk.CTkFrame(t_card, fg_color="transparent")
            info_row.pack(fill="x", padx=12, pady=(0, 6))
            
            # 動態計算死線壓力顏色
            days_left = (t.deadline - self._app.today).days
            if days_left > 7:
                dl_color = T2              # 灰色 (安全)
            elif days_left > 5:
                dl_color = "#E3B341"       # 橘黃色 (警告)
            else:
                dl_color = ERR_CLR         # 紅色 (緊急)

            dl_str = t.deadline.strftime('%b %d (%a)')
            body_label(info_row, f"DL: {dl_str}", color=dl_color, size=11).pack(side="left")
            
            # ── 升級：進度條與詳細時間切換按鈕 ──
            time_frame = ctk.CTkFrame(info_row, fg_color="transparent")
            time_frame.pack(side="right")

            total_m = max(1.0, t.time_allocation * 60)
            rem_m = max(0.0, t.remaining_minutes)
            # 計算完成進度百分比 (0.0 ~ 1.0)
            prog_val = min(1.0, max(0.0, (total_m - rem_m) / total_m))

            # 1. 建立詳細時間標籤 (預設不 pack，所以先隱藏起來)
            time_str = f"原定 {format_hm(total_m)} / 剩 {format_hm(rem_m)}"
            time_lbl = body_label(time_frame, time_str, color=T2, size=11)

            # 2. 展開/收起詳細數字的小按鈕 (最右側)
            def make_time_toggle(lbl=time_lbl):
                def _toggle():
                    if lbl.winfo_manager():
                        lbl.pack_forget()  # 如果已經顯示，就收合
                    else:
                        lbl.pack(side="right", padx=(0, 8)) # 如果隱藏，就顯示出來
                return _toggle

            ctk.CTkButton(
                time_frame, text="⏱", width=24, height=24,
                fg_color="transparent", hover_color=ARC_BG, text_color=T2,
                font=ctk.CTkFont(size=14), corner_radius=4,
                command=make_time_toggle()
            ).pack(side="right")

            # 3. 視覺化進度條 (在按鈕的左邊)
            prog_bar = ctk.CTkProgressBar(time_frame, width=70, height=8, 
                                          progress_color=T1, fg_color=BORDER)
            prog_bar.set(prog_val)
            prog_bar.pack(side="right", padx=(0, 6))
            
            # --- 第三列：隱藏的子任務 ---
            sub_container = ctk.CTkFrame(t_card, fg_color="transparent")
            if t.subtasks:
                ctk.CTkFrame(sub_container, height=1, fg_color=BORDER).pack(fill="x", pady=(0, 6))
                for st in t.subtasks:
                    sub_item = ctk.CTkFrame(sub_container, fg_color="transparent")
                    sub_item.pack(fill="x", pady=2)
                    sm, color = ("✓", OK_CLR) if st.completed else ("·", T2)
                    body_label(sub_item, f"  {sm} {st.name}", color=color, size=11).pack(side="left")
                    
                    # ── 升級：子任務的進度條與詳細時間切換按鈕 ──
                    sub_time_frame = ctk.CTkFrame(sub_item, fg_color="transparent")
                    sub_time_frame.pack(side="right")

                    st_total = max(1.0, st.estimated_minutes)
                    st_rem   = max(0.0, st.remaining_minutes)
                    st_prog  = min(1.0, max(0.0, (st_total - st_rem) / st_total))

                    sub_time_str = f"原定 {format_hm(st_total)} / 剩 {format_hm(st_rem)}"
                    sub_time_lbl = body_label(sub_time_frame, sub_time_str, color=T2, size=11)

                    def make_sub_time_toggle(lbl=sub_time_lbl):
                        def _toggle():
                            if lbl.winfo_manager():
                                lbl.pack_forget()
                            else:
                                lbl.pack(side="right", padx=(0, 8))
                        return _toggle

                    ctk.CTkButton(
                        sub_time_frame, text="⏱", width=22, height=22,
                        fg_color="transparent", hover_color=ARC_BG, text_color=T2,
                        font=ctk.CTkFont(size=12), corner_radius=4,
                        command=make_sub_time_toggle()
                    ).pack(side="right")

                    # 子任務的進度條稍微做小一點 (50x6)，以建立與主任務 (70x8) 不同的視覺層級
                    sub_prog_bar = ctk.CTkProgressBar(sub_time_frame, width=50, height=6, 
                                                      progress_color=T1, fg_color=BORDER)
                    sub_prog_bar.set(st_prog)
                    sub_prog_bar.pack(side="right", padx=(0, 6))
                    
                def make_toggle(c=sub_container, b=toggle_btn):
                    return lambda: (c.pack(fill="x", padx=12, pady=(0, 8)), b.configure(text="-")) if not c.winfo_manager() else (c.pack_forget(), b.configure(text="+"))
                toggle_btn.configure(command=make_toggle())
            else:
                toggle_btn.pack_forget()

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

        work_days = [ws + timedelta(days=i) for i in range(7)]

        if not entries:
            msg = card_frame(self._schedule_scroll)
            msg.pack(fill="x", pady=20)
            body_label(msg, "No schedule yet. Add a task to begin.", color=T2).pack(pady=(24, 12))
            ctk.CTkButton(msg, text="+ Add Task", width=140, height=36,
                          fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF", font=ctk.CTkFont(size=13),
                          command=self._add_task).pack(pady=(0, 24))
        else:
            for d in work_days:
                ds      = d.isoformat()
                ch      = db.get_class_hours_for_day(d)
                classes = db.get_classes_for_day(d)

                day_card = card_frame(self._schedule_scroll)
                day_card.pack(fill="x", pady=5)

                hdr_row = ctk.CTkFrame(day_card, fg_color="transparent")
                hdr_row.pack(fill="x", padx=14, pady=(10, 4))
                body_label(hdr_row, f"{d.strftime('%A, %b %d')}", size=13).pack(side="left")
                if ch > 0:
                    body_label(hdr_row, f"−{ch:.1f}h classes", color=T2, size=11).pack(side="right")

                for c in classes:
                    body_label(day_card,
                               f"  📚 {c['course_name']}  {c['start_time']}–{c['end_time']}",
                               color=T2, size=11).pack(anchor="w", padx=14)

                if ds in by_day:
                    for e in by_day[ds]:
                        t = all_tasks.get(e["task_id"])
                        if not t: continue
                        trow = ctk.CTkFrame(day_card, fg_color="transparent")
                        trow.pack(fill="x", padx=14, pady=2)
                        mark  = "✓" if t.completed else "○"
                        color = OK_CLR if t.completed else T1
                        body_label(trow, f"{mark}  {t.name}", color=color, size=12).pack(side="left")

                        right_w = ctk.CTkFrame(trow, fg_color="transparent")
                        right_w.pack(side="right")

                        ctk.CTkButton(
                            right_w, text="⋯", width=28, height=24,
                            fg_color="transparent", hover_color=ARC_BG, text_color=T2, 
                            font=ctk.CTkFont(size=14), corner_radius=6,
                            command=lambda task=t: EditTaskDialog(self._app, task, self.refresh),
                        ).pack(side="right", padx=(4, 0))

                        body_label(right_w, format_hm(e['allocated_minutes']),
                                   color=T2, size=11).pack(side="right")

                ctk.CTkFrame(day_card, height=8, fg_color="transparent").pack()
            
        # 直接呼叫新的渲染函式 (大幅精簡程式碼)
        tasks = db.get_all_tasks(week_start=ws, completed=False)
        self._render_task_list(tasks)

    def _add_task(self):
        AddTaskDialog(self._app, self._app.week_start, self.refresh)
    def _difficulty_review(self):
        last_week = self._app.week_start - timedelta(weeks=1)
        tasks = db.get_tasks_from_week(last_week)
        if not tasks:
            messagebox.showinfo(
                "沒有上週資料",
                "找不到上週的任務記錄。\n請先完成一週的排程後再來回顧。",
                parent=self._app,
            )
            return
        DifficultyReviewDialog(self._app, self._app.week_start, on_done=self.refresh)

    def _regen(self):
        try:
            h_val = float(self._hours_var.get())
            if 0.1 <= h_val <= 24.0:
                self._app.hours_per_day = h_val
                self._hours_var.set(f"{h_val:g}") 
                try:
                    with open("data/config.txt", "w", encoding="utf-8") as f:
                        f.write(str(h_val))
                except Exception:
                    pass
            else:
                self._hours_var.set(f"{self._app.hours_per_day:g}")
        except ValueError:
            self._hours_var.set(f"{self._app.hours_per_day:g}")

        tasks = db.get_all_tasks(week_start=self._app.week_start, completed=False)
        if not tasks:
            messagebox.showinfo("No Tasks", "Add tasks before generating a schedule.")
            return
        work_days   = [self._app.week_start + timedelta(days=i) for i in range(7)]
        class_hours = {d: db.get_class_hours_for_day(d) for d in work_days}
        # 讀取介面選擇並標準化為下底線格式字串 ("deep_work" 或 "balanced")
        strat = self._strategy_var.get().lower().replace(" ", "_")
        self._app.schedule_strategy = strat  # 更新全域變數

        try:
            alloc = scheduler.allocate_weekly(
                tasks, self._app.week_start, self._app.hours_per_day, class_hours, strategy=strat)
        except scheduler.PomodoroDebtError as e:
            messagebox.showerror("Schedule Impossible", str(e))
            return
        db.clear_schedule_for_week(self._app.week_start)
        for day_date, entries in alloc.items():
            for task_id, minutes in entries:
                db.insert_schedule_entry(
                    self._app.week_start, day_date, task_id, minutes)
        self.refresh()
            
        # 取得本週所有未完成任務並重新繪製右側清單
        tasks = db.get_all_tasks(week_start=self._app.week_start, completed=False)
        self._render_task_list(tasks)

    def _add_task(self):
        AddTaskDialog(self._app, self._app.week_start, self.refresh)

    def _regen(self):
        # ---- 新增：安全讀取並更新全域讀書時數 (防呆與記憶機制) ----
        try:
            h_val = float(self._hours_var.get())
            if 0.1 <= h_val <= 24.0:
                self._app.hours_per_day = h_val
                self._hours_var.set(f"{h_val:g}") # 存檔後自動將介面格式化
                
                # 將最新的時數設定同步寫入本地文字檔
                try:
                    with open("data/config.txt", "w", encoding="utf-8") as f:
                        f.write(str(h_val))
                except Exception:
                    pass
            else:
                self._hours_var.set(f"{self._app.hours_per_day:g}")
        except ValueError:
            self._hours_var.set(f"{self._app.hours_per_day:g}")

        tasks = db.get_all_tasks(week_start=self._app.week_start, completed=False)
        if not tasks:
            messagebox.showinfo("No Tasks", "Add tasks before generating a schedule.")
            return
        work_days   = [self._app.week_start + timedelta(days=i) for i in range(7)]
        class_hours = {d: db.get_class_hours_for_day(d) for d in work_days}
        
        # --- 加上這段：讀取介面按鈕的策略並存下來 ---
        strat = self._strategy_var.get().lower().replace(" ", "_")
        self._app.schedule_strategy = strat
        # ------------------------------------------

        try:
            # 修改點 1：用 alloc, warnings 接住兩個回傳值
            alloc, warnings = scheduler.allocate_weekly(
                tasks, 
                self._app.week_start, 
                self._app.hours_per_day, 
                class_hours,
                strategy=strat
            )
        except scheduler.PomodoroDebtError as e:
            DeadMascotDialog(self._app, str(e))  #Claude修正
            return
            
        # 修改點 2：若有警告，跳出提示視窗
        if warnings:
            messagebox.showwarning("Pacing Warning", "\n".join(warnings))
            
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
        # --- 新增：行內警告提示區塊 (預設隱藏) ---
        self._error_lbl = ctk.CTkLabel(scroll, text="", text_color="#FFF", fg_color=ERR_CLR, 
                                       corner_radius=6, height=30, font=ctk.CTkFont(size=12, weight="bold"))
        # ----------------------------------------
        
        Divider(scroll).pack(fill="x", pady=8)
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
        
        urg_row = ctk.CTkFrame(scroll, fg_color="transparent")
        urg_row.pack(fill="x", pady=(0, 10))
        body_label(urg_row, "Low", color=T2, size=11).pack(side="left", padx=(0, 8))
        ctk.CTkSlider(urg_row, from_=1, to=5, number_of_steps=4,
                      variable=self._urg_var, button_color=T1, progress_color=T1,
                      command=lambda v: self._urg_lbl.configure(text=f"{int(v)} / 5")
                     ).pack(side="left", fill="x", expand=True)
        body_label(urg_row, "High", color=T2, size=11).pack(side="left", padx=(8, 0))

        # Importance
        section_label(scroll, "IMPORTANCE").pack(anchor="w", pady=(6, 0))
        self._imp_lbl = body_label(scroll, "3 / 5", color=T2, size=11)
        self._imp_lbl.pack(anchor="w")
        self._imp_var = tk.IntVar(value=3)
        
        imp_row = ctk.CTkFrame(scroll, fg_color="transparent")
        imp_row.pack(fill="x", pady=(0, 10))
        body_label(imp_row, "Low", color=T2, size=11).pack(side="left", padx=(0, 8))
        ctk.CTkSlider(imp_row, from_=1, to=5, number_of_steps=4,
                      variable=self._imp_var, button_color=T1, progress_color=T1,
                      command=lambda v: self._imp_lbl.configure(text=f"{int(v)} / 5")
                     ).pack(side="left", fill="x", expand=True)
        body_label(imp_row, "High", color=T2, size=11).pack(side="left", padx=(8, 0))

        # Hours
        section_label(scroll, "ESTIMATED HOURS").pack(anchor="w")

        # Try to pull difficulty suggestion
        last_week  = self._week_start - timedelta(weeks=1)
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
        self._deadline_entry = DateEntry(
            scroll, 
            width=16,
            background="#1A1A1A",
            foreground="white", 
            borderwidth=0,
            font=("Arial", 12), 
            date_pattern="yyyy-mm-dd",
            selectbackground="#2C7A45"
        )
        self._deadline_entry.set_date(date.today() + timedelta(days=4))
        self._deadline_entry.pack(anchor="w", pady=(2, 10))

        # Notes
        section_label(scroll, "NOTES (optional)").pack(anchor="w")
        self._notes = ctk.CTkEntry(scroll, height=36,
                                    font=ctk.CTkFont(size=12),
                                    fg_color=CARD, border_color=BORDER,
                                    text_color=T1)
        self._notes.pack(fill="x", pady=(2, 10))

        # ── 修正：子任務區域 ──
        section_label(scroll, "SUB-TASKS").pack(anchor="w", pady=(4, 0))

        # 1. 先放輸入框，避免被下面的空 Frame 撐到底部
        sub_row = ctk.CTkFrame(scroll, fg_color="transparent")
        sub_row.pack(fill="x", pady=(4, 6))
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

        # 2. 再放裝已新增子任務的容器，讓清單往下長
        self._sub_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._sub_frame.pack(fill="x", pady=(0, 10))
        # ────────────────────────

        # Save Task 按鈕留在外層 (scroll 之外)，固定在視窗最下方
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

    def _remove_subtask_new(self, index: int):
        if 0 <= index < len(self._subtasks):
            self._subtasks.pop(index)
        self._refresh_sub_frame()

    def _refresh_sub_frame(self):
        for w in self._sub_frame.winfo_children():
            w.destroy()
        for i, s in enumerate(self._subtasks):
            row = ctk.CTkFrame(self._sub_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            body_label(row, f"  ·  {s['name']}  ({s['minutes']:.0f}m)",
                       color=T2, size=11).pack(side="left")
            ctk.CTkButton(
                row, text="✕", width=24, height=24,
                fg_color="transparent", hover_color=ERR_CLR,
                text_color=T2, font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._remove_subtask_new(idx)
            ).pack(side="right")

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
        self._refresh_sub_frame()
        self._sub_entry.delete(0, "end")
        self._sub_mins.delete(0, "end")

    def _save(self):
        # --- 內部函式：顯示行內警告 ---
        def show_error(msg):
            self._error_lbl.configure(text=f" ⚠ {msg} ")
            # ❗把這行的 scroll 替換成 self._error_lbl.master
            self._error_lbl.pack(fill="x", pady=(0, 10), after=self._error_lbl.master.winfo_children()[0])
            self.after(4000, lambda: self._error_lbl.pack_forget()) # 4秒後自動消失

        name = self._name.get().strip()
        if not name:
            show_error("Task name is required.")
            return
        try:
            hours = float(self._hours.get())
        except ValueError:
            show_error("Estimated hours must be a valid number.")
            return

        total_sub_mins = sum(s["minutes"] for s in self._subtasks)
        if total_sub_mins > hours * 60:
            show_error(f"Sub-task total ({total_sub_mins:.0f}m) exceeds task time ({hours*60:.0f}m).")
            return

        if db.task_in_week_by_name(name, self._week_start):
            messagebox.showwarning("Duplicate",
                f"'{name}' already exists this week.", parent=self)
            return

        dl  = self._deadline_entry.get_date()
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
        work_days   = [self._week_start + timedelta(days=i) for i in range(7)] 
        class_hours = {d: db.get_class_hours_for_day(d) for d in work_days}
        debt_message = None  #Claude修正
        try:
            # 讀取全域策略設定
            strat = getattr(self._app, "schedule_strategy", "balanced")
            
            # 修改點 1：用 alloc, warnings 接住兩個回傳值
            alloc, warnings = scheduler.allocate_weekly(
                tasks, 
                self._week_start,
                self._app.hours_per_day, 
                class_hours, 
                strategy=strat
            )
            
            # 修改點 2：若有警告，跳出提示視窗 (加入 parent=self 確保視窗顯示在最上層)
            if warnings:
                messagebox.showwarning("Pacing Warning", "\n".join(warnings), parent=self)
                
            db.clear_schedule_for_week(self._week_start)
            for day_date, entries in alloc.items():
                for task_id, minutes in entries:
                    db.insert_schedule_entry(
                        self._week_start, day_date, task_id, minutes)
        except scheduler.PomodoroDebtError as e:
            debt_message = str(e)  #Claude修正

        self.destroy()
        self._on_done()
        if debt_message is not None:                   #Claude修正
            DeadMascotDialog(self._app, debt_message)  #Claude修正

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

                # ── 編輯按鈕：開啟 EditClassDialog ────────────────────────
                ctk.CTkButton(
                    right, text="⋯", width=28, height=24,
                    fg_color="transparent", hover_color=ARC_BG,
                    text_color=T2, font=ctk.CTkFont(size=14),
                    corner_radius=6,
                    command=lambda cls=c: EditClassDialog(
                        self._app, cls, self.refresh),
                ).pack(side="right", padx=(4, 0))
                # ──────────────────────────────────────────────────────────

                body_label(right,
                           f"{c['start_time']}–{c['end_time']}  "
                           f"({hrs:.1f}h)   "
                           f"{c['term_start']} → {c['term_end']}",
                           color=T2, size=11).pack(side="left", padx=8)

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

        # 刪除原本的 days21, day_strs, self._day_map 相關程式碼
        
        # ── 改用 DateEntry 實作 TERM START ──
        section_label(scroll, "TERM START").pack(anchor="w", pady=(8, 0))
        self._tstart_entry = DateEntry(
            scroll, 
            width=16,
            background="#1A1A1A",
            foreground="white", 
            borderwidth=0,
            font=("Arial", 12), 
            date_pattern="yyyy-mm-dd",
            selectbackground="#2C7A45"
        )
        self._tstart_entry.set_date(date.today())
        self._tstart_entry.pack(anchor="w", pady=(2, 10))

        # ── 改用 DateEntry 實作 TERM END ──
        section_label(scroll, "TERM END").pack(anchor="w")
        self._tend_entry = DateEntry(
            scroll, 
            width=16,
            background="#1A1A1A",
            foreground="white", 
            borderwidth=0,
            font=("Arial", 12), 
            date_pattern="yyyy-mm-dd",
            selectbackground="#2C7A45"
        )
        # 預設學期結束日大約在 4 個月 (120天) 後
        self._tend_entry.set_date(date.today() + timedelta(days=120))
        self._tend_entry.pack(anchor="w", pady=(2, 10))

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
        # 改為直接從 DateEntry 取得 date 物件
        ts    = self._tstart_entry.get_date()
        te    = self._tend_entry.get_date()
        loc   = self._loc.get().strip()
        db.insert_term_class(name, dow, start, end, ts, te, loc)
        self.destroy()
        self._on_done()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ② 新增 EditClassDialog 類別
#
# 貼在 AddClassDialog 類別的最後一行（self._on_done()）之後，
# 在 # ── App ── 區塊之前。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EditClassDialog(ctk.CTkToplevel):
    """
    彈出式編輯/刪除課程視窗。
    外觀與 AddClassDialog 一致，但預填原有資料。
    """

    _DAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"]

    def __init__(self, app, class_dict: dict, on_done):
        super().__init__(app)
        self.title("Edit Class")
        self.geometry("420x560")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG)
        self._app      = app
        self._cls      = class_dict   # dict from db.get_term_classes()
        self._on_done  = on_done
        self._build()

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        heading(scroll, "Edit Term Class", size=16).pack(anchor="w",
                                                          pady=(0, 4))
        body_label(scroll, self._cls["course_name"],
                   color=T2, size=12).pack(anchor="w")
        Divider(scroll).pack(fill="x", pady=8)

        # ── Course name ────────────────────────────────────────────────────
        section_label(scroll, "COURSE NAME").pack(anchor="w")
        self._name = ctk.CTkEntry(scroll, height=36,
                                   font=ctk.CTkFont(size=13),
                                   fg_color=CARD, border_color=BORDER,
                                   text_color=T1)
        self._name.insert(0, self._cls["course_name"])
        self._name.pack(fill="x", pady=(2, 10))

        # ── Day of week ────────────────────────────────────────────────────
        section_label(scroll, "DAY OF WEEK").pack(anchor="w")
        self._dow_var = tk.StringVar(
            value=self._DAYS_FULL[self._cls["day_of_week"]])
        ctk.CTkOptionMenu(scroll, values=self._DAYS_FULL,
                          variable=self._dow_var,
                          font=ctk.CTkFont(size=12),
                          fg_color=CARD, button_color=T1,
                          button_hover_color=SIDE_SEL,
                          text_color=T1, dropdown_text_color=T1,
                          dropdown_fg_color=CARD).pack(fill="x",
                                                        pady=(2, 10))

        # ── Start / End time ───────────────────────────────────────────────
        time_row = ctk.CTkFrame(scroll, fg_color="transparent")
        time_row.pack(fill="x", pady=(0, 10))

        col1 = ctk.CTkFrame(time_row, fg_color="transparent")
        col1.pack(side="left", expand=True, fill="x", padx=(0, 8))
        section_label(col1, "START (HH:MM)").pack(anchor="w")
        self._start = ctk.CTkEntry(col1, height=36,
                                    font=ctk.CTkFont(size=13),
                                    fg_color=CARD, border_color=BORDER,
                                    text_color=T1)
        self._start.insert(0, self._cls["start_time"])
        self._start.pack(fill="x", pady=(2, 0))

        col2 = ctk.CTkFrame(time_row, fg_color="transparent")
        col2.pack(side="left", expand=True, fill="x")
        section_label(col2, "END (HH:MM)").pack(anchor="w")
        self._end = ctk.CTkEntry(col2, height=36,
                                  font=ctk.CTkFont(size=13),
                                  fg_color=CARD, border_color=BORDER,
                                  text_color=T1)
        self._end.insert(0, self._cls["end_time"])
        self._end.pack(fill="x", pady=(2, 0))

        # ── Term start / end（改用 DateEntry 月曆元件）────────────────
        section_label(scroll, "TERM START").pack(anchor="w", pady=(8, 0))
        self._tstart_entry = DateEntry(
            scroll, 
            width=16,
            background="#1A1A1A",
            foreground="white", 
            borderwidth=0,
            font=("Arial", 12), 
            date_pattern="yyyy-mm-dd",
            selectbackground="#2C7A45"
        )
        # 讀取資料庫中舊的日期並設定為月曆預設值
        self._tstart_entry.set_date(date.fromisoformat(self._cls["term_start"]))
        self._tstart_entry.pack(anchor="w", pady=(2, 10))

        section_label(scroll, "TERM END").pack(anchor="w")
        self._tend_entry = DateEntry(
            scroll, 
            width=16,
            background="#1A1A1A",
            foreground="white", 
            borderwidth=0,
            font=("Arial", 12), 
            date_pattern="yyyy-mm-dd",
            selectbackground="#2C7A45"
        )
        self._tend_entry.set_date(date.fromisoformat(self._cls["term_end"]))
        self._tend_entry.pack(anchor="w", pady=(2, 10))

        # ── Location ───────────────────────────────────────────────────────
        section_label(scroll, "LOCATION (optional)").pack(anchor="w")
        self._loc = ctk.CTkEntry(scroll, height=36,
                                  font=ctk.CTkFont(size=12),
                                  fg_color=CARD, border_color=BORDER,
                                  text_color=T1)
        self._loc.insert(0, self._cls.get("location", ""))
        self._loc.pack(fill="x", pady=(2, 0))

        # ── 按鈕列：Save / Delete ──────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=16)

        ctk.CTkButton(btn_row, text="Save Changes",
                      fg_color=T1, hover_color=SIDE_SEL, text_color="#FFF",
                      font=ctk.CTkFont(size=13), height=40, corner_radius=8,
                      command=self._save).pack(side="left", expand=True,
                                               fill="x", padx=(0, 6))

        ctk.CTkButton(btn_row, text="Delete",
                      fg_color=CARD, hover_color="#FDEAEA",
                      text_color=ERR_CLR,
                      border_width=1, border_color="#E8CECE",
                      font=ctk.CTkFont(size=13), height=40, corner_radius=8,
                      command=self._delete).pack(side="left", expand=True,
                                                 fill="x", padx=(6, 0))

    # ── Validation helper ──────────────────────────────────────────────────
    @staticmethod
    def _valid_time(t: str) -> bool:
        parts = t.split(":")
        return (len(parts) == 2 and all(p.isdigit() for p in parts))

    @staticmethod
    def _valid_date(d: str) -> bool:
        try:
            date.fromisoformat(d)
            return True
        except ValueError:
            return False

    # ── Save ───────────────────────────────────────────────────────────────
    def _save(self):
        name  = self._name.get().strip()
        start = self._start.get().strip()
        end   = self._end.get().strip()
        ts    = self._tstart_entry.get_date()
        te    = self._tend_entry.get_date()

        if not name or not start or not end:
            messagebox.showwarning("Missing",
                                   "Name, start and end are required.",
                                   parent=self)
            return

        for t in (start, end):
            if not self._valid_time(t):
                messagebox.showwarning("Invalid",
                                       "Time must be HH:MM (e.g. 09:30).",
                                       parent=self)
                return

        if end <= start:
            messagebox.showwarning("Invalid",
                                   "End time must be after start.",
                                   parent=self)
            return

        

        if te < ts:
            messagebox.showwarning("Invalid",
                                   "Term end must be on or after term start.",
                                   parent=self)
            return

        dow = self._DAYS_FULL.index(self._dow_var.get())
        loc = self._loc.get().strip()

        # database.py 沒有 update_term_class，用 delete + insert 實現
        db.delete_term_class(self._cls["id"])
        db.insert_term_class(
            name, dow, start, end, ts, te, loc)

        self.destroy()
        self._on_done()

    # ── Delete ─────────────────────────────────────────────────────────────
    def _delete(self):
        confirmed = messagebox.askyesno(
            "Delete Class",
            f"Delete '{self._cls['course_name']}'?\n\n"
            "This class will be removed from all future weeks.",
            parent=self,
        )
        if confirmed:
            db.delete_term_class(self._cls["id"])
            self.destroy()
            self._on_done()

# ── Splash Screen ─────────────────────────────────────────────────────────────

class SplashScreen(ctk.CTk):
    """
    啟動歡迎頁：顯示 TaskFlow Pomodoro 標題與圓弧開始按鈕。
    按下開始後關閉此視窗並啟動主程式 App。
    """

    def __init__(self):
        super().__init__()
        self.title("TaskFlow Pomodoro")
        self.geometry("820x560")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        self._build()
        # 讓視窗置中
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - 820) // 2
        y  = (sh - 560) // 2
        self.geometry(f"820x560+{x}+{y}")

    def _build(self):
        # ── 主容器（垂直置中）────────────────────────────────────────────
        outer = ctk.CTkFrame(self, fg_color=BG)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        # ── 裝飾性小番茄圖示（Unicode 替代，不需要外部圖片）─────────────
        ctk.CTkLabel(
            outer,
            text="🍅",
            font=ctk.CTkFont(size=52),
            text_color=T1,
        ).pack(pady=(0, 18))

        # ── 主標題 ────────────────────────────────────────────────────────
        ctk.CTkLabel(
            outer,
            text="TaskFlow Pomodoro",
            font=ctk.CTkFont(size=46, weight="bold"),
            text_color=T1,
        ).pack()

        # ── 副標題 ────────────────────────────────────────────────────────
        ctk.CTkLabel(
            outer,
            text="Plan smart. Focus deep. Rest well.",
            font=ctk.CTkFont(size=15),
            text_color=T2,
        ).pack(pady=(10, 0))

        # ── 分隔線 ────────────────────────────────────────────────────────
        Divider(outer, width=260).pack(pady=36)

        # ── 開始按鈕（圓弧設計，corner_radius=26 讓長方形變膠囊狀）────────
        start_btn = ctk.CTkButton(
            outer,
            text="開 始",
            font=ctk.CTkFont(size=17, weight="bold"),
            width=200,
            height=52,
            corner_radius=26,
            fg_color=T1,
            hover_color="#3A3A3A",
            text_color="#FFFFFF",
            command=self._launch,
        )
        start_btn.pack()

        # ── 介紹按鈕（線框風格，在開始下方）─────────────────────────────
        intro_btn = ctk.CTkButton(
            outer,
            text="介 紹",
            font=ctk.CTkFont(size=14),
            width=200,
            height=42,
            corner_radius=21,
            fg_color="transparent",
            hover_color=BORDER,
            text_color=T2,
            border_width=1,
            border_color=BORDER,
            command=self._open_intro,
        )
        intro_btn.pack(pady=(14, 0))

        # ── 底部版本資訊 ──────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="v1.0",
            font=ctk.CTkFont(size=10),
            text_color="#CCCCCC",
        ).place(relx=1.0, rely=1.0, anchor="se", x=-16, y=-12)

    def _launch(self):
        """關閉啟動頁，開啟主程式。"""
        self.destroy()
        app = App()
        app.mainloop()

    def _open_intro(self):
        """開啟介紹頁（SplashScreen 保持在背景）。"""
        IntroScreen(self)


# ── Intro Screen ──────────────────────────────────────────────────────────────

class IntroScreen(ctk.CTkToplevel):
    """
    介紹頁：從 SplashScreen 點擊「介紹」後跳出的獨立視窗。
    點擊「返回」後關閉此視窗，回到 SplashScreen。

    ════════════════════════════════════════════════════════════════
    ★  自行設計介紹頁面的完整說明  ★
    ════════════════════════════════════════════════════════════════

    【區塊 A】大標題 ── 修改 _INTRO_TITLE 字串
        _INTRO_TITLE = "TaskFlow Pomodoro"
        → 改成你想要的標題文字即可。

    【區塊 B】內文段落 ── 修改 _INTRO_PARAGRAPHS 列表
        每一個字串 = 一個獨立段落，會自動換行並保留段落間距。
        範例：
            _INTRO_PARAGRAPHS = [
                "第一段：這是應用程式的簡介……",
                "第二段：介紹功能特色……",
                "第三段：使用方法說明……",
            ]
        → 要加更多段落，就在列表裡繼續加字串。
        → 每段文字如果太長，customtkinter 會自動依視窗寬度折行。

    【字體大小 / 顏色】
        大標題字體：在 _build() 找到「區塊 A」下方的
            font=ctk.CTkFont(size=28, weight="bold")
            → 改 size 數字調整大小，weight="bold" 移除則變細體。
            → text_color=T1  改成任何 hex 色碼，如 "#2C7A45"。

        段落字體：找到「區塊 B」下方的
            font=ctk.CTkFont(size=14)
            → 同上方式調整。

    【版面 Padding / 間距】
        scroll_frame 的 padx / pady 控制內容與邊框的距離。
        每個 Label 的 pady=(0, 16) 控制段落之間的間距。
        → 數字越大間距越大。

    【加入小標題（h2 效果）】
        在 _INTRO_PARAGRAPHS 之外，仿照「區塊 A」再多加一個
        CTkLabel 並設定較大字體 + 粗體，放在對應段落的 pack 之前。

    【加入圖示 / emoji】
        在任何 CTkLabel 的 text 裡直接插入 emoji，例如：
            text="🍅  功能一覽"

    【捲軸】
        內文使用 CTkScrollableFrame，文字超出視窗高度時自動出現捲軸，
        不需要額外設定。

    ════════════════════════════════════════════════════════════════
    """

    # ── ★ 在這裡填寫你的介紹內容 ★ ─────────────────────────────────────────

    _INTRO_TITLE = "TaskFlow Pomodoro"   # 【區塊 A】大標題

    # 【區塊 B】內文段落（一個字串 = 一段）。  #Claude修正
    # 以下整理自我們這次對話新增／說明過的所有功能，作為原本「介紹」的補充。  #Claude修正
    _INTRO_PARAGRAPHS = [  #Claude修正
        "TaskFlow Pomodoro 是一套「週計畫 + 每日番茄鐘」的讀書排程工具。"     #Claude修正
        "你在 Weekly 規劃整週要完成的任務，系統會依照緊急／重要程度與死線，"
        "自動把工作量分配到每一天；到了 Daily 再用番茄鐘專注執行。",

        "WORKSPACES（三個分頁）\n"                                          #Claude修正
        "• 📆 Daily — 今天要做的任務 ＋ 番茄鐘計時器。\n"
        "• 📅 Weekly — 新增任務、設定時數與死線、產生整週排程。\n"
        "• 📚 Term Schedule — 登記固定課表，排程時會自動避開上課時間。",

        "HOW IT WORKS（四個步驟）\n"                                        #Claude修正
        "1. 在 Term Schedule 輸入每週固定課程（只需設定一次）。\n"
        "2. 在 Weekly 用「+ Add Task」加入任務：名稱、緊急度、重要度、"
        "預估時數、死線，並可拆分子任務（sub-tasks）。\n"
        "3. 按「⟳ Regenerate」產生本週排程；系統會避開課堂並依優先序分配。\n"
        "4. 切到 Daily，按開始啟動番茄鐘，依排定的區塊專注與休息。",

        "PRIORITY COLORS（艾森豪矩陣，任務卡會以底色標示優先序）\n"          #Claude修正
        "• 🟥 UI  Urgent & Important（緊急且重要）— 權重 50%\n"
        "• 🟧 UU  Urgent but Unimportant（緊急但不重要）— 權重 25%\n"
        "• 🟨 INU Important but Not Urgent（重要但不緊急）— 權重 15%\n"
        "• 🟩 N   Neither（皆非）— 權重 10%\n"
        "權重越高、死線越近的任務，會被排在越前面、分到越多時間。",

        "SCHEDULING STRATEGIES（兩種排程策略，可在 Weekly 切換）\n"         #Claude修正
        "🎯 Deep Work：傾向把同一任務集中在連續時段，減少切換、利於專注。\n"
        "⚖️ Balanced： 在多個任務之間均衡推進，讓每件事都穩定往前，"
        "避免某些任務拖到最後才開始。",

        "POMODORO MODES（番茄鐘兩種模式）\n"                                #Claude修正
        "🍅 Chunk：每個番茄鐘區塊只專注一個任務，適合需要深度投入的工作。\n"
        "🥪 Sandwich：把多個小任務「夾」進同一個番茄鐘區塊，並可設定每段"
        "最短時間（min slice），避免切換太碎；適合把零碎小事一次清掉。",

        "SMART TOUCHES（貼心設計）\n"                                       #Claude修正
        "• 難度記憶：在 Weekly 頁面按「📊 Review」，替上週任務評分（0–5）；"
        "下次新增同名任務時，系統會依難度自動建議時數（難 → 加時，易 → 減時）。\n"
        "• 死線壓力：越接近死線的任務，優先序會動態升高。\n"
        "• 隔日結轉：每天結束的報告可把未完成任務自動帶到明天。\n"
        "• 進度回填：在完成視窗用滑桿回報各任務／子任務的完成百分比，"
        "剩餘時間會即時重算。",

        "⚠️ SCHEDULE WARNINGS（排程警告）\n"
        "系統有兩種警告層級：\n"
        "• 黃色警告（Pacing Warning）：任務本週分配到的時間略少於目標，"
        "但死線還在下週以後，屬於輕度提醒。看到這個訊息時，"
        "可考慮調高每日可讀書時數，或切換為 Deep Work 策略集中推進。\n"
        "• R.I.P. 小蘑菇（Pomodoro Debt）：某個任務在死線前物理上塞不下，"
        "排程完全不可能完成。此時請延後死線、調低預估時數，或把工作分散到更多天。",
    ]

    # ────────────────────────────────────────────────────────────────────────

    def __init__(self, splash: SplashScreen):
        super().__init__(splash)
        self._splash = splash
        self.title("介紹")
        self.geometry("700x520")
        self.resizable(False, True)
        self.configure(fg_color=BG)
        self.grab_set()           # 鎖定焦點在此視窗

        # 置中於 SplashScreen 上方
        self.update_idletasks()
        px = splash.winfo_x() + (splash.winfo_width()  - 700) // 2
        py = splash.winfo_y() + (splash.winfo_height() - 520) // 2
        self.geometry(f"700x520+{px}+{py}")

        self._build()

    def _build(self):
        # ── 外框（上方內容 + 下方按鈕）────────────────────────────────────
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        # ── 可捲動的內容區 ────────────────────────────────────────────────
        scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=T2,
        )
        scroll_frame.grid(row=0, column=0, sticky="nsew", padx=48, pady=(40, 16))
        scroll_frame.grid_columnconfigure(0, weight=1)

        # ── 【區塊 A】大標題 ──────────────────────────────────────────────
        ctk.CTkLabel(
            scroll_frame,
            text=self._INTRO_TITLE,
            font=ctk.CTkFont(size=28, weight="bold"),  # ← 調整標題字體
            text_color=T1,                              # ← 調整標題顏色
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(0, 20))

        Divider(scroll_frame).pack(fill="x", pady=(0, 20))

        # ── 【區塊 B】段落內文 ────────────────────────────────────────────
        for para in self._INTRO_PARAGRAPHS:
            ctk.CTkLabel(
                scroll_frame,
                text=para,
                font=ctk.CTkFont(size=14),   # ← 調整內文字體大小
                text_color=T1,               # ← 調整內文顏色
                anchor="w",
                justify="left",
                wraplength=580,              # ← 自動折行寬度（px），視窗變寬可調大
            ).pack(anchor="w", pady=(0, 16))

        # ── 分隔 ──────────────────────────────────────────────────────────
        Divider(self).grid(row=1, column=0, sticky="ew", padx=0)

        # ── 返回按鈕 ──────────────────────────────────────────────────────
        back_btn = ctk.CTkButton(
            self,
            text="← 返回開始頁面",
            font=ctk.CTkFont(size=14),
            width=200,
            height=44,
            corner_radius=22,
            fg_color="transparent",
            hover_color=BORDER,
            text_color=T2,
            border_width=1,
            border_color=BORDER,
            command=self.destroy,
        )
        back_btn.grid(row=2, column=0, pady=20)


# ── App ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        db.init_db()
        self.title("Study Planner")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)
        # 綁定 Ctrl + B 作為隱藏作弊鍵
        self.bind_all('<Control-b>', self._trigger_cheat)
        self.bind_all('<Control-B>', self._trigger_cheat)

        self.today      = date.today()
        self.week_start = week_start_of(self.today)

        # 預設每日可讀書時數
        self.hours_per_day = 8.0
        self.schedule_strategy = "balanced"  # 新增：紀錄全域排程策略變數，預設為均衡推進
        
        # 嘗試從本地檔案讀取上一次儲存的設定值
        try:
            import os
            os.makedirs("data", exist_ok=True)
            if os.path.exists("data/config.txt"):
                with open("data/config.txt", "r", encoding="utf-8") as f:
                    val = float(f.read().strip())
                    if 0.1 <= val <= 24.0:
                        self.hours_per_day = val
        except Exception:
            self.hours_per_day = 8.0

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
# ... (上面是 __init__ 的結尾) ...

    # 👇 把作弊函式貼在這裡
    def _trigger_cheat(self, event=None):
        """隱藏的展示用捷徑 (按 Ctrl+B 觸發)"""
        import database as db
        
        # 1. 在作弊碼把任務歸零之前，先偷看今天真正排定的「未完成任務」總剩餘時間
        tasks = db.get_tasks_for_date(self.today)
        realistic_focus = sum(int(t.remaining_minutes) for t in tasks if not t.completed)
        
        # 2. 執行底層結算邏輯 (讓資料庫打勾)
        from daily_planner import _simulate_day_complete
        _simulate_day_complete(self.today)
        
        # 3. 刷新畫面
        self._daily_view.refresh()
        self._weekly_view.refresh()
        
        # 4. 彈出專屬彩蛋視窗
        from tkinter import messagebox
        messagebox.showinfo("Secret Unlocked", "Ray is going to Berkeley next year 🎉")
        
        # 5. 強制使用我們自己算的合理時間，丟掉資料庫裡累積的 10560 分鐘！
        ReportWindow(self, self.today, realistic_focus)

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
        self._date_lbl.pack(side="bottom", pady=(0, 16))

        # ── 返回首頁按鈕（sidebar 最底部）────────────────────────────────
        ctk.CTkButton(
            self._sidebar,
            text="⌂  首頁",
            font=ctk.CTkFont(size=12),
            height=36,
            corner_radius=8,
            fg_color="transparent",
            hover_color=SIDE_SEL,
            text_color="#777777",
            anchor="w",
            command=self._go_home,
        ).pack(side="bottom", fill="x", padx=12, pady=(0, 6))

        ctk.CTkFrame(self._sidebar, height=1,
                     fg_color="#2A2A2A").pack(side="bottom", fill="x",
                                              padx=16, pady=(0, 4))

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
        # ── 裝上安全鎖：確保沒有其他計時器在背景搗亂 ──
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        # ──────────────────────────────────────────────
        while self._block_idx < len(self._blocks):
            if not self._blocks[self._block_idx].completed:
                break
            self._block_idx += 1
        if self._block_idx >= len(self._blocks):
            self._finish()
            return
        self._in_break      = False
        self._elapsed_s     = 0
        self._accumulated_s = 0.0                 # [優化] 記錄暫停前累積的時間
        self._anchor_time   = time.time()         # [優化] 記錄系統絕對時間錨點
        self._total_s       = self._focus_min * 60
        self._timer_active  = True
        self._timer_paused  = False
        b = self._blocks[self._block_idx]
        self._daily_view.timer_panel.on_block_start(
            self._block_idx, len(self._blocks), b, self._task_map, False)
        # [優化] 把 1000ms 改成 100ms，讓圓弧動畫變得像 60fps 一樣滑順
        self._after_id = self.after(100, self._tick)

    def _start_break(self):
        # ── 裝上安全鎖 ──
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        # ────────────────
        self._in_break      = True
        self._elapsed_s     = 0
        self._accumulated_s = 0.0                 # [優化]
        self._anchor_time   = time.time()         # [優化]
        self._total_s       = self._break_min * 60
        b = self._blocks[self._block_idx]
        self._daily_view.timer_panel.on_block_start(
            self._block_idx, len(self._blocks), b, self._task_map, True)
        self._after_id = self.after(100, self._tick)

    def _tick(self):
        if not self._timer_active or self._timer_paused:
            return
            
        now = time.time()
        exact_elapsed = self._accumulated_s + (now - self._anchor_time)
        self._elapsed_s = int(exact_elapsed)
        
        remaining = self._total_s - self._elapsed_s
        progress  = (exact_elapsed / self._total_s) if self._total_s else 1.0
        
        # [變色優化] 正常計時中，傳入 is_paused = False
        self._daily_view.timer_panel.update_display(remaining, progress, self._in_break, False)
        
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
            self._after_id = self.after(100, self._tick)

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
            # [恢復計時]
            # ── 裝上安全鎖 ──
            if self._after_id is not None:
                self.after_cancel(self._after_id)
                self._after_id = None
            # ────────────────
                
            self._anchor_time = time.time()
            self._after_id = self.after(100, self._tick)
            
            # 瞬間把顏色切換回原本的顏色 (黑色或綠色)
            remaining = self._total_s - self._elapsed_s
            progress  = (self._accumulated_s / self._total_s) if self._total_s else 1.0
            self._daily_view.timer_panel.update_display(remaining, progress, self._in_break, False)
        else:
            # [暫停計時]
            now = time.time()
            self._accumulated_s += (now - self._anchor_time)
            
            # 瞬間把顏色切換成黃色
            remaining = self._total_s - self._elapsed_s
            progress  = (self._accumulated_s / self._total_s) if self._total_s else 1.0
            self._daily_view.timer_panel.update_display(remaining, progress, self._in_break, True)
            
    def timer_stop(self):
        self._timer_active = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None  # 補上這行，把變數徹底清空

    def _finish(self):
        self._timer_active = False
        all_blocks = db.get_blocks_for_date(self.today)
        if all_blocks and all(b.completed for b in all_blocks):
            self._daily_view.timer_panel.reset_display()
            ReportWindow(self, self.today, self._total_focus_min)
        else:
            self._daily_view.timer_panel.reset_display()
            self._daily_view.refresh()

    def _go_home(self):
        """停止計時器，關閉主程式，重新開啟 SplashScreen。"""
        # 若計時器正在執行，先詢問使用者
        if self._timer_active:
            confirmed = messagebox.askyesno(
                "返回首頁",
                "番茄鐘正在計時中，確定要停止並返回首頁嗎？",
                parent=self,
            )
            if not confirmed:
                return
            self.timer_stop()

        self.destroy()
        splash = SplashScreen()
        splash.mainloop()


if __name__ == "__main__":
    splash = SplashScreen()
    splash.mainloop()
