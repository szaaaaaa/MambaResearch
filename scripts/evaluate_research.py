"""Bounded evaluation scheduling and offline citation resolution; no model judge."""
import re


def resolved_targets(marker, answer, sources, bibliography=""):
    """Resolve explicit IDs or a bibliography entry that names the supplied paper."""
    documents = {s["id"]: s for s in sources}
    papers = {identifier.split("_all_")[0] for identifier in documents}

    def explicit(text):
        text = text.replace(chr(96), "").replace("\\_", "_")
        ids = set(re.findall(r"\b\d{4}\.\d{4,5}_all_\d+\b", text)) & set(documents)
        pattern = r"(?P<paper>\d{4}\.\d{4,5})_all_(?P<start>\d+)\s*[-–—]\s*(?:(?P=paper)_all_)?(?P<end>\d+)(?![\w.])"
        for match in re.finditer(pattern, text):
            start, end = int(match["start"]), int(match["end"])
            prefix = match["paper"] + "_all_"
            ids |= {identifier for identifier in documents if identifier.startswith(prefix)
                    and start <= int(identifier.rsplit("_", 1)[1]) <= end}
        remaining = re.sub(r"\b\d{4}\.\d{4,5}_all_\d+\b", "", text)
        ids |= set(re.findall(r"\b\d{4}\.\d{4,5}\b", remaining)) & papers
        return ids

    targets = explicit(marker)
    cite = re.fullmatch(r"\\cite(?:p|t)?\{([^}]+)\}", marker)
    if cite:
        entries = dict(re.findall(r"\\bibitem(?:\[[^\]]+\])?\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\}|\Z)", answer, re.S))
        # Entry boundaries, rather than a closing-brace regex, preserve nested titles.
        entries.update(dict(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*\{|\Z)", bibliography, re.S)))
        for key in cite.group(1).split(","):
            entry = entries.get(key.strip(), "")
            targets |= explicit(entry)
            normalized = re.sub(r"\W+", "", entry).casefold()
            for source in sources:
                title = re.sub(r"\W+", "", source.get("title", "")).casefold()
                if title and len(title) >= 12 and title in normalized:
                    targets.add(source["id"].split("_all_")[0])
    return targets



def _run_command(command, cwd, timeout):
    import os
    import signal
    import subprocess

    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace",
                          start_new_session=os.name != "nt") as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, check=False)
                if process.poll() is None:
                    process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            return None, stdout, stderr
        return process.returncode, stdout, stderr


def run_jobs(jobs, output, *, max_runs, timeout, runner=_run_command):
    import json
    from pathlib import Path

    if max_runs < 1 or timeout <= 0 or not isinstance(jobs, list) or not 1 <= len(jobs) <= max_runs:
        raise ValueError("job count must fit the explicit run budget; timeout must be positive")
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("command"), list) or not job["command"]:
            raise ValueError("each job requires an argv command")
        if any(not isinstance(arg, str) for arg in job["command"]) or not job.get("cwd") or not Path(job["cwd"]).is_dir():
            raise ValueError("each job requires string arguments and an existing cwd")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for index, job in enumerate(jobs):
        directory = output / f"run_{index + 1:03d}"
        directory.mkdir()
        try:
            code, stdout, stderr = runner(job["command"], job["cwd"], timeout)
        except OSError as exc:
            code, stdout, stderr = None, "", str(exc)
        error_text = stderr + ("\n" + stdout if code != 0 else "")
        limited = bool(re.search(r"\b429\b|usage[_ -]?limit|hit your usage limit|insufficient_quota|rate[_ -]?limit", error_text, re.I))
        failed_event = False
        for line in stdout.splitlines():
            candidate = line.removeprefix("[[RUN_STATE]]").strip()
            try:
                event = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(event, dict):
                is_failure = event.get("type") == "turn.failed" or event.get("status") in {"failed", "stopped"}
                failed_event |= is_failure
                if is_failure:
                    limited |= bool(re.search(r"\b429\b|usage[_ -]?limit|hit your usage limit|insufficient_quota|rate[_ -]?limit", line, re.I))
        status = "quota_exhausted" if limited else "failed" if code != 0 or failed_event else "process_completed"
        (directory / "stdout.log").write_text(stdout, encoding="utf-8")
        (directory / "stderr.log").write_text(stderr, encoding="utf-8")
        records.append({"index": index, "returncode": code, "status": status})
        (output / "execution.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        if status != "process_completed":
            break
    return records


def main():
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    batch = commands.add_parser("run")
    batch.add_argument("manifest", type=Path)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument("--max-runs", type=int, required=True)
    batch.add_argument("--timeout", type=int, required=True)
    batch.add_argument("--execute", action="store_true", help="Explicitly start the listed native commands")
    cite = commands.add_parser("citations")
    cite.add_argument("input", type=Path, help="JSON: marker, answer, sources, optional bibliography")
    args = parser.parse_args()
    if args.action == "citations":
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        print(json.dumps(sorted(resolved_targets(**payload))))
        return 0
    jobs = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not args.execute:
        print("Dry run: no commands started. Review the manifest and explicit budget before --execute.")
        return 0
    records = run_jobs(jobs, args.output, max_runs=args.max_runs, timeout=args.timeout)
    return 0 if len(records) == len(jobs) and all(r["status"] == "process_completed" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
