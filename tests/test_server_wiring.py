import random
import sys
from unittest import mock

from telnet_server import FireState, parse_args, render_fire, step_fire


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
    import telnet_server
    assert not hasattr(telnet_server, "WAVE")
    assert not hasattr(telnet_server, "render_screen")
