# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Fan the Flames** is a telnet splash-screen server: when a client connects, it streams a Doom-style ASCII fire animation in 24-bit truecolor, then closes the connection after a fixed duration. It is a GPL-3.0 fork of [ride-the-wave](https://github.com/michael-lazar/ride-the-wave) (which animated a wave); the rendering technique is adapted from [lavat](https://github.com/AngelJumbo/lavat) (MIT). Intended to run on a Raspberry Pi Zero and be viewed from a truecolor + UTF-8 terminal (e.g. Ghostty).

## Environment & commands

Dependencies live in a virtualenv at `venv/` (it has `telnetlib3`, `pytest`, and the linters). A bare `python3` will **not** have `telnetlib3` — always use the venv interpreter:

```bash
venv/bin/python -m pytest                 # full suite
venv/bin/python -m pytest tests/test_fire.py::test_step_is_deterministic_under_seed -v   # single test
venv/bin/python -m pyflakes telnet_server.py
venv/bin/python -m black --line-length 100 telnet_server.py tests/
venv/bin/python -m isort --profile black telnet_server.py tests/
venv/bin/python -m flake8 --config=setup.cfg telnet_server.py
```

Run it locally (two terminals — server, then client):

```bash
venv/bin/python telnet_server.py --port 7777        # terminal 1
telnet 127.0.0.1 7777                                # terminal 2 (press q to quit early)
```

CLI knobs: `--host`, `--port`, `--fps`, `--duration`, `--cooling` (lower = taller flames).

## Architecture

All runtime code is in the single file **`telnet_server.py`**, deliberately (see "Constraints"). It reads top-to-bottom as a pipeline; understanding these four stages is the whole program:

1. **Palette** (`fire_rgb`, `FG_PALETTE`, `BG_PALETTE`) — `fire_rgb` interpolates a heat value 0–255 over the `_FIRE_STOPS` ramp (black→red→orange→yellow→white). `FG_PALETTE`/`BG_PALETTE` are 256 precomputed truecolor escape strings (`38;2…` / `48;2…`) so rendering never builds color strings per cell — this is the main performance lever for the Pi Zero.

2. **Simulation** (`FireState`, `step_fire`) — `FireState.heat` is a flat list of `cols × (rows*2)` heat bytes, indexed `y*cols + x`; the doubled height exists because of half-block rendering. `step_fire` re-heats a shimmering bottom source row, then propagates heat upward, each cell = the cell below minus random cooling, with random horizontal drift. **Critical:** it iterates rows *top-to-bottom* on purpose, so each row reads the **previous frame's** value of the row below it. Iterating bottom-to-top would read same-frame writes and make the fire memoryless (instant full-height cascade, no rising motion). Do not "simplify" the loop direction.

3. **Render** (`build_overlay`, `render_fire`) — each terminal cell is a `▀` half-block: foreground colors the upper heat sample, background the lower, doubling vertical resolution. Color escapes are emitted only when the fg/bg index changes from the previous cell (run-length). `build_overlay` returns the `[q]uit` footer cells (bottom-right; empty when the window is too narrow) — there is **no title banner**. A footer cell breaks the color run and resets the fg/bg trackers.

4. **Server** (`shell`, `negotiate_telnet_options`, `main`) — `shell` is the per-connection asyncio coroutine: negotiate telnet options (incl. NAWS for live terminal size), hide the cursor, then loop `DURATION*FPS` frames re-reading size each frame (rebuilding `FireState` on resize), stepping + rendering, and quitting on `q`. `FPS`/`DURATION`/`COOLING` are module globals set from CLI args in `main`; the loop reads them live. `main` runs the server via `asyncio.run`.

Tests cover the pure stages directly (`test_palette`, `test_fire`, `test_render`); `test_server_wiring` drives the `shell` coroutine with a fake writer; `test_licensing` asserts the fork/attribution text stays present.

## Constraints

- **Single file.** All runtime code stays in `telnet_server.py` — do not split it into a package without an explicit decision; tests import the pure functions from it.
- **GPL-3.0 fork obligations.** Keep `LICENSE` unchanged. Keep Michael Lazar's copyright/attribution in the module header, the README, and the docstring, plus the dated modification notice (GPL §5). `test_licensing.py` enforces this; don't strip those strings.
- **Truecolor + UTF-8 only.** Emit 24-bit escapes and the `▀` glyph; the target client is assumed to support them.
- **Commits.** Conventional Commits. Never add AI/tool commit trailers, co-author credits, or AI git identities.

## Design docs

The spec and implementation plan live in `docs/superpowers/specs/` and `docs/superpowers/plans/` — consult them before reworking the simulation or renderer; they record the rationale for the decisions above.
