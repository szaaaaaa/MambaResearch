## Review guidelines

- Only flag real bugs — logic errors, off-by-one, null/None mishandling, race conditions.
- Flag security issues: injection, auth bypass, secrets exposure, SSRF.
- Flag performance problems: N+1 queries, unnecessary allocations, missing indexes.
- Flag dead code or unnecessary complexity.
- Do NOT comment on formatting, import order, or naming conventions unless they cause bugs.
- Do NOT suggest adding tests, logging, or error handling unless there is a concrete risk.
- If the PR is clean, say "LGTM" and nothing else.
- Be concise. No filler. For each issue: file, line, what's wrong, how to fix.
