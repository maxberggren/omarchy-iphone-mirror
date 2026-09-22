"""Explicit USB or authenticated network transport. Never creates pairing records."""
import asyncio
import ipaddress
import json
import os
from pathlib import Path
from local_feedback import show_notice
from pymobiledevice3.exceptions import ConnectionFailedToUsbmuxdError
from pymobiledevice3.remote import userspace_tunnel as ut
from pymobiledevice3.remote.tunnel_service import (
    browse_remotepairing, iter_remote_paired_identifiers,
    RemotePairingTunnelService,
)

MODES = ('usb','wifi','auto')

async def select_connection(mode, serial=None):
    if mode not in MODES:
        raise ValueError('Unknown connection mode')
    if mode == 'wifi':
        return 'wifi', serial
    from pymobiledevice3.usbmux import list_devices
    try:
        devices = [d for d in await list_devices() if d.is_usb and (not serial or d.matches_udid(serial))]
    except (OSError,ConnectionFailedToUsbmuxdError):
        if mode != 'auto':
            raise
        devices = []
    if len(devices)>1:
        raise RuntimeError('Several USB iPhones are connected. Select one with --serial.')
    if devices:
        return 'usb', devices[0].serial
    if mode == 'auto':
        return 'wifi', serial
    raise RuntimeError('No matching USB iPhone is connected.')

async def network_route_allowed(address):
    """Reject USB tethering and tunnel interfaces; Wi-Fi mode must be LAN-only."""
    ipaddress.ip_address(address.split('%',1)[0])
    proc = await asyncio.create_subprocess_exec('ip','-j','route','get',address,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try:
        data, _ = await asyncio.wait_for(proc.communicate(),2)
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        return False
    routes = json.loads(data)
    if not routes:
        return False
    dev = routes[0].get('dev','')
    if not dev or dev=='lo' or dev.startswith(('tailscale','tun','utun')):
        return False
    driver = Path('/sys/class/net')/dev/'device/driver'
    return driver.resolve().name != 'ipheth'

async def connect_wifi(identifier, address, port, timeout=8):
    service = RemotePairingTunnelService(identifier,address,port)
    try:
        await asyncio.wait_for(service.connect(autopair=False),timeout)
        return service
    except BaseException:
        import contextlib
        with contextlib.suppress(Exception):
            await asyncio.wait_for(service.close(),1)
        raise

BROWSE_ROUNDS = 10          # ~40 s: a locked iPhone's Wi-Fi sleeps and wakes irregularly
BROWSE_ROUND_SECONDS = 4
WAKE_HINT_AFTER_ROUND = 2   # after ~8 s, suggest waking the phone's screen

def endpoint_cache_path():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'iphone-mirror/wifi-endpoint.json'

def load_last_endpoint():
    """The address the phone last answered on; unicast to it wakes a dozing phone
    more reliably than multicast discovery. Only the LAN address and port are kept."""
    try:
        data = json.loads(endpoint_cache_path().read_text())
        address, port = data['address'], data['port']
        ipaddress.ip_address(address.split('%',1)[0])
        if isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536:
            return address, port
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None

def save_last_endpoint(address, port):
    path = endpoint_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name+'.tmp')
        tmp.write_text(json.dumps({'address': address, 'port': port}))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass

async def try_endpoint(identifier, address, port, timeout=8):
    """A provider, or None when the endpoint is disallowed or does not answer."""
    try:
        if not await network_route_allowed(address):
            return None
        return await connect_wifi(identifier, address, port, timeout=timeout)
    except (OSError, TimeoutError, asyncio.IncompleteReadError, ValueError):
        return None

async def find_wifi_provider(identifier):
    """Search in short rounds and connect as soon as the phone answers. Each round
    also knocks on the last known address directly, in parallel with discovery."""
    last = load_last_endpoint()
    for round_no in range(BROWSE_ROUNDS):
        if round_no == WAKE_HINT_AFTER_ROUND:
            show_notice('Looking for the iPhone on Wi-Fi. Wake its screen to speed this up.')
        direct = asyncio.create_task(try_endpoint(identifier, *last, timeout=BROWSE_ROUND_SECONDS)) if last else None
        try:
            answers = await browse_remotepairing(timeout=BROWSE_ROUND_SECONDS)
            provider = await direct if direct else None   # bounded by its own timeout
        except BaseException:
            if direct and not direct.done():
                direct.cancel()
                await asyncio.gather(direct, return_exceptions=True)
            raise
        if provider:
            return provider, last
        endpoints = {(a.full_ip, answer.port) for answer in answers for a in answer.addresses}
        # Prefer IPv4; deduplicate repeated multicast advertisements.
        for address, port in sorted(endpoints, key=lambda ep: (':' in ep[0], ep[0], ep[1])):
            provider = await try_endpoint(identifier, address, port)
            if provider:
                return provider, (address, port)
    return None, None

async def wifi_provider(serial, autopair=False, remotepairing_fallback=False):
    identifiers = list(iter_remote_paired_identifiers())
    if serial:
        identifiers = [i for i in identifiers if i.replace('-','')==serial.replace('-','')]
    if not identifiers:
        raise RuntimeError('No saved CoreDevice pairing matches this device. Pair over USB first.')
    if len(identifiers)>1:
        raise RuntimeError('Several pairing records exist. Select an iPhone with --serial.')
    provider, endpoint = await find_wifi_provider(identifiers[0])
    if provider is None:
        raise RuntimeError('The paired iPhone was not reachable on the local network.')
    save_last_endpoint(*endpoint)
    return provider, None

class WifiTunnel(ut.UserspaceRsdTunnel):
    async def _aopen_locked(self):
        # The pinned library exposes no provider injection API. Its process-wide
        # tunnel lock is held here; replace the selector only during opening.
        # Restore it on success, failure, and cancellation. Never edit library files.
        original = ut._create_no_root_tunnel_provider
        ut._create_no_root_tunnel_provider = wifi_provider
        try:
            return await super()._aopen_locked()
        finally:
            ut._create_no_root_tunnel_provider = original

def get_tunnel(mode,serial):
    cls = WifiTunnel if mode=='wifi' else ut.UserspaceRsdTunnel
    return cls(serial=serial,autopair=False,remotepairing_fallback=False)
