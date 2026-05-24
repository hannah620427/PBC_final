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
) -> tuple[dict, list[str]]:
    # 注意：回傳型態變更為 tuple，包含 schedule 字典與 warnings 清單
    if class_hours is None:
        class_hours = {}

    work_days = [start_date + timedelta(days=i) for i in range(7)]
    
    day_remaining = {}
    for d in work_days:
        blocked = class_hours.get(d, 0.0) * 60
        day_remaining[d] = max(0.0, hours_per_day * 60 - blocked)

    schedule = {d: [] for d in work_days}
    warnings = []

    # 統一計算本週低消配額 (Quota)
    weekly_quota = {}
    for t in tasks:
        days_until_dl = max(1, (t.deadline - start_date).days + 1)
        if days_until_dl > 7:
            base_quota = t.remaining_minutes * (7 / days_until_dl)
            pacing_factor = 0.5 + (t.priority_score / 5.0)
            quota = min(t.remaining_minutes, base_quota * pacing_factor)
        else:
            quota = t.remaining_minutes
        weekly_quota[t.id] = quota

    # 策略一：DEEP WORK (集中模式)
    if strategy == "deep_work":
        task_needs = {t.id: weekly_quota[t.id] for t in tasks}
        
        # 第一階段：保底與集中塞入 (以天為本位)
        for current_day in work_days:
            if day_remaining[current_day] <= 0:
                continue
                
            # A. 處理死線就在今天的任務 (無條件最優先，解決死線被霸凌的問題)
            must_finish_today = [t for t in tasks if current_day == t.deadline and task_needs[t.id] > 0]
            for t in must_finish_today:
                need = task_needs[t.id]
                if day_remaining[current_day] < need:
                    missing = need - day_remaining[current_day]
                    raise PomodoroDebtError(
                        f"Schedule failed! Task '{t.name}' lacks {missing:.0f} mins on deadline."
                    )
                schedule[current_day].append((t.id, need))
                day_remaining[current_day] -= need
                task_needs[t.id] = 0.0

            # B. 剩餘時間處理：找出還沒到期的任務
            active_tasks = [t for t in tasks if task_needs[t.id] > 0 and current_day < t.deadline]
            if not active_tasks or day_remaining[current_day] <= 0:
                continue
                
            # Deep Work 核心：依照分數高低排序，由最高分者獨佔剩餘時間！
            active_tasks.sort(key=lambda x: (-x.priority_score, x.deadline))
            
            for t in active_tasks:
                if day_remaining[current_day] <= 0:
                    break
                alloc = min(day_remaining[current_day], task_needs[t.id])
                if alloc > 0:
                    schedule[current_day].append((t.id, alloc))
                    day_remaining[current_day] -= alloc
                    task_needs[t.id] -= alloc

        # 檢驗階段：判斷報錯或產生軟性提醒
        for t in tasks:
            days_until_dl = (t.deadline - start_date).days + 1
            if task_needs[t.id] > 0.5:
                if days_until_dl <= 7:
                    raise PomodoroDebtError(
                        f"Schedule impossible! Urgent task '{t.name}' requires {task_needs[t.id]:.0f} more minutes."
                    )
                else:
                    warnings.append(
                        f"Task '{t.name}' missed its weekly pacing target by {task_needs[t.id]:.0f} mins."
                    )

        # 第二階段：填滿剩餘時間 (提前推進遠期任務)
        pass2_needs = {t.id: max(0.0, t.remaining_minutes - weekly_quota[t.id]) for t in tasks}
        
        for current_day in work_days:
            if day_remaining[current_day] <= 0:
                continue
                
            active_tasks = [t for t in tasks if pass2_needs[t.id] > 0.5 and current_day <= t.deadline]
            if not active_tasks:
                continue
                
            # 一樣由最高分優先填補空檔
            active_tasks.sort(key=lambda x: (-x.priority_score, x.deadline))
            
            for t in active_tasks:
                if day_remaining[current_day] <= 0:
                    break
                alloc = min(day_remaining[current_day], pass2_needs[t.id])
                if alloc > 0:
                    # 合併同一天內同一個任務的時數
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

        return schedule, warnings
    
    # 策略二：BALANCED (均衡模式)
    else:
        task_needs = {t.id: weekly_quota[t.id] for t in tasks}
        
        # 第一階段：按比例分配
        for current_day in work_days:
            if day_remaining[current_day] <= 0:
                continue
                
            must_finish_today = [t for t in tasks if current_day == t.deadline and task_needs[t.id] > 0]
            for t in must_finish_today:
                need = task_needs[t.id]
                if day_remaining[current_day] < need:
                    missing = need - day_remaining[current_day]
                    raise PomodoroDebtError(
                        f"Schedule failed! Task '{t.name}' lacks {missing:.0f} mins on deadline."
                    )
                schedule[current_day].append((t.id, need))
                day_remaining[current_day] -= need
                task_needs[t.id] = 0.0
                    
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

        # 檢驗階段：判斷報錯或產生軟性提醒
        for t in tasks:
            days_until_dl = (t.deadline - start_date).days + 1
            if task_needs[t.id] > 0.5:
                if days_until_dl <= 7:
                    raise PomodoroDebtError(
                        f"Insufficient time! Urgent task '{t.name}' lacks {task_needs[t.id]:.0f} mins."
                    )
                else:
                    warnings.append(
                        f"Task '{t.name}' missed its weekly pacing target by {task_needs[t.id]:.0f} mins."
                    )

        # 第二階段：填補彈性時間
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

        return schedule, warnings

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