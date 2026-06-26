# Fan the Flames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scrolling ASCII wave in the `ride-the-wave` telnet splash screen with a Doom-style truecolor fire animation, rebranded as "Fan the Flames".

**Architecture:** Reuse the existing telnetlib3 + asyncio server wholesale. Replace only the rendering core: a per-connection heat-field simulation (`FireState` + `step_fire`) feeding a half-block truecolor renderer (`render_fire`) backed by two precomputed gradient palettes. The banner is overlaid at the cell level before escape generation. All new code lives in `telnet_server.py` per the spec's single-file constraint; pure functions are unit-tested.

**Tech Stack:** Python 3.11+, telnetlib3, pytest (dev), black/isort/flake8/mypy.

## Global Constraints

- **License:** project stays **GPL-3.0**. Keep `LICENSE` unchanged; keep Michael Lazar's author/license header; add a modification notice + date.
- **Single file:** all runtime code stays in `telnet_server.py` (spec constraint). Tests import pure functions from it.
- **Python floor:** 3.11+ (matches mypy/pyupgrade config). Type hints allowed (`tuple[int, int, int]`, etc.).
- **Style:** black line-length 100; isort profile black; flake8 per `setup.cfg`.
- **Commits:** Conventional Commits. **Never** add AI trailers, co-author credits, or AI git identities.
- **Truecolor only:** emit 24-bit escapes (`\x1b[38;2;r;g;bm` / `\x1b[48;2;r;g;bm`) and the `▀` half-block glyph. Target client is Ghostty.
- **Banner text:** "FAN THE FLAMES". No mozz.us identity. No Joan Stark credit (wave art removed).

---

### Task 1: Dev tooling & test scaffold

**Files:**
- Create: `requirements-dev.in`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `python3 -m pytest` invocation for later tasks.

- [ ] **Step 1: Create dev requirements**

`requirements-dev.in`:
```
pytest
telnetlib3
```

- [ ] **Step 2: Install into the active environment**

Run: `python3 -m pip install -r requirements-dev.in`
Expected: pytest + telnetlib3 install successfully.

- [ ] **Step 3: Create an empty tests package**

Create `tests/__init__.py` with no content.

- [ ] **Step 4: Write a smoke test that the module imports**

`tests/test_smoke.py`:
```python
def test_module_imports():
    import telnet_server  # noqa: F401
```

- [ ] **Step 5: Run it**

Run: `python3 -m pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.in tests/__init__.py tests/test_smoke.py
git commit -m "test: add pytest scaffold and import smoke test"
```

---

### Task 2: Fire gradient palettes

**Files:**
- Modify: `telnet_server.py` (add palette code near the other VT-100 constants)
- Test: `tests/test_palette.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `fire_rgb(heat: int) -> tuple[int, int, int]` — clamps heat to 0–255, returns an `(r, g, b)` on the ramp.
  - `FG_PALETTE: list[str]` — 256 entries, `"\x1b[38;2;{r};{g};{b}m"`.
  - `BG_PALETTE: list[str]` — 256 entries, `"\x1b[48;2;{r};{g};{b}m"`.

- [ ] **Step 1: Write the failing test**

`tests/test_palette.py`:
```python
from telnet_server import BG_PALETTE, FG_PALETTE, fire_rgb


def test_ramp_endpoints_and_stops():
    assert fire_rgb(0) == (0, 0, 0)        # coldest -> black
    assert fire_rgb(128) == (255, 0, 0)    # mid -> red
    assert fire_rgb(255) == (255, 255, 255)  # hottest -> white


def test_ramp_clamps_out_of_range():
    assert fire_rgb(-50) == (0, 0, 0)
    assert fire_rgb(999) == (255, 255, 255)


def test_palettes_have_256_entries_and_correct_escapes():
    assert len(FG_PALETTE) == 256
    assert len(BG_PALETTE) == 256
    assert FG_PALETTE[255] == "\x1b[38;2;255;255;255m"
    assert BG_PALETTE[0] == "\x1b[48;2;0;0;0m"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_palette.py -v`
Expected: FAIL with `ImportError: cannot import name 'fire_rgb'`.

- [ ] **Step 3: Write minimal implementation**

Add to `telnet_server.py` (after the existing VT-100 constants block):
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_palette.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add telnet_server.py tests/test_palette.py
git commit -m "feat: add fire gradient palettes"
```

