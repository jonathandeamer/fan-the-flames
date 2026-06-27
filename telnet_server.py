#!/usr/bin/env python3
"""
An animated telnet fire splash screen ("Fan the Flames").

When a connection is established, a Doom-style ASCII fire animation is rendered
in 24-bit truecolor using half-block glyphs, then the connection is closed after
a short period.

This is a modified fork of "ride-the-wave" by Michael Lazar
(https://github.com/michael-lazar/ride-the-wave), which displayed a scrolling
wave. The fire rendering technique (half-block 2x vertical resolution and a
gradient palette) is adapted from "lavat" by AngelJumbo
(https://github.com/AngelJumbo/lavat, MIT).

The telnet server uses asyncio and requires python 3.11+.
"""

# Copyright (C) Michael Lazar — original "ride-the-wave"
# Copyright (C) 2026 Jonathan Deamer — "Fan the Flames" fire animation
# Licensed under the GNU GPL v3; see LICENSE.
#
# Modified 2026 by Jonathan Deamer: replaced the wave animation with a fire
# animation and rebranded the project as "Fan the Flames".

__version__ = "2.0.0"

import argparse
import asyncio
import logging
import math
import random
import time

from telnetlib3 import create_server, telopt

# VT-100 terminal commands
END = "\x1b[0m"
CLEAR = "\x1b[2J"
RESET = "\x1b[0;0H"  # move cursor to (0, 0) coordinates
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"

# Fire color ramp: (heat_index, (r, g, b)) control stops, black -> white.
_FIRE_STOPS = [
    (0, (0, 0, 0)),
    (64, (128, 0, 0)),
    (128, (255, 0, 0)),
    (192, (255, 128, 0)),
    (224, (255, 255, 0)),
    (255, (255, 255, 255)),
]


def fire_rgb(heat: int) -> tuple[int, int, int]:
    """Map a heat value (0-255) onto the fire color ramp."""
    heat = max(0, min(255, heat))
    for (p0, c0), (p1, c1) in zip(_FIRE_STOPS, _FIRE_STOPS[1:]):
        if p0 <= heat <= p1:
            t = (heat - p0) / (p1 - p0)
            return tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return _FIRE_STOPS[-1][1]


FG_PALETTE = [f"\x1b[38;2;{r};{g};{b}m" for r, g, b in (fire_rgb(h) for h in range(256))]
BG_PALETTE = [f"\x1b[48;2;{r};{g};{b}m" for r, g, b in (fire_rgb(h) for h in range(256))]


class FireState:
    """Per-connection heat grid for the fire simulation."""

    def __init__(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        self.height = rows * 2
        self.heat = [0] * (cols * self.height)


def step_fire(state: FireState, cooling: int, rng=random) -> None:
    """Advance the fire one frame: re-heat the bottom row, propagate upward."""
    cols, height, heat = state.cols, state.height, state.heat
    if cols == 0 or height == 0:
        return

    # This loop runs once per cell, so on a Pi Zero it dominates the frame
    # budget. `random.randint` carries heavy per-call overhead; `random()` is a
    # thin C call, so we draw a float and scale it instead. The arithmetic
    # below reproduces the exact integer ranges randint produced:
    #   int(rnd() * 26)          -> 0..25   (was randint(0, 25))
    #   int(rnd() * 3) - 1       -> -1..1   (was randint(-1, 1))
    #   int(rnd() * cool_span)   -> 0..cooling (was randint(0, cooling))
    rnd = rng.random
    cool_span = cooling + 1

    # Hot, shimmering source row along the bottom.
    base = (height - 1) * cols
    for x in range(cols):
        heat[base + x] = 230 + int(rnd() * 26)

    # Each cell cools off a copy of the cell below (previous frame), with horizontal drift.
    # Iterate top-to-bottom so each row reads the still-unmodified row beneath it.
    for y in range(0, height - 1):
        row = y * cols
        below = (y + 1) * cols
        for x in range(cols):
            src_x = x + int(rnd() * 3) - 1
            src = heat[below + src_x] if 0 <= src_x < cols else 0
            value = src - int(rnd() * cool_span)
            heat[row + x] = value if value > 0 else 0


HALF_BLOCK = "▀"  # upper half block: fg paints top pixel, bg paints bottom
FOOTER_FG = "\x1b[1m\x1b[38;2;255;255;255m"  # bold white
FOOTER_BG = "\x1b[48;2;0;0;0m"  # black
FOOTER = "[q]uit"


def build_overlay(rows: int, cols: int) -> dict[tuple[int, int], str]:
    """Map (row, col) -> glyph for the footer cells overlaid on the fire."""
    cells: dict[tuple[int, int], str] = {}

    if rows >= 1 and cols >= len(FOOTER):
        r = rows - 1
        start = cols - len(FOOTER)
        for j, ch in enumerate(FOOTER):
            cells[(r, start + j)] = ch

    return cells


def render_fire(state: FireState, rows: int, cols: int) -> str:
    """Render one frame: half-block truecolor cells with the footer overlaid."""
    heat = state.heat
    grid_cols = state.cols
    height = state.height
    overlay = build_overlay(rows, cols)

    out = [RESET]
    for r in range(rows):
        last_fg = last_bg = None
        in_footer = False
        upper = 2 * r
        lower = 2 * r + 1
        for x in range(cols):
            glyph = overlay.get((r, x))
            if glyph is not None:
                if not in_footer:
                    out.append(FOOTER_FG + FOOTER_BG)
                    in_footer = True
                    last_fg = last_bg = None  # footer broke the color run
                out.append(glyph)
                continue
            in_footer = False

            if x < grid_cols:
                u = heat[upper * grid_cols + x] if upper < height else 0
                lo = heat[lower * grid_cols + x] if lower < height else 0
            else:
                u = lo = 0

            if u != last_fg:
                out.append(FG_PALETTE[u])
                last_fg = u
            if lo != last_bg:
                out.append(BG_PALETTE[lo])
                last_bg = lo
            out.append(HALF_BLOCK)

        if r < rows - 1:
            out.append("\r\n")
    out.append(END)
    return "".join(out)


FPS = 10
DURATION = 20
COOLING = 10


def parse_args():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7777, type=int)
    parser.add_argument("--fps", default=FPS, type=float)
    parser.add_argument("--duration", default=DURATION, type=float)
    parser.add_argument("--cooling", default=COOLING, type=int)
    args = parser.parse_args()

    if args.port < 1 or args.port > 65535:
        parser.error("port must be between 1 and 65535")
    if not math.isfinite(args.fps) or args.fps <= 0:
        parser.error("fps must be finite and greater than 0")
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("duration must be finite and non-negative")
    if args.cooling < 0 or args.cooling > 255:
        parser.error("cooling must be between 0 and 255")
    return args


