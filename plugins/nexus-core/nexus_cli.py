#!/usr/bin/env python3
"""NEXUS CLI for deterministic task/fix lifecycle operations."""
from __future__ import annotations

import argparse
import json

from task_manager import TaskManager
from hooks.fix_queue import FixQueue


def cmd_status(args):
    tm = TaskManager()
    print(json.dumps(tm.status(), indent=2, ensure_ascii=False))
    return 0


def cmd_task_start(args):
    tm = TaskManager()
    task = tm.start_task(args.goal)
    print(json.dumps(task, indent=2, ensure_ascii=False))
    return 0


def cmd_task_close(args):
    tm = TaskManager()
    success = True if args.success else False
    task = tm.close_task(success=success, note=args.note or "")
    print(json.dumps(task, indent=2, ensure_ascii=False))
    return 0


def cmd_fix_stats(args):
    fq = FixQueue()
    print(json.dumps(fq.get_stats(), indent=2, ensure_ascii=False))
    return 0


def cmd_fix_process_one(args):
    fq = FixQueue()
    print(json.dumps(fq.process_one_task(executor="manual"), indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus", description="NEXUS CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_p = subparsers.add_parser("status", help="Show current status")
    status_p.set_defaults(func=cmd_status)

    task_p = subparsers.add_parser("task", help="Task lifecycle commands")
    task_sub = task_p.add_subparsers(dest="task_cmd", required=True)

    task_start = task_sub.add_parser("start", help="Start a task")
    task_start.add_argument("goal", help="Task goal")
    task_start.set_defaults(func=cmd_task_start)

    task_close = task_sub.add_parser("close", help="Close active task")
    close_group = task_close.add_mutually_exclusive_group(required=True)
    close_group.add_argument("--success", action="store_true", help="Mark task as successful")
    close_group.add_argument("--fail", action="store_true", help="Mark task as failed")
    task_close.add_argument("--note", default="", help="Closure note")
    task_close.set_defaults(func=cmd_task_close)

    fix_p = subparsers.add_parser("fix", help="Fix queue commands")
    fix_sub = fix_p.add_subparsers(dest="fix_cmd", required=True)

    fix_stats = fix_sub.add_parser("stats", help="Show fix queue stats")
    fix_stats.set_defaults(func=cmd_fix_stats)

    fix_process_one = fix_sub.add_parser("process-one", help="Process one pending fix task")
    fix_process_one.set_defaults(func=cmd_fix_process_one)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
