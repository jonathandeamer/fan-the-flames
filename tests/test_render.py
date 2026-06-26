import random

from telnet_server import FireState, build_overlay, render_fire, step_fire


def test_overlay_places_footer_on_bottom_row():
    overlay = build_overlay(rows=24, cols=80)
    assert "q" in overlay.values()
    # every overlaid cell sits on the bottom row
    assert all(r == 23 for (r, _c) in overlay)


def test_overlay_skips_footer_when_too_narrow():
    overlay = build_overlay(rows=24, cols=4)  # narrower than "[q]uit"
    assert overlay == {}


def test_render_all_cold_is_black_and_well_formed():
    state = FireState(cols=4, rows=2)  # all-zero heat
    frame = render_fire(state, rows=2, cols=4)
    assert frame.startswith("\x1b[0;0H")       # cursor reset first
    assert "▀" in frame                    # half-block glyph used
    assert "\x1b[38;2;0;0;0m" in frame          # cold -> black fg
    assert "\x1b[48;2;0;0;0m" in frame          # cold -> black bg
    assert frame.endswith("\x1b[0m")            # reset at end


def test_render_has_no_title_banner():
    random.seed(0)
    state = FireState(cols=80, rows=24)
    step_fire(state, cooling=18)
    frame = render_fire(state, rows=24, cols=80)
    assert "FAN THE FLAMES" not in frame
    assert "[q]uit" in frame  # footer still present