DEFAULT_ROWS = 24
DEFAULT_COLS = 80
# Sanity bound only -- far above any real full-screen terminal, just low
# enough to reject the absurd 16-bit NAWS maximum (65535) before it allocates
# a multi-gigabyte heat grid.
MAX_ROWS = 1000
MAX_COLS = 1000


def _sanitize_dimension(value, default, maximum):
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def get_terminal_size(writer):
    """
    Grab the most recent terminal size reported by the client via telnet NAWS.
    """
    rows = writer.get_extra_info("rows", DEFAULT_ROWS)
    cols = writer.get_extra_info("cols", DEFAULT_COLS)
    return (
        _sanitize_dimension(rows, DEFAULT_ROWS, MAX_ROWS),
        _sanitize_dimension(cols, DEFAULT_COLS, MAX_COLS),
    )


async def negotiate_telnet_options(writer):
    """
    Negotiate the telnet connection options with the client.
    """
    writer.iac(telopt.DO, telopt.NAWS)
    writer.iac(telopt.DO, telopt.SGA)
    writer.iac(telopt.WILL, telopt.SGA)
    writer.iac(telopt.WILL, telopt.ECHO)
    writer.iac(telopt.WONT, telopt.LINEMODE)

    # Give the client a bit of time to respond to the commands before starting.
    # This prevents needing to resize the animation 1-2 frames when the NAWS
    # response finally comes back.
    await asyncio.sleep(0.5)


async def shell(reader, writer):
    """
    A coroutine that's invoked after a new connection has been established.
    """
    await negotiate_telnet_options(writer)

    writer.write(CLEAR + HIDE_CURSOR)
    try:
        state = None
        for _frame in range(int(DURATION * FPS)):
            frame_start = time.monotonic()
            rows, cols = get_terminal_size(writer)
            if state is None or state.rows != rows or state.cols != cols:
                state = FireState(cols, rows)

            step_fire(state, COOLING)
            writer.write(render_fire(state, rows, cols))
            await writer.drain()

            # The input read doubles as frame pacing: wait only the remainder of
            # the frame period after the time already spent computing this frame,
            # so we hit the target FPS instead of (compute + 1/FPS). A small
            # floor keeps input polled -- so 'q' stays responsive -- on hardware
            # too slow to hit the target rate (where the remainder goes negative).
            remaining = 1 / FPS - (time.monotonic() - frame_start)
            try:
                char = await asyncio.wait_for(reader.read(1), timeout=max(0.001, remaining))
                if char == "q":
                    break
            except asyncio.TimeoutError:
                pass
    finally:
        # Restore the client's cursor even if they drop the connection mid-frame.
        writer.write(SHOW_CURSOR)
        writer.close()


def main():
    """
    Main entry point.
    """
    args = parse_args()

    logging.basicConfig(level=logging.INFO)
    logging.info(f"Listening on {args.host}:{args.port}.")

    global FPS
    FPS = args.fps
    logging.info(f"Animation speed {FPS} fps")

    global DURATION
    DURATION = args.duration
    logging.info(f"Duration {DURATION} seconds")

    global COOLING
    COOLING = args.cooling
    logging.info(f"Cooling {COOLING}")

    async def shell_wrapper(*arguments):
        try:
            await shell(*arguments)
        except ConnectionError:
            # This can at any point in the coroutine if the client kills the
            # connection. If we don't handle it, the coroutine will never
            # finish and asyncio will complain about the task being destroyed
            # while still pending.
            pass

    async def serve():
        server = await create_server(host=args.host, port=args.port, shell=shell_wrapper)
        await server.wait_closed()

    asyncio.run(serve())


if __name__ == "__main__":
    main()
