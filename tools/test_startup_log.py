import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from app.__main__ import _open_log


class StartupLogTests(unittest.TestCase):
    def test_invalid_windows_gui_handles_use_the_startup_log(self):
        invalid = Mock()
        invalid.fileno.side_effect=OSError(22,'Invalid argument')
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{'LOCALAPPDATA':folder}), \
                 patch.object(sys,'stdout',invalid), patch.object(sys,'stderr',invalid):
                handle = _open_log()
                self.assertIs(sys.stdout,handle)
                self.assertIs(sys.stderr,handle)
                print('native startup',file=sys.stderr)
            handle.close()
            self.assertIn('native startup',Path(folder,'VertexViewer/logs/startup.log').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