---

### Task 3: Fire simulation

**Files:**
- Modify: `telnet_server.py`
- Test: `tests/test_fire.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class FireState` with attributes `cols: int`, `rows: int`, `height: int` (`= rows * 2`), and `heat: list[int]` (flat, length `cols * height`, indexed `y * cols + x`, all zero at init).
  - `step_fire(state: FireState, cooling: int, rng=random) -> None` — mutates `state.heat` in place: re-heats the bottom row and propagates upward.

- [ ] **Step 1: Write the failing test**

`tests/test_fire.py`:
```python
import random

from telnet_server import FireState, step_fire


def test_firestate_dimensions():
    state = FireState(cols=10, rows=4)
    assert state.cols == 10
    assert state.rows == 4
    assert state.height == 8
    assert len(state.heat) == 80
    assert set(state.heat) == {0}


def test_step_heats_bottom_row_and_stays_in_range():
    random.seed(0)
    state = FireState(cols=8, rows=3)  # height 6
    step_fire(state, cooling=18)
    bottom = state.heat[(state.height - 1) * state.cols:]
    assert all(230 <= v <= 255 for v in bottom)
    assert all(0 <= v <= 255 for v in state.heat)


def test_step_is_deterministic_under_seed():
    random.seed(42)
    a = FireState(cols=6, rows=3)
    step_fire(a, cooling=12)
    random.seed(42)
    b = FireState(cols=6, rows=3)
    step_fire(b, cooling=12)
    assert a.heat == b.heat


def test_flames_cool_toward_the_top():
    random.seed(1)
    state = FireState(cols=12, rows=5)
    for _ in range(30):  # let the fire establish
        step_fire(state, cooling=18)
    top_row_avg = sum(state.heat[: state.cols]) / state.cols
    bottom_row_avg = sum(state.heat[(state.height - 1) * state.cols:]) / state.cols
    assert top_row_avg < bottom_row_avg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_fire.py -v`
Expected: FAIL with `ImportError: cannot import name 'FireState'`.

- [ ] **Step 3: Write minimal implementation**

Add `import random` to the imports block, and add to `telnet_server.py`:
```python
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

    # Hot, shimmering source row along the bottom.
    base = (height - 1) * cols
    for x in range(cols):
        heat[base + x] = 230 + rng.randint(0, 25)

    # Each cell above cools off a copy of the cell below, with horizontal drift.
    for y in range(height - 2, -1, -1):
        row = y * cols
        below = (y + 1) * cols
        for x in range(cols):
            src_x = x + rng.randint(-1, 1)
            src = heat[below + src_x] if 0 <= src_x < cols else 0
            value = src - rng.randint(0, cooling)
            heat[row + x] = value if value > 0 else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_fire.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add telnet_server.py tests/test_fire.py
git commit -m "feat: add doom-style fire simulation"
```

---

### Task 4: Half-block renderer & banner overlay

**Files:**
- Modify: `telnet_server.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `FireState`, `step_fire`, `FG_PALETTE`, `BG_PALETTE`.
- Produces:
  - `BANNER: list[str]` — equal-width rows spelling "FAN THE FLAMES".
  - `build_overlay(rows: int, cols: int) -> dict[tuple[int, int], str]` — maps `(term_row, col) -> glyph` for banner + `[q]uit` footer cells; empty banner cells (spaces) are omitted; banner skipped entirely when the window is smaller than the banner.
  - `render_fire(state: FireState, rows: int, cols: int) -> str` — full frame string: cursor reset, half-block cells with run-length color, banner overlaid, trailing reset.

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:
```python
import random

from telnet_server import FireState, build_overlay, render_fire, step_fire


def test_overlay_centers_banner_when_room():
    overlay = build_overlay(rows=24, cols=80)
    glyphs = "".join(sorted(set(overlay.values())))
    # banner letters present
    for ch in "FANTHEL":
        assert ch in glyphs
    # footer present
    assert "q" in overlay.values()


