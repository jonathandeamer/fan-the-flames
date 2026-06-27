# Lightsail Deployment + Connection Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publicly serve "Fan the Flames" at `telnet.jonathandeamer.com:23` from the existing AWS Lightsail box, after adding application-level connection-flood protection, with a committed, repeatable manual deploy script (no GitHub Actions).

**Architecture:** Two halves. (1) **Code** — add per-source-IP and global concurrent-connection caps to the single-file asyncio server, enforced in `shell` before the render loop, configured by new CLI flags + module globals (mirroring the existing `FPS`/`DURATION`/`COOLING` pattern). (2) **Ops** — a parameterized `deploy.sh` that rsyncs the source to a host, builds a venv, renders the systemd unit for the target path, and restarts the service; plus one-shot AWS CLI commands to create the Route 53 A record and open the Lightsail firewall. Deploy mirrors the manual rsync-+-`systemctl restart` pattern used by the `nex` project on the same box.

**Tech Stack:** Python 3.11+, telnetlib3, pytest (dev); bash, OpenSSH, rsync; AWS CLI v2 (Route 53 + Lightsail); systemd.

## Global Constraints

- **License:** project stays **GPL-3.0**. Keep `LICENSE` and Michael Lazar's author/license header unchanged.
- **Single file:** all runtime code stays in `telnet_server.py`. Tests import from it.
- **Python floor:** 3.11+ (`dict[...]`/`tuple[...]` hints allowed).
- **Style:** black line-length 100; isort profile black; flake8 per `setup.cfg`. Run `venv/bin/python -m pyflakes telnet_server.py` and `... -m flake8 --config=setup.cfg telnet_server.py` clean before each code commit.
- **Commits:** Conventional Commits. **Never** add AI trailers, co-author credits, or AI git identities.
- **Truecolor only:** emit 24-bit escapes and the `▀` glyph. The rejection notice (new) must be **plain ASCII** so it encodes even for clients that never negotiate UTF-8.
- **Deployment facts (verbatim):**
  - SSH alias: `lightsail` → `admin@34.196.64.138`, key `~/.ssh/id_ed25519_lightsail`.
  - Lightsail instance name: `Debian-1`; region: `us-east-1`; static IP `34.196.64.138` (`StaticIp-1`, attached).
  - Box also runs `nex` (`buffetcar` service, ports 80/1900) under `/srv/nex`. Do not disturb it.
  - Route 53 hosted zone for `jonathandeamer.com`: `Z07504492U14KTJQU578V`. Existing `nex.jonathandeamer.com` is `A`, TTL 300 → `34.196.64.138`.
  - Lightsail firewall currently opens 22/80/1900 only; **23 is closed**. No OS firewall (iptables INPUT = ACCEPT).
  - Install dir on Lightsail: **`/srv/fan-the-flames`** (matches the `/srv/nex` convention).
- **Connection-limit defaults:** `MAX_PER_IP = 2`, `MAX_CONNECTIONS = 50` (CLI-overridable).

---

### Task 1: Connection-limit registry

Pure, synchronous accounting helpers plus a peer-IP extractor. No server wiring yet.

**Files:**
- Modify: `telnet_server.py` (add globals + functions after the `FPS`/`DURATION`/`COOLING` block, around line 175; add `get_peer_ip` near `get_terminal_size`, around line 197)
- Test: `tests/test_server_wiring.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MAX_PER_IP: int`, `MAX_CONNECTIONS: int` (module globals)
  - `_active_per_ip: dict[str, int]`, `_active_total: int` (module state)
  - `acquire_connection(ip: str) -> bool` — reserves a slot; `False` if a cap is hit.
  - `release_connection(ip: str) -> None` — frees a slot reserved by `acquire_connection`.
  - `get_peer_ip(writer) -> str` — returns the client IP from `writer.get_extra_info("peername")`, or `"?"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server_wiring.py`:

```python
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
        # a different IP is unaffected
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_server_wiring.py -k "acquire or release or peer_ip" -v`
Expected: FAIL with `AttributeError: module 'telnet_server' has no attribute 'acquire_connection'` (and the others).

- [ ] **Step 3: Write the minimal implementation**

In `telnet_server.py`, immediately after the `COOLING = 10` line (currently line 175):

