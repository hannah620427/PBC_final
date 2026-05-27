"""SQLite data layer — all reads and writes go through here."""

import sqlite3
import json
from pathlib import Path
from datetime import date
from typing import List, Optional

from models import Task, Subtask, PomodoroBlock, Quadrant

DB_PATH = Path(__file__).parent / "data" / "planner.db"


# ── Connection ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL,
                urgency           INTEGER NOT NULL CHECK(urgency    BETWEEN 1 AND 5),
                importance        INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
                time_allocation   REAL    NOT NULL,
                remaining_minutes REAL    NOT NULL,
                deadline          TEXT    NOT NULL,
                quadrant          TEXT    NOT NULL,
                priority_score    REAL    NOT NULL,
                completed         INTEGER NOT NULL DEFAULT 0,
                source            TEXT    NOT NULL DEFAULT 'weekly',
                week_start        TEXT,
                notes             TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS subtasks (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id           INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                name              TEXT    NOT NULL,
                completed         INTEGER NOT NULL DEFAULT 0,
                estimated_minutes REAL    NOT NULL DEFAULT 30,
                actual_minutes    REAL    NOT NULL DEFAULT 0,
                remaining_minutes REAL    NOT NULL DEFAULT -1,
                order_index       INTEGER NOT NULL DEFAULT 0
            );

            -- Canonical daily assignment for every task (weekly and adhoc)
            CREATE TABLE IF NOT EXISTS weekly_schedule (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start        TEXT    NOT NULL,
                day_date          TEXT    NOT NULL,
                task_id           INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                allocated_minutes REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pomodoro_blocks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                block_date     TEXT    NOT NULL,
                block_index    INTEGER NOT NULL,
                focus_minutes  INTEGER NOT NULL,
                break_minutes  INTEGER NOT NULL,
                task_slices    TEXT    NOT NULL,   -- JSON array
                completed      INTEGER NOT NULL DEFAULT 0,
                actual_minutes INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date         TEXT    NOT NULL UNIQUE,
                completed_count     INTEGER NOT NULL DEFAULT 0,
                incomplete_count    INTEGER NOT NULL DEFAULT 0,
                total_focus_minutes INTEGER NOT NULL DEFAULT 0,
                carried_over_ids    TEXT    NOT NULL DEFAULT '[]',
                created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- Recurring class schedule valid for the whole term
            CREATE TABLE IF NOT EXISTS term_classes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name  TEXT    NOT NULL,
                day_of_week  INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
                start_time   TEXT    NOT NULL,   -- HH:MM (24-hour)
                end_time     TEXT    NOT NULL,   -- HH:MM (24-hour)
                term_start   TEXT    NOT NULL,   -- YYYY-MM-DD
                term_end     TEXT    NOT NULL,   -- YYYY-MM-DD
                location     TEXT    NOT NULL DEFAULT ''
            );

            -- Weekly difficulty feedback; drives adaptive time suggestions
            CREATE TABLE IF NOT EXISTS difficulty_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name    TEXT    NOT NULL,
                week_start   TEXT    NOT NULL,
                difficulty   INTEGER NOT NULL CHECK(difficulty BETWEEN 0 AND 5),
                logged_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_name, week_start)
            );
        """)
        # Migration: add remaining_minutes to subtasks if not present
        cols = [r[1] for r in conn.execute("PRAGMA table_info(subtasks)").fetchall()]
        if "remaining_minutes" not in cols:
            conn.execute("ALTER TABLE subtasks ADD COLUMN remaining_minutes REAL NOT NULL DEFAULT -1")
            conn.execute("""
                UPDATE subtasks
                SET remaining_minutes = CASE WHEN completed=1 THEN 0 ELSE estimated_minutes END
            """)


# ── Tasks ─────────────────────────────────────────────────────────────────────

def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        name=row["name"],
        urgency=row["urgency"],
        importance=row["importance"],
        time_allocation=row["time_allocation"],
        remaining_minutes=row["remaining_minutes"],
        deadline=date.fromisoformat(row["deadline"]),
        quadrant=Quadrant(row["quadrant"]),
        priority_score=row["priority_score"],
        completed=bool(row["completed"]),
        source=row["source"],
        week_start=date.fromisoformat(row["week_start"]) if row["week_start"] else None,
        notes=row["notes"],
    )


def insert_task(task: Task) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO tasks
               (name, urgency, importance, time_allocation, remaining_minutes,
                deadline, quadrant, priority_score, completed, source, week_start, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task.name, task.urgency, task.importance,
             task.time_allocation, task.remaining_minutes,
             task.deadline.isoformat(), task.quadrant.value,
             task.priority_score, int(task.completed), task.source,
             task.week_start.isoformat() if task.week_start else None,
             task.notes),
        )
        return cur.lastrowid


def get_task(task_id: int) -> Optional[Task]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row:
        t = _row_to_task(row)
        t.subtasks = get_subtasks(task_id)
        return t
    return None


def get_all_tasks(
    week_start: Optional[date] = None,
    source:     Optional[str]  = None,
    completed:  Optional[bool] = None,
) -> List[Task]:
    query  = "SELECT * FROM tasks WHERE 1=1"
    params: list = []
    if week_start is not None:
        query += " AND week_start=?"
        params.append(week_start.isoformat())
    if source is not None:
        query += " AND source=?"
        params.append(source)
    if completed is not None:
        query += " AND completed=?"
        params.append(int(completed))
    query += " ORDER BY priority_score DESC"

    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    tasks = [_row_to_task(r) for r in rows]
    for t in tasks:
        t.subtasks = get_subtasks(t.id)
    return tasks


def get_tasks_for_date(day: date) -> List[Task]:
    """All incomplete tasks scheduled for *day* via weekly_schedule."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT t.* FROM tasks t
               JOIN weekly_schedule ws ON ws.task_id = t.id
               WHERE ws.day_date = ? AND t.completed = 0
               ORDER BY t.priority_score DESC""",
            (day.isoformat(),),
        ).fetchall()
    tasks = [_row_to_task(r) for r in rows]
    for t in tasks:
        t.subtasks = get_subtasks(t.id)
    return tasks


def task_on_date_by_name(name: str, day: date) -> bool:
    with _conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM tasks t
               JOIN weekly_schedule ws ON ws.task_id = t.id
               WHERE ws.day_date = ? AND LOWER(t.name) = LOWER(?) LIMIT 1""",
            (day.isoformat(), name),
        ).fetchone()
    return row is not None


