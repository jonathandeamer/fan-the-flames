# Lightsail Deployment + Connection Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publicly serve "Fan the Flames" at `telnet.jonathandeamer.com:23` from the existing AWS Lightsail box, after adding application-level connection-flood protection, with a committed, repeatable manual deploy script (no GitHub Actions).

**Architecture:** Two halves. (1) **Code** — retain the existing NAWS dimension sanitization and bounded frame-input pacing, and add per-source-IP/global concurrent-connection caps in a `TelnetServer` protocol subclass. The subclass admits or rejects each TCP connection in `connection_made`, before Telnet negotiation and before `shell`, with caps configured by new CLI flags + module globals. (2) **Ops** — a parameterized `deploy.sh` that rsyncs the source to a host, builds a venv, renders the systemd unit for the target path, and restarts the service; plus one-shot AWS CLI commands to create the Route 53 A record and open the Lightsail firewall. Deploy mirrors the manual rsync-+-`systemctl restart` pattern used by the `nex` project on the same box.

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
- **Existing rendering hardening:** preserve `MAX_ROWS = 1000`, `MAX_COLS = 1000`, EOF termination, `MAX_INPUT_READS_PER_FRAME`, residual frame sleeping, and the 1 ms overrun input poll exactly as implemented by commits `7f1f4f6` and `b3b4f33`. This plan must not replace or weaken the current `shell` loop.

---

### Task 1: Connection-limit registry

Pure, synchronous accounting helpers plus a peer-IP extractor. No server wiring yet.

**Files:**
- Modify: `telnet_server.py` (add globals + functions after the `FPS`/`DURATION`/`COOLING` block, around line 176; add `get_peer_ip` after `get_terminal_size`, around line 230)
- Test: `tests/test_server_wiring.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MAX_PER_IP: int`, `MAX_CONNECTIONS: int` (module globals)
  - `_active_per_ip: dict[str, int]`, `_active_total: int` (module state)
  - `acquire_connection(ip: str) -> bool` — reserves a slot; `False` if a cap is hit.
  - `release_connection(ip: str) -> None` — frees a slot reserved by `acquire_connection`.
  - `get_peer_ip(connection) -> str` — returns the client IP from a writer or transport exposing `get_extra_info("peername")`, or `"?"`.

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

Then, immediately after `get_terminal_size` (currently ends around line 230):

```python
def get_peer_ip(connection) -> str:
    """Best-effort client IP from a writer or transport, or '?' if unknown."""
    peername = connection.get_extra_info("peername")
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

### Task 2: Enforce caps before Telnet negotiation

Reject over-cap TCP connections in the protocol's `connection_made` callback, before `telnetlib3` starts its negotiation or waits up to `connect_maxwait`. Do not modify `shell`; its existing terminal-size, EOF, and pacing protections are part of the deployment baseline.

**Files:**
- Modify: `telnet_server.py` (import `TelnetServer`; add `LimitedTelnetServer` after `get_peer_ip`; pass it to `create_server` in `main`)
- Test: `tests/test_server_wiring.py`

**Interfaces:**
- Consumes: `get_peer_ip`, `acquire_connection`, `release_connection` (Task 1).
- Produces:
  - `REJECTION_NOTICE: bytes` — plain ASCII suitable before encoding negotiation.
  - `LimitedTelnetServer(TelnetServer)` — reserves a slot before calling `super().connection_made`, rejects immediately when full, and releases exactly once from `connection_lost`.
  - `main` passes `protocol_factory=LimitedTelnetServer` to `create_server`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server_wiring.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_server_wiring.py -k "protocol_rejects or protocol_releases" -v`
Expected: FAIL with `AttributeError: module 'telnet_server' has no attribute 'LimitedTelnetServer'`.

- [ ] **Step 3: Write the minimal implementation**

Change the telnetlib3 import in `telnet_server.py`:

```python
from telnetlib3 import TelnetServer, create_server, telopt
```

Immediately after `get_peer_ip`, add:

