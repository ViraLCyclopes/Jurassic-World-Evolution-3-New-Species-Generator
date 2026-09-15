"""Generated scale hosts must tolerate ACSE's global scenery-removal broadcast."""
from pathlib import Path
import unittest

from lupa import LuaRuntime


class ScaleControllerLifecycleTests(unittest.TestCase):
    def test_scenery_removal_does_not_crash_or_change_dinosaur_scales(self):
        generator = Path(__file__).resolve().parents[1]
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
            api = {debug = {Trace = function() end}}
            require = function() return {subclass = function() return {} end} end
            module = function() captured = {}; return captured end
        ''')
        # Use ACSE's actual dispatch to cover its unconditional callback contract.
        acse = generator.parent / 'ACSE/Main/components.standalonesceneryserialisation.lua'
        lua.execute(acse.read_text(encoding='utf-8'))
        remove = lua.globals().captured.RemoveComponentFromEntities
        lua.execute((generator / 'templates/scalecontroller.template.lua').read_text(encoding='utf-8'))
        controller = lua.globals().captured
        controller.tEntities = lua.table_from({101: 1.25})
        controller.tLoadedScales = lua.table_from({202: 1.5})
        host = lua.table_from({
            'Components': lua.table_from({'testScaleHost': controller}),
            'tEntities': lua.table_from({999: True}),
        })
        for _ in range(2):
            remove(host, lua.table_from([999]))
        self.assertIsNone(host.tEntities[999])
        self.assertEqual(controller.tEntities[101], 1.25)
        self.assertEqual(controller.tLoadedScales[202], 1.5)


if __name__ == '__main__':
    unittest.main()