def task_in_week_by_name(name: str, week_start: date) -> Optional[Task]:
    """Return the Task if *name* already exists anywhere in *week_start*'s week."""
    with _conn() as conn:
        row = conn.execute(
            """SELECT t.* FROM tasks t
               JOIN weekly_schedule ws ON ws.task_id = t.id
               WHERE ws.week_start = ? AND LOWER(t.name) = LOWER(?) LIMIT 1""",
            (week_start.isoformat(), name),
        ).fetchone()
    if row:
        t = _row_to_task(row)
        t.subtasks = get_subtasks(t.id)
        return t
    return None


def mark_task_complete(task_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE tasks SET completed=1, remaining_minutes=0 WHERE id=?",
            (task_id,),
        )


def update_remaining_minutes(task_id: int, minutes: float) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE tasks SET remaining_minutes=? WHERE id=?",
            (max(0.0, minutes), task_id),
        )


# ── Subtasks ──────────────────────────────────────────────────────────────────

def _row_to_subtask(row: sqlite3.Row) -> Subtask:
    est  = row["estimated_minutes"]
    rem  = row["remaining_minutes"]
    if rem < 0:          # -1 sentinel → not yet initialised
        rem = 0.0 if bool(row["completed"]) else est
    return Subtask(
        id=row["id"],
        task_id=row["task_id"],
        name=row["name"],
        completed=bool(row["completed"]),
        estimated_minutes=est,
        actual_minutes=row["actual_minutes"],
        remaining_minutes=rem,
        order_index=row["order_index"],
    )


