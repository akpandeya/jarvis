---
name: activity_tracker
description: Collects computer-wide activity (CLI, Firefox, Thunderbird, shell) and writes it to the activity_log table
component: jarvis/activity.py
---

# Spec — ActivityTracker

**Component:** `jarvis/activity.py`

ActivityTracker collects activity events from four sources and upserts them into the `activity_log` table. Each source is an independent collector that can be run individually or together.

## Glossary

- **activity event** — a single observable computer action: a CLI command run, a page visited, an email received, or a shell command executed.
- **happened_at** — ISO 8601 UTC timestamp of when the activity occurred, derived from the source data (not ingestion time).

## Behaviours

### F1. Running all collectors returns the total count of new rows inserted

**WHEN** all collectors are run **THEN** ActivityTracker **SHALL** invoke each collector (CLI, Firefox, Thunderbird, shell) in sequence and return the sum of new rows inserted across all collectors.

### F2. Each collector skips sources that are unavailable without raising

**WHEN** a collector's source is unavailable (Firefox not installed, history file absent, database locked and unreadable) **THEN** that collector **SHALL** return zero and log a warning, leaving other collectors unaffected.

### F3. CLI tracker records each Jarvis command on completion

**WHEN** a Jarvis CLI command completes **THEN** the CLI collector **SHALL** insert one row into `activity_log` with source `jarvis_cli`, kind `command`, the command name as title, the arguments as body, and exit code and duration in metadata.

### F4. Firefox collector reads from all profiles and labels each row with the profile name

**WHEN** the Firefox collector runs **THEN** it **SHALL** read browsing history from every Firefox profile on the machine, record each page visit with its title, URL, and visit time, and tag each row with the profile name per F10.

### F5. Firefox collector copies a locked database before reading

**WHEN** a Firefox profile database cannot be opened directly because Firefox is running **THEN** the collector **SHALL** copy the file to a temporary location, read from the copy, and delete it afterwards.

### F6. Thunderbird collector reads email subjects and senders only, labelled by account context

**WHEN** the Thunderbird collector runs **THEN** it **SHALL** insert one row per message with the subject as title, sender address as body, and account context in metadata per F11. It **SHALL NOT** store message body text.

### F7. Shell collector reads zsh history and filters noise

**WHEN** the shell collector runs **THEN** it **SHALL** parse `~/.zsh_history`, record each command with its timestamp, and skip commands whose first word is any of `ls`, `cd`, `clear`, `pwd`, `exit`, or `history`.

### F8. All collectors deduplicate silently

**WHEN** a collector attempts to insert a row that already exists with the same source, kind, URL, and timestamp **THEN** the row **SHALL** be silently skipped.

### F9. All collectors log a summary on completion

**WHEN** all collectors finish **THEN** ActivityTracker **SHALL** emit one log line per collector showing how many new rows were inserted.

### F10. Firefox profile label is read from the profile's own settings

**WHEN** the Firefox collector processes a profile **THEN** it **SHALL** read the display name from that profile's preferences file and store it in metadata. If no display name is found it **SHALL** fall back to the profile directory name. A label configured in `~/.jarvis/config.toml` under `[firefox.profiles]` **SHALL** override both.

### F11. Thunderbird account context is derived from sender domain

**WHEN** the Thunderbird collector inserts a row **THEN** it **SHALL** set the account context in metadata to `work` if the sender's email domain matches any domain listed under `[thunderbird] work_domains` in `~/.jarvis/config.toml`. When no domains are configured, all emails are labelled `personal`.

### F12. Collectors respect an optional upper time bound

**WHEN** collectors are run with an upper time bound **THEN** each collector **SHALL** exclude rows with a timestamp after that bound. When no upper bound is given, no upper limit is applied.

### F13. Thunderbird collector skips spam and deleted messages

**WHEN** the Thunderbird collector processes a message **THEN** it **SHALL** skip any message with a junk score of 50 or above, or whose folder name is any of `Spam`, `Junk`, `Trash`, `Deleted Items`, or `Deleted` (case-insensitive). Skipped messages **SHALL NOT** be inserted into `activity_log`.


### F14. Firefox profile discovery

**WHEN** `discover_firefox_profiles` is called **THEN** it **SHALL** return a list of dicts, one per profile directory under the macOS Firefox profiles path, each containing the directory stem, the detected display name, and a boolean indicating whether `places.sqlite` is present.

### F15. Thunderbird profile discovery

**WHEN** `discover_thunderbird_profiles` is called **THEN** it **SHALL** return a list of dicts, one per profile directory under the macOS Thunderbird profiles path, each containing the directory stem and a boolean indicating whether `global-messages-db.sqlite` is present.
