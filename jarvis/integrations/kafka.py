"""Kafka integration — track Kafka activity from shell history.

Parses zsh/bash history for hfkcat and kcat commands to record
which Kafka topics were read/produced to, and when.

hfkcat is a HelloTech internal Kafka CLI tool.  Typical usage:
    hfkcat read "<topic>" -b lv -U "<service-name>" -10
The topics.yaml in ~/.claude/skills/hfkcat-read/ maps service names to topics.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from jarvis.integrations.base import RawEvent

# hfkcat read "<topic>" or hfkcat read <topic>
# Topics look like: public.production-demand.v1
HFKCAT_READ_RE = re.compile(r'hfkcat\s+read\s+["\']?([a-zA-Z0-9._-]+)["\']?')
# kcat -t <topic>
KCAT_TOPIC_RE = re.compile(r"-t\s+(\S+)")
# Extract broker from -b flag
KCAT_BROKER_RE = re.compile(r"-b\s+(\S+)")
# Extract username/service from -U flag
HFKCAT_USER_RE = re.compile(r"-U\s+[\"']?(\S+?)[\"']?\s")
# Extract filter query from -q flag
HFKCAT_QUERY_RE = re.compile(r"-q\s+['\"](.+?)['\"]")


def _parse_zsh_history(since: datetime) -> list[tuple[datetime, str]]:
    """Parse zsh history for kafka-related commands.

    Handles both extended (`: <timestamp>:0;cmd`) and plain formats.
    Also handles `\\x1bE` continuation markers used for multi-line commands.
    For non-timestamped history, uses file mtime to estimate recency.
    """
    history_file = Path.home() / ".zsh_history"
    if not history_file.exists():
        return []

    entries: list[tuple[datetime, str]] = []
    since_ts = since.timestamp()

    try:
        raw = history_file.read_bytes()
        text = raw.decode("utf-8", errors="replace")

        # Join multi-line commands: zsh uses \\\n or \x1bE\n as continuation
        text = text.replace("\\\x1bE\n", " ").replace("\\\n", " ")
        # Also clean up remaining \x1bE markers
        text = text.replace("\x1b", "")

        has_timestamps = False
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            ts_val: datetime | None = None

            # Extended history: : <epoch>:<duration>;<command>
            if line.startswith(": "):
                match = re.match(r"^: (\d+):\d+;(.+)$", line)
                if match:
                    has_timestamps = True
                    epoch = int(match.group(1))
                    cmd = match.group(2)
                    if epoch >= since_ts:
                        ts_val = datetime.fromtimestamp(epoch)
                    else:
                        continue
                else:
                    continue
            else:
                cmd = line

            # Match actual hfkcat/kcat commands at the start or after a pipe
            if not re.search(r"(?:^|\|)\s*hfkcat\s", cmd):
                continue

            # Clean up extra whitespace from joined continuations
            cmd = re.sub(r"\s+", " ", cmd).strip()

            if ts_val:
                entries.append((ts_val, cmd))
            elif not has_timestamps:
                # No timestamps — use file mtime as rough estimate
                mtime = history_file.stat().st_mtime
                if mtime >= since_ts:
                    entries.append((datetime.fromtimestamp(mtime), cmd))
    except (OSError, UnicodeDecodeError):
        pass

    return entries


def _parse_bash_history(since: datetime) -> list[tuple[datetime, str]]:
    """Parse bash history. Bash doesn't store timestamps by default,
    but HISTTIMEFORMAT can enable it."""
    history_file = Path.home() / ".bash_history"
    if not history_file.exists():
        return []

    entries: list[tuple[datetime, str]] = []
    since_ts = since.timestamp()

    try:
        lines = history_file.read_text(errors="replace").splitlines()
        current_ts: float | None = None
        for line in lines:
            line = line.strip()
            # Timestamp line: #<epoch>
            if line.startswith("#") and line[1:].isdigit():
                current_ts = float(line[1:])
                continue
            if re.search(r"(?:^|\|)\s*hfkcat\s", line) and current_ts and current_ts >= since_ts:
                entries.append((datetime.fromtimestamp(current_ts), line))
            current_ts = None
    except OSError:
        pass

    return entries


class Kafka:
    name = "kafka"

    def health_check(self) -> bool:
        """Check if hfkcat or kcat is available and history exists."""
        import shutil

        has_tool = bool(shutil.which("hfkcat") or shutil.which("kcat"))
        has_history = (Path.home() / ".zsh_history").exists() or (
            Path.home() / ".bash_history"
        ).exists()
        return has_tool and has_history

    def fetch_since(self, since: datetime) -> list[RawEvent]:
        # Gather commands from shell history
        commands = _parse_zsh_history(since) + _parse_bash_history(since)

        events: list[RawEvent] = []
        seen: set[str] = set()  # dedup by (timestamp, topic)

        for ts, cmd in commands:
            topic = None
            action = "read"
            broker = None
            service = None
            query_filter = None

            # hfkcat read "<topic>" -b lv -U <service>
            m = HFKCAT_READ_RE.search(cmd + " ")  # trailing space for regex
            if m:
                topic = m.group(1).strip()
                action = "read"

            # kcat -t <topic>
            if not topic:
                m = KCAT_TOPIC_RE.search(cmd)
                if m:
                    topic = m.group(1)

            # Extract broker
            m = KCAT_BROKER_RE.search(cmd)
            if m:
                broker = m.group(1)

            # Extract service name (-U flag)
            m = HFKCAT_USER_RE.search(cmd + " ")
            if m:
                service = m.group(1)

            # Extract filter query (-q flag)
            m = HFKCAT_QUERY_RE.search(cmd)
            if m:
                query_filter = m.group(1)

            if not topic:
                # Couldn't parse topic — store the raw command
                dedup_key = f"{ts.isoformat()}:{cmd[:60]}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                events.append(
                    RawEvent(
                        source="kafka",
                        kind="kafka_command",
                        title=cmd[:120],
                        happened_at=ts,
                        metadata={"raw_command": cmd[:500]},
                    )
                )
                continue

            dedup_key = f"{ts.isoformat()}:{topic}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Build a descriptive title
            short_topic = topic.split(".")[-1] if "." in topic else topic
            title = f"kafka {action}: {short_topic}"
            if query_filter:
                title += f" (filter: {query_filter[:40]})"

            metadata = {
                "topic": topic,
                "broker": broker,
                "raw_command": cmd[:500],
            }
            if service:
                metadata["service"] = service
            if query_filter:
                metadata["filter"] = query_filter

            entities: list[tuple[str, str, str]] = [("topic", topic, "target")]
            if service:
                entities.append(("service", service, "source"))

            events.append(
                RawEvent(
                    source="kafka",
                    kind=f"kafka_{action}",
                    title=title,
                    happened_at=ts,
                    metadata=metadata,
                    entities=entities,
                )
            )

        return events
