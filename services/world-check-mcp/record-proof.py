"""Record a command's terminal output as an asciinema v2 cast."""

import json
import os
import pty
import select
import sys
import time


def main() -> None:
    command = sys.argv[1]
    destination = sys.argv[2]
    width = 120
    height = 40
    with open(destination, "w", encoding="utf-8") as cast:
        cast.write(
            json.dumps(
                {
                    "version": 2,
                    "width": width,
                    "height": height,
                    "timestamp": int(time.time()),
                    "title": "World-Check MCP tools",
                    "env": {"TERM": "xterm-256color"},
                }
            )
            + "\n"
        )
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = str(width)
            os.environ["LINES"] = str(height)
            os.execvp("bash", ["bash", command])
        started = time.monotonic()
        while True:
            readable, _, _ = select.select([fd], [], [], 0.2)
            if fd in readable:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                cast.write(
                    json.dumps(
                        [round(time.monotonic() - started, 6), "o", data.decode("utf-8", "replace")]
                    )
                    + "\n"
                )
                cast.flush()
            elif os.waitpid(pid, os.WNOHANG) != (0, 0):
                break
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            cast.write(
                json.dumps(
                    [round(time.monotonic() - started, 6), "o", data.decode("utf-8", "replace")]
                )
                + "\n"
            )
        os.waitpid(pid, 0)


if __name__ == "__main__":
    main()
