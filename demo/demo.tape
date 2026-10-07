# Records the README images. Run from the repo root: vhs demo/demo.tape
Output demo/picker.gif

Set Shell bash
Set FontSize 18
Set Width 1280
Set Height 720
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms
Set WindowBar Colorful

Hide
Type "export PATH=$PWD/demo/bin:$PATH HERDR_BIN_PATH=$PWD/demo/bin/herdr PS1='$ ' && clear"
Enter
Type "python3 copy_last.py picker"
Enter
Sleep 1.2s
Show

Sleep 1.5s
Screenshot demo/picker.png
Sleep 1s
Down
Sleep 1.4s
Down
Sleep 1.6s
Down
Sleep 1.4s
Type "3"
Sleep 1.2s
Enter
Sleep 0.3s
Hide
Type "clear"
Enter
Show
Sleep 0.4s
Type "pbpaste"
Sleep 0.4s
Enter
Sleep 3s