```python
MAX_PER_IP = 2
MAX_CONNECTIONS = 50

# Concurrent-connection accounting for flood protection. asyncio is
# single-threaded, so these are mutated without locking.
_active_per_ip: dict[str, int] = {}
_active_total = 0


def acquire_connection(ip: str) -> bool:
    """Reserve a connection slot for `ip`; return False if a cap is hit."""
    global _active_total
    if _active_total >= MAX_CONNECTIONS:
        return False
    if _active_per_ip.get(ip, 0) >= MAX_PER_IP:
        return False
    _active_per_ip[ip] = _active_per_ip.get(ip, 0) + 1
    _active_total += 1
    return True


def release_connection(ip: str) -> None:
    """Release a slot previously reserved with acquire_connection."""
    global _active_total
    count = _active_per_ip.get(ip, 0)
    if count <= 1:
        _active_per_ip.pop(ip, None)
    else:
        _active_per_ip[ip] = count - 1
    if _active_total > 0:
        _active_total -= 1
```

Then, immediately after `get_terminal_size` (currently ends line 197):

```python
def get_peer_ip(writer) -> str:
    """Best-effort client IP from the telnet transport, or '?' if unknown."""
    peername = writer.get_extra_info("peername")
    if peername:
        return peername[0]
    return "?"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_server_wiring.py -k "acquire or release or peer_ip" -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
venv/bin/python -m pyflakes telnet_server.py && venv/bin/python -m flake8 --config=setup.cfg telnet_server.py
git add telnet_server.py tests/test_server_wiring.py
git commit -m "feat: add concurrent-connection accounting helpers"
```

---

### Task 2: Enforce caps in the shell coroutine

Reject over-cap connections with a one-line ASCII notice before the render loop; always release the slot. Also teach the test fakes to report a peername.

**Files:**
- Modify: `telnet_server.py` (`shell`, currently lines 216-250)
- Test: `tests/test_server_wiring.py` (extend `_FakeWriter`; add a rejection test)

**Interfaces:**
- Consumes: `get_peer_ip`, `acquire_connection`, `release_connection` (Task 1).
- Produces: `shell` now acquires a slot first; on rejection it writes `"Too many connections, please try again shortly.\r\n"`, closes, and returns without rendering.

- [ ] **Step 1: Write the failing test**

First, extend the existing `_FakeWriter` in `tests/test_server_wiring.py` so it can report a peername (the real writer exposes this; `shell` now reads it). Replace the `_FakeWriter` class body's end by adding a method:

```python
class _FakeWriter:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True

    def get_extra_info(self, key, default=None):
        return {"peername": ("203.0.113.7", 51000), "rows": 4, "cols": 4}.get(key, default)
```

(Leave `_LoopWriter` as-is; it inherits the new `get_extra_info` and overrides nothing it needs.)

Then add the rejection test:

```python
def test_shell_rejects_when_over_capacity():
    async def _noop(writer):
        return

    _reset_conns()
    writer = _FakeWriter()
    # Pre-fill the global cap so this connection is refused.
    with mock.patch.object(telnet_server, "MAX_CONNECTIONS", 0), mock.patch.object(
        telnet_server, "negotiate_telnet_options", _noop
    ):
        asyncio.run(telnet_server.shell(reader=None, writer=writer))

    output = "".join(writer.writes)
    assert "Too many connections" in output
    assert telnet_server.HIDE_CURSOR not in output  # never started the animation
    assert writer.closed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_server_wiring.py::test_shell_rejects_when_over_capacity -v`
Expected: FAIL — current `shell` ignores caps, so it writes `HIDE_CURSOR` (and, with `reader=None`, would error in the loop) instead of the rejection notice.

- [ ] **Step 3: Write the minimal implementation**

Replace the body of `shell` (lines 216-250) with:

