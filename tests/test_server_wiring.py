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


class _LoopWriter(_FakeWriter):
    """A writer the shell render loop can actually drive for one frame."""

    def get_extra_info(self, key, default=None):
        return {"rows": 4, "cols": 4}.get(key, default)

    async def drain(self):
        return


def test_parse_args_validation():
    import pytest

    invalid_values = [
        ("--port", "0"),
        ("--port", "65536"),
        ("--fps", "0"),
        ("--fps", "nan"),
        ("--fps", "inf"),
        ("--fps", "-inf"),
        ("--duration", "-2.5"),
        ("--duration", "nan"),
        ("--duration", "inf"),
        ("--duration", "-inf"),
        ("--cooling", "-1"),
        ("--cooling", "256"),
    ]
    for option, value in invalid_values:
        with mock.patch.object(sys, "argv", ["telnet_server.py", option, value]):
            with pytest.raises(SystemExit):
                parse_args()


def test_parse_args_has_cooling_default():
    with mock.patch.object(sys, "argv", ["telnet_server.py"]):
        args = parse_args()
    assert hasattr(args, "cooling")
    assert args.cooling > 0


def test_parse_args_accepts_cooling_override():
    with mock.patch.object(sys, "argv", ["telnet_server.py", "--cooling", "25"]):
        args = parse_args()
    assert args.cooling == 25


def test_get_terminal_size_defensive():
    from telnet_server import MAX_COLS, MAX_ROWS, get_terminal_size

    writer = mock.Mock()
    # Malformed / missing sizes (non-integer types)
    writer.get_extra_info.side_effect = lambda key, default: {"rows": "abc", "cols": None}.get(
        key, default
    )
    rows, cols = get_terminal_size(writer)
    assert rows == 24
    assert cols == 80

    # Zero means unspecified; malformed negative values also use defaults.
    writer.get_extra_info.side_effect = lambda key, default: {"rows": 0, "cols": -10}.get(
        key, default
    )
    rows, cols = get_terminal_size(writer)
    assert rows == 24
    assert cols == 80

    # NAWS fields are 16-bit and untrusted, so cap oversized dimensions.
    writer.get_extra_info.side_effect = lambda key, default: {"rows": 65535, "cols": 65535}.get(
        key, default
    )
    rows, cols = get_terminal_size(writer)
    assert rows == MAX_ROWS
    assert cols == MAX_COLS


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


def test_shell_input_wait_subtracts_compute_time():
    # The per-frame input wait doubles as frame pacing. It should wait only the
    # remainder of the frame period after the time already spent computing the
    # frame -- not a full 1/FPS on top of the compute time.
    async def _noop(writer):
        return

    reader = mock.Mock()

    captured = {}

    async def fake_wait_for(aw, timeout):
        captured["timeout"] = timeout
        aw.close()  # we never await the read; close it to avoid a warning
        return "q"  # break out after the first frame

    # Frame compute takes 0.05s of a 0.1s period (FPS=10), so the wait that
    # follows should be the remaining 0.05s. Replace the module's `time` name
    # with a fake clock so we don't disturb asyncio's own clock.
    fake_time = mock.Mock()
    fake_time.monotonic = mock.Mock(side_effect=[0.0, 0.05])

    writer = _LoopWriter()
    with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), mock.patch.object(
        telnet_server, "DURATION", 1
    ), mock.patch.object(telnet_server, "FPS", 10), mock.patch.object(
        telnet_server.asyncio, "wait_for", fake_wait_for
    ), mock.patch.object(
        telnet_server, "time", fake_time
    ):
        asyncio.run(telnet_server.shell(reader=reader, writer=writer))

    assert captured["timeout"] == 0.05


def test_shell_negotiation_failure_closes_writer():
    async def _fail(writer):
        raise ConnectionError("Negotiation dropped")

    writer = _FakeWriter()
    with mock.patch.object(telnet_server, "negotiate_telnet_options", _fail):
        try:
            asyncio.run(telnet_server.shell(reader=None, writer=writer))
        except ConnectionError:
            pass

    assert writer.closed


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
