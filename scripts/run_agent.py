#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dynamic_os.runtime import DynamicResearchRuntime
from src.server.settings import RUN_EVENT_PREFIX, RUN_LOG_PREFIX, RUN_STATE_PREFIX


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dynamic Research OS CLI")
    parser.add_argument("--topic", required=False, help="Research topic or question")
    parser.add_argument("--user_request", type=str, default=None, help="Full user request")
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    if not args.topic and not args.user_request:
        parser.error("either --topic or --user_request must be provided")
    return args


def _print_line(prefix: str, payload: object) -> None:
    if isinstance(payload, str):
        print(f"{prefix}{payload}", flush=True)
        return
    print(f"{prefix}{json.dumps(payload, ensure_ascii=False)}", flush=True)


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    user_request = str(args.user_request or args.topic or "").strip()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else (ROOT / "outputs").resolve()

    def emit_event(payload: dict) -> None:
        _print_line(RUN_EVENT_PREFIX, payload)

    try:
        runtime = DynamicResearchRuntime(root=ROOT, output_root=output_dir, event_sink=emit_event)
        result = await runtime.run(user_request=user_request)
    except ValueError as exc:
        _print_line(RUN_LOG_PREFIX, f"[dynamic_os invalid run configuration: {exc}]")
        return 1
    except Exception as exc:
        _print_line(RUN_LOG_PREFIX, f"[dynamic_os run failed: {exc}]")
        return 1

    _print_line(
        RUN_STATE_PREFIX,
        {
            "run_id": result.run_id,
            "status": result.status,
            "route_plan": result.route_plan,
            "node_status": result.node_status,
            "artifacts": result.artifacts,
            "report_text": result.report_text,
        },
    )
    print(result.report_text, flush=True)
    return 0


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
