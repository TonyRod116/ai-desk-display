"""Keep the clock's WSL session alive without starting another monitor.

Windows starts this through its private login launcher. Systemd starts the
enabled clock services during WSL boot; this host only observes them. An explicit
service stop ends this host, not the other programs in WSL. No account, browser
or provider data is accessed here.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


SERVICE = "token-tv.service"


def clock_host(*, run=subprocess.run, sleep=time.sleep) -> int:
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

    def control(*args: str) -> str | None:
        try:
            result = run(
                ["/usr/bin/systemctl", "--user", *args, SERVICE],
                env=env, capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if args == ("is-enabled",) and result.stdout.strip() in (
            "disabled", "masked", "static", "indirect", "enabled-runtime"
        ):
            return result.stdout.strip()
        if result.returncode:
            return None
        return result.stdout.strip()

    # A cold WSL boot may take a little time to create the user's service bus.
    for _ in range(12):
        enabled = control("is-enabled")
        if enabled is not None:
            break
        sleep(5)
    else:
        return 1
    if enabled != "enabled":
        return 0
    # Let the user's default target start enabled services. Starting one here
    # could undo a manual stop if the launcher ran again during the same boot.
    for _ in range(12):
        state = control("show", "--property=ActiveState", "--value")
        if state in ("active", "activating", "reloading"):
            break
        sleep(5)
    else:
        return 1 if state is None else 0
    missing = 0
    while True:
        if state in ("active", "activating", "reloading"):
            missing = 0
        else:
            missing += 1
            if missing >= 6:
                return 1 if state is None else 0
        # A restart passes through deactivating; a transient bus failure is not
        # a manual stop. Give observations a bounded grace without mutating it.
        sleep(10)
        state = control("show", "--property=ActiveState", "--value")


def main() -> int:
    os.umask(0o077)
    directory = Path.home() / ".config" / "token-tv"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "windows-host.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        status = {"pid": os.getpid(), "started_at": int(time.time())}

        def record() -> None:
            lock.seek(0)
            lock.truncate()
            json.dump(status, lock)
            lock.flush()

        record()
        try:
            os.nice(12)
        except OSError:
            pass
        result = clock_host()
        status.update(finished_at=int(time.time()), exit_code=result)
        record()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