def test_overlay_skips_banner_when_too_small():
    overlay = build_overlay(rows=2, cols=5)
    # No banner letters fit; must not raise and must not place banner rows.
    assert all(r < 2 for (r, _c) in overlay)


def test_render_all_cold_is_black_and_well_formed():
    state = FireState(cols=4, rows=2)  # all-zero heat
    frame = render_fire(state, rows=2, cols=4)
    assert frame.startswith("\x1b[0;0H")       # cursor reset first
    assert "▀" in frame                    # half-block glyph used
    assert "\x1b[38;2;0;0;0m" in frame          # cold -> black fg
    assert "\x1b[48;2;0;0;0m" in frame          # cold -> black bg
    assert frame.endswith("\x1b[0m")            # reset at end


def test_render_includes_banner_glyphs():
    random.seed(0)
    state = FireState(cols=80, rows=24)
    step_fire(state, cooling=18)
    frame = render_fire(state, rows=24, cols=80)
    assert "FAN" in frame or "F" in frame  # banner text rendered into the frame
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_overlay'`.

- [ ] **Step 3: Write minimal implementation**

Add to `telnet_server.py`:
```python
HALF_BLOCK = "▀"  # upper half block: fg paints top pixel, bg paints bottom
BANNER_FG = "\x1b[1m\x1b[38;2;255;255;255m"  # bold white
BANNER_BG = "\x1b[48;2;0;0;0m"  # black
FOOTER = "[q]uit"

BANNER = [
    "                   ",
    "   F A N   T H E   ",
    "    F L A M E S    ",
    "  ---------------  ",
    "                   ",
]


def build_overlay(rows: int, cols: int) -> dict[tuple[int, int], str]:
    """Map (row, col) -> glyph for banner and footer cells overlaid on the fire."""
    cells: dict[tuple[int, int], str] = {}

    banner_h = len(BANNER)
    banner_w = len(BANNER[0])
    if rows >= banner_h and cols >= banner_w:
        top = (rows - banner_h) // 2
        left = (cols - banner_w) // 2
        for i, line in enumerate(BANNER):
            for j, ch in enumerate(line):
                if ch != " ":
                    cells[(top + i, left + j)] = ch

    if rows >= 1 and cols > len(FOOTER):
        r = rows - 1
        start = cols - len(FOOTER)
        for j, ch in enumerate(FOOTER):
            cells[(r, start + j)] = ch

    return cells


def render_fire(state: FireState, rows: int, cols: int) -> str:
    """Render one frame: half-block truecolor cells with the banner overlaid."""
    heat = state.heat
    grid_cols = state.cols
    height = state.height
    overlay = build_overlay(rows, cols)

    out = [RESET]
    for r in range(rows):
        last_fg = last_bg = None
        upper = 2 * r
        lower = 2 * r + 1
        for x in range(cols):
            glyph = overlay.get((r, x))
            if glyph is not None:
                out.append(BANNER_FG + BANNER_BG + glyph)
                last_fg = last_bg = None  # banner broke the color run
                continue

            if x < grid_cols:
                u = heat[upper * grid_cols + x] if upper < height else 0
                l = heat[lower * grid_cols + x] if lower < height else 0
            else:
                u = l = 0

            if u != last_fg:
                out.append(FG_PALETTE[u])
                last_fg = u
            if l != last_bg:
                out.append(BG_PALETTE[l])
                last_bg = l
            out.append(HALF_BLOCK)

        if r < rows - 1:
            out.append("\r\n")
    out.append(END)
    return "".join(out)
```