def insert_subtask(subtask: Subtask) -> int:
    rem = subtask.remaining_minutes if subtask.remaining_minutes >= 0 else subtask.estimated_minutes
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO subtasks
               (task_id, name, completed, estimated_minutes, actual_minutes, remaining_minutes, order_index)
               VALUES (?,?,?,?,?,?,?)""",
            (subtask.task_id, subtask.name, int(subtask.completed),
             subtask.estimated_minutes, subtask.actual_minutes, rem, subtask.order_index),
        )
        return cur.lastrowid


def get_subtasks(task_id: int) -> List[Subtask]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subtasks WHERE task_id=? ORDER BY order_index",
            (task_id,),
        ).fetchall()
    return [_row_to_subtask(r) for r in rows]


def mark_subtask_complete(subtask_id: int, actual_minutes: float) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE subtasks SET completed=1, actual_minutes=?, remaining_minutes=0 WHERE id=?",
            (actual_minutes, subtask_id),
        )


def update_subtask_remaining(subtask_id: int, remaining: float) -> None:
    """Update sub-task remaining_minutes without marking it complete."""
    with _conn() as conn:
        conn.execute(
            "UPDATE subtasks SET remaining_minutes=? WHERE id=?",
            (max(0.0, remaining), subtask_id),
        )


# ── Weekly Schedule ───────────────────────────────────────────────────────────

def insert_schedule_entry(
    week_start: date, day_date: date, task_id: int, allocated_minutes: float
) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO weekly_schedule (week_start, day_date, task_id, allocated_minutes)
               VALUES (?,?,?,?)""",
            (week_start.isoformat(), day_date.isoformat(), task_id, allocated_minutes),
        )


def clear_schedule_for_week(week_start: date) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM weekly_schedule WHERE week_start=?",
            (week_start.isoformat(),),
        )


def get_schedule_for_week(week_start: date) -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM weekly_schedule WHERE week_start=? ORDER BY day_date, id",
            (week_start.isoformat(),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_schedule_for_date(day: date) -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM weekly_schedule WHERE day_date=? ORDER BY id",
            (day.isoformat(),),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Pomodoro Blocks ───────────────────────────────────────────────────────────

def insert_pomodoro_block(block: PomodoroBlock) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO pomodoro_blocks
               (block_date, block_index, focus_minutes, break_minutes,
                task_slices, completed, actual_minutes)
               VALUES (?,?,?,?,?,?,?)""",
            (block.block_date.isoformat(), block.block_index,
             block.focus_minutes, block.break_minutes,
             json.dumps(block.task_slices), int(block.completed),
             block.actual_minutes),
        )
        return cur.lastrowid


def get_blocks_for_date(day: date) -> List[PomodoroBlock]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pomodoro_blocks WHERE block_date=? ORDER BY block_index",
            (day.isoformat(),),
        ).fetchall()
    return [
        PomodoroBlock(
            id=r["id"],
            block_date=date.fromisoformat(r["block_date"]),
            block_index=r["block_index"],
            focus_minutes=r["focus_minutes"],
            break_minutes=r["break_minutes"],
            task_slices=json.loads(r["task_slices"]),
            completed=bool(r["completed"]),
            actual_minutes=r["actual_minutes"],
        )
        for r in rows
    ]


def mark_block_complete(block_id: int, actual_minutes: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE pomodoro_blocks SET completed=1, actual_minutes=? WHERE id=?",
            (actual_minutes, block_id),
        )


def update_block_slices(block_id: int, slices: List[dict]) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE pomodoro_blocks SET task_slices=? WHERE id=?",
            (json.dumps(slices), block_id),
        )


def get_future_blocks_with_task(task_id: int, after_date: date) -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pomodoro_blocks WHERE block_date > ? AND completed=0",
            (after_date.isoformat(),),
        ).fetchall()
    result = []
    for r in rows:
        slices = json.loads(r["task_slices"])
        if any(s["task_id"] == task_id for s in slices):
            result.append({"id": r["id"], "task_slices": slices})
    return result


# ── Daily Reports ─────────────────────────────────────────────────────────────

def save_daily_report(
    report_date: date,
    completed:   int,
    incomplete:  int,
    focus_mins:  int,
    carried_ids: List[int],
) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO daily_reports
               (report_date, completed_count, incomplete_count,
                total_focus_minutes, carried_over_ids)
               VALUES (?,?,?,?,?)
               ON CONFLICT(report_date) DO UPDATE SET
                 completed_count     = excluded.completed_count,
                 incomplete_count    = excluded.incomplete_count,
                 total_focus_minutes = excluded.total_focus_minutes,
                 carried_over_ids    = excluded.carried_over_ids""",
            (report_date.isoformat(), completed, incomplete,
             focus_mins, json.dumps(carried_ids)),
        )


