---
name: launcher
description: Non-blocking daemon launcher — starts menu bar and web server as detached background processes with PID-file idempotency
component: jarvis/launcher.py
---

# Launcher

## Behaviours

**F1** WHEN `jarvis` is invoked with no subcommand THEN it SHALL start the menu bar icon and web server as detached background processes and return to the shell immediately.

**F2** WHEN `jarvis` is invoked with no subcommand AND a live Jarvis process is already running THEN it SHALL print a message and exit without starting a second instance.

**F3** WHEN the background processes are started THEN they SHALL survive terminal close (i.e. not receive SIGHUP when the launching terminal exits).

**F4** WHEN Jarvis starts successfully THEN it SHALL write the menubar process PID to `~/.jarvis/jarvis.pid`.

**F5** WHEN `jarvis quit` is run THEN it SHALL send SIGTERM to the PID recorded in `~/.jarvis/jarvis.pid` and remove the PID file.

**F6** WHEN `jarvis quit` is run AND the PID file does not exist THEN it SHALL print a message indicating Jarvis is not running.

**F7** WHEN the PID file exists but the recorded process no longer exists THEN `_already_running` SHALL return False and remove the stale PID file.

**F8** WHEN the menu bar quit action is triggered THEN it SHALL delete `~/.jarvis/jarvis.pid` so a subsequent `jarvis` invocation starts fresh.
