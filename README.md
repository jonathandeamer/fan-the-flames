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
