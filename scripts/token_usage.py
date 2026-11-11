"""Report the tokens a Claude Code session used, for issue comments and PR metrics.

Claude Code writes each session to ~/.claude/projects/<project>/<session id>.jsonl,
and each subagent (reviewer, tester) to <session id>/subagents/*.jsonl. Every model
call in those files carries a usage record. This script adds them up.

Examples:
    # This session so far (Claude Code sets CLAUDE_CODE_SESSION_ID)
    uv run python scripts/token_usage.py

    # This session since the previous issue comment
    uv run python scripts/token_usage.py --since 2026-11-12T09:30:00Z

    # Several sessions, for the Metrics block of a PR
    uv run python scripts/token_usage.py --session <id> --session <id>

It only reads local files and needs no network access or secrets.
"""

import argparse
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Dollars per million tokens: (input, output, cache read). Anthropic API list prices.
# Cache writes cost 1.25x input (5-minute cache) or 2x input (1-hour cache).
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}


@dataclass
class Usage:
    """Token counts summed over model calls."""

    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    calls: int = 0
    cost: float | None = 0.0  # None once a call used a model without a known price
    missing: list[str] = field(default_factory=list)  # sessions with no transcript here

    @property
    def total(self) -> int:
        return self.input + self.cache_write + self.cache_read + self.output


def find_transcripts(session_id: str) -> list[Path]:
    """Return the session's transcript and its subagent transcripts."""
    files: list[Path] = []
    for project in PROJECTS_DIR.glob("*"):
        main = project / f"{session_id}.jsonl"
        if main.exists():
            files.append(main)
            files.extend(sorted((project / session_id / "subagents").glob("*.jsonl")))
    return files


def read_calls(path: Path) -> Iterator[tuple[str, str, str, dict]]:
    """Yield (message id, timestamp, model, usage) for each model call in a transcript."""
    with path.open() as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = record.get("message") or {}
            if record.get("type") != "assistant" or not message.get("usage"):
                continue
            if message.get("model") == "<synthetic>":
                continue
            yield (
                message["id"],
                record.get("timestamp", ""),
                message.get("model", ""),
                message["usage"],
            )


def call_cost(model: str, usage: dict) -> float | None:
    """Return the dollar cost of one call at list prices, or None for an unknown model."""
    if model not in PRICES:
        return None
    price_in, price_out, price_read = PRICES[model]
    cache = usage.get("cache_creation") or {}
    write_1h = cache.get("ephemeral_1h_input_tokens", 0)
    write_5m = usage.get("cache_creation_input_tokens", 0) - write_1h
    dollars = (
        usage.get("input_tokens", 0) * price_in
        + write_5m * price_in * 1.25
        + write_1h * price_in * 2
        + usage.get("cache_read_input_tokens", 0) * price_read
        + usage.get("output_tokens", 0) * price_out
    )
    return dollars / 1_000_000


def sum_usage(session_ids: list[str], since: datetime | None) -> Usage:
    """Add up every model call in the given sessions, optionally only after `since`."""
    seen: set[str] = set()  # a call is split over several records; count it once
    total = Usage()
    for session_id in session_ids:
        files = find_transcripts(session_id)
        if not files:
            total.missing.append(session_id)
        for path in files:
            for message_id, timestamp, model, usage in read_calls(path):
                if message_id in seen:
                    continue
                if since and datetime.fromisoformat(timestamp) <= since:
                    continue
                seen.add(message_id)
                total.input += usage.get("input_tokens", 0)
                total.cache_write += usage.get("cache_creation_input_tokens", 0)
                total.cache_read += usage.get("cache_read_input_tokens", 0)
                total.output += usage.get("output_tokens", 0)
                total.calls += 1
                cost = call_cost(model, usage)
                total.cost = None if cost is None or total.cost is None else total.cost + cost
    return total


def format_line(usage: Usage) -> str:
    """Return the one-line summary that goes into a comment or PR description."""
    cost = "unknown" if usage.cost is None else f"${usage.cost:.2f}"
    line = (
        f"{usage.total:,} tokens ({usage.output:,} output, {usage.cache_read:,} cache read, "
        f"{usage.input + usage.cache_write:,} other input) over {usage.calls} calls; "
        f"est. cost {cost} at API list prices"
    )
    if usage.missing:
        line += f"; no transcript on this machine for session(s) {', '.join(usage.missing)}"
    return line


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--session",
        action="append",
        help="session id; repeat for several (default: this session)",
    )
    parser.add_argument("--since", help="only count calls after this ISO timestamp")
    args = parser.parse_args()

    session_ids = args.session or [os.environ.get("CLAUDE_CODE_SESSION_ID", "")]
    if not session_ids[0]:
        sys.exit("Pass --session, or run inside Claude Code so CLAUDE_CODE_SESSION_ID is set")
    since = datetime.fromisoformat(args.since) if args.since else None
    if since and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)  # transcripts use UTC timestamps
    print(format_line(sum_usage(session_ids, since)))


if __name__ == "__main__":
    main()
