<h1 align="center">Fan the Flames</h1>

<p align="center">An animated telnet fire splash screen.</p>
<p align="center">Connect with <strong>$ telnet &lt;host&gt; 7777</strong></p>

<p align="center"><img src="demo.gif" alt="Animated ASCII fire rendered in truecolor over telnet" width="640"></p>

## About

An ASCII fire animation served over telnet, rendered in 24-bit
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

| Option | Default | Description |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Address to bind. Use `0.0.0.0` to accept connections from other machines. |
| `--port` | `7777` | TCP port to listen on. |
| `--fps` | `10` | Animation frames per second. Higher is smoother but sends more data each second — keep it modest on lower-spec machines. |
| `--duration` | `20` | Seconds to run the animation before the server closes the connection. |
| `--cooling` | `10` | How fast heat fades as it rises. Lower values let flames climb higher; higher values make them shorter and stubbier. |

Connected clients can press `q` to disconnect early.
