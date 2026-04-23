---
name: thunderbird
description: Thunderbird email integration — reads sent and received emails from Thunderbird's global-messages-db.sqlite and ingests them as Jarvis events.
component: jarvis/integrations/thunderbird.py
---

# Thunderbird Integration Behaviours

- **F1**: WHEN the integration is initialised THEN it SHALL locate the Thunderbird profile directory by scanning `~/Library/Thunderbird/Profiles/*.default*/` on macOS and `~/.thunderbird/*.default*/` on Linux, using the first matching directory that contains `global-messages-db.sqlite`.

- **F2**: WHEN `fetch_since` or `health_check` reads `global-messages-db.sqlite` THEN the integration SHALL copy the database to a temporary file before opening it, so that a locked database used by a running Thunderbird process does not cause an error.

- **F3**: WHEN `fetch_since(since)` is called THEN the integration SHALL return one `RawEvent` per row in the `messages` table whose `date` (seconds since Unix epoch) is greater than or equal to `since`, joined to `folderLocations` to obtain the folder URI.

- **F4**: WHEN an email event is created THEN the `RawEvent` SHALL have `source="thunderbird"`, and `kind` set to `"email_sent"` if the folder URI contains `"Sent"`, or `"email_received"` otherwise.

- **F5**: WHEN an email event is created THEN the `RawEvent` SHALL have `title` set to the email subject and `project` set to the domain extracted from the sender's email address (e.g. `example.com`).

- **F6**: WHEN a message has no subject AND no body text THEN the integration SHALL skip that message and not emit a `RawEvent` for it.

- **F7**: WHEN `health_check` is called and no Thunderbird profile directory containing `global-messages-db.sqlite` can be found THEN `health_check` SHALL return `False`.

- **F8**: WHEN `fetch_since` is called and the database file is missing or cannot be opened THEN the integration SHALL return an empty list rather than raising an exception.