```python
async def shell(reader, writer):
    """
    A coroutine that's invoked after a new connection has been established.
    """
    ip = get_peer_ip(writer)
    if not acquire_connection(ip):
        # ASCII only: an over-capacity client may not have negotiated UTF-8.
        writer.write("Too many connections, please try again shortly.\r\n")
        writer.close()
        return

    try:
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

                # The input read doubles as frame pacing: wait only the remainder
                # of the frame period after the time spent computing this frame, so
                # we hit the target FPS instead of (compute + 1/FPS). A small floor
                # keeps input polled -- so 'q' stays responsive -- on hardware too
                # slow to hit the target rate (where the remainder goes negative).
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
    finally:
        release_connection(ip)
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (all prior tests + the new one). In particular `test_shell_hides_cursor_then_restores_it` still passes (its `_FakeWriter` now has `get_extra_info`, `acquire_connection` succeeds, loop is skipped because `DURATION=0`, slot is released).

- [ ] **Step 5: Commit**

```bash
venv/bin/python -m pyflakes telnet_server.py && venv/bin/python -m flake8 --config=setup.cfg telnet_server.py
git add telnet_server.py tests/test_server_wiring.py
git commit -m "feat: reject connections over per-IP/global caps"
```

---

### Task 3: CLI flags + globals for the caps

Expose `--max-per-ip` / `--max-connections`, wired into `main` like the other globals.

**Files:**
- Modify: `telnet_server.py` (`parse_args` lines 182-188; `main` after the `COOLING` block, around line 272)
- Test: `tests/test_server_wiring.py`

**Interfaces:**
- Consumes: `MAX_PER_IP`, `MAX_CONNECTIONS` (Task 1).
- Produces: `parse_args()` result gains `.max_per_ip` and `.max_connections`; `main` sets the globals from them.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_args_has_connection_cap_defaults():
    with mock.patch.object(sys, "argv", ["telnet_server.py"]):
        args = parse_args()
    assert args.max_per_ip == 2
    assert args.max_connections == 50


def test_parse_args_accepts_connection_cap_overrides():
    with mock.patch.object(
        sys, "argv", ["telnet_server.py", "--max-per-ip", "5", "--max-connections", "100"]
    ):
        args = parse_args()
    assert args.max_per_ip == 5
    assert args.max_connections == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_server_wiring.py -k connection_cap -v`
Expected: FAIL with `AttributeError: 'Namespace' object has no attribute 'max_per_ip'`.

- [ ] **Step 3: Write the minimal implementation**

In `parse_args`, add before `return parser.parse_args()`:

```python
    parser.add_argument("--max-per-ip", default=MAX_PER_IP, type=int)
    parser.add_argument("--max-connections", default=MAX_CONNECTIONS, type=int)
```

In `main`, after the `COOLING` block (after line 272):

```python
    global MAX_PER_IP
    MAX_PER_IP = args.max_per_ip
    global MAX_CONNECTIONS
    MAX_CONNECTIONS = args.max_connections
    logging.info(f"Limits: {MAX_PER_IP}/IP, {MAX_CONNECTIONS} total")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
venv/bin/python -m pyflakes telnet_server.py && venv/bin/python -m flake8 --config=setup.cfg telnet_server.py
git add telnet_server.py tests/test_server_wiring.py
git commit -m "feat: add --max-per-ip and --max-connections flags"
```

---

### Task 4: Repoint the systemd unit at `/srv/fan-the-flames`

The committed unit hardcodes `/opt/...`; `deploy.sh` (Task 5) renders the path per host, using this committed value as the substitution source. Standardize the committed value on `/srv/fan-the-flames`.

**Files:**
- Modify: `fan-the-flames.service`

**Interfaces:**
- Consumes: nothing.
- Produces: a unit whose `WorkingDirectory`/`ExecStart` reference `/srv/fan-the-flames`, the literal string `deploy.sh` rewrites.

- [ ] **Step 1: Edit the unit paths**

In `fan-the-flames.service`, change the two `/opt/fan-the-flames` references:

```ini
WorkingDirectory=/srv/fan-the-flames
ExecStart=/srv/fan-the-flames/venv/bin/python /srv/fan-the-flames/telnet_server.py --host 0.0.0.0 --port 23
```

(Leave the top comment, sandboxing directives, `DynamicUser=yes`, and `AmbientCapabilities=CAP_NET_BIND_SERVICE` unchanged.)

- [ ] **Step 2: Verify licensing/structure tests still pass**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (no test asserts the unit path).

- [ ] **Step 3: Commit**

```bash
git add fan-the-flames.service
git commit -m "chore: install under /srv/fan-the-flames to match host convention"
```

---

### Task 5: Manual deploy script

A parameterized, idempotent `deploy.sh` that mirrors the `nex` manual deploy: rsync source → host, build/refresh venv, render+install the unit for the target path, restart, verify. It is an ops script — verified by running it (Task 7), not unit-tested.

**Files:**
- Create: `deploy.sh`

