# Fan the Flames — Design

**Date:** 2026-06-26
**Status:** Approved (pending spec review)

## Summary

Fork `michael-lazar/ride-the-wave` (a GPL-3.0 telnet splash screen for mozz.us)
into **Fan the Flames** (`fan-the-flames`): replace the scrolling ASCII wave with
a Doom-style fire animation rendered in 24-bit truecolor using half-block glyphs.

The existing telnet/asyncio server is reused wholesale; only the rendering core
is replaced. Rendering technique is adapted (concepts, not code) from
`AngelJumbo/lavat` (MIT) — its half-block 2× vertical resolution trick and its
continuous-scalar-to-gradient-palette approach.

## Context & Constraints

- **Host:** Raspberry Pi Zero (single-core ARMv6 ~1 GHz, 512 MB). Sim is cheap;
  the cost that matters is building/sending truecolor strings per frame.
- **Client:** the author's Mac running Ghostty (full truecolor + UTF-8), so
  half-blocks and 24-bit color render correctly. Target is a single client.
- **Protocol:** telnet only for v1. SSH is deliberately deferred (YAGNI); the
  rendering core stays protocol-agnostic so SSH can be added later as a second
  front-end via `asyncssh` without a rewrite.
- **Window:** author runs Ghostty fullscreen, but smaller windows must degrade
  gracefully. Terminal size is already read every frame via telnet NAWS; the
  banner already no-ops when the window is too small.

## Architecture

Keep the single-file structure and reuse the working scaffold.

**Keep as-is:** `negotiate_telnet_options`, `get_terminal_size`, `main` /
`shell_wrapper`, and the per-frame loop + `[q]uit` handling in `shell`.

**Extend:** `parse_args` gains a `--cooling` argument (and `main` wires it into
the sim) alongside the existing `--fps` / `--duration`. The rest of `parse_args`
is unchanged.

**Replace:** `WAVE`, `render_screen`, the `^color` ANSI-cycle trick, and the
`lru_cache` — a stochastic fire is not periodic, so caching by
`(rows, cols, offset)` no longer applies and is dropped.

**Add:**
- `FireState` — per-connection object holding the heat grid (flat array of
  `cols × H` bytes, 0–255, where `H = rows * 2`). Created in `shell`,
  reallocated on resize.
- `step_fire(state)` — advances the simulation one frame.
- `render_fire(state, rows, cols)` — heat grid → truecolor half-block string,
  with the `[q]uit` footer overlaid at the cell level (see Rendering). No title
  banner.
- `FG_PALETTE` / `BG_PALETTE` — 256 precomputed truecolor escape strings each
  (`38;2;…m` foreground and `48;2;…m` background) over the same black→red→
  orange→yellow→white RGB ramp, so both halves of a cell color without per-cell
  string building.

## Simulation (`step_fire`)

Doom-style heat-field over a `cols × H` byte grid (`H = rows * 2`).

- **Source row:** the bottom row is held hot each frame, randomized around max
  (e.g. `230 + rand(0..25)`) so the base shimmers instead of sitting flat.
- **Propagation (bottom→up):** each cell derives heat from the cell below minus
  a random cooling amount, with a random horizontal drift so flames lean/lick:
  `new[x][y] = old[x ± drift][y+1] − decay`, clamped at 0.
- **Edges:** off-grid reads as 0 (cold), so flames taper at the left/right
  margins.
- **Resize:** if `(rows, cols)` changed since the last frame, allocate a fresh
  grid; discarded heat re-establishes within a few frames.
- **Tunable:** one knob, `cooling`, exposed as `--cooling` alongside the existing
  `--fps` / `--duration`. No other knobs (YAGNI).

## Rendering (`render_fire` + `PALETTE`)

- **Palette:** one fixed black→red→orange→yellow→white RGB ramp (256 entries),
  precomputed into `FG_PALETTE` (`38;2;r;g;bm`) and `BG_PALETTE` (`48;2;r;g;bm`)
  so a cell's upper and lower halves each index a ready-made escape (lavat's
  palette concept with a fixed ramp).
- **Half-blocks:** each terminal cell renders two vertical heat samples as `▀`
  with fg = `FG_PALETTE[upper]`, bg = `BG_PALETTE[lower]` — doubling vertical
  resolution (lavat.c:223-289).
- **Run-length color optimization:** track the previously emitted foreground and
  background indices independently, and emit an `FG_PALETTE` / `BG_PALETTE`
  escape only when its index changes from the previous cell. Primary lever for
  keeping the Pi Zero within framerate (cuts both CPU and bytes).
- **No title banner:** the fire fills the whole screen. (The old wave version
  centered a `MOZZ.US / Ride the Wave` banner; we drop the title entirely.)
- **Footer only:** a small `[q]uit` hint is overlaid **into the cell grid before
  escape generation**, not by string-slicing rendered rows (which would miscount
  ANSI escape bytes as columns on truecolor rows). It is marked as fixed
  glyph + fixed fg/bg in the per-cell render path, placed at the bottom edge, and
  auto-skipped when the window is too narrow for it. The old `overlay_banner`
  string-slicing helper is removed.

### Performance risk & mitigation

Python on ARMv6 building per-frame truecolor strings is the only real risk to
target framerate. De-risk by measuring on the Pi Zero at the author's terminal
size. If it can't hold ~10–15 fps: the run-length color optimization is the first
lever; a compiled emitter is the last-resort fallback. Expectation: Python holds
framerate fine for a single client.

## Licensing / Fork Workstream

`ride-the-wave` is **GPL-3.0** and we keep its server code, so our version is a
derivative and **must remain GPL-3.0**. `lavat` is **MIT**; we reimplement its
ideas in Python (algorithms aren't copyrightable), so attribution is courtesy.

- Keep `LICENSE` (GPL-3.0) unchanged.
- File header: keep Michael Lazar's author + license notice; add a modification
  notice + date (GPL §5 requires marking modified files) and bump the version.
- Rewrite `README`: state it is a GPL-3.0 fork of `ride-the-wave` (link),
  describe the fire change, and credit `lavat` (MIT, link) for the rendering
  technique.
- Remove the Joan Stark ASCII-wave art credit (wave art is removed).
- Rename project to `fan-the-flames`; drop the mozz.us banner entirely (no title
  is overlaid). Branding lives in the README and module header only.
- Remote rewiring (`origin` → author's fork, add `upstream`) is deferred until
  the GitHub fork exists. Build locally first.

## Out of Scope (v1)

- SSH front-end (deferred; core kept protocol-agnostic).
- Multiple concurrent-client tuning beyond what the existing server provides.
- Configurable palettes / additional animation modes.
