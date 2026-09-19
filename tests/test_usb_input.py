import unittest
from unittest.mock import AsyncMock
import keyboard_layouts
from usb_input import InputBridge, below_video, key_chords, key_usages, touch_position

class MappingTests(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(key_usages('a', 'a'), {4})
        self.assertEqual(key_usages('A', 'A'), {4, 225})
        self.assertEqual(key_usages('Ctrl+a'), {4, 224})
        self.assertEqual(key_usages('Shift+LEFT'), {225, 80})
        self.assertEqual(key_usages('ENTER'), {40})
        self.assertEqual(key_usages('F12'), set())
        self.assertEqual(key_usages('é'), set())

    def test_swedish_phone_layout(self):
        se = keyboard_layouts.load('se')
        self.assertEqual(key_usages('å', 'å', se), {0x2F})
        self.assertEqual(key_usages('Ä', 'Ä', se), {0x34, 225})
        self.assertEqual(key_usages('-', '-', se), {0x38})
        self.assertEqual(key_usages('@', '@', se), {0x1F, 226})
        self.assertEqual(key_usages('\\', '\\', se), {0x24, 225, 226})
        self.assertEqual(key_usages('Meta+c', '', se), {0x06, 227})
        # Dead-key characters are sequences, not one held chord.
        self.assertEqual(key_usages('è', 'è', se), set())
        self.assertEqual(key_chords('è', 'è', se)[1], [(0x2E, frozenset({225})), (0x08, frozenset())])
        self.assertEqual(key_chords('~', '~', se)[1], [(0x30, frozenset({226})), (44, frozenset())])

    def test_below_video(self):
        dims = {'w': 500, 'h': 2000, 'mt': 500, 'mb': 500}
        self.assertTrue(below_video({'x':250,'y':1600,'hover':True}, dims))
        self.assertFalse(below_video({'x':250,'y':1400,'hover':True}, dims))
        self.assertFalse(below_video({'x':250,'y':1600,'hover':False}, dims))

    def test_letterbox(self):
        dims = {'w': 600, 'h': 1000, 'ml': 100, 'mr': 100, 'mt': 50, 'mb': 50}
        self.assertEqual(touch_position({'x':100,'y':50,'hover':True},dims), (0,0))
        self.assertEqual(touch_position({'x':499,'y':949,'hover':True},dims), (65535,65535))
        self.assertIsNone(touch_position({'x':50,'y':50,'hover':True},dims))
        self.assertIsNone(touch_position({'x':200,'y':200,'hover':False},dims))
        self.assertEqual(touch_position({'x':999,'y':999},dims,True), (65535,65535))

class InputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = InputBridge(None, 'unused')
        self.b.hid = AsyncMock()
        self.b.indigo = AsyncMock()
        self.b.keyboard = 512
        self.b.command = AsyncMock()

    async def test_unfocused(self):
        self.assertTrue(self.b.enabled)
        await self.b.key('d--','a','a')
        self.b.hid.send_keyboard.assert_not_awaited()
        self.b.focused = True
        await self.b.key('d--','a','a')
        self.b.hid.send_keyboard.assert_awaited_with(512,{4})

    async def test_keyboard_release(self):
        self.b.enabled = self.b.focused = True
        await self.b.key('d--','a','a')
        self.b.hid.send_keyboard.assert_awaited_with(512,{4})
        await self.b.release()
        self.b.hid.send_keyboard.assert_awaited_with(512,[])
        self.assertEqual(self.b.held,{})

    async def test_touch_release(self):
        self.b.enabled = self.b.focused = True
        self.b.dimensions = {'w': 400, 'h': 870}
        self.b.mouse = {'x':200,'y':300,'hover':True}
        await self.b.key('dm-','MBTN_LEFT','')
        self.assertIsNotNone(self.b.contact)
        await self.b.release()
        self.assertIsNone(self.b.contact)
        self.assertEqual(self.b.hid.send_touchscreen.await_count,2)

    async def test_f8_has_no_action(self):
        self.b.focused = True
        await self.b.key('d--','F8','')
        await self.b.key('u--','F8','')
        self.assertTrue(self.b.enabled)
        self.b.command.assert_not_awaited()
        self.b.hid.send_keyboard.assert_not_awaited()

    async def home_presses(self):
        import asyncio
        await asyncio.sleep(.1)
        return [c.args for c in self.b.indigo.send_button.await_args_list]

    async def test_escape_presses_home_once(self):
        self.b.focused = True
        for state in ('d-', 'r-', 'u-'):
            await self.b.key(state, 'ESC', '')
        self.assertEqual(await self.home_presses(), [(12,64,1),(12,64,2)])
        # Escape itself is never typed; only the release-all report is sent.
        self.assertFalse(any(c.args[1] for c in self.b.hid.send_keyboard.await_args_list))

    async def test_drag_up_from_home_strip_presses_home(self):
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000}
        self.b.mouse = {'x':200,'y':980,'hover':True}
        await self.b.key('d-','MBTN_LEFT','')
        self.b.mouse = {'x':200,'y':600,'hover':True}
        await self.b.key('u-','MBTN_LEFT','')
        self.assertEqual(await self.home_presses(), [(12,64,1),(12,64,2)])
        self.b.hid.send_touchscreen.assert_not_awaited()

    async def test_click_in_home_strip_is_a_tap(self):
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000}
        self.b.mouse = {'x':200,'y':980,'hover':True}
        await self.b.key('d-','MBTN_LEFT','')
        self.b.hid.send_touchscreen.assert_not_awaited()
        await self.b.key('u-','MBTN_LEFT','')
        states = [c.args[0] for c in self.b.hid.send_touchscreen.await_args_list]
        self.assertEqual(states, [0xC2, 0x02])
        self.assertEqual(await self.home_presses(), [])

    async def test_drag_up_from_letterbox_presses_home(self):
        self.b.focused = True
        self.b.dimensions = {'w':500,'h':2000,'mt':500,'mb':500}
        self.b.mouse = {'x':250,'y':1600,'hover':True}
        await self.b.key('d-','MBTN_LEFT','')
        self.b.mouse = {'x':250,'y':1200,'hover':True}
        await self.b.key('u-','MBTN_LEFT','')
        self.assertEqual(await self.home_presses(), [(12,64,1),(12,64,2)])

    async def test_dead_key_character_is_typed_as_sequence(self):
        self.b.focused = True
        self.b.layout = keyboard_layouts.load('se')
        await self.b.key('d-','è','è')
        await self.b.key('u-','è','è')
        states = [set(c.args[1]) for c in self.b.hid.send_keyboard.await_args_list]
        self.assertEqual(states, [{225}, {225, 0x2E}, {225}, set(), {0x08}, set()])

    async def test_overlap_does_not_leak_modifiers(self):
        self.b.focused = True
        for state, name in (('d-','H'), ('d-','i'), ('u-','H'), ('u-','i')):
            await self.b.key(state, name, name)
        states = [set(c.args[1]) for c in self.b.hid.send_keyboard.await_args_list]
        self.assertEqual(states, [{225}, {225, 0x0B}, {225}, set(), {0x0C}, set()])

    async def test_shift_precedes_letter(self):
        self.b.focused = True
        await self.b.key('d--','A','A')
        states = [c.args[1] for c in self.b.hid.send_keyboard.await_args_list]
        self.assertEqual(states,[{225},{225,4}])
        await self.b.key('u--','A','A')
        states = [c.args[1] for c in self.b.hid.send_keyboard.await_args_list]
        self.assertEqual(states,[{225},{225,4},{225},set()])
        self.assertEqual(self.b.reported_keys,set())

    async def test_case_changed_key_release(self):
        self.b.focused = True
        await self.b.key('d--','A','A')
        await self.b.key('u--','a','a')
        self.assertEqual(self.b.held,{})
        self.assertEqual(self.b.reported_keys,set())

    async def test_shifted_symbol(self):
        self.b.focused = True
        await self.b.key('p--','!','!')
        states = [c.args[1] for c in self.b.hid.send_keyboard.await_args_list]
        self.assertEqual(states,[{225},{225,30},{225},set()])

    async def test_ctrl_precedes_letter(self):
        self.b.focused = True
        await self.b.key('d--','Ctrl+a','')
        states = [c.args[1] for c in self.b.hid.send_keyboard.await_args_list]
        self.assertEqual(states,[{224},{224,4}])
        await self.b.key('u--','a','a')
        self.assertEqual(self.b.reported_keys,set())

    async def test_overlap_preserves_shift(self):
        self.b.focused = True
        await self.b.key('d--','A','A')
        await self.b.key('d--','B','B')
        await self.b.key('u--','A','A')
        self.assertEqual(self.b.reported_keys,{225,5})
        await self.b.key('u--','B','B')
        self.assertEqual(self.b.reported_keys,set())

    async def test_wheel_directions(self):
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':200,'y':450,'hover':True}
        for name, sign in [('WHEEL_UP',1),('WHEEL_DOWN',-1)]:
            self.b.hid.send_touchscreen.reset_mock()
            await self.b.key('p--',name,'')
            await self.b.gesture_task
            reports = self.b.hid.send_touchscreen.await_args_list
            self.assertEqual(len(reports),10)
            self.assertGreater(sign*(reports[-1].args[2]-reports[0].args[2]),0)
            self.assertEqual(reports[-1].args[0],2)
            self.assertIsNone(self.b.contact)

    async def test_wheel_toolbar_ignored(self):
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':200,'y':960,'hover':True}
        await self.b.key('p--','WHEEL_DOWN','')
        self.assertIsNone(self.b.gesture_task)

    async def test_wheel_during_drag_ignored(self):
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':200,'y':450,'hover':True}
        self.b.contact = (30000,30000)
        await self.b.key('p--','WHEEL_DOWN','')
        self.assertIsNone(self.b.gesture_task)
        self.assertEqual(self.b.contact,(30000,30000))

    async def test_wheel_cancel_and_bounded_burst(self):
        import asyncio
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':200,'y':450,'hover':True}
        for _ in range(20):
            await self.b.key('p--','WHEEL_DOWN','')
        self.assertEqual(self.b.scroll_pending,-4)
        await asyncio.sleep(.02)
        await self.b.release()
        self.assertIsNone(self.b.contact)
        self.assertFalse(self.b.scrolling)
        self.assertEqual(self.b.scroll_pending,0)
        self.assertEqual(self.b.hid.send_touchscreen.await_args_list[-1].args[0],2)

    async def test_wheel_invalid_scale(self):
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':200,'y':450,'hover':True}
        for scale in ('nan','inf','bad','0','-1'):
            await self.b.key('p--','WHEEL_DOWN','',scale)
        self.assertIsNone(self.b.gesture_task)

    async def test_search_cancel_releases_modifiers(self):
        import asyncio
        self.b.focused = True
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':300,'y':960,'hover':True}
        await self.b.key('dm-','MBTN_LEFT','')
        await asyncio.sleep(.02)
        await self.b.release()
        self.assertIsNone(self.b.gesture_task)
        self.assertEqual(self.b.reported_keys,set())
        self.assertEqual(self.b.held,{})

    async def test_usb_failure_keeps_viewer_and_does_not_replay_keys(self):
        import asyncio
        self.b.focused = True
        self.b.writer = AsyncMock()
        self.b.hid.send_keyboard.side_effect = asyncio.IncompleteReadError(b'',9)
        with self.assertLogs('iphone-mirror.input',level='ERROR') as logs:
            await self.b.dispatch_key('d--','a','a')
        self.assertFalse(self.b.enabled)
        self.assertIsNotNone(self.b.error)
        self.b.writer.close.assert_not_called()
        self.assertIsNone(self.b.hid)
        self.assertIsNone(self.b.keyboard)
        await self.b.dispatch_key('d--','b','b')
        self.assertIsNone(self.b.hid)
        self.assertIn('IncompleteReadError',logs.output[0])
        self.assertNotIn('partial=',logs.output[0])

    async def test_reconnect_click_does_not_tap_phone(self):
        self.b.focused = True
        self.b.enabled = False
        self.b.error = 'disconnected'
        self.b.dimensions = {'w':400,'h':1000,'mb':80}
        self.b.mouse = {'x':200,'y':450,'hover':True}
        await self.b.dispatch_key('dm-','MBTN_LEFT','')
        self.assertTrue(self.b.enabled)
        self.assertIsNone(self.b.error)
        self.b.hid.send_touchscreen.assert_not_awaited()

    async def test_cancellation(self):
        self.b.enabled = self.b.focused = True
        await self.b.key('d--','a','a')
        await self.b.key('u-c','a','')
        self.assertEqual(self.b.held,{})
        self.b.hid.send_keyboard.assert_awaited_with(512,[])

if __name__ == '__main__':
    unittest.main()
