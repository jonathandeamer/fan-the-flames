# Codebase Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Robustify the `fan-the-flames` telnet server by fixing CPU consumption bugs, socket leaks, input pacing issues, implementing input validations, and updating documentation defaults.

**Architecture:** We will modify `telnet_server.py` to add strict finite and range validation, bounded terminal dimensions, and correct connection cleanup. We will extend the existing monotonic remaining-period pacing with bounded input work per frame, preserving its overrun input poll. We will also write corresponding test cases in `tests/test_server_wiring.py` and update the documentation in `README.md`.

**Tech Stack:** Python (asyncio, telnetlib3, pytest)

---

### Task 1: CLI Arguments Validation

Ensure CLI parameters passed to the application are valid. Bound cooling to the 0–255 heat domain; after commit `bec9a2e`, larger arbitrary-precision integers are multiplied by `random()` and sufficiently large values raise `OverflowError`.

**Files:**
- Modify: [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py)
- Test: [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py)

- [ ] **Step 1: Write the failing tests**
  Add `test_parse_args_validation` to [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py):
  ```python
  def test_parse_args_validation():
      import pytest
      from unittest import mock
      import sys
      from telnet_server import parse_args

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
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py::test_parse_args_validation -v`
  Expected: FAIL (or AttributeError/TypeError instead of expected SystemExit, as no validation exists yet)

- [ ] **Step 3: Write minimal implementation**
  Add `import math` alongside the standard-library imports, then modify `parse_args` in [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py):
  ```python
  import math


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
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py::test_parse_args_validation -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add telnet_server.py tests/test_server_wiring.py
  git commit -m "fix(cli): validate numeric argument ranges"
  ```

---

### Task 2: Defensive Terminal Size Handling

Ensure that advisory window sizes queried via NAWS are sanitized and bounded before allocating or rendering the fire grid. Per RFC 1073, a zero dimension means that the client is not supplying that dimension, so use the corresponding default rather than converting it to one.

**Files:**
- Modify: [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py)
- Test: [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py)

- [ ] **Step 1: Write the failing tests**
  Add `test_get_terminal_size_defensive` to [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py):
  ```python
  def test_get_terminal_size_defensive():
      from unittest import mock
      from telnet_server import MAX_COLS, MAX_ROWS, get_terminal_size

      writer = mock.Mock()
      # Malformed / missing sizes (non-integer types)
      writer.get_extra_info.side_effect = lambda key, default: {
          "rows": "abc",
          "cols": None
      }.get(key, default)
      rows, cols = get_terminal_size(writer)
      assert rows == 24
      assert cols == 80

      # Zero means unspecified; malformed negative values also use defaults.
      writer.get_extra_info.side_effect = lambda key, default: {
          "rows": 0,
          "cols": -10
      }.get(key, default)
      rows, cols = get_terminal_size(writer)
      assert rows == 24
      assert cols == 80

      # NAWS fields are 16-bit and untrusted, so cap oversized dimensions.
      writer.get_extra_info.side_effect = lambda key, default: {
          "rows": 65535,
          "cols": 65535
      }.get(key, default)
      rows, cols = get_terminal_size(writer)
      assert rows == MAX_ROWS
      assert cols == MAX_COLS
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py::test_get_terminal_size_defensive -v`
  Expected: FAIL (assertion failure since "abc" cannot be converted to int directly, or values <= 0 returned)

- [ ] **Step 3: Write minimal implementation**
  Modify `get_terminal_size` in [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py). The cap exists only to reject absurd values — NAWS fields are 16-bit, so an untrusted client can claim up to 65535×65535, which would allocate a multi-gigabyte heat list. We still want the fire to fill any real full-screen terminal, so set the cap far above any realistic terminal grid (a `1000×1000` grid is ~2M cells, trivially affordable) rather than at a size that would shrink a legitimately large window:
  ```python
  DEFAULT_ROWS = 24
  DEFAULT_COLS = 80
  # Sanity bound only -- far above any real full-screen terminal, just low
  # enough to reject the absurd 16-bit NAWS maximum (65535) before it
  # allocates a multi-gigabyte heat grid.
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
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py::test_get_terminal_size_defensive -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add telnet_server.py tests/test_server_wiring.py
  git commit -m "feat(server): sanitize terminal row and col values defensively"
  ```

---

### Task 3: Resource Leak Prevention during Option Negotiation

Move option negotiation inside the core connection wrapper try-finally block.

**Files:**
- Modify: [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py)
- Test: [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py)