**Interfaces:**
- Consumes: `telnet_server.py`, `requirements.txt`, `fan-the-flames.service` (repo root).
- Produces: `./deploy.sh <ssh-host> [install-dir]` — deploys to that host. Defaults: `install-dir=/srv/fan-the-flames`.

- [ ] **Step 1: Create `deploy.sh`**

```bash
#!/usr/bin/env bash
#
# Manual deploy for Fan the Flames. No GitHub Actions.
#
# Usage:
#   ./deploy.sh <ssh-host> [install-dir]
#
# Examples:
#   ./deploy.sh lightsail /srv/fan-the-flames   # AWS Lightsail (public, port 23)
#   ./deploy.sh pi /opt/fan-the-flames          # Raspberry Pi
#
# Requires on this machine: ssh (host configured), rsync.
# Requires on the host: python3 with venv, passwordless sudo, systemd.
set -euo pipefail

HOST="${1:?usage: deploy.sh <ssh-host> [install-dir]}"
DIR="${2:-/srv/fan-the-flames}"
UNIT="fan-the-flames.service"

echo ">> Deploying to ${HOST}:${DIR}"

# 1. Ensure the install dir exists and is owned by the login user (so rsync
#    needs no sudo). DynamicUser only needs read access to world-readable files.
ssh "$HOST" "sudo mkdir -p '$DIR' && sudo chown \"\$(id -un):\$(id -gn)\" '$DIR'"

# 2. Sync runtime files.
rsync -az telnet_server.py requirements.txt "$HOST:$DIR/"

# 3. Render the unit for this install dir and install it.
sed "s#/srv/fan-the-flames#${DIR}#g" "$UNIT" > "/tmp/${UNIT}.rendered"
scp "/tmp/${UNIT}.rendered" "$HOST:/tmp/${UNIT}"
rm -f "/tmp/${UNIT}.rendered"
ssh "$HOST" "sudo install -m 644 /tmp/${UNIT} /etc/systemd/system/${UNIT} && rm /tmp/${UNIT}"

# 4. Build/refresh the venv.
ssh "$HOST" "cd '$DIR' && python3 -m venv venv && ./venv/bin/pip install --quiet --upgrade pip && ./venv/bin/pip install --quiet -r requirements.txt"

# 5. Enable + restart, then verify.
ssh "$HOST" "sudo systemctl daemon-reload && sudo systemctl enable --now ${UNIT} && sudo systemctl restart ${UNIT} && sleep 3 && systemctl is-active ${UNIT} && (ss -ltn | grep -E ':23 ' || echo 'WARNING: not listening on :23')"

echo ">> Done."
```

- [ ] **Step 2: Make it executable and syntax-check it**

Run:
```bash
chmod +x deploy.sh
bash -n deploy.sh && echo "syntax ok"
```
Expected: `syntax ok`.

- [ ] **Step 3: Commit**

```bash
git add deploy.sh
git commit -m "chore: add manual deploy.sh for ssh hosts"
```

---

### Task 6: Provision DNS + Lightsail firewall (AWS CLI, one-shot)

Manual infra commands run from this machine. No code; verified by reading AWS back.

**Files:** none.

**Interfaces:**
- Consumes: zone `Z07504492U14KTJQU578V`, instance `Debian-1`/`us-east-1`, static IP `34.196.64.138`.
- Produces: `telnet.jonathandeamer.com A → 34.196.64.138`; Lightsail TCP 23 open.

- [ ] **Step 1: Create the A record (UPSERT, mirrors `nex`)**

Run:
```bash
aws route53 change-resource-record-sets --hosted-zone-id Z07504492U14KTJQU578V \
  --change-batch '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"telnet.jonathandeamer.com","Type":"A","TTL":300,"ResourceRecords":[{"Value":"34.196.64.138"}]}}]}'
```
Expected: JSON with `"Status": "PENDING"`.

- [ ] **Step 2: Open TCP 23 in the Lightsail firewall**

Run:
```bash
aws lightsail open-instance-public-ports --instance-name Debian-1 --region us-east-1 \
  --port-info fromPort=23,toPort=23,protocol=TCP
```
Expected: JSON `operations[].status == "Succeeded"`.

- [ ] **Step 3: Verify both**

Run:
```bash
aws lightsail get-instance-port-states --instance-name Debian-1 --region us-east-1 \
  --query "portStates[?fromPort==\`23\`]" --output json
dig +short telnet.jonathandeamer.com
```
Expected: a port-state entry for 23 with `"state": "open"`; `dig` eventually prints `34.196.64.138` (allow up to TTL 300s for propagation).

