#!/usr/bin/env python3
"""
Daily Planner — standalone program.
Reads today's schedule from the shared SQLite DB (written by Weekly Planner),
shows term classes as fixed blocks, runs Pomodoro sessions with sub-task
management, and generates an end-of-day report with mascot.
"""

import os
import sys
import select
import threading
import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import database as db
import scheduler
from models import Task, Subtask, PomodoroBlock, SplitMode
from mascots import HAPPY_MASCOT, RESENTFUL_MASCOT, FOCUS_MASCOT, BREAK_MASCOT


# ── Terminal helpers ──────────────────────────────────────────────────────────

def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def banner(title: str, width: int = 62) -> None:
    print("=" * width)
    print(title.center(width))
    print("=" * width)


def prompt_int(prompt: str, lo: int, hi: int) -> int:
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        print(f"  ✗  Enter a whole number between {lo} and {hi}.")


def prompt_float(prompt: str, lo: float = 0.1) -> float:
    while True:
        try:
            val = float(input(prompt).strip())
            if val >= lo:
                return val
        except ValueError:
            pass
        print(f"  ✗  Numbers only, minimum {lo}.")


# ── Pomodoro timer ────────────────────────────────────────────────────────────

class _Timer:
    def __init__(self, total_seconds: int) -> None:
        self.total    = total_seconds
        self.elapsed  = 0
        self._paused  = False
        self._stopped = False
        self._lock    = threading.Lock()
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self.done     = threading.Event()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
        self.done.set()

    def toggle_pause(self) -> bool:
        with self._lock:
            self._paused = not self._paused
        return self._paused

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.total - self.elapsed)

    def _run(self) -> None:
        while True:
            time.sleep(1)
            with self._lock:
                if self._stopped:
                    break
                if not self._paused:
                    self.elapsed += 1
                    if self.elapsed >= self.total:
                        break
        self.done.set()


