import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from lifecycle import Runtime
from mirror import Mirror

class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_expected_player_exit_during_cleanup_is_not_failure(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=Runtime(Path(root)/'runtime').acquire()
            try:
                app=Mirror(runtime)
                app.cleaning_up=True
                app.stop('player-exited')
                self.assertIsNone(app.error)
            finally:
                runtime.close()

    async def test_run_does_not_cancel_cleanup_already_started(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=Runtime(Path(root)/'runtime').acquire()
            app=Mirror(runtime)
            completed=[]
            async def capture():
                app.cleaning_up=True
                app.stop_event.set()
                await asyncio.sleep(.02)
                completed.append(True)
            app.capture=capture
            try:
                await app.run()
                self.assertEqual(completed,[True])
                self.assertEqual(runtime.state['state'],'stopped')
            finally:
                runtime.close()

    async def test_capture_start_and_stop_keep_tunnel_until_cleanup(self):
        events=[]
        with tempfile.TemporaryDirectory() as root:
            runtime=Runtime(Path(root)/'runtime').acquire()
            app=Mirror(runtime)
            class Tunnel:
                def __init__(self, **kw): pass
                async def __aenter__(self):
                    events.append('tunnel-open')
                    return Mock(service=Mock(address=['::1']))
                async def __aexit__(self,*args): events.append('tunnel-close')
            async def start(**kw):
                return {'connection':{'options':{'avcMediaStreamOptionClientSessionID':{'uuid':kw['client_session_id']}},
                                      'streamConfig':{}}}
            async def stop(sid): events.append('device-stop')
            async def close(): events.append('display-close')
            service=Mock(connect=AsyncMock(), start_video_stream=AsyncMock(side_effect=start),
                         stop_media_stream=AsyncMock(side_effect=stop), close=AsyncMock(side_effect=close))
            class Bridge:
                error = None
                def __init__(self,*args):
                    self.ready=asyncio.Event()
                async def run(self):
                    self.ready.set()
                    await asyncio.Event().wait()
                async def close(self): events.append('input-close')
            class Player:
                def __init__(self,*args,on_ready,**kwargs):
                    self.player=Mock(pid=123)
                    on_ready(self)
                def close(self): events.append('player-close')
            class Receiver:
                def __init__(self,*args,**kwargs): self._pli_tasks=set()
                async def _udp_recv_and_pipe(self,transport):
                    self._transcoder_cls(b'',b'',b'')
                    await asyncio.Event().wait()
                async def _rtcp_send_loop(self,transport): await asyncio.Event().wait()
            transport=Mock(port=1000,close=Mock(side_effect=lambda:events.append('transport-close')))
            with patch('connection.select_connection',AsyncMock(return_value=('usb',None))), \
                 patch('pymobiledevice3.remote.userspace_tunnel.UserspaceRsdTunnel',Tunnel), \
                 patch('pymobiledevice3.remote.core_device.display_service.DisplayService',return_value=service), \
                 patch('pymobiledevice3.remote.core_device.screen_stream.open_media_receiver',return_value=(transport,'::2')), \
                 patch('pymobiledevice3.remote.core_device.vnc_server.VncStreamServer',Receiver), \
                 patch('mirror.DirectPlayer',Player), patch('mirror.InputBridge',Bridge):
                task=asyncio.create_task(app.capture())
                try:
                    await asyncio.wait_for(app.player_ready.wait(),2)
                    # Let the bridge complete setup, then request a normal stop.
                    for _ in range(100):
                        if runtime.state['state']=='running': break
                        await asyncio.sleep(.001)
                    self.assertEqual(runtime.state['state'],'running')
                    app.stop()
                    await asyncio.wait_for(task,3)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task,return_exceptions=True)
                    runtime.close()
            self.assertEqual(events,['tunnel-open','input-close','device-stop','player-close','transport-close','display-close','tunnel-close'])
            self.assertIsNone(app.error)


    def test_display_service_detection_never_guesses(self):
        import mirror
        self.assertIsNone(mirror.display_service_offered(Mock()))
        self.assertIsNone(mirror.display_service_offered(Mock(peer_info={})))
        self.assertFalse(mirror.display_service_offered(Mock(peer_info={'Services':{}})))
        self.assertTrue(mirror.display_service_offered(Mock(peer_info={'Services':{mirror.DISPLAY_SERVICE:{}}})))

    async def test_mount_image_if_missing_mounts_once_and_reports_phase(self):
        import mirror
        phases=[]
        with tempfile.TemporaryDirectory() as root:
            runtime=Runtime(Path(root)/'runtime').acquire()
            try:
                app=Mirror(runtime)
                rsd=Mock(peer_info={'Services':{}})
                async def mount(client):
                    phases.append(runtime.state.get('phase'))
                with patch('pymobiledevice3.services.mobile_image_mounter.auto_mount',AsyncMock(side_effect=mount)) as auto_mount, \
                     patch('local_feedback.show_notice') as notice:
                    self.assertTrue(await app.mount_image_if_missing(rsd))
                    auto_mount.assert_awaited_once_with(rsd)
                    notice.assert_called_once()
                    self.assertEqual(phases,['mounting'])
                    self.assertIsNone(runtime.state.get('phase'))
                    # Present: nothing to do, no notification.
                    self.assertFalse(await app.mount_image_if_missing(Mock(peer_info={'Services':{mirror.DISPLAY_SERVICE:{}}})))
                    self.assertFalse(await app.mount_image_if_missing(Mock()))
                    auto_mount.assert_awaited_once()
            finally:
                runtime.close()

    async def test_mount_errors_map_to_fixed_messages(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=Runtime(Path(root)/'runtime').acquire()
            try:
                app=Mirror(runtime)
                rsd=Mock(peer_info={'Services':{}})
                with patch('mirror.auto_mount_enabled',return_value=False), \
                     patch('pymobiledevice3.services.mobile_image_mounter.auto_mount',AsyncMock()) as auto_mount:
                    with self.assertRaises(RuntimeError) as ctx:
                        await app.mount_image_if_missing(rsd)
                    self.assertEqual(str(ctx.exception),'Developer image is not mounted.')
                    auto_mount.assert_not_awaited()
                locked=Exception("command ReceiveBytes failed with: {'Error': 'DeviceLocked'}")
                with patch('local_feedback.show_notice'), \
                     patch('pymobiledevice3.services.mobile_image_mounter.auto_mount',AsyncMock(side_effect=locked)):
                    with self.assertRaises(Exception) as ctx:
                        await app.mount_image_if_missing(rsd)
                    self.assertIs(ctx.exception,locked)
                with patch('local_feedback.show_notice'), \
                     patch('pymobiledevice3.services.mobile_image_mounter.auto_mount',AsyncMock(side_effect=OSError('secret host'))):
                    with self.assertRaises(RuntimeError) as ctx:
                        await app.mount_image_if_missing(rsd)
                    self.assertEqual(str(ctx.exception),'Mounting the developer image failed.')
                async def slow(client): await asyncio.sleep(5)
                with patch('local_feedback.show_notice'), patch('mirror.MOUNT_TIMEOUT',0.01), \
                     patch('pymobiledevice3.services.mobile_image_mounter.auto_mount',AsyncMock(side_effect=slow)):
                    with self.assertRaises(RuntimeError) as ctx:
                        await app.mount_image_if_missing(rsd)
                    self.assertEqual(str(ctx.exception),'Mounting the developer image timed out.')
                self.assertIsNone(runtime.state.get('phase'))
            finally:
                runtime.close()

    async def _capture_with_tunnels(self, peer_infos, events):
        import mirror
        class Boom(Exception): pass
        opened=iter(peer_infos)
        class Tunnel:
            def __init__(self, **kw): pass
            async def __aenter__(self):
                events.append('tunnel-open')
                return Mock(service=Mock(address=['::1']),peer_info=next(opened))
            async def __aexit__(self,*args): events.append('tunnel-close')
        with tempfile.TemporaryDirectory() as root:
            runtime=Runtime(Path(root)/'runtime').acquire()
            try:
                app=Mirror(runtime)
                with patch('connection.select_connection',AsyncMock(return_value=('usb',None))), \
                     patch('pymobiledevice3.remote.userspace_tunnel.UserspaceRsdTunnel',Tunnel), \
                     patch('pymobiledevice3.remote.core_device.display_service.DisplayService',side_effect=Boom), \
                     patch('pymobiledevice3.services.mobile_image_mounter.auto_mount',AsyncMock()) as auto_mount, \
                     patch('local_feedback.show_notice'):
                    try:
                        await asyncio.wait_for(app.capture(),3)
                    except Exception as error:
                        return auto_mount, error
                    return auto_mount, None
            finally:
                runtime.close()

    async def test_capture_mounts_missing_image_then_reconnects(self):
        import mirror
        events=[]
        auto_mount,error=await self._capture_with_tunnels(
            [{'Services':{}},{'Services':{mirror.DISPLAY_SERVICE:{}}}],events)
        self.assertEqual(type(error).__name__,'Boom')  # reached the display service on the second tunnel
        auto_mount.assert_awaited_once()
        self.assertEqual(events,['tunnel-open','tunnel-close','tunnel-open','tunnel-close'])

    async def test_capture_mounts_at_most_once(self):
        events=[]
        auto_mount,error=await self._capture_with_tunnels([{'Services':{}},{'Services':{}}],events)
        self.assertIsInstance(error,RuntimeError)
        self.assertEqual(str(error),'The mounted image does not expose the display service.')
        auto_mount.assert_awaited_once()
        self.assertEqual(events,['tunnel-open','tunnel-close','tunnel-open','tunnel-close'])

    async def test_capture_skips_mounting_when_service_is_offered(self):
        import mirror
        events=[]
        auto_mount,error=await self._capture_with_tunnels([{'Services':{mirror.DISPLAY_SERVICE:{}}}],events)
        self.assertEqual(type(error).__name__,'Boom')
        auto_mount.assert_not_awaited()
        self.assertEqual(events,['tunnel-open','tunnel-close'])

if __name__=='__main__':unittest.main()
