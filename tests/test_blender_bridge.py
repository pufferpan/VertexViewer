"""发送到 Blender：手势判定、路径查找、导入脚本、启动参数。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from core import blender_bridge


class GestureTest(unittest.TestCase):
    def test_requires_modifier_and_distance(self):
        self.assertTrue(blender_bridge.is_gesture(True, 80))
        self.assertFalse(blender_bridge.is_gesture(False, 800))
        self.assertFalse(blender_bridge.is_gesture(True, 5))

    def test_threshold_is_a_few_dozen_pixels(self):
        self.assertGreaterEqual(blender_bridge.GESTURE_THRESHOLD, 24)
        self.assertLessEqual(blender_bridge.GESTURE_THRESHOLD, 64)


class ScriptTest(unittest.TestCase):
    def test_glb_script_uses_gltf_import(self):
        script = blender_bridge.import_script(r"C:\temp\a b\model.glb")
        self.assertIn("import_scene.gltf", script)
        self.assertIn("C:/temp/a b/model.glb", script)
        self.assertIn("view3d.view_selected", script)

    def test_obj_script_uses_obj_import(self):
        script = blender_bridge.import_script("C:/temp/part.obj")
        self.assertIn("wm.obj_import", script)
        self.assertIn("endswith('.obj')", script)

    def test_import_does_not_touch_existing_scene(self):
        script = blender_bridge.import_script("a.glb")
        self.assertNotIn("object.delete", script)
        self.assertNotIn("select_all(action='SELECT')", script)

    def test_reset_is_opt_in(self):
        self.assertIn("object.delete", blender_bridge.import_script("a.glb", reset=True))


class LaunchTest(unittest.TestCase):
    def test_missing_blender_raises(self):
        with mock.patch.object(blender_bridge, "blender_exe", return_value=""):
            with self.assertRaises(FileNotFoundError):
                blender_bridge.launch("a.glb")

    def test_launch_builds_python_argv(self):
        with mock.patch.object(blender_bridge, "blender_exe", return_value=r"C:\Blender\blender.exe"):
            with mock.patch.object(blender_bridge.subprocess, "Popen") as popen:
                blender_bridge.launch("C:/temp/a.glb")
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], r"C:\Blender\blender.exe")
        self.assertEqual(argv[1], "--python")
        self.assertTrue(argv[2].endswith(".py"))
        self.assertTrue(Path(argv[2]).is_file())
        script = Path(argv[2]).read_text(encoding="utf-8")
        self.assertIn("C:/temp/a.glb", script)

    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"VERTEXVIEWER_BLENDER": __file__}, clear=False):
            with mock.patch.object(blender_bridge, "_config_value", return_value=""):
                self.assertEqual(blender_bridge.blender_exe(), __file__)


if __name__ == "__main__":
    unittest.main()
