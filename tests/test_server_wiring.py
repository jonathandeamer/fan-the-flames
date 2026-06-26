import asyncio
import random
import sys
from unittest import mock

import telnet_server
from telnet_server import FireState, parse_args, render_fire, step_fire


class _FakeWriter:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True


def test_parse_args_has_cooling_default():
    with mock.patch.object(sys, "argv", ["telnet_server.py"]):
        args = parse_args()
    assert hasattr(args, "cooling")
    assert args.cooling > 0


def test_parse_args_accepts_cooling_override():
    with mock.patch.object(sys, "argv", ["telnet_server.py", "--cooling", "25"]):
        args = parse_args()
    assert args.cooling == 25


def test_end_to_end_frame_render():
    random.seed(0)
    state = FireState(cols=40, rows=12)
    step_fire(state, cooling=18)
    frame = render_fire(state, rows=12, cols=40)
    assert isinstance(frame, str)
    assert frame.startswith("\x1b[0;0H")


def test_wave_symbols_are_gone():
    assert not hasattr(telnet_server, "WAVE")
    assert not hasattr(telnet_server, "render_screen")


def test_shell_hides_cursor_then_restores_it():
    async def _noop(writer):
        return

    writer = _FakeWriter()
    with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), mock.patch.object(
        telnet_server, "DURATION", 0
    ):
        asyncio.run(telnet_server.shell(reader=None, writer=writer))

    output = "".join(writer.writes)
    assert telnet_server.HIDE_CURSOR in output
    assert telnet_server.SHOW_CURSOR in output
    # cursor is restored only after it was hidden, and the connection is closed
    assert output.index(telnet_server.HIDE_CURSOR) < output.index(telnet_server.SHOW_CURSOR)
    assert writer.closed
