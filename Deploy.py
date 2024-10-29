import shutil

import PyInstaller.__main__

shutil.rmtree('./dist/', ignore_errors=True)
shutil.rmtree('./build/', ignore_errors=True)

PyInstaller.__main__.run([
    'Main.py',
    '-y',
    '-F',
    '-w',
    '-i', 'res/BracketIcon.png',
    "--add-data", "res/Roboto-Regular.ttf:res",
    "--add-data", "res/end.wav:res",
])
