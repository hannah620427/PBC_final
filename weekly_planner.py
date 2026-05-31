#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weekly Planner - Tomato Project Core Module
"""

import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
import database as db
import scheduler
from models import Task, Subtask, Quadrant, QUADRANT_LABELS
from mascots import DEAD_MASCOT

DAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ==========================================
# Terminal Helpers
# ==========================================
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
        print(f" ❌ Enter a whole number between {lo} and {hi}.")

def prompt_float(prompt: str, lo: float = 0.1) -> float:
    while True:
        try:
            val = float(input(prompt).strip())
            if val >= lo:
                return val
            print(f" ❌ Value must be ≥ {lo}.")
        except ValueError:
            print(" ❌ Numbers only.")

def prompt_time(prompt: str) -> str:
    """Prompt for HH:MM in 24-hour format."""
    while True:
        raw = input(prompt).strip()
        parts = raw.split(":")
        if len(parts) == 2:
            try:
                h = int(parts[0])
                m = int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    return f"{h:02d}:{m:02d}"
            except ValueError:
                pass
        print(" ❌ Format: HH:MM (e.g. 09:30)")

def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())

# ==========================================
# Day Picker
# ==========================================
def select_deadline(from_date: Optional[date] = None) -> date:
    """Show a numbered 3-week day menu and return the chosen date (must be today or future)."""
    base = from_date or date.today()
    days: List[date] = [base + timedelta(days=i) for i in range(21)]
    
    print()
    week_labels = {0: "--- This week: ---", 7: "--- Next week: ---", 14: "--- Week after: ---"}
    
    for i, d in enumerate(days):
        if i in week_labels:
            print(week_labels[i])
        print(f"  {i+1:>2}. ({DAYS_SHORT[d.weekday()]}) {d.strftime('%b %d, %Y')}")
    print()
    
    while True:
        raw = input(" Enter number (1-21) or YYYY-MM-DD: ").strip()
        chosen_date = None
        
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(days):
                chosen_date = days[idx]
            else:
                print(f" ❌ Number out of range. Please enter 1-{len(days)}.")
                continue
        else:
            try:
                chosen_date = date.fromisoformat(raw)
            except ValueError:
                print(" ❌ Invalid format. Please enter a valid number or YYYY-MM-DD.")
                continue
                
        if chosen_date < date.today():
            print(f" ❌ Deadline cannot be in the past! (Today is {date.today()}). Please try again.")
            input(" Press Enter to continue...")
            continue
            
        return chosen_date

# ==========================================
# Term Schedule Management
# ==========================================
def manage_term_schedule() -> None:
    while True:
        clear()
        banner(" Term Class Schedule ")
        classes = db.get_term_classes()
        
        if classes:
            print("\n Saved classes:\n")
            for c in classes:
                dow = DAYS_FULL[c["day_of_week"]]
                hrs = db._time_diff_hours(c["start_time"], c["end_time"])
                loc = f" [{c['location']}]" if c['location'] else ""
                print(f"  {c['id']:>3}. {c['course_name']:<18} {dow:<10} {c['start_time']}-{c['end_time']} ({hrs:.1f}h) {c['term_start']} → {c['term_end']}{loc}")
        else:
            print("\n No term classes saved yet.")
            
        while True:
            print("\n a Add class    d Delete class    b Back")
            choice = input(" > ").strip().lower()
            
            if choice == "a":
                _add_term_class()
                break
            elif choice == "d":
                if not classes:
                    input(" Nothing to delete. Press Enter...")
                    continue
                
                ids = [c["id"] for c in classes]
                while True:
                    raw_id = input(f" Class ID to delete {ids}: ").strip()
                    if raw_id.isdigit():
                        cid = int(raw_id)
                        if cid in ids:
                            break
                    print(f" ❌ Invalid ID. Please choose from {ids}.")
                    
                db.delete_term_class(cid)
                print(f" ✓ Class {cid} removed.")
                input(" Press Enter to continue...")
                break
            elif choice == "b":
                return
            else:
                print(" Only a, d, and b are allowed. Please try again.")
                input(" Press Enter to continue...")

def _add_term_class() -> None:
    print("\n - Add Term Class -")
    name = input(" Course name (e.g. MATH 101): ").strip()
    if not name:
        print(" Cancelled.")
        return
        
    print(" " + " ".join(f"[{i}={DAYS_SHORT[i]}]" for i in range(7)))
    dow = prompt_int(" Day of week [0=Mon 6=Sun]: ", 0, 6)
    start = prompt_time(" Start time (HH:MM 24-hour): ")
    end = prompt_time(" End time (HH:MM 24-hour): ")
    
    if end <= start:
        print(" ❌ End time must be after start time.")
        input(" Press Enter to continue...")
        return

    # ✨【程式夥伴修改】：新修正點 — 課程時間重疊過濾器
    # 抓出現有所有課表，逐一比對「星期幾」以及「時間區間」是否重疊
    existing_classes = db.get_term_classes()
    for c in existing_classes:
        if c["day_of_week"] == dow:
            # 標準區間重疊判定公式: start1 < end2 and end1 > start2
            if start < c["end_time"] and end > c["start_time"]:
                print(f" ❌ Class time overlaps with an existing class: '{c['course_name']}' ({c['start_time']}-{c['end_time']})!")
                input(" Press Enter to continue...")
                return
        
    print(" Select term start date:")
    term_start = select_deadline()
    print(" Select term end date:")
    term_end = select_deadline(term_start)
    
    if term_end < term_start:
        print(" ❌ End date must be on or after start date.")
        input(" Press Enter to continue...")
        return
        
    location = input(" Location / room (optional): ").strip()
    db.insert_term_class(name, dow, start, end, term_start, term_end, location)
    hours = db._time_diff_hours(start, end)
    print(f"\n '{name}' on {DAYS_FULL[dow]} {start}-{end} ({hours:.1f}h) saved.")
    input(" Press Enter to continue...")

# ==========================================
# Adaptive Difficulty Survey
# ==========================================
def run_difficulty_survey(last_week_start: date) -> None:
    tasks = db.get_tasks_from_week(last_week_start)
    if not tasks:
        print(" (No tasks found for last week; skipping difficulty review.)")
        return
        
    print(f"\n --- Last Week Review (week of {last_week_start}) ---")
    print(" 0 = trivially easy | 2 = about right | 5 = brutal\n")
    
    # ✨【程式夥伴修改】：新修正點 — 重複任務過濾器
    # 建立一個集合紀錄已經問過難度的任務名稱，避免同名任務重複轟炸使用者
    asked_tasks = set()
    
    for t in tasks:
        # 將名字轉小寫進行去重比對
        t_name_lower = t.name.strip().lower()
        if t_name_lower in asked_tasks:
            continue # 如果這個任務名字上一輪問過了，直接跳過不問！
            
        asked_tasks.add(t_name_lower)
        
        score = prompt_int(f" '{t.name}' difficulty [0-5]: ", 0, 5)
        db.log_difficulty(t.name, last_week_start, score)
        mult = db.DIFFICULTY_MULTIPLIER[score]
        adj = round(t.time_allocation * mult, 1)
        label = ", harder than expected" if score > 2 else " easier than expected" if score < 2 else " as expected"
        print(f" -> Adjusted allocation suggestion: {adj}h ({label})\n")

# ==========================================
# Task Survey
# ==========================================
def survey_one_task(week_start: date) -> Task:
    print("\n === New Task ===")
    name = input(" | Name: ").strip()
    if not name:
        raise ValueError("Task name cannot be empty.")
        
    existing = db.task_in_week_by_name(name, week_start)
    if existing:
        raise ValueError(f" '{name}' already exists this week (P = {existing.priority_score:.2f}).")
        
    diff_hint = db.get_latest_difficulty(name)
    suggested_h = 1.0
    
    last_week = week_start - timedelta(weeks=1)
    prev_tasks = db.get_tasks_from_week(last_week)
    prev_match = next((t for t in prev_tasks if t.name.lower() == name.lower()), None)
    
    if prev_match and diff_hint is not None:
        mult = db.DIFFICULTY_MULTIPLIER[diff_hint]
        suggested_h = round(prev_match.time_allocation * mult, 2)
        print(f" | i Last week: {prev_match.time_allocation}h, difficulty {diff_hint}/5 -> suggested {suggested_h}h")
    elif prev_match:
        suggested_h = prev_match.time_allocation
        print(f" | i Last week you allocated {suggested_h}h for this task.")
        
    print(" | Urgency and importance: 1 (low) to 5 (high).")
    urgency = prompt_int(" | Urgency [1-5]: ", 1, 5)
    importance = prompt_int(" | Importance [1-5]: ", 1, 5)
    
    raw_h = input(f" | Hours to complete [{suggested_h}]: ").strip()
    hours = float(raw_h) if raw_h else suggested_h
    if hours <= 0:
        raise ValueError("Hours must be > 0.")
        
    print(" | Choose deadline day:")
    deadline = select_deadline()
    notes = input(" | Notes (optional): ").strip()
    
    quadrant = scheduler.classify_quadrant(urgency, importance)
    score = scheduler.compute_priority_score(urgency, importance, quadrant, deadline)
    
    print(f" | Quadrant: {QUADRANT_LABELS[quadrant]} | Priority Score: {score:.2f}")
    
    task = Task(
        id=None, name=name, urgency=urgency, importance=importance,
        time_allocation=hours, remaining_minutes=hours * 60,
        deadline=deadline, quadrant=quadrant, priority_score=score,
        completed=0, source="weekly", week_start=week_start, notes=notes
    )
    
    task_id = db.insert_task(task)
    task.id = task_id
    
    while True:
        sub_ans = input(" Add sub-tasks? (y/n): ").strip().lower()
        if sub_ans in ['y', 'n']:
            break
        print(" ❌ Only y and n are allowed. Plz try again.")
        
    if sub_ans == "y":
        idx = 0
        while True:
            sub_name = input(f"   Sub-task {idx+1} name (blank = done): ").strip()
            if not sub_name:
                break
            sub_mins = prompt_float(f"   Estimated minutes for '{sub_name}': ")
            sub = Subtask(id=None, task_id=task_id, name=sub_name, estimated_minutes=sub_mins, order_index=idx)
            db.insert_subtask(sub)
            task.subtasks.append(sub)
            idx += 1
            
    return task

def run_survey(week_start: date) -> Tuple[List[Task], float]:
    clear()
    banner(f" Weekly Survey - Week of {week_start} ")
    print(f"\n Today: {date.today().strftime('%A, %B %d, %Y')}")
    
    work_days = [week_start + timedelta(days=i) for i in range(5)]
    class_total = sum(db.get_class_hours_for_day(d) for d in work_days)
    
    if class_total > 0:
        print("\n --- Classes blocking time this week ---")
        for d in work_days:
            ch = db.get_class_hours_for_day(d)
            if ch > 0:
                names = ", ".join(c["course_name"] for c in db.get_classes_for_day(d))
                print(f"  | {d.strftime('%a %b %d')}: {ch:.1f}h ({names})")
        print(f"  | Total blocked: {class_total:.1f}h\n")
        
    last_week = week_start - timedelta(weeks=1)
    last_week_tasks = db.get_tasks_from_week(last_week)
    
    if last_week_tasks:
        while True:
            ans = input("\n Review last week's task difficulty? (y/n): ").strip().lower()
            if ans in ['y', 'n']:
                break
            print(" ❌ Only y and n are allowed. Plz try again.")
            
        if ans == "y":
            run_difficulty_survey(last_week)
        else:
            print(" Skip review")
            
    print()
    hours_per_day = prompt_float(" Available productive hours per day (e.g. 6): ")
    while hours_per_day > 24:
        print(" You are alien! Why do you have more than 24 hours a day?")
        print(" Plz try again! within 24 hours")
        hours_per_day = prompt_float(" Available productive hours per day (e.g. 6): ")
        
    tasks: List[Task] = []
    while True:
        ans = input("\n Add a task? (y/n): ").strip().lower()
        if ans not in ['y', 'n']:
            print(" Only y and n are allowed. Plz try again.")
            continue
        if ans == 'n':
            if not tasks:
                print(" No tasks added.")
            break
        try:
            task = survey_one_task(week_start)
            tasks.append(task)
            print(f" '{task.name}' saved.")
        except ValueError as exc:
            print(f" ❌ {exc}")
            
    return tasks, hours_per_day

# ==========================================
# Display Logic
# ==========================================
def display_schedule(week_start: date) -> None:
    clear()
    banner(f" Week Schedule - Starting {date.today()} ")
    all_tasks = {t.id: t for t in db.get_all_tasks(week_start=week_start)}
    entries = db.get_schedule_for_week(week_start)
    
    if not entries:
        print("\n No schedule for this week. Run option 2 first.")
        return
        
    by_day = {}
    for e in entries:
        by_day.setdefault(e["day_date"], []).append(e)
        
    today = date.today()
    work_days = [today + timedelta(days=i) for i in range(7)]
    total_week_min = 0
    
    for d in work_days:
        day_str = d.isoformat()
        ch = db.get_class_hours_for_day(d)
        avail = max(0.0, 8.0 - ch)
        print(f"\n--- {d.strftime('%A, %b %d')} (~{avail:.1f}h free) ---")
        
        for c in db.get_classes_for_day(d):
            hrs = db._time_diff_hours(c["start_time"], c["end_time"])
            loc = f" [{c['location']}]" if c["location"] else ""
            print(f"  📖 {c['course_name']:<20} {c['start_time']}-{c['end_time']} ({hrs:.1f}h){loc}")
            
        if day_str in by_day:
            for e in by_day[day_str]:
                t = all_tasks.get(e["task_id"])
                if not t:
                    continue
                mins = e["allocated_minutes"]
                total_week_min += mins
                mark = "✓" if t.completed else "o"
                q_tag = f"[{t.quadrant.value}]"
                print(f"  {mark} {q_tag:<6} {t.name:<33} {mins:>5.0f}m  P={t.priority_score:.2f}")
        else:
            print("  (no tasks scheduled)")
            
    print(f"\n Week task total: {total_week_min/60:.1f}h")

def display_matrix(week_start: date) -> None:
    clear()
    banner(" Eisenhower Priority Matrix ")
    tasks = db.get_all_tasks(week_start=week_start, completed=False)
    groups = {q: [] for q in [Quadrant.UI, Quadrant.UU, Quadrant.INU, Quadrant.N]}
    
    for t in tasks:
        groups[t.quadrant].append(t)
        
    meta = {
        Quadrant.UI: ("DO FIRST", "50%", "================================="),
        Quadrant.UU: ("DELEGATE", "25%", "================================="),
        Quadrant.INU: ("SCHEDULE", "15%", "================================="),
        Quadrant.N: ("ELIMINATE", "10%", "=================================")
    }
    
    for q in [Quadrant.UI, Quadrant.UU, Quadrant.INU, Quadrant.N]:
        action, weight, bar = meta[q]
        print(f"\n {QUADRANT_LABELS[q]} ({weight}) -> {action}")
        print(bar)
        if groups[q]:
            for t in groups[q]:
                dl = t.deadline.strftime("%m/%d")
                print(f"  | {t.name[:38]:<38} dl:{dl} P:{t.priority_score:.1f} |")
        else:
            print("  | (no tasks)")
        print("-" * 45)

# ==========================================
# Core Algorithm Trigger
# ==========================================
def generate_schedule(week_start: date, hours_per_day: float) -> bool:
    tasks = db.get_all_tasks(week_start=week_start, completed=False)
    if not tasks:
        print("\n No tasks found for this week. Add tasks first.")
        return False
        
    today = date.today()
    work_days = [today + timedelta(days=i) for i in range(7)]
    class_hours = {d: db.get_class_hours_for_day(d) for d in work_days}
    
    try:
        allocation = scheduler.allocate_weekly(tasks, today, hours_per_day, class_hours)
    except scheduler.PomodoroDebtError as exc:
        clear()
        print(DEAD_MASCOT)
        print(f"\n ⚠️ 排程債務危機: {exc}")
        input("\n Press Enter to return to the menu...")
        return False
        
    db.clear_schedule_for_week(week_start)
    for day_date, entries in allocation.items():
        for task_id, minutes in entries:
            db.insert_schedule_entry(week_start, day_date, task_id, minutes)
            
    print(f"\n ✅ Schedule successfully generated starting from TODAY ({today}).")
    return True

def delete_task(week_start: date) -> None:
    clear()
    banner(" Delete Task ")
    tasks = db.get_all_tasks(week_start=week_start, completed=False)
    if not tasks:
        input(" No tasks to delete for this week. Press Enter...")
        return
        
    print("\n Current tasks:\n")
    for t in tasks:
        dl = t.deadline.strftime("%m/%d")
        print(f"  {t.id:>3}. {t.name:<33} dl:{dl} P:{t.priority_score:.1f}")
        
    while True:
        raw_id = input("\n Enter task ID to delete (or blank to cancel): ").strip()
        if not raw_id:
            print(" Cancelled.")
            return
        if raw_id.isdigit():
            task_id = int(raw_id)
            if any(t.id == task_id for t in tasks):
                db.delete_task(task_id)
                print(f" ✓ Task {task_id} removed.")
                input(" Press Enter to continue...")
                break
            else:
                print(" ❌ Invalid Task ID. Please enter a valid ID from the list.")
        else:
            print(" ❌ Invalid input. Please enter a number or leave blank to cancel.")

# ==========================================
# Main Program Loop
# ==========================================
def main() -> None:
    db.init_db()
    week_start = date.today()
    hours_per_day = 8.0
    
    while True:
        clear()
        banner(f" Weekly Planner - Week of {week_start} ")
        print(f"\n Today: {date.today().strftime('%A, %B %d, %Y')}")
        
        work_days = [week_start + timedelta(days=i) for i in range(5)]
        class_total = sum(db.get_class_hours_for_day(d) for d in work_days)
        if class_total > 0:
            print(f" Classes this week: {class_total:.1f}h blocked")
            
        while True:
            print()
            print(" 1  Manage term class schedule")
            print(" 2  Run weekly survey (tasks + difficulty review)")
            print(" 3  View week schedule")
            print(" 4  View priority matrix")
            print(" 5  Delete task")
            print(" 6  Regenerate schedule")
            print(" 7  Exit") 
            
            choice = input("\n > ").strip()
            
            if choice == "1":
                manage_term_schedule()
                break
            elif choice == "2":
                tasks, hours_per_day = run_survey(date.today())
                if tasks:
                    generate_schedule(date.today(), hours_per_day)
                input("\n Press Enter to continue...")
                break
            elif choice == "3":
                display_schedule(week_start)
                input("\n Press Enter to continue...")
                break
            elif choice == "4":
                display_matrix(week_start)
                input("\n Press Enter to continue...")
                break
            elif choice == "5":
                delete_task(week_start)
                break
            elif choice == "6":
                while True:
                    h = prompt_float(" Hours available per day: ")
                    if h <= 24.0:
                        break 
                    print(" ❌ You are alien! Why do you have more than 24 hours a day?")
                    print("    Plz try again! within 24 hours")
                    
                generate_schedule(week_start, h)
                input("\n Press Enter to continue...")
                break
            elif choice == "7":
                print("\n Goodbye!\n")
                sys.exit(0)
            else:
                print(" ❌ Only int between 1 and 7 are allowed. Plz try again.")
                input(" Press Enter to continue...")

if __name__ == "__main__":
    main()
