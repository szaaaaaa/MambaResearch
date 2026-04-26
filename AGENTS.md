## Review guidelines

- Only flag real bugs — logic errors, off-by-one, null/None mishandling, race conditions.
- Flag security issues: injection, auth bypass, secrets exposure, SSRF.
- Flag performance problems: N+1 queries, unnecessary allocations, missing indexes.
- Flag dead code or unnecessary complexity.
- Do NOT comment on formatting, import order, or naming conventions unless they cause bugs.
- Do NOT suggest adding tests, logging, or error handling unless there is a concrete risk.
- If the PR is clean, say "LGTM" and nothing else.
- Be concise. No filler. For each issue: file, line, what's wrong, how to fix.

## Pipeline artifact naming convention

`.codex/skills/` (synced from `.claude/skills/` via NTFS junction) hosts 7 pipeline SKILL.md files. All sub-agents communicate via files under `outputs/<run_id>/` in the active project workspace; no in-memory artifact store.

### Path prefix

`outputs/<run_id>/` (under active project workspace root)

`run_id` formats by pipeline:
- `lit_review_<YYYYMMDD>_<HHMMSS>` — structured-lit-review
- `exp_<YYYYMMDD>_<HHMMSS>` — empirical-study
- `method_cmp_<YYYYMMDD>_<HHMMSS>` — method-comparison
- `iter_<YYYYMMDD>_<HHMMSS>` — experiment-iteration
- `review_<YYYYMMDD>_<HHMMSS>_<artifact_short_name>` — artifact-review
- `brainstorm_<YYYYMMDD>_<HHMMSS>` — idea-brainstorming
- `data_explore_<YYYYMMDD>_<HHMMSS>_<dataset_short_name>` — data-exploration

### Standard file names

| File | Producer | Content |
|---|---|---|
| `plan.md` | conductor | markdown checklist; visible pipeline progress |
| `sources.json` | paper-searcher | `[{title, authors, year, venue, abstract, url}]` |
| `evidence.json` | evidence-extractor | Per-paper relevant excerpts + counter-examples |
| `analysis.md` | analyzer | findings / conflicts / open_questions, each with evidence ref |
| `report.md` | writer | Final narrative (markdown by default; `report.tex` + `references.bib` for LaTeX) |
| `review.md` | reviewer | 5-dim scores + standard issue list + verdict |
| `critique.md` | critic | 🔴/🟠/🟡 severity issues + detailed reasoning |
| `experiments/exp_<NNN>/` | experimenter | Per-experiment subdir: `spec.md` + `script.py` + `result.json` + optional `lessons.md` |
| `sweep_plan.md` | experimenter | Sweep matrix + spec_overrides + compute estimate |
| `sweep_analysis.md` | analyzer | Sweep aggregate + best config + trend observations |

### Invariants

- **Never modify physical workspace files**: all artifacts go under `outputs/<run_id>/`; raw user data / paper PDFs / existing scripts are untouched.
- **One sub-agent owns one file**: paper-searcher only writes sources.json, analyzer only writes analysis.md / sweep_analysis.md, etc.
- **Main agent orchestrates**: after spawning a sub-agent, the main agent checks file existence to decide the next step. Sub-agents do not call each other.