- [ ] **Step 1: Write the failing tests**
  Add `test_shell_negotiation_failure_closes_writer` to [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py):
  ```python
  def test_shell_negotiation_failure_closes_writer():
      from unittest import mock
      import telnet_server

      async def _fail(writer):
          raise ConnectionError("Negotiation dropped")

      writer = _FakeWriter()
      with mock.patch.object(telnet_server, "negotiate_telnet_options", _fail):
          try:
              asyncio.run(telnet_server.shell(reader=None, writer=writer))
          except ConnectionError:
              pass

      assert writer.closed
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py::test_shell_negotiation_failure_closes_writer -v`
  Expected: FAIL (assertion failure, as negotiation occurs outside the try-finally block and leaves writer unclosed)

- [ ] **Step 3: Write minimal implementation**
  Modify `shell` in [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py) to wrap negotiation and the existing frame loop inside the try-finally block, and guard cursor restore writes. Preserve the remaining-period pacing added in commit `a7ec407`; do not restore the old fixed `1 / FPS` timeout:
  ```python
  async def shell(reader, writer):
      """
      A coroutine that's invoked after a new connection has been established.
      """
      try:
          await negotiate_telnet_options(writer)
          writer.write(CLEAR + HIDE_CURSOR)
          state = None
          for _frame in range(int(DURATION * FPS)):
              frame_start = time.monotonic()
              rows, cols = get_terminal_size(writer)
              if state is None or state.rows != rows or state.cols != cols:
                  state = FireState(cols, rows)

              step_fire(state, COOLING)
              writer.write(render_fire(state, rows, cols))
              await writer.drain()

              remaining = 1 / FPS - (time.monotonic() - frame_start)
              try:
                  char = await asyncio.wait_for(
                      reader.read(1), timeout=max(0.001, remaining)
                  )
                  if char == "q":
                      break
              except asyncio.TimeoutError:
                  pass
      finally:
          # Restore the client's cursor even if they drop the connection mid-frame.
          try:
              writer.write(SHOW_CURSOR)
          except ConnectionError:
              pass
          writer.close()
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py -v` (ensuring the new test and the existing `test_shell_input_wait_subtracts_compute_time` and `test_shell_hides_cursor_then_restores_it` tests pass)
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add telnet_server.py tests/test_server_wiring.py
  git commit -m "fix(server): wrap negotiation in try/finally to prevent socket leaks"
  ```

---

### Task 4: EOF Detection, Bounded Input, and Client Pacing

Fix EOF tight-loop spinning, ensure frame rates remain correct when user keystrokes occur, and limit the input work a flooding client can trigger during each frame.

**Files:**
- Modify: [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py)
- Test: [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py)

- [ ] **Step 1: Write the failing tests**
  Reuse the existing `_LoopWriter`, added in commit `a7ec407`, because it already implements `get_extra_info()` and `drain()`. Add `test_shell_eof_terminates_loop`, `test_shell_paces_next_frame_after_input`, and `test_shell_bounds_input_reads_per_frame` to [tests/test_server_wiring.py](file:///Users/jonathan/ride-the-wave/tests/test_server_wiring.py):
  ```python
  def test_shell_eof_terminates_loop():
      from unittest import mock
      import telnet_server

      class _FakeReader:
          async def read(self, n):
              return ""  # EOF immediately

      writer = _LoopWriter()
      async def _noop(writer):
          pass

      with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), \
           mock.patch.object(telnet_server, "DURATION", 10.0), \
           mock.patch.object(telnet_server, "FPS", 10):
          asyncio.run(telnet_server.shell(reader=_FakeReader(), writer=writer))

      # The simulation should have terminated immediately on EOF, having written very few outputs.
      assert len(writer.writes) < 5


  def test_shell_paces_next_frame_after_input():
      from unittest import mock
      import telnet_server

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

      with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), \
           mock.patch.object(telnet_server, "DURATION", 0.2), \
           mock.patch.object(telnet_server, "FPS", 10):
          asyncio.run(telnet_server.shell(reader=_FakeReader(), writer=writer))

      assert len(writer.frame_times) == 2
      assert writer.frame_times[1] - writer.frame_times[0] >= 0.08


  def test_shell_bounds_input_reads_per_frame():
      from unittest import mock
      import telnet_server

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

      with mock.patch.object(telnet_server, "negotiate_telnet_options", _noop), \
           mock.patch.object(telnet_server, "DURATION", 0.1), \
           mock.patch.object(telnet_server, "FPS", 10), \
           mock.patch.object(asyncio, "sleep", _record_sleep):
          asyncio.run(telnet_server.shell(reader=reader, writer=writer))

      assert 0 < reader.calls <= telnet_server.MAX_INPUT_READS_PER_FRAME
      assert sleep_delays
      assert 0 < sleep_delays[0] <= 0.1
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py -k "shell_eof or shell_paces or shell_bounds" -v`
  Expected: FAIL. The current loop does not stop on EOF, advances immediately after buffered input, and does not explicitly sleep after consuming bounded input.

- [ ] **Step 3: Write minimal implementation**
  Define a small per-frame input budget and modify the main frame loop inside `shell` in [telnet_server.py](file:///Users/jonathan/ride-the-wave/telnet_server.py). Continue using `time.monotonic()` so the existing compute-time pacing test remains valid. Preserve one 1 ms input poll when rendering overruns the frame period so `q` remains responsive; after bounded immediate reads, explicitly sleep for any remaining frame time:
  ```python
  MAX_INPUT_READS_PER_FRAME = 16
  MIN_INPUT_POLL_TIMEOUT = 0.001


  async def shell(reader, writer):
      """
      A coroutine that's invoked after a new connection has been established.
      """
      try:
          await negotiate_telnet_options(writer)
          writer.write(CLEAR + HIDE_CURSOR)
          state = None
          for _frame in range(int(DURATION * FPS)):
              frame_start = time.monotonic()
              rows, cols = get_terminal_size(writer)
              if state is None or state.rows != rows or state.cols != cols:
                  state = FireState(cols, rows)

              step_fire(state, COOLING)
              writer.write(render_fire(state, rows, cols))
              await writer.drain()

              should_exit = False
              if reader is not None:
                  for read_index in range(MAX_INPUT_READS_PER_FRAME):
                      elapsed = time.monotonic() - frame_start
                      delay = (1.0 / FPS) - elapsed
                      if delay <= 0:
                          if read_index > 0:
                              break
                          delay = MIN_INPUT_POLL_TIMEOUT
                      try:
                          char = await asyncio.wait_for(reader.read(1), timeout=delay)
                          if not char or char == "q":
                              should_exit = True
                              break
                      except asyncio.TimeoutError:
                          break

              if should_exit:
                  break

              elapsed = time.monotonic() - frame_start
              delay = (1.0 / FPS) - elapsed
              if delay > 0:
                  await asyncio.sleep(delay)
      finally:
          # Restore the client's cursor even if they drop the connection mid-frame.
          try:
              writer.write(SHOW_CURSOR)
          except ConnectionError:
              pass
          writer.close()
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `venv/bin/python -m pytest tests/test_server_wiring.py -v` (confirming all new tests and the existing `test_shell_input_wait_subtracts_compute_time` regression test pass)
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add telnet_server.py tests/test_server_wiring.py
  git commit -m "fix(server): bound input reads and preserve frame pacing"
  ```

---

### Task 5: README Default Values Alignment

Update the defaults table in the README to match the actual configuration in the codebase. Only `--duration` (currently `10`, should be `20`) and `--cooling` (currently `18`, should be `10`) are out of sync; `--fps` already shows `10` and must keep its descriptive guidance. There is no automated test for this table, so it is verified by reading the rendered result.

**Files:**
- Modify: [README.md](file:///Users/jonathan/ride-the-wave/README.md)

- [ ] **Step 1: Edit only the duration and cooling rows**
  In [README.md](file:///Users/jonathan/ride-the-wave/README.md), change the `--duration` default from `10` to `20` and the `--cooling` default from `18` to `10`. **Do not rewrite the `--fps` row** — its default is already correct; only soften its guidance wording away from the Pi by replacing `keep it modest on a Pi Zero` with `keep it modest on lower-spec machines`. After the edit the three rows should read:
  ```markdown
  | `--fps` | `10` | Animation frames per second. Higher is smoother but sends more data each second — keep it modest on lower-spec machines. |
  | `--duration` | `20` | Seconds to run the animation before the server closes the connection. |
  | `--cooling` | `10` | How fast heat fades as it rises. Lower values let flames climb higher; higher values make them shorter and stubbier. |
  ```

- [ ] **Step 2: Verify the table manually**
  There is no test covering the defaults table — the implementer must check it by eye. Re-read the edited table in [README.md](file:///Users/jonathan/ride-the-wave/README.md) and confirm, value by value, that every default matches `telnet_server.py` (`FPS = 10`, `DURATION = 20`, `COOLING = 10`, `--port` default `7777`, `--host` default `127.0.0.1`). Confirm the `--fps` guidance text survived the edit (no longer Pi-specific, but still present). Do not mark this step done until each row has been eyeballed against the source.

- [ ] **Step 3: Commit**
  ```bash
  git add README.md
  git commit -m "docs: align README defaults with configuration in server code"
  ```