---

### Task 7: Deploy to Lightsail + end-to-end verification

Run the script against the public box and confirm the animation streams to a real client.

**Files:** none (uses Task 5 `deploy.sh`).

**Interfaces:**
- Consumes: `deploy.sh`, the hardened `telnet_server.py`, the `/srv` unit, the open firewall + DNS.
- Produces: a running, enabled `fan-the-flames` service on Lightsail listening on `:23`.

- [ ] **Step 1: Deploy**

Run: `./deploy.sh lightsail /srv/fan-the-flames`
Expected: ends with `active` and no `WARNING: not listening on :23`.

- [ ] **Step 2: Confirm the service and that nex is undisturbed**

Run:
```bash
ssh lightsail 'systemctl is-active fan-the-flames buffetcar; ss -ltn | grep -E ":23 |:80 |:1900 "'
```
Expected: `active` for both services; listeners on 23, 80, 1900.

- [ ] **Step 3: End-to-end frame check from this machine (negotiating client)**

Run:
```bash
venv/bin/python - <<'PY'
import asyncio, telnetlib3
async def main():
    reader, writer = await telnetlib3.open_connection("telnet.jonathandeamer.com", 23, encoding="utf-8")
    data = await asyncio.wait_for(reader.read(4096), timeout=5)
    writer.close()
    print("frame-home seen:", "\x1b[0;0H" in data, "| half-blocks:", "▀" in data)
asyncio.run(main())
PY
```
Expected: `frame-home seen: True | half-blocks: True`. (If DNS hasn't propagated yet, substitute `34.196.64.138` for the hostname.)

- [ ] **Step 4: Verify the per-IP cap rejects a flood**

Run (opens 3 simultaneous connections from one IP; with `MAX_PER_IP=2` the 3rd must be refused):
```bash
venv/bin/python - <<'PY'
import asyncio, telnetlib3
HOST = "telnet.jonathandeamer.com"
async def grab():
    reader, writer = await telnetlib3.open_connection(HOST, 23, encoding="utf-8")
    data = await asyncio.wait_for(reader.read(256), timeout=5)
    return data
async def main():
    results = await asyncio.gather(*[grab() for _ in range(3)], return_exceptions=True)
    refused = sum("Too many connections" in r for r in results if isinstance(r, str))
    print("refused:", refused)
    for w in []:
        pass
asyncio.run(main())
PY
```
Expected: `refused: 1` (two animations, one rejection notice).

- [ ] **Step 5: Final commit (runbook note)**

Append a short "Deploying" section to `README.md` documenting `./deploy.sh lightsail` and the public address, then:
```bash
git add README.md
git commit -m "docs: document Lightsail deploy and telnet.jonathandeamer.com"
```

---

## Self-Review

**Spec coverage** (against the agreed plan):
- Hardening before exposure → Tasks 1-3 (caps + CLI), enforced before the firewall/DNS open in Tasks 6-7. ✓
- `/srv/fan-the-flames` install path → Task 4 + `deploy.sh` rendering. ✓
- Committed `deploy.sh` (manual, no Actions) → Task 5. ✓
- Subdomain via AWS CLI → Task 6 Step 1. ✓
- Firewall open 23 → Task 6 Step 2. ✓
- Coexist with nex → Task 7 Step 2 verifies both. ✓
- Connection-limit defaults 2/50 → Global Constraints + Tasks 1/3. ✓

**Placeholder scan:** no TBD/"handle edge cases"/"similar to Task N"; every code step shows code; every command shows expected output. ✓

**Type consistency:** `acquire_connection(ip: str) -> bool`, `release_connection(ip: str) -> None`, `get_peer_ip(writer) -> str`, globals `MAX_PER_IP`/`MAX_CONNECTIONS`, state `_active_per_ip`/`_active_total`, args `.max_per_ip`/`.max_connections` — used identically across Tasks 1-3. ✓

**Notes / risks:**
- Telnet on 23 is unauthenticated by design; caps blunt floods but do not authenticate. Acceptable for a public splash screen.
- `deploy.sh` and the AWS/verification steps are ops actions verified by running them, not unit tests (per TDD's config/script exception).
- DNS propagation up to 300s (TTL); Task 7 Step 3 offers the raw-IP fallback.