Note: `RESET` (`"\x1b[0;0H"`) and `END` (`"\x1b[0m"`) already exist in the file's constants block — reuse them, do not redefine.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add telnet_server.py tests/test_render.py
git commit -m "feat: add half-block fire renderer with banner overlay"
```

---

### Task 5: Wire the renderer into the server

**Files:**
- Modify: `telnet_server.py` (`parse_args`, `main`, `shell`; remove `WAVE`, `render_screen`, old `overlay_banner`, `lru_cache` import, and now-unused wave constants)
- Test: `tests/test_server_wiring.py`

**Interfaces:**
- Consumes: `FireState`, `step_fire`, `render_fire`, `parse_args`.
- Produces: a `--cooling` CLI argument; a `COOLING` module global; a fire-driven `shell` loop.

- [ ] **Step 1: Write the failing test**

`tests/test_server_wiring.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_server_wiring.py -v`
Expected: FAIL (`args` has no attribute `cooling`, and `WAVE` still exists).

- [ ] **Step 3: Add the `--cooling` arg and `COOLING` global**

In the constants block add:
```python
COOLING = 18
```
In `parse_args`, add before `return parser.parse_args()`:
```python
    parser.add_argument("--cooling", default=COOLING, type=int)
```
In `main`, after the `DURATION` wiring, add:
```python
    global COOLING
    COOLING = args.cooling
    logging.info(f"Cooling {COOLING}")
```

- [ ] **Step 4: Replace the `shell` loop body**

Replace the existing `for frame in range(...)` block inside `shell` with:
```python
    writer.write(CLEAR)
    state = None
    for _frame in range(int(DURATION * FPS)):
        rows, cols = get_terminal_size(writer)
        if state is None or state.rows != rows or state.cols != cols:
            state = FireState(cols, rows)

        step_fire(state, COOLING)
        writer.write(render_fire(state, rows, cols))
        await writer.drain()

        try:
            char = await asyncio.wait_for(reader.read(1), timeout=1 / FPS)
            if char == "q":
                break
        except asyncio.TimeoutError:
            pass

    writer.close()
```

- [ ] **Step 5: Delete dead wave code**

Remove from `telnet_server.py`: `from functools import lru_cache`; the `WAVE` list; the `BANNER_ROWS`/`BANNER_COLS` lines tied to the old banner; the entire `render_screen` function (including its `@lru_cache` decorator); the old `overlay_banner` function; and the now-unused wave constants `WATER`, `BOLD`, `RED`, `GREEN`, `YELLOW`, `MAGENTA`, `HIDE_CURSOR` if not referenced elsewhere. Keep `END`, `CLEAR`, `RESET`. Verify with: `python3 -m pyflakes telnet_server.py` (or `flake8`) showing no unused-import/name errors.

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest -v`
Expected: PASS (all tests across all files).

- [ ] **Step 7: Manual smoke (optional but recommended)**

Run the server and connect:
```bash
python3 telnet_server.py --port 7777 &
telnet 127.0.0.1 7777
```
Expected: a fire animation with the "FAN THE FLAMES" banner; pressing `q` disconnects; resizing the window reflows. Kill the server when done: `kill %1`.

- [ ] **Step 8: Commit**

```bash
git add telnet_server.py tests/test_server_wiring.py
git commit -m "feat: drive the telnet shell with the fire animation"
```

---

### Task 6: Licensing, branding & docs

**Files:**
- Modify: `telnet_server.py` (module docstring + header metadata)
- Modify: `README.md`
- Modify: `ride-the-wave.service` (description/comment only)
- Test: `tests/test_licensing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: GPL-compliant modification notice; rebranded docs; no mozz.us/Joan Stark references in code.

- [ ] **Step 1: Write the failing test**

`tests/test_licensing.py`:
```python
from pathlib import Path

SRC = Path("telnet_server.py").read_text()
README = Path("README.md").read_text()


def test_header_keeps_original_author_and_marks_modification():
    assert "Michael Lazar" in SRC          # original author retained (GPL)
    assert "Modified" in SRC               # modification notice present
    assert "2026" in SRC


def test_joan_stark_and_wave_credit_removed():
    assert "Joan Stark" not in SRC
    assert "Ride the Wave" not in SRC


def test_readme_states_fork_and_credits():
    assert "GPL" in README
    assert "ride-the-wave" in README       # links the upstream fork source
    assert "lavat" in README               # credits the technique
    assert "Fan the Flames" in README
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_licensing.py -v`
Expected: FAIL (Joan Stark still in docstring; README unchanged).

- [ ] **Step 3: Update the module docstring + header**

Replace the top-of-file docstring and metadata in `telnet_server.py` with:
```python
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

