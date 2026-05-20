"""
Scheduling algorithms shared by both planners.
Weekly Planner calls these directly; Daily Planner imports them via Option-B.
"""

from datetime import date, timedelta
from typing import List

import database as db
from models import Task, PomodoroBlock, Quadrant, QUADRANT_WEIGHTS, SplitMode


# ── Classification & Scoring ──────────────────────────────────────────────────

def classify_quadrant(urgency: int, importance: int) -> Quadrant:
    urgent    = urgency    >= 3
    important = importance >= 3
    if urgent and important:      return Quadrant.UI
    if urgent and not important:  return Quadrant.UU
    if not urgent and important:  return Quadrant.INU
    return Quadrant.N


def compute_priority_score(
    urgency:    int,
    importance: int,
    quadrant:   Quadrant,
    deadline:   date,
) -> float:
    """
    score = quadrant_weight × (urgency×0.4 + importance×0.3 + deadline_factor×0.3)
    deadline_factor ramps from 0 (30+ days away) to 1 (today or overdue).
    Result is scaled to 0–10.
    """
    days_left       = (deadline - date.today()).days
    deadline_factor = max(0.0, 1.0 - days_left / 30.0)
    raw = (urgency    / 5.0 * 0.4
         + importance / 5.0 * 0.3
         + deadline_factor  * 0.3)
    return round(QUADRANT_WEIGHTS[quadrant] * raw * 10, 4)


