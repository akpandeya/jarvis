---
name: firefox
description: Firefox browser history integration — reads visit history from Firefox's places.sqlite and ingests URL visits as Jarvis events.
component: jarvis/integrations/firefox.py
---

# Firefox Integration Behaviours

- **F1**: WHEN the integration is initialised THEN it SHALL locate the Firefox profile directory by scanning `~/Library/Application Support/Firefox/Profiles/*.default-release/` on macOS and `~/.mozilla/firefox/*.default-release/` on Linux, using the first matching directory that contains `places.sqlite`.

- **F2**: WHEN `fetch_since` or `health_check` reads `places.sqlite` THEN the integration SHALL copy `places.sqlite` to a temporary file before opening it, so that a locked database used by a running Firefox process does not cause an error.

- **F3**: WHEN `fetch_since(since)` is called THEN the integration SHALL return one `RawEvent` per row in `moz_historyvisits` whose `visit_date` (microseconds since Unix epoch) is strictly greater than `since`, joined to `moz_places` to obtain the URL and title.

- **F4**: WHEN a visit event is created THEN the `RawEvent` SHALL have `source="firefox"`, `event_type="url_visit"`, `title` set to the page title (falling back to the URL when the title is NULL or empty), and `project` set to the domain extracted from the URL (netloc component, e.g. `github.com`).

- **F5**: WHEN a visited URL has a scheme of `about` or `moz-extension` THEN the integration SHALL skip that URL and not emit a `RawEvent` for it.

- **F6**: WHEN `health_check` is called and no Firefox profile directory containing `places.sqlite` can be found THEN `health_check` SHALL return `False`.

- **F7**: WHEN `fetch_since` is called and no Firefox profile can be found THEN the integration SHALL return an empty list and log a warning, rather than raising an exception.