def get_daily_report(report_date: date) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_reports WHERE report_date=?",
            (report_date.isoformat(),),
        ).fetchone()
    return dict(row) if row else None


# ── Term Classes ──────────────────────────────────────────────────────────────

def _time_diff_hours(start: str, end: str) -> float:
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    return max(0.0, (h2 * 60 + m2 - h1 * 60 - m1) / 60)


def insert_term_class(
    course_name: str,
    day_of_week: int,
    start_time:  str,
    end_time:    str,
    term_start:  date,
    term_end:    date,
    location:    str = "",
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO term_classes
               (course_name, day_of_week, start_time, end_time,
                term_start, term_end, location)
               VALUES (?,?,?,?,?,?,?)""",
            (course_name, day_of_week, start_time, end_time,
             term_start.isoformat(), term_end.isoformat(), location),
        )
        return cur.lastrowid


def get_term_classes() -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM term_classes ORDER BY day_of_week, start_time"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_term_class(class_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM term_classes WHERE id=?", (class_id,))


def get_classes_for_day(day: date) -> List[dict]:
    """Return all term classes that meet on *day* and are within their term dates."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM term_classes
               WHERE day_of_week = ?
                 AND term_start <= ?
                 AND term_end   >= ?
               ORDER BY start_time""",
            (day.weekday(), day.isoformat(), day.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def get_class_hours_for_day(day: date) -> float:
    """Total hours blocked by term classes on *day*."""
    classes = get_classes_for_day(day)
    return sum(_time_diff_hours(c["start_time"], c["end_time"]) for c in classes)


# ── Difficulty Log ────────────────────────────────────────────────────────────

# Multiplier table: difficulty 0→0.70, 1→0.85, 2→1.00, 3→1.15, 4→1.30, 5→1.45
DIFFICULTY_MULTIPLIER = {0: 0.70, 1: 0.85, 2: 1.00, 3: 1.15, 4: 1.30, 5: 1.45}


def log_difficulty(task_name: str, week_start: date, difficulty: int) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO difficulty_log (task_name, week_start, difficulty)
               VALUES (?,?,?)
               ON CONFLICT(task_name, week_start) DO UPDATE SET
                 difficulty = excluded.difficulty,
                 logged_at  = CURRENT_TIMESTAMP""",
            (task_name, week_start.isoformat(), difficulty),
        )


def get_latest_difficulty(task_name: str) -> Optional[int]:
    """Return the most recent difficulty score for a task name, or None."""
    with _conn() as conn:
        row = conn.execute(
            """SELECT difficulty FROM difficulty_log
               WHERE LOWER(task_name) = LOWER(?)
               ORDER BY logged_at DESC LIMIT 1""",
            (task_name,),
        ).fetchone()
    return row["difficulty"] if row else None


