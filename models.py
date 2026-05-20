"""Shared dataclasses and enumerations used by both planners."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, List
from enum import Enum


class Quadrant(str, Enum):
    UI  = "UI"    # Urgent & Important
    UU  = "UU"    # Urgent but Unimportant
    INU = "INU"   # Important but Not Urgent
    N   = "N"     # Neither


QUADRANT_LABELS: dict = {
    Quadrant.UI:  "Urgent & Important",
    Quadrant.UU:  "Urgent but Unimportant",
    Quadrant.INU: "Important but Not Urgent",
    Quadrant.N:   "Neither",
}

# Weights from spec: 0.5 / 0.25 / 0.15 / 0.10
QUADRANT_WEIGHTS: dict = {
    Quadrant.UI:  0.50,
    Quadrant.UU:  0.25,
    Quadrant.INU: 0.15,
    Quadrant.N:   0.10,
}


class SplitMode(str, Enum):
    CHUNK    = "chunk"     # one task fills each Pomodoro block
    SANDWICH = "sandwich"  # multiple tasks packed into one block


@dataclass
class Subtask:
    id:                 Optional[int]
    task_id:            int
    name:               str
    completed:          bool  = False
    estimated_minutes:  float = 30.0
    actual_minutes:     float = 0.0
    order_index:        int   = 0


@dataclass
class Task:
    id:                Optional[int]
    name:              str
    urgency:           int          # 1–5
    importance:        int          # 1–5
    time_allocation:   float        # original hours
    remaining_minutes: float        # minutes still needed
    deadline:          date
    quadrant:          Quadrant
    priority_score:    float
    completed:         bool         = False
    source:            str          = "weekly"   # "weekly" | "adhoc"
    week_start:        Optional[date] = None
    notes:             str          = ""
    subtasks:          List[Subtask] = field(default_factory=list)


@dataclass
class PomodoroBlock:
    id:           Optional[int]
    block_date:   date
    block_index:  int
    focus_minutes: int
    break_minutes: int
    # [{"task_id": int, "minutes": float}, ...]
    task_slices:  List[dict]
    completed:    bool = False
    actual_minutes: int = 0