def break_for_focus(focus_minutes: int) -> int:
    """Break = Focus / 5, minimum 5 minutes (per spec)."""
    return max(5, focus_minutes // 5)


# ── Weekly Allocation ─────────────────────────────────────────────────────────

class PomodoroDebtError(Exception):
    """Raised when total workload exceeds available weekly time."""


def allocate_weekly(
    tasks:                 List[Task],
    start_date:            date, # MODIFIED: Changed from week_start to start_date for flexibility
    hours_per_day:         float = 8.0,
    class_hours:           dict  = None,   # {date: float} hours blocked by term classes
    daily_task_cap_hours:  float = 5.0, # NEW: Max hours a single task can be allocated per day
) -> dict:
    """
    Distribute tasks across Mon–Fri of *week_start*'s week.
    class_hours subtracts fixed class time from each day's capacity.
    Returns {date: [(task_id, allocated_minutes), ...]}
    Raises PomodoroDebtError if infeasible.
    """
    if class_hours is None:
        class_hours = {}

    # MODIFIED: Schedule for the next 7 days starting from start_date (today)
    work_days = [start_date + timedelta(days=i) for i in range(7)]
    daily_task_cap_minutes = daily_task_cap_hours * 60 # NEW: Convert daily task cap to minutes

    # Per-day cap after subtracting class time
    day_caps: dict = {}
    for d in work_days:
        blocked = class_hours.get(d, 0.0) * 60      # hours → minutes
        day_caps[d] = max(0.0, hours_per_day * 60 - blocked)

    total_needed = sum(t.remaining_minutes for t in tasks)
    total_avail  = sum(day_caps.values())

    if total_needed > total_avail:
        class_total = sum(class_hours.get(d, 0.0) for d in work_days)
        raise PomodoroDebtError(
            f"Workload {total_needed/60:.1f}h exceeds available "
            f"{total_avail/60:.1f}h  "
            f"({hours_per_day}h/day × {len(work_days)} days "
            f"− {class_total:.1f}h classes)."
        )

    day_remaining = {d: day_caps[d] for d in work_days}
    schedule      = {d: []          for d in work_days}

    # Higher priority first; among ties, earlier deadline first
    sorted_tasks = sorted(tasks, key=lambda t: (-t.priority_score, t.deadline))

    # NEW: Track how much time each task has been allocated on a given day
    task_daily_allocation = {task.id: {day: 0.0 for day in work_days} for task in sorted_tasks}

    for task in sorted_tasks:
        remaining = task.remaining_minutes
        # Prefer days before the deadline; fall back to all days if needed
        eligible  = [d for d in work_days if d <= task.deadline] or work_days

        for day in eligible:
            if remaining <= 0:
                break
            if day_remaining[day] <= 0:
                continue

            # NEW: Calculate how much more time this task can be allocated on this day
            #      considering the daily task cap.
            current_task_allocated_today = task_daily_allocation[task.id][day]
            task_cap_for_today = max(0.0, daily_task_cap_minutes - current_task_allocated_today)

            # MODIFIED: Allocate considering remaining task time, day capacity, and daily task cap
            alloc = min(remaining, day_remaining[day], task_cap_for_today)

            if alloc > 0:
                schedule[day].append((task.id, alloc))
                day_remaining[day] -= alloc
                remaining          -= alloc
                task_daily_allocation[task.id][day] += alloc # NEW: Update daily allocation for this task

    return schedule


# ── Post-completion Recalculation ─────────────────────────────────────────────

def recalculate_after_completion(completed_task_id: int, on_date: date) -> None:
    """
    Mark a task complete, then redistribute its time from future Pomodoro
    blocks proportionally to the remaining tasks in those blocks.
    Called from Daily Planner (Option B integration point).
    """
    db.mark_task_complete(completed_task_id)

    future_blocks = db.get_future_blocks_with_task(completed_task_id, on_date)
    for block in future_blocks:
        freed   = sum(s["minutes"] for s in block["task_slices"]
                      if s["task_id"] == completed_task_id)
        remaining_slices = [s for s in block["task_slices"]
                            if s["task_id"] != completed_task_id]

        if remaining_slices and freed > 0:
            total = sum(s["minutes"] for s in remaining_slices)
            for s in remaining_slices:
                s["minutes"] = round(s["minutes"] + freed * (s["minutes"] / total), 1)

        db.update_block_slices(block["id"], remaining_slices)


# ── Daily Block Builder ───────────────────────────────────────────────────────

def build_daily_blocks(
    task_slices:       List[dict],
    focus_minutes:     int,
    break_minutes:     int,
    mode:              SplitMode,
    min_slice_minutes: int = 10,
) -> List[PomodoroBlock]:
    """
    Convert a flat list of task time-slices into ordered PomodoroBlocks.

    task_slices: [{"task_id": int, "minutes": float}, ...]

    CHUNK mode:    one task per block; carry over if it needs multiple blocks.
    SANDWICH mode: pack as many tasks as possible per block, respecting
                   min_slice_minutes so no task gets a trivially short slot.
    """
    blocks: List[PomodoroBlock] = []
    queue  = [(s["task_id"], float(s["minutes"])) for s in task_slices]
    idx    = 0

    while queue:
        current_slices: List[dict] = []

        if mode == SplitMode.CHUNK:
            task_id, minutes = queue[0]
            take = min(minutes, float(focus_minutes))
            current_slices.append({"task_id": task_id, "minutes": round(take, 1)})
            if take >= minutes:
                queue.pop(0)
            else:
                queue[0] = (task_id, minutes - take)

        else:  # SANDWICH
            remaining_focus = float(focus_minutes)
            while queue and remaining_focus >= min_slice_minutes:
                task_id, minutes = queue[0]
                take = min(minutes, remaining_focus)
                if take < min_slice_minutes:
                    break   # slice would be too small; leave for next block
                current_slices.append({"task_id": task_id, "minutes": round(take, 1)})
                remaining_focus -= take
                if take >= minutes:
                    queue.pop(0)
                else:
                    queue[0] = (task_id, minutes - take)

        if current_slices:
            blocks.append(PomodoroBlock(
                id=None,
                block_date=date.today(),   # caller should override
                block_index=idx,
                focus_minutes=focus_minutes,
                break_minutes=break_minutes,
                task_slices=current_slices,
            ))
            idx += 1

    return blocks