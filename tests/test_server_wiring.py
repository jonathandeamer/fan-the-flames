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


class _FakeTransport:
    def __init__(self, ip="203.0.113.7"):
        self.ip = ip
        self.writes = []
        self.closed = False

    def get_extra_info(self, key, default=None):
        if key == "peername":
            return (self.ip, 51000)
        return default

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True


def _reset_conns():
    telnet_server._active_per_ip.clear()
    telnet_server._active_total = 0


def test_acquire_allows_under_caps():
    _reset_conns()
    with mock.patch.object(telnet_server, "MAX_PER_IP", 2), mock.patch.object(
        telnet_server, "MAX_CONNECTIONS", 50
    ):
        assert telnet_server.acquire_connection("1.2.3.4") is True
        assert telnet_server.acquire_connection("1.2.3.4") is True


def test_acquire_rejects_over_per_ip_cap():
    _reset_conns()
    with mock.patch.object(telnet_server, "MAX_PER_IP", 2), mock.patch.object(
        telnet_server, "MAX_CONNECTIONS", 50
    ):
        assert telnet_server.acquire_connection("1.2.3.4") is True
        assert telnet_server.acquire_connection("1.2.3.4") is True
        assert telnet_server.acquire_connection("1.2.3.4") is False
        assert telnet_server.acquire_connection("5.6.7.8") is True


def test_acquire_rejects_over_global_cap():
    _reset_conns()
    with mock.patch.object(telnet_server, "MAX_PER_IP", 99), mock.patch.object(
        telnet_server, "MAX_CONNECTIONS", 2
    ):
        assert telnet_server.acquire_connection("1.1.1.1") is True
        assert telnet_server.acquire_connection("2.2.2.2") is True
        assert telnet_server.acquire_connection("3.3.3.3") is False


def test_release_frees_a_slot():
    _reset_conns()
    with mock.patch.object(telnet_server, "MAX_PER_IP", 1), mock.patch.object(
        telnet_server, "MAX_CONNECTIONS", 50
    ):
        assert telnet_server.acquire_connection("1.2.3.4") is True
        assert telnet_server.acquire_connection("1.2.3.4") is False
        telnet_server.release_connection("1.2.3.4")
        assert telnet_server.acquire_connection("1.2.3.4") is True


def test_get_peer_ip_reads_peername():
    writer = mock.Mock()
    writer.get_extra_info.return_value = ("203.0.113.7", 51000)
    assert telnet_server.get_peer_ip(writer) == "203.0.113.7"


def test_get_peer_ip_falls_back_when_unknown():
    writer = mock.Mock()
    writer.get_extra_info.return_value = None
    assert telnet_server.get_peer_ip(writer) == "?"


def test_protocol_rejects_before_telnet_negotiation():
    async def exercise():
        _reset_conns()
        transport = _FakeTransport()
        protocol = telnet_server.LimitedTelnetServer()
        with mock.patch.object(telnet_server, "MAX_CONNECTIONS", 0), mock.patch.object(
            telnet_server.TelnetServer, "connection_made"
        ) as parent_connection_made:
            protocol.connection_made(transport)

        parent_connection_made.assert_not_called()
        assert transport.writes == [telnet_server.REJECTION_NOTICE]
        assert transport.closed
        assert protocol._waiter_connected.cancelled()
        assert telnet_server._active_total == 0

    asyncio.run(exercise())


def test_protocol_releases_admitted_connection_exactly_once():
    async def exercise():
        _reset_conns()
        transport = _FakeTransport()
        protocol = telnet_server.LimitedTelnetServer()
        with mock.patch.object(
            telnet_server.TelnetServer, "connection_made"
        ) as parent_connection_made, mock.patch.object(
            telnet_server.TelnetServer, "connection_lost"
        ) as parent_connection_lost:
            protocol.connection_made(transport)
            parent_connection_made.assert_called_once()
            assert telnet_server._active_total == 1

            protocol.connection_lost(None)
            protocol.connection_lost(None)

        parent_connection_lost.assert_called_once()
        assert telnet_server._active_total == 0
        assert telnet_server._active_per_ip == {}

    asyncio.run(exercise())


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


def test_shell_eof_terminates_loop():
    class _FakeReader:
        async def read(self, n):
            return ""  # EOF immediately

    writer = _LoopWriter()

    async def _noop(writer):
        pass

    with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), mock.patch.object(
        telnet_server, "DURATION", 10.0
    ), mock.patch.object(telnet_server, "FPS", 10):
        asyncio.run(telnet_server.shell(reader=_FakeReader(), writer=writer))

    # The simulation should have terminated immediately on EOF, having written
    # very few outputs.
    assert len(writer.writes) < 5


def test_shell_paces_next_frame_after_input():
    class _FakeReader:
        def __init__(self):
            self.calls = 0

        async def read(self, n):
            self.calls += 1
            if self.calls == 1:
                return "a"
            if self.calls == 2:
                # Force the first frame to wait for its remaining time.
                await asyncio.Event().wait()
            return ""  # EOF on the next frame

    class _TimedWriter(_LoopWriter):
        def __init__(self):
            super().__init__()
            self.frame_times = []

        def write(self, data):
            super().write(data)
            if data.startswith(telnet_server.RESET):
                self.frame_times.append(asyncio.get_running_loop().time())

    writer = _TimedWriter()

    async def _noop(writer):
        pass

    with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), mock.patch.object(
        telnet_server, "DURATION", 0.2
    ), mock.patch.object(telnet_server, "FPS", 10):
        asyncio.run(telnet_server.shell(reader=_FakeReader(), writer=writer))

    assert len(writer.frame_times) == 2
    assert writer.frame_times[1] - writer.frame_times[0] >= 0.08


def test_shell_bounds_input_reads_per_frame():
    class _FloodReader:
        def __init__(self):
            self.calls = 0

        async def read(self, n):
            self.calls += 1
            return "a"

    reader = _FloodReader()
    writer = _LoopWriter()
    sleep_delays = []

    async def _noop(writer):
        pass

    async def _record_sleep(delay):
        sleep_delays.append(delay)

    with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), mock.patch.object(
        telnet_server, "DURATION", 0.1
    ), mock.patch.object(telnet_server, "FPS", 10), mock.patch.object(
        asyncio, "sleep", _record_sleep
    ):
        asyncio.run(telnet_server.shell(reader=reader, writer=writer))

    assert 0 < reader.calls <= telnet_server.MAX_INPUT_READS_PER_FRAME
    assert sleep_delays
    assert 0 < sleep_delays[0] <= 0.1


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
