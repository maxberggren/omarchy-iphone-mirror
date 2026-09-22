"""Local desktop feedback; no device replies or identifiers are displayed."""
import subprocess


def message_for(error):
    name = type(error).__name__
    if name in ('PasswordRequiredError', 'DeviceLockedError') or (name == 'PyMobileDevice3Exception' and "'Error': 'DeviceLocked'" in str(error)):
        return 'Unlock your iPhone and keep its screen awake, then reopen iPhone Mirror.'
    if name in ('NotPairedError', 'InvalidHostIDError'):
        return 'USB trust is missing. Reconnect and approve Trust on the iPhone.'
    if name == 'ConnectionFailedToUsbmuxdError':
        return 'USB service unavailable. Unlock and reconnect the iPhone; check usbmuxd.'
    if name == 'IncompleteReadError':
        return 'The iPhone disconnected. Unlock it, reconnect and reopen iPhone Mirror.'
    if name == 'CoreDeviceError':
        return 'The iPhone rejected screen sharing. Check unlock, Developer Mode and the developer image.'
    if name == 'TimeoutError':
        return 'The iPhone is not answering. Unlock it, keep the screen on, then open iPhone Mirror again.'
    if name == 'RuntimeError':
        known = {
            'The paired iPhone was not reachable on the local network.': 'iPhone not found on Wi-Fi. Use the same network, check the phone VPN, or reconnect USB.',
            'No saved CoreDevice pairing matches this device. Pair over USB first.': 'Wi-Fi pairing is missing. Connect USB and run phone setup.',
            'No matching USB iPhone is connected.': 'No iPhone detected by USB. Unlock it and reconnect both cable ends.',
            'Several USB iPhones are connected. Select one with --serial.': 'Multiple iPhones connected. Disconnect the others and try again.',
            'No supported display features.': 'This iPhone/iOS/image combination reports no screen-sharing support.',
            'Developer image is not mounted.': 'The developer image is not mounted. Unlock the iPhone and run phone setup over USB, or enable auto_mount_image in ui.json.',
            'The mounted image does not expose the display service.': 'The developer image is mounted but offers no screen sharing. Check image compatibility in docs/phone-setup.md.',
            'Mounting the developer image failed.': 'Could not mount the developer image. Unlock the iPhone, check internet access, or run phone setup over USB.',
            'Mounting the developer image timed out.': 'Mounting the developer image took too long. Unlock the iPhone and open iPhone Mirror again.',
        }
        if str(error) in known:
            return known[str(error)]
    return 'Could not start screen sharing. Run iphone-mirror status for details; check the unlocked phone and connection.'


def notify(message, expire_ms):
    # A notification, not the OSD: the OSD is a one-line volume-style popup
    # that prints unknown icon names as text and cuts long messages off.
    try:
        subprocess.run(['notify-send', '--app-name=iPhone Mirror', '--icon=phone',
                        f'--expire-time={expire_ms}', 'iPhone Mirror', message],
                       timeout=4, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def show_error(message):
    notify(message, 10000)


def show_notice(message):
    notify(message, 6000)
