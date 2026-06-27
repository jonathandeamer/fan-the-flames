# demo.tape - VHS script for the README hero gif (demo.gif).
#
# Render from the repo root:  vhs demo.tape
# Needs vhs, ttyd, and ffmpeg on PATH:  brew install vhs ffmpeg ttyd
# Also needs the project venv and a `telnet` client.
Require telnet

Output demo.gif

# --- Look ----------------------------------------------------------------
# 16:9 at the README's display width. The fire is chunky half-block cells,
# so a 1x render stays crisp while keeping the GIF light.
Set Width 600
Set Height 338
Set FontSize 13
# Installed family name for JetBrainsMono Nerd Font
# (brew install --cask font-jetbrains-mono-nerd-font).
Set FontFamily "JetBrainsMono NF"
Set Padding 12

# Match the sim's 10 fps (capturing faster just bloats the file with
# near-duplicate frames) and use a calm cursor (no blink shimmer).
Set Framerate 10
Set CursorBlink false

# macOS-style window card, framed on a sky-blue background.
Set WindowBar Colorful
Set BorderRadius 8
Set Margin 20
Set MarginFill "#87CEEB"

# Pure-black terminal background so the card blends seamlessly into the
# fire's dark base (heat 0 renders black in the fire palette).
Set Theme { "name": "ftf", "background": "#000000", "foreground": "#f0edf5", "black": "#000000", "brightBlack": "#5c5c5c", "red": "#ff5f5f", "brightRed": "#ff5f5f", "green": "#5fd75f", "brightGreen": "#5fd75f", "yellow": "#ffd75f", "brightYellow": "#ffd75f", "blue": "#5fafff", "brightBlue": "#5fafff", "magenta": "#d75fff", "brightMagenta": "#d75fff", "cyan": "#5fd7d7", "brightCyan": "#5fd7d7", "white": "#f0edf5", "brightWhite": "#ffffff", "selection": "#333333", "cursor": "#ff8c00" }

Set TypingSpeed 80ms

# --- Start the server and connect, all off-camera ------------------------
# The fire rises one row per frame, so it takes ~5s to climb from cold to
# full height. We do that warm-up under Hide and only record the steady,
# full-height flames -- this also gives a seamless loop with no empty frames.
Hide
Type "export PS1='$ '"
Enter
Type "clear"
Enter
Type "venv/bin/python telnet_server.py --port 7777 --duration 20 --cooling 10 >/dev/null 2>&1 &"
Enter
Sleep 1s
Type "telnet 127.0.0.1 7777"
Enter
# Let the fire climb to full height before we start recording.
Sleep 6s
Show

# --- Record the steady, full-height fire ---------------------------------
Sleep 4s