def _fmt(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _read_cmd() -> Optional[str]:
    """Non-blocking stdin check; returns stripped lowercase line or None."""
    if os.name == "nt":
        import msvcrt
        if msvcrt.kbhit():
            line = ""
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    break
                line += ch
            return line.strip().lower() or None
        return None
    else:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if ready:
            return sys.stdin.readline().strip().lower() or None
        return None


def run_countdown(label: str, total_seconds: int, icon: str) -> Tuple[int, str]:
    """
    Countdown with live display.  Commands (type + Enter):
      d — done / finished early
      p — pause / resume
      q — quit the whole session
    Returns (elapsed_seconds, "done"|"quit"|"timeout").
    """
    timer = _Timer(total_seconds)
    timer.start()

    print(f"\n  Commands:  [d] done early   [p] pause/resume   [q] quit session")

    last_display = ""
    result       = "timeout"

    while not timer.done.is_set():
        cmd = _read_cmd()
        if cmd == "d":
            timer.stop()
            result = "done"
            break
        elif cmd == "p":
            paused = timer.toggle_pause()
            state  = "PAUSED ⏸" if paused else "RESUMED ▶"
            print(f"\r  {icon}  {label}  [{_fmt(timer.remaining)}]  *** {state} ***     ")
        elif cmd == "q":
            timer.stop()
            result = "quit"
            break

        display = f"\r  {icon}  {label}  [{_fmt(timer.remaining)}]   "
        if display != last_display:
            print(display, end="", flush=True)
            last_display = display
        time.sleep(0.25)

    print()
    return timer.elapsed, result


# ── Today view ────────────────────────────────────────────────────────────────

def display_today_tasks(today: date) -> None:
    banner(f"  {today.strftime('%A, %B %d, %Y')}  ")

    # ── Fixed class blocks ─────────────────────────────────────────────────
    classes = db.get_classes_for_day(today)
    if classes:
        print("\n  ┌─ Today's Classes (fixed) ──────────────────────────┐")
        for c in classes:
            hrs = db._time_diff_hours(c["start_time"], c["end_time"])
            loc = f"  [{c['location']}]" if c["location"] else ""
            print(f"  │  📚 {c['course_name']:<18}  "
                  f"{c['start_time']}–{c['end_time']}  ({hrs:.1f}h){loc}")
        total_cls = db.get_class_hours_for_day(today)
        print(f"  │  Total class time: {total_cls:.1f}h")
        print("  └────────────────────────────────────────────────────┘")

    # ── Scheduled tasks ────────────────────────────────────────────────────
    tasks = db.get_tasks_for_date(today)

    if not tasks:
        print("\n  ⚠  No tasks scheduled for today from the Weekly Planner.")
        print("  → Run weekly_planner.py to set up your week,")
        print("    or use option 2 to add an ad-hoc task.")
        return

    weekly = [t for t in tasks if t.source == "weekly"]
    adhoc  = [t for t in tasks if t.source == "adhoc"]

    if weekly:
        print("\n  ┌─ From Weekly Planner ───────────────────────────────┐")
        for t in weekly:
            mark = "✓" if t.completed else "○"
            dl   = t.deadline.strftime("%m/%d")
            print(f"  │  {mark} [{t.quadrant.value}] {t.name:<30}  "
                  f"{t.remaining_minutes:>5.0f}m  dl:{dl}")
            for s in t.subtasks:
                sm = "✓" if s.completed else "·"
                print(f"  │       {sm} {s.name}  ({s.estimated_minutes:.0f}m)")
        print("  └────────────────────────────────────────────────────┘")

    if adhoc:
        print("\n  ┌─ Ad-Hoc Tasks ──────────────────────────────────────┐")
        for t in adhoc:
            mark = "✓" if t.completed else "○"
            print(f"  │  {mark} {t.name:<36}  {t.remaining_minutes:>5.0f}m")
            for s in t.subtasks:
                sm = "✓" if s.completed else "·"
                print(f"  │       {sm} {s.name}  ({s.estimated_minutes:.0f}m)")
        print("  └────────────────────────────────────────────────────┘")


# ── Ad-hoc task ───────────────────────────────────────────────────────────────

def add_adhoc_task(today: date) -> None:
    week_start = today - timedelta(days=today.weekday())

    print("\n  ── Add Ad-Hoc Task ──")
    name = input("  Task name: ").strip()
    if not name:
        print("  Cancelled.")
        return

    # ── Deduplication: check entire week, not just today ──────────────────
    existing = db.task_in_week_by_name(name, week_start)
    if existing:
        sched_entries = db.get_schedule_for_week(week_start)
        days_scheduled = sorted({
            e["day_date"] for e in sched_entries
            if e["task_id"] == existing.id
        })
        days_str = ", ".join(
            date.fromisoformat(d).strftime("%a %b %d") for d in days_scheduled)
        print(f"\n  ⚠  '{name}' already exists in this week's plan.")
        print(f"     Scheduled on: {days_str}")
        print(f"     P={existing.priority_score:.2f}  |  "
              f"{existing.remaining_minutes:.0f}m remaining")
        print()
        print("  Options:")
        print("  1  Keep as-is (do nothing — avoid duplicate)")
        print("  2  Move it to today  (reschedule to today instead)")
        print("  3  Add anyway as a separate task")
        choice = input("  › ").strip()

        if choice == "1":
            print("  No change made.")
            return

        elif choice == "2":
            # Remove from other days, add to today
            with db._conn() as conn:
                conn.execute(
                    "DELETE FROM weekly_schedule WHERE task_id=?",
                    (existing.id,))
            db.insert_schedule_entry(week_start, today, existing.id,
                                     existing.remaining_minutes)
            print(f"  ✓ '{name}' moved to today.")
            return

        # choice == "3": fall through to create new task

    hours      = prompt_float("  Estimated hours: ")
    urgency    = prompt_int("  Urgency    [1–5]: ", 1, 5)
    importance = prompt_int("  Importance [1–5]: ", 1, 5)

    quadrant = scheduler.classify_quadrant(urgency, importance)
    score    = scheduler.compute_priority_score(urgency, importance, quadrant, today)

    task = Task(
        id=None, name=name,
        urgency=urgency, importance=importance,
        time_allocation=hours, remaining_minutes=hours * 60,
        deadline=today, quadrant=quadrant, priority_score=score,
        source="adhoc", week_start=week_start, notes="",
    )
    task_id = db.insert_task(task)
    task.id = task_id
    db.insert_schedule_entry(week_start, today, task_id, hours * 60)

    if input("  Add sub-tasks? (y/n): ").strip().lower() == "y":
        idx = 0
        while True:
            sub_name = input(f"    Sub-task {idx+1} (blank = done): ").strip()
            if not sub_name:
                break
            sub_mins = prompt_float(f"    Minutes for '{sub_name}': ")
            sub = Subtask(id=None, task_id=task_id, name=sub_name,
                          estimated_minutes=sub_mins, order_index=idx)
            db.insert_subtask(sub)
            idx += 1

    print(f"\n  ✓ '{name}' added to today's schedule.")


# ── Pomodoro configuration ────────────────────────────────────────────────────

def configure_session() -> Tuple[int, int, SplitMode, int]:
    """Returns (focus_min, break_min, mode, min_slice_min)."""
    print("\n  ── Pomodoro Configuration ──")
    focus = prompt_int("  Focus duration (minutes, e.g. 50): ", 5, 120)

    auto_ans = input(f"  Auto break = Focus/5 = {focus//5}m? (y/n): ").strip().lower()
    brk      = (scheduler.break_for_focus(focus) if auto_ans == "y"
                else prompt_int("  Break duration (minutes): ", 1, 60))

    print("\n  Split mode:")
    print("  1  Chunk    — one task fills each Pomodoro block")
    print("  2  Sandwich — multiple tasks packed into one block")
    mode_choice = prompt_int("  › ", 1, 2)
    mode        = SplitMode.CHUNK if mode_choice == 1 else SplitMode.SANDWICH

    min_slice = 10
    if mode == SplitMode.SANDWICH:
        min_slice = prompt_int(
            f"  Minimum minutes per task slice (max {focus}): ", 5, focus)

    return focus, brk, mode, min_slice


# ── Sub-task completion handler ───────────────────────────────────────────────

def handle_completions(
    block:    PomodoroBlock,
    task_map: Dict[int, Task],
    today:    date,
) -> None:
    for sl in block.task_slices:
        t = task_map.get(sl["task_id"])
        if not t or t.completed:
            continue

        print(f"\n  Task: {t.name}  ({sl['minutes']:.0f}m allocated this block)")

        if t.subtasks:
            pending = [s for s in t.subtasks if not s.completed]
            for st in pending:
                ans = input(f"    Subtask '{st.name}' complete? (y/n): ").strip().lower()
                if ans == "y":
                    db.mark_subtask_complete(st.id, st.estimated_minutes)
                    st.completed = True
                    t.remaining_minutes = max(
                        0.0, t.remaining_minutes - st.estimated_minutes)
                    db.update_remaining_minutes(t.id, t.remaining_minutes)
            all_done = all(s.completed for s in t.subtasks)
        else:
            ans      = input(f"    Task fully complete? (y/n): ").strip().lower()
            all_done = ans == "y"

        if all_done:
            scheduler.recalculate_after_completion(t.id, today)
            t.completed = True
            print(f"  ✓ '{t.name}' complete — future blocks recalculated.")


# ── Main Pomodoro session ─────────────────────────────────────────────────────

def run_pomodoro_session(today: date) -> int:
    """Returns total focus minutes logged."""
    tasks = db.get_tasks_for_date(today)

    if not tasks:
        print("\n  ⚠  No tasks found for today.")
        print("  Make sure you have run weekly_planner.py and generated a schedule,")
        print("  or add ad-hoc tasks via option 2.")
        return 0

    # Refresh task_map with the full task objects
    task_map: Dict[int, Task] = {t.id: t for t in tasks}

    # Reuse existing day blocks if present
    existing_blocks = db.get_blocks_for_date(today)
    if existing_blocks:
        ans = input("\n  Existing session found for today. Continue it? (y/n): ").strip().lower()
        blocks: Optional[List[PomodoroBlock]] = existing_blocks if ans == "y" else None
    else:
        blocks = None

    focus, brk, mode, min_slice = configure_session()

    if blocks is None:
        schedule_entries = db.get_schedule_for_date(today)
        task_slices = [
            {"task_id": e["task_id"], "minutes": e["allocated_minutes"]}
            for e in schedule_entries
            if not task_map.get(e["task_id"],
               Task(None,"",1,1,0,0,today,__import__("models").Quadrant.N,0)).completed
        ]

        if not task_slices:
            print("\n  All of today's tasks are already complete — nothing to schedule!")
            return 0

        blocks = scheduler.build_daily_blocks(task_slices, focus, brk, mode, min_slice)
        for i, b in enumerate(blocks):
            b.block_date  = today
            b.block_index = i
            b.id = db.insert_pomodoro_block(b)

    total_focus_s = 0
    total_blocks  = len(blocks)

    clear()
    banner(f"  Pomodoro Session — {today.strftime('%A, %b %d')}  ")
    print(f"\n  {total_blocks} block(s) | {mode.value} mode | "
          f"focus {focus}m + break {brk}m")

    # Show a compact task list so the user knows what's loaded
    print("\n  Tasks loaded for this session:")
    for t in tasks:
        if not t.completed:
            src = " [ad-hoc]" if t.source == "adhoc" else ""
            print(f"    • {t.name}{src}  ({t.remaining_minutes:.0f}m)")

    print()
    input("  Press Enter to begin the first block...")

    for num, block in enumerate(blocks, 1):
        if block.completed:
            continue

        clear()
        banner(f"  Block {num} / {total_blocks}  ")
        print("\n  Tasks this block:")
        for sl in block.task_slices:
            t = task_map.get(sl["task_id"])
            name = t.name if t else f"Task #{sl['task_id']}"
            print(f"    • {name}: {sl['minutes']:.0f}m")

        # Focus countdown
        elapsed_s, cmd = run_countdown(f"Block {num} Focus", focus * 60, FOCUS_MASCOT)

        if cmd == "quit":
            db.mark_block_complete(block.id, elapsed_s // 60)
            total_focus_s += elapsed_s
            print("\n  Session ended early.")
            break

        total_focus_s += elapsed_s

        # Completion check
        handle_completions(block, task_map, today)
        db.mark_block_complete(block.id, elapsed_s // 60)

        # Break (skip after last block)
        if num < total_blocks:
            print(f"\n  Break — {brk} minutes.")
            _, cmd = run_countdown("Break", brk * 60, BREAK_MASCOT)
            if cmd == "quit":
                print("  Session ended.")
                break

    total_focus_min = total_focus_s // 60
    print(f"\n  ✓ Session complete. Total focus: {total_focus_min}m")
    return total_focus_min


# ── Test cheat code ──────────────────────────────────────────────────────────

_CHEAT_CODE = "RAYISGOINGTOBERKELEYNEXTYEAR"

def _simulate_day_complete(today: date) -> int:
    """
    Dev shortcut: instantly marks every pending task and every pomodoro block
    for *today* as complete, then returns the simulated total focus minutes.
    Triggered by typing the cheat code at the main menu.
    """
    tasks = db.get_tasks_for_date(today)
    if not tasks:
        print("\n  [TEST] No tasks to simulate — add some first.")
        return 0

    total_sim_minutes = 0

    for t in tasks:
        if t.completed:
            continue
        # Complete all subtasks
        for st in t.subtasks:
            if not st.completed:
                db.mark_subtask_complete(st.id, st.estimated_minutes)
        # Complete the task itself
        db.mark_task_complete(t.id)
        total_sim_minutes += int(t.remaining_minutes)

    # Mark all today's blocks complete
    blocks = db.get_blocks_for_date(today)
    for b in blocks:
        if not b.completed:
            db.mark_block_complete(b.id, b.focus_minutes)

    # If no blocks existed yet, compute simulated focus from task time
    if not blocks:
        total_sim_minutes = total_sim_minutes   # already set above
    else:
        total_sim_minutes = sum(b.focus_minutes for b in blocks)

    print(f"\n  [TEST] Simulated full Pomodoro day complete.")
    print(f"  [TEST] {len(tasks)} task(s) marked done, "
          f"{total_sim_minutes}m focus logged.")
    print(f"  [TEST]  Ray is going to Berkeley next year 🎉")
    return total_sim_minutes


# ── End-of-day report ─────────────────────────────────────────────────────────

def generate_report(today: date, total_focus_min: int) -> None:
    clear()
    banner(f"  End-of-Day Report — {today.strftime('%B %d, %Y')}  ")

    tasks      = db.get_tasks_for_date(today)
    done       = [t for t in tasks if     t.completed]
    incomplete = [t for t in tasks if not t.completed]

    print(f"\n  Completed ({len(done)}):")
    for t in done:
        print(f"    ✓  {t.name}")

    if incomplete:
        print(f"\n  Incomplete ({len(incomplete)}):")
        for t in incomplete:
            print(f"    ○  {t.name}  —  {t.remaining_minutes:.0f}m remaining")
        print(RESENTFUL_MASCOT)
    else:
        print(HAPPY_MASCOT)

    carried_ids: List[int] = []
    if incomplete:
        ans = input("  Carry incomplete tasks to tomorrow? (y/n): ").strip().lower()
        if ans == "y":
            tomorrow   = today + timedelta(days=1)
            tom_monday = tomorrow - timedelta(days=tomorrow.weekday())
            for t in incomplete:
                db.insert_schedule_entry(tom_monday, tomorrow, t.id,
                                         t.remaining_minutes)
                carried_ids.append(t.id)
            print(f"\n  ✓ {len(carried_ids)} task(s) carried to "
                  f"{tomorrow.strftime('%A, %b %d')}.")

    db.save_daily_report(today, len(done), len(incomplete),
                         total_focus_min, carried_ids)
    print(f"\n  Total focus time today: {total_focus_min}m")


# ── Main menu ─────────────────────────────────────────────────────────────────

def main() -> None:
    db.init_db()
    today           = date.today()
    total_focus_min = 0

    while True:
        clear()
        banner(f"  Daily Planner — {today.strftime('%A, %B %d, %Y')}  ")

        # Startup summary: how many tasks are loaded
        tasks   = db.get_tasks_for_date(today)
        pending = [t for t in tasks if not t.completed]
        classes = db.get_classes_for_day(today)

        if classes:
            class_h = db.get_class_hours_for_day(today)
            names   = ", ".join(c["course_name"] for c in classes)
            print(f"\n  📚 Classes today: {names}  ({class_h:.1f}h blocked)")

        if pending:
            weekly_n = sum(1 for t in pending if t.source == "weekly")
            adhoc_n  = sum(1 for t in pending if t.source == "adhoc")
            print(f"  Tasks pending: {len(pending)}  "
                  f"({weekly_n} from weekly plan, {adhoc_n} ad-hoc)")
        else:
            print("  ⚠  No pending tasks found for today.")

        print()
        print("  1  View today's schedule")
        print("  2  Add ad-hoc task")
        print("  3  Start / continue Pomodoro session")
        print("  4  Change date")
        print("  5  Exit")

        choice = input("\n  › ").strip()

        if choice == _CHEAT_CODE:
            simulated = _simulate_day_complete(today)
            total_focus_min += simulated
            input("\n  Press Enter to generate today's report...")
            generate_report(today, total_focus_min)
            today           = today + timedelta(days=1)
            total_focus_min = 0
            input(f"\n  ➜  Moving to {today.strftime('%A, %b %d')}. Press Enter...")
            continue

        if choice == "1":
            clear()
            display_today_tasks(today)
            input("\n  Press Enter to continue...")

        elif choice == "2":
            clear()
            add_adhoc_task(today)
            input("\n  Press Enter to continue...")

        elif choice == "3":
            mins = run_pomodoro_session(today)
            total_focus_min += mins
            all_blocks = db.get_blocks_for_date(today)
            if all_blocks and all(b.completed for b in all_blocks):
                input("\n  All blocks finished — generating today's report. Press Enter...")
                generate_report(today, total_focus_min)
                today           = today + timedelta(days=1)
                total_focus_min = 0
                input(f"\n  ➜  Moving to {today.strftime('%A, %b %d')}. Press Enter...")
            else:
                input("\n  Press Enter to continue...")

        elif choice == "4":
            raw = input("  Date (YYYY-MM-DD): ").strip()
            try:
                today           = date.fromisoformat(raw)
                total_focus_min = 0
                report          = db.get_daily_report(today)
                if report:
                    total_focus_min = report["total_focus_minutes"]
                    print(f"  Loaded saved report: {total_focus_min}m focus logged.")
            except ValueError:
                print("  ✗  Invalid date.")
            input("  Press Enter to continue...")

        elif choice == "5":
            print("\n  Goodbye!\n")
            sys.exit(0)


if __name__ == "__main__":
    main()
