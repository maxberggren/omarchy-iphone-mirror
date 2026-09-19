"""Measure the phone's hardware-keyboard layout.

Presses every key position plain and with Shift, Option and Shift+Option in
the text field that is focused on the phone, copies the field, and reads the
phone pasteboard back. Writes layout.json; keyboard_layouts.py's Swedish table
was built from such a measurement.

Before running: start iPhone Mirror (input needs its active stream) and focus
an empty, harmless text field on the phone, e.g. Spotlight search. The probe
types into that field and overwrites the phone clipboard. It takes about four
minutes. Smart punctuation may report ' and " as curly quotes.

Run with the app's Python:
  ~/.local/share/iphone-mirror/venv/bin/python tools/probe_layout.py [plain shift alt shift+alt]
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from connection import select_connection, get_tunnel
from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService
from pymobiledevice3.remote.core_device.pasteboard_service import PasteboardService

USAGES = list(range(0x04, 0x28)) + [0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x64]
STATES = {'plain': [], 'shift': [225], 'alt': [226], 'shift+alt': [225, 226]}
only = sys.argv[1:]  # optional subset of state names

async def main():
    mode, serial = await select_connection('usb')
    async with get_tunnel(mode, serial) as rsd:
        hid = UniversalHIDServiceService(rsd); await hid.connect()
        kb = await hid.create_keyboard_service(service_id=0x100002002)
        async def chord(keys, hold=.04):
            mods = [k for k in keys if k >= 224]
            if mods:
                await hid.send_keyboard(kb, mods); await asyncio.sleep(.02)
            await hid.send_keyboard(kb, keys); await asyncio.sleep(hold)
            await hid.send_keyboard(kb, mods); await asyncio.sleep(.01)
            await hid.send_keyboard(kb, []); await asyncio.sleep(.04)
        out = {}
        try:
            for state, mods in STATES.items():
                if only and state not in only: continue
                out[state] = {}
                for usage in USAGES:
                    await chord([227, 0x04])              # Cmd+A: select all
                    await chord(mods + [usage])           # the key under test replaces it
                    await chord([0x2C])                   # space: resolves a dead key
                    await chord([227, 0x04]); await chord([227, 0x06])  # select all, copy
                    await asyncio.sleep(.12)
                    pb = PasteboardService(rsd); await pb.connect()
                    try:
                        out[state][f'{usage:#04x}'] = await asyncio.wait_for(pb.get_text(), 6)
                    finally:
                        try: await asyncio.wait_for(pb.close(), 1)
                        except Exception: pass
                print(state, json.dumps(out[state], ensure_ascii=False), flush=True)
        finally:
            await hid.send_keyboard(kb, [])
            await hid.close()
        json.dump(out, open('layout.json', 'w'), ensure_ascii=False, indent=1)
asyncio.run(main())