```python
REJECTION_NOTICE = b"Too many connections, please try again shortly.\r\n"


class LimitedTelnetServer(TelnetServer):
    """Admit connections before Telnet negotiation and release slots on close."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connection_ip = None

    def _release_connection_slot(self):
        if self._connection_ip is not None:
            release_connection(self._connection_ip)
            self._connection_ip = None

    def connection_made(self, transport):
        ip = get_peer_ip(transport)
        if not acquire_connection(ip):
            # No encoding has been negotiated, so write ASCII bytes directly.
            self._closing = True
            self._waiter_connected.cancel()
            try:
                transport.write(REJECTION_NOTICE)
            finally:
                transport.close()
            return

        self._connection_ip = ip
        try:
            super().connection_made(transport)
        except BaseException:
            self._release_connection_slot()
            raise

    def connection_lost(self, exc):
        if self._connection_ip is None:
            return
        try:
            super().connection_lost(exc)
        finally:
            self._release_connection_slot()
```

Finally, preserve the existing `shell_wrapper` and pass the protocol subclass in `main`:

```python
        server = await create_server(
            host=args.host,
            port=args.port,
            protocol_factory=LimitedTelnetServer,
            shell=shell_wrapper,
        )
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `venv/bin/python -m pytest -q`
Expected: PASS. In particular, the existing terminal-size, EOF, buffered-input pacing, bounded-read, and cursor-cleanup tests must remain unchanged and pass.

- [ ] **Step 5: Commit**

```bash
venv/bin/python -m pyflakes telnet_server.py && venv/bin/python -m flake8 --config=setup.cfg telnet_server.py
git add telnet_server.py tests/test_server_wiring.py
git commit -m "feat: reject connections before telnet negotiation"
```

---

### Task 3: CLI flags + globals for the caps

Expose `--max-per-ip` / `--max-connections`, wired into `main` like the other globals.

**Files:**
- Modify: `telnet_server.py` (`parse_args`, currently lines 179-199; `main` after the `COOLING` block, currently around line 331)
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


def test_parse_args_rejects_invalid_connection_caps():
    import pytest

    invalid_argv = [
        ["telnet_server.py", "--max-per-ip", "0"],
        ["telnet_server.py", "--max-connections", "0"],
        ["telnet_server.py", "--max-per-ip", "3", "--max-connections", "2"],
    ]
    for argv in invalid_argv:
        with mock.patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            parse_args()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_server_wiring.py -k connection_cap -v`
Expected: FAIL with `AttributeError: 'Namespace' object has no attribute 'max_per_ip'`.

- [ ] **Step 3: Write the minimal implementation**

In `parse_args`, add these arguments before the existing `args = parser.parse_args()` call:

```python
    parser.add_argument("--max-per-ip", default=MAX_PER_IP, type=int)
    parser.add_argument("--max-connections", default=MAX_CONNECTIONS, type=int)
```

After the existing cooling validation, add:

```python
    if args.max_per_ip < 1:
        parser.error("max-per-ip must be at least 1")
    if args.max_connections < 1:
        parser.error("max-connections must be at least 1")
    if args.max_per_ip > args.max_connections:
        parser.error("max-per-ip cannot exceed max-connections")
```

In `main`, after the `COOLING` block (currently around line 331):

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
ssh "$HOST" "sudo systemctl daemon-reload && sudo systemctl enable --now ${UNIT} && sudo systemctl restart ${UNIT} && sleep 3 && systemctl is-active ${UNIT} && if ss -ltn | grep -Eq ':23 '; then echo 'listening on :23'; else echo 'ERROR: not listening on :23' >&2; exit 1; fi"

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
  --port-info fromPort=23,toPort=23,protocol=tcp
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
Expected: prints `active`, then `listening on :23`, and ends with `>> Done.`. A missing listener exits nonzero before the final message.

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

async def read_until_markers(reader, markers, timeout):
    async def collect():
        data = ""
        while not all(marker in data for marker in markers):
            chunk = await reader.read(4096)
            if not chunk:
                break
            data += chunk
        return data

    data = await asyncio.wait_for(collect(), timeout=timeout)
    missing = [repr(marker) for marker in markers if marker not in data]
    if missing:
        raise RuntimeError(f"connection closed before markers arrived: {missing}")
    return data