__author__ = "Michael Lazar"
__license__ = "GNU GPL v3"
__copyright__ = "Michael Lazar"
__version__ = "2.0.0"

# Modified 2026 by Jonathan Deamer: replaced the wave animation with a fire
# animation and rebranded the project as "Fan the Flames".
```

- [ ] **Step 4: Rewrite README.md**

Replace `README.md` with:
```markdown
<h1 align="center">Fan the Flames</h1>

<p align="center">An animated telnet fire splash screen.</p>
<p align="center">Connect with <strong>$ telnet &lt;host&gt; 7777</strong></p>

## About

A Doom-style ASCII fire animation served over telnet, rendered in 24-bit
truecolor with half-block glyphs. Designed to run on a Raspberry Pi Zero and
viewed from a truecolor terminal such as Ghostty.

## Credits & License

This is a fork of [ride-the-wave](https://github.com/michael-lazar/ride-the-wave)
by Michael Lazar, which displayed a scrolling ASCII wave. As a derivative of
that GPL-3.0 project, **Fan the Flames is also licensed under GPL-3.0** (see
`LICENSE`).

The fire rendering technique — half-block glyphs for 2x vertical resolution and
a continuous heat-to-gradient palette — is adapted from
[lavat](https://github.com/AngelJumbo/lavat) by AngelJumbo (MIT).

## Usage

```
python3 telnet_server.py --host 0.0.0.0 --port 7777
```

Options: `--fps`, `--duration`, `--cooling` (flame height; lower = taller).
```

- [ ] **Step 5: Update the systemd unit description**

In `ride-the-wave.service`, update only the human-readable `Description=` line to `Description=Fan the Flames telnet fire splash screen`. Leave `ExecStart` and the rest untouched (the script filename is unchanged).

- [ ] **Step 6: Run the licensing test + full suite**

Run: `python3 -m pytest -v`
Expected: PASS (all tests).

- [ ] **Step 7: Run formatters/linters**

Run: `python3 -m black --line-length 100 telnet_server.py tests/ && python3 -m isort --profile black telnet_server.py tests/ && python3 -m flake8 --config=setup.cfg telnet_server.py`
Expected: no changes needed / no lint errors. Re-stage if black/isort reformatted anything.

- [ ] **Step 8: Commit**

```bash
git add telnet_server.py README.md ride-the-wave.service tests/test_licensing.py
git commit -m "docs: rebrand to Fan the Flames and record fork licensing"
```

---

## Self-Review

**Spec coverage:**
- Architecture (keep server scaffold, replace render core, drop lru_cache) → Tasks 4–5. ✓
- `parse_args` extended with `--cooling` → Task 5. ✓
- `FireState` + `step_fire` (source row, upward propagation, drift, edge=0, resize) → Task 3 + Task 5 (resize in `shell`). ✓
- `FG_PALETTE`/`BG_PALETTE` precomputed RGB ramp → Task 2. ✓
- Half-blocks + run-length fg/bg optimization → Task 4. ✓
- Cell-level banner overlay (not string-slicing), centered, auto-skip when small, footer → Task 4. ✓
- Performance: run-length optimization implemented; manual smoke in Task 5 Step 7 (Pi Zero fps validated at execution time). ✓
- Licensing/fork workstream (LICENSE kept, header modification notice, README fork+credits, remove Joan Stark, rebrand) → Task 6. ✓
- Out of scope (SSH, multi-palette) → not planned. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `FireState(cols, rows)` with `.cols/.rows/.height/.heat` used identically in Tasks 3, 4, 5. `step_fire(state, cooling, rng=random)` signature consistent. `render_fire(state, rows, cols)` and `build_overlay(rows, cols)` consistent across Tasks 4–5. `FG_PALETTE`/`BG_PALETTE`/`fire_rgb` consistent across Tasks 2, 4. ✓

**Note for executor:** the spec mandates the single-file layout, so `telnet_server.py` grows; that is intentional, not a decomposition miss.
