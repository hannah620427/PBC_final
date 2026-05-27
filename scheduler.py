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
    start_date:            date, 
    hours_per_day:         float = 8.0,
    class_hours:           dict  = None,
    strategy:              str   = "balanced",
) -> dict:
    if class_hours is None:
        class_hours = {}

    work_days = [start_date + timedelta(days=i) for i in range(7)]

    # --- [新增：逾期任務處理機制] ---
    # 如果任務已經過期，強制把它的死線展延到「今天」，迫使系統立刻排程
    for t in tasks:
        if t.deadline < start_date:
            t.deadline = start_date
    # -----------------------------
    
    # Initialize daily available capacity in minutes
    day_remaining = {}
    for d in work_days:
        blocked = class_hours.get(d, 0.0) * 60
        day_remaining[d] = max(0.0, hours_per_day * 60 - blocked)

    schedule = {d: [] for d in work_days}

    # ── STRATEGY 1: DEEP WORK (Task-by-Task Greedy Vertical Allocation) ──
    if strategy == "deep_work":
        # Sort tasks by priority score descending, then by deadline ascending
        sorted_tasks = sorted(tasks, key=lambda x: (-x.priority_score, x.deadline))
        task_needs = {t.id: t.remaining_minutes for t in sorted_tasks}
        
        for t in sorted_tasks:
            remaining = task_needs[t.id]
            eligible_days = [d for d in work_days if d <= t.deadline] or work_days
            
            for day in eligible_days:
                if remaining <= 0:
                    break
                if day_remaining[day] <= 0:
                    continue
                
                alloc = min(remaining, day_remaining[day])
                if alloc > 0:
                    schedule[day].append((t.id, alloc))
                    day_remaining[day] -= alloc
                    remaining -= alloc
            task_needs[t.id] = remaining

        # Final validation to detect insufficient capacity
        for t in sorted_tasks:
            if task_needs[t.id] > 0.5:
                raise PomodoroDebtError(
                    f"Schedule impossible! Task '{t.name}' requires {task_needs[t.id]:.0f} more minutes "
                    f"but weekly time capacity is completely exhausted."
                )
        return schedule

    # ── STRATEGY 2: BALANCED (Two-Pass Proportional Linear Pacing Allocation) ──
    else:
        # Pass 1: Calculate and allocate mandatory weekly pacing quotas
        weekly_quota = {}
        for t in tasks:
            days_until_dl = max(1, (t.deadline - start_date).days + 1)
            if days_until_dl > 7:
                # Calculate base linear pacing quota
                base_quota = t.remaining_minutes * (7 / days_until_dl)
                
                # Priority-adjusted pacing multiplier (0.5x to 1.5x based on priority_score)
                pacing_factor = 0.5 + (t.priority_score / 5.0)
                
                # Apply factor and bound it by the total remaining minutes
                quota = min(t.remaining_minutes, base_quota * pacing_factor)
            else:
                # Full allocation required for tasks due within the current week
                quota = t.remaining_minutes
                
            weekly_quota[t.id] = quota

        task_needs = {t.id: weekly_quota[t.id] for t in tasks}
       
        # --- [優化開始] 先把任務按照死線 (deadline) 分類到字典裡 ---
        tasks_by_deadline = {}
        for t in tasks:
            tasks_by_deadline.setdefault(t.deadline, []).append(t)
        # --- [優化結束] ---

        # Chronological day-by-day distribution loop
        for current_day in work_days:
            if day_remaining[current_day] <= 0:
                continue
                
            # A. Enforce hard deadlines due on the current day
            must_finish_today = [t for t in tasks_by_deadline.get(current_day, []) if task_needs[t.id] > 0]
            for t in must_finish_today:
                need = task_needs[t.id]
                if day_remaining[current_day] < need:
                    missing = need - day_remaining[current_day]
                    raise PomodoroDebtError(
                        f"Schedule failed! Task '{t.name}' is due on {current_day.strftime('%m/%d')} ({current_day.strftime('%A')}), "
                        f"but lacks {missing:.0f} minutes of available capacity before deadline."
                    )
                schedule[current_day].append((t.id, need))
                day_remaining[current_day] -= need
                task_needs[t.id] = 0.0
                    
            # B. Distribute time to active tasks proportionally based on priority scores
            active_tasks = [t for t in tasks if task_needs[t.id] > 0 and current_day < t.deadline]
            if not active_tasks or day_remaining[current_day] <= 0:
                continue
                
            total_score = sum(t.priority_score for t in active_tasks)
            if total_score <= 0:
                weights = {t.id: 1.0 / len(active_tasks) for t in active_tasks}
            else:
                weights = {t.id: (t.priority_score / total_score) for t in active_tasks}

            day_capacity = day_remaining[current_day]
            for t in active_tasks:
                alloc = round(min(day_capacity * weights[t.id], task_needs[t.id]))
                if alloc > 0:
                    schedule[current_day].append((t.id, alloc))
                    day_remaining[current_day] -= alloc
                    task_needs[t.id] -= alloc

        # Pass 1 Validation: Ensure all tasks due this week met their minimum required quotas
        for t in tasks:
            days_until_dl = (t.deadline - start_date).days + 1
            if days_until_dl <= 7 and task_needs[t.id] > 0.5:
                raise PomodoroDebtError(
                    f"Insufficient time! Urgent task '{t.name}' due this week lacks {task_needs[t.id]:.0f} minutes of required pacing."
                )

        # Pass 2: Fill residual free time with future task quotas (opportunistic advancement)
        pass2_needs = {}
        for t in tasks:
            scheduled_in_pass1 = weekly_quota[t.id] - task_needs[t.id]
            pass2_needs[t.id] = max(0.0, t.remaining_minutes - scheduled_in_pass1)

        for current_day in work_days:
            if day_remaining[current_day] <= 0:
                continue

            active_tasks = [t for t in tasks if pass2_needs[t.id] > 0.5 and current_day <= t.deadline]
            if not active_tasks:
                continue

            total_score = sum(t.priority_score for t in active_tasks)
            if total_score <= 0:
                weights = {t.id: 1.0 / len(active_tasks) for t in active_tasks}
            else:
                weights = {t.id: (t.priority_score / total_score) for t in active_tasks}

            day_capacity = day_remaining[current_day]
            for t in active_tasks:
                alloc = round(min(day_capacity * weights[t.id], pass2_needs[t.id]))
                if alloc > 0:
                    # Append or merge time slices if the task already exists on this day
                    found = False
                    for i, (tid, mins) in enumerate(schedule[current_day]):
                        if tid == t.id:
                            schedule[current_day][i] = (tid, mins + alloc)
                            found = True
                            break
                    if not found:
                        schedule[current_day].append((t.id, alloc))

                    day_remaining[current_day] -= alloc
                    pass2_needs[t.id] -= alloc

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