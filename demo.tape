# VHS tape for the Fan the Flames demo GIF.
# Render with:  vhs demo.tape   (produces demo.gif)
# Requires: vhs, ffmpeg, ttyd, and the project venv.

Output demo.gif

Set Shell zsh
Set FontSize 14
Set Width 760
Set Height 300
Set Padding 8
Set Framerate 10

# Start the server quietly in the background, then connect.
Hide
Type "venv/bin/python telnet_server.py --port 7777 --duration 9 --cooling 10 >/dev/null 2>&1 &"
Enter
Sleep 1.5s
Show

Type "telnet 127.0.0.1 7777"
Enter

# Watch the fire for the full run; the server closes the connection itself.
Sleep 9s
