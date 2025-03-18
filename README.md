# cmpdc
A simple mpd client using Qt 6, inspired by Cantata and suckless software.

Features include:
- simple playlist management
- showing song metadata including lyrics (using mutagen)
- multiple ways to obtain album covers
- desktop notifications

Features do not include:
- using various internet services
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
- Ctrl+1 - Ctrl+6: switch to tab 1-6
- Ctrl+C: show current song in the queue
- Ctrl+D: toggle random playback
- F5: update library
- Ctrl+Space: toggle play/pause
- Ctrl+Left: previous
- Ctrl+Right: next
- Ctrl+P: (search) append selection to queue
- Ctrl+R: (search) replace queue with selection
- Ctrl+S: save queue as playlist
- Crtl+Shift+K: kill and restart mpd
- Ctrl++, Ctrl+-, Ctrl+0: change priority of the selected songs in the queue
