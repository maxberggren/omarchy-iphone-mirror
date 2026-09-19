"""Character -> key presses for the *phone's* hardware-keyboard layout.

The viewer receives finished characters from the desktop ('å', '@', '-'),
but the virtual USB keyboard can only send key positions (HID usages). iOS
turns a position into a character with the hardware-keyboard layout it picked
from the phone's language, so the table must match the phone, not the desk.

A character maps to a sequence of chords. One chord is (usage, modifiers).
Most characters are one chord; dead-key characters (e.g. 'è', '~') are two.

The Swedish table was measured on an iPhone (iOS 27, Swedish): every key
position was pressed plain and with Shift, Option and Shift+Option, then the
resulting text was read back from the phone pasteboard.
"""
import json
import os
from pathlib import Path
import subprocess

from pymobiledevice3.remote.core_device.vnc_server import ASCII_TO_HID

SHIFT, ALT = 225, 226
SPACE = 44


def _us():
    return {char: [(usage, frozenset({SHIFT}) if shift else frozenset())]
            for char, (usage, shift) in ASCII_TO_HID.items()}


def _rows(table, mods, usages, chars):
    for usage, char in zip(usages, chars):
        if char != ' ':
            table.setdefault(char, [(usage, frozenset(mods))])


def _se():
    table = {}
    letters = range(0x04, 0x1E)
    _rows(table, (), letters, 'abcdefghijklmnopqrstuvwxyz')
    _rows(table, (SHIFT,), letters, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    digits = range(0x1E, 0x28)
    _rows(table, (), digits, '1234567890')
    _rows(table, (SHIFT,), digits, '!"#€%&/()=')
    _rows(table, (ALT,), digits, '©@£$∞§|[]≈')
    _rows(table, (SHIFT, ALT), digits, '¡ ¥¢‰¶\\{}≠')
    # 0x2D + | 0x2F å | 0x31 ' | 0x33 ö | 0x34 ä | 0x35 < | 0x36 , | 0x37 . | 0x38 - | 0x64 §
    keys = (0x2D, 0x2F, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x64)
    _rows(table, (), keys, "+å'öä<,.-§")
    _rows(table, (SHIFT,), keys, '?Å*ÖÄ>;:_°')
    _rows(table, (ALT,), keys, '± ™øæ≤‚…– ')
    _rows(table, (SHIFT, ALT), keys, '¿  ØÆ≥„·—•')
    _rows(table, (ALT,), letters, ' ›ç∂éƒ   √ªﬁ  œπ•®ß†ü‹Ω≈µ÷')
    _rows(table, (SHIFT, ALT), letters, '◊»Ç∆É∫     ﬂ  Œ∏  ∑‡Ü«    ⁄')
    # Typographic quotes typed on the desk land on the plain quote keys.
    for fancy, plain in (('’', "'"), ('‘', "'"), ('”', '"'), ('“', '"')):
        table.setdefault(fancy, table[plain])
    # Dead keys: 0x2E is ´ (Shift `), 0x30 is ¨ (Shift ^, Option ~).
    dead = {'´': (0x2E, frozenset()), '`': (0x2E, frozenset({SHIFT})),
            '¨': (0x30, frozenset()), '^': (0x30, frozenset({SHIFT})),
            '~': (0x30, frozenset({ALT}))}
    for accent, chord in dead.items():
        table.setdefault(accent, [chord, (SPACE, frozenset())])
    composed = {'´': ('aeiouy', 'áéíóúý'), '`': ('aeiou', 'àèìòù'),
                '¨': ('aeiouy', 'äëïöüÿ'), '^': ('aeiou', 'âêîôû'),
                '~': ('ano', 'ãñõ')}
    for accent, (bases, results) in composed.items():
        for base, result in zip(bases, results):
            table.setdefault(result, [dead[accent], table[base][0]])
            if result.upper() != result and len(result.upper()) == 1:
                table.setdefault(result.upper(), [dead[accent], table[base.upper()][0]])
    table[' '] = [(SPACE, frozenset())]
    return table


LAYOUTS = {'us': _us, 'se': _se}


def host_layout():
    """The desktop's first keyboard layout, e.g. 'se'. Empty when unknown."""
    try:
        result = subprocess.run(['hyprctl', 'devices', '-j'], capture_output=True, text=True, timeout=2)
        keyboards = json.loads(result.stdout).get('keyboards', [])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ''
    keyboards.sort(key=lambda k: not k.get('main'))
    for keyboard in keyboards:
        layout = str(keyboard.get('layout', '')).split(',')[0].strip().lower()
        if layout:
            return layout
    return ''


def configured_layout():
    """'keyboard_layout' in ~/.config/iphone-mirror/ui.json: 'us', 'se' or 'auto'.

    'auto' (the default) assumes the phone uses the same layout as the desk,
    which holds when both follow the same language.
    """
    path = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'iphone-mirror/ui.json'
    try:
        name = json.loads(path.read_text()).get('keyboard_layout', 'auto')
    except (OSError, ValueError, AttributeError):
        name = 'auto'
    if name == 'auto' or name not in LAYOUTS:
        name = host_layout()
    return name if name in LAYOUTS else 'us'


def load(name=None):
    return LAYOUTS[name or configured_layout()]()
