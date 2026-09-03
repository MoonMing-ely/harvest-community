import os
import select
import subprocess
import sys
import time

import pytest


pty = pytest.importorskip("pty")
termios = pytest.importorskip("termios")


def test_cli_deletes_a_whole_chinese_character_before_retyping() -> None:
    master, slave = pty.openpty()
    attributes = termios.tcgetattr(slave)
    attributes[0] &= ~getattr(termios, "IUTF8", 0)
    termios.tcsetattr(slave, termios.TCSANOW, attributes)
    process = subprocess.Popen(
        [sys.executable, "-c", "import harvest.cli; print(repr(input('Q: ')))"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)

    output = b""
    sent_input = False
    deadline = time.monotonic() + 5
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    output += os.read(master, 4096)
                except OSError:
                    break
            if b"Q: " in output and not sent_input:
                os.write(master, "错".encode() + b"\x7f" + "对\n".encode())
                sent_input = True
            if process.poll() is not None:
                break
        process.wait(timeout=1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)

    decoded = output.decode("utf-8")
    assert process.returncode == 0, decoded
    assert "'对'" in decoded
