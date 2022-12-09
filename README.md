# cmpdc
A simple mpd client, inspired by Cantata and suckless software.

Features include:
- simple playlist management
- showing song metadata including lyrics (using mutagen)
- multiple ways to obtain album covers

Features do not include:
- using various internet services
- Notifications
- MPRIS

## Installation
Edit ``cmpdc.py`` to connect to your mpd server, then run:
```
cp cmpdc.py ~/.local/bin
cp cmpdc.desktop ~/.local/share/applications
```

## Customization
cmpc is designed to be configured/customized by editing the source code.

## Default keyboard shortcuts
- Ctrl+1 - Ctrl+5: switch to tab 1-5
- Ctrl+C: show current song
- F5: update library
- Ctrl+Space: toggle play/pause
- Ctrl+Left: previous
- Ctrl+Right: next
- Ctrl+P: (search) append selection to queue
- Ctrl+R: (search) replace queue with selection