async def main():
    reader, writer = await telnetlib3.open_connection("telnet.jonathandeamer.com", 23, encoding="utf-8")
    try:
        data = await read_until_markers(reader, ("\x1b[0;0H", "▀"), timeout=5)
    finally:
        writer.close()
    print("frame-home seen:", "\x1b[0;0H" in data, "| half-blocks:", "▀" in data)

asyncio.run(main())
PY
```
Expected: `frame-home seen: True | half-blocks: True`. (If DNS hasn't propagated yet, substitute `34.196.64.138` for the hostname.)

- [ ] **Step 4: Verify the per-IP cap rejects a flood**

Run (opens three raw TCP connections from one IP and deliberately does not answer Telnet negotiation; with `MAX_PER_IP=2`, the third must be refused immediately while the first two remain pending):
```bash
venv/bin/python - <<'PY'
import asyncio

HOST = "telnet.jonathandeamer.com"

REJECTION = b"Too many connections, please try again shortly.\r\n"

async def collect_until_rejected(reader, timeout=2):
    data = b""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while REJECTION not in data:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            chunk = await asyncio.wait_for(reader.read(256), timeout=remaining)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        data += chunk
    return data

async def main():
    connections = await asyncio.gather(
        *(asyncio.open_connection(HOST, 23) for _ in range(3))
    )
    try:
        payloads = await asyncio.gather(
            *(collect_until_rejected(reader) for reader, _writer in connections)
        )
        refused = sum(REJECTION in payload for payload in payloads)
        if refused != 1:
            raise RuntimeError(f"expected exactly one refusal, got {refused}")
        print("refused:", refused)
    finally:
        for _reader, writer in connections:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for _reader, writer in connections))

asyncio.run(main())
PY
```
Expected: `refused: 1`. This also verifies that pending pre-negotiation connections consume admission slots.

- [ ] **Step 5: Final commit (runbook note)**

Append a short "Deploying" section to `README.md` documenting `./deploy.sh lightsail` and the public address, then:
```bash
git add README.md
git commit -m "docs: document Lightsail deploy and telnet.jonathandeamer.com"
```

---

## Self-Review

**Spec coverage** (against the agreed plan):
- Rendering hardening before exposure → existing NAWS sanitization, EOF handling, bounded reads, and residual frame pacing are immutable baseline constraints and remain covered by the existing server-wiring tests. ✓
- Connection hardening before exposure → Tasks 1-3 (registry + pre-negotiation protocol admission + CLI), completed before the firewall/DNS open in Tasks 6-7. ✓
- `/srv/fan-the-flames` install path → Task 4 + `deploy.sh` rendering. ✓
- Committed `deploy.sh` (manual, no Actions) → Task 5. ✓
- Subdomain via AWS CLI → Task 6 Step 1. ✓
- Firewall open 23 → Task 6 Step 2. ✓
- Coexist with nex → Task 7 Step 2 verifies both. ✓
- Connection-limit defaults 2/50 → Global Constraints + Tasks 1/3. ✓

**Placeholder scan:** complete; every code step shows code and every command shows expected output. ✓

**Type consistency:** `acquire_connection(ip: str) -> bool`, `release_connection(ip: str) -> None`, `get_peer_ip(connection) -> str`, `LimitedTelnetServer`, globals `MAX_PER_IP`/`MAX_CONNECTIONS`, state `_active_per_ip`/`_active_total`, and args `.max_per_ip`/`.max_connections` are used identically across Tasks 1-3. ✓

**Notes / risks:**
- Telnet on 23 is unauthenticated by design; pre-negotiation caps bound admitted sockets but do not authenticate or replace host-level volumetric DDoS protection. Acceptable for a public splash screen.
- `MAX_ROWS = 1000` and `MAX_COLS = 1000` are intentionally preserved from commit `7f1f4f6`; changing those last-hour hardening commits is outside this plan. An admitted client at both maxima can still force a two-million-cell heat grid and substantial per-frame CPU/output, which is an explicitly accepted residual risk.
- `deploy.sh` and the AWS/verification steps are ops actions verified by running them, not unit tests (per TDD's config/script exception).
- DNS propagation up to 300s (TTL); Task 7 Step 3 offers the raw-IP fallback.