def get_tasks_from_week(week_start: date) -> List[Task]:
    """All tasks (completed or not) belonging to *week_start*."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE week_start=? ORDER BY priority_score DESC",
            (week_start.isoformat(),),
        ).fetchall()
    tasks = [_row_to_task(r) for r in rows]
    for t in tasks:
        t.subtasks = get_subtasks(t.id)
    return tasks

# ── Task Edit & Delete ────────────────────────────────────────────────────────

def update_task(
    task_id:           int,
    name:              str,
    urgency:           int,
    importance:        int,
    time_allocation:   float,
    remaining_minutes: float,
    quadrant:          Quadrant,   # ← 修正：移除字串 quote（BUG-5）
    priority_score:    float,
) -> None:
    """
    UPDATE 任務的可編輯欄位。
    deadline / source / week_start / notes / completed 維持不變。
    """
    with _conn() as conn:
        conn.execute(
            """UPDATE tasks
               SET name              = ?,
                   urgency           = ?,
                   importance        = ?,
                   time_allocation   = ?,
                   remaining_minutes = ?,
                   quadrant          = ?,
                   priority_score    = ?
               WHERE id = ?""",
            (name, urgency, importance,
             time_allocation, remaining_minutes,
             quadrant.value, priority_score,
             task_id),
        )


def delete_task(task_id: int) -> None:
    """
    【原子操作版】完整刪除一個任務，在單一 transaction 內執行：
      1. 從 pomodoro_blocks.task_slices（JSON）移除相關 slice
      2. 刪除 weekly_schedule entries（ON DELETE CASCADE 也會處理，此處顯式）
      3. 刪除 subtasks（ON DELETE CASCADE 也會處理，此處顯式）
      4. 刪除 tasks 本體

    修正 BUG-2：原本四個函式各自開 _conn()，
    現在全部合進同一個 with _conn() as conn，確保原子性。
    """
    with _conn() as conn:
        # ── 步驟 1：清理 pomodoro_blocks 的 JSON task_slices ──────────────
        rows = conn.execute(
            "SELECT id, task_slices FROM pomodoro_blocks WHERE completed = 0"
        ).fetchall()

        for row in rows:
            slices = json.loads(row["task_slices"])
            new_slices = [s for s in slices if s["task_id"] != task_id]
            if len(new_slices) != len(slices):      # 有異動才寫回
                conn.execute(
                    "UPDATE pomodoro_blocks SET task_slices = ? WHERE id = ?",
                    (json.dumps(new_slices), row["id"]),
                )

        # ── 步驟 2：刪除 weekly_schedule entries ──────────────────────────
        conn.execute(
            "DELETE FROM weekly_schedule WHERE task_id = ?",
            (task_id,),
        )

        # ── 步驟 3：刪除 subtasks ──────────────────────────────────────────
        conn.execute(
            "DELETE FROM subtasks WHERE task_id = ?",
            (task_id,),
        )

        # ── 步驟 4：刪除 task 本體 ────────────────────────────────────────
        conn.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,),
        )


# ── 以下三個函式保留，供其他地方單獨呼叫（如需要） ───────────────────────────

def delete_block_slices(task_id: int) -> None:
    """
    從所有未完成的 pomodoro_blocks 的 task_slices（JSON）中移除 task_id 的條目。
    注意：若需原子性，請使用 delete_task() 而非單獨呼叫此函式。
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, task_slices FROM pomodoro_blocks WHERE completed = 0"
        ).fetchall()

        for row in rows:
            slices = json.loads(row["task_slices"])
            new_slices = [s for s in slices if s["task_id"] != task_id]
            if len(new_slices) != len(slices):
                conn.execute(
                    "UPDATE pomodoro_blocks SET task_slices = ? WHERE id = ?",
                    (json.dumps(new_slices), row["id"]),
                )


def delete_schedule_entries(task_id: int) -> None:
    """刪除 weekly_schedule 中所有與 task_id 相關的排程列。"""
    with _conn() as conn:
        conn.execute(
            "DELETE FROM weekly_schedule WHERE task_id = ?",
            (task_id,),
        )


def delete_subtasks(task_id: int) -> None:
    """
    明確刪除 task_id 的所有 subtasks。
    （subtasks 表已設 ON DELETE CASCADE，但提供明確函式供外部直接呼叫。）
    """
    with _conn() as conn:
        conn.execute(
            "DELETE FROM subtasks WHERE task_id = ?",
            (task_id,),
        )
