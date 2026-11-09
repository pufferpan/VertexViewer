"""Play the bundled startup cue once, without blocking the UI thread."""
import logging
from pathlib import Path
import sys


def audio_path():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    return root/'assets'/'audio'/'OPEN_0.wav'


class StartupAudio:
    def __init__(self):
        self._played=False
        self._backend=None

    def play(self):
        if self._played:return True
        try:
            import winsound
            path=audio_path()
            if not path.is_file():raise FileNotFoundError(path)
            winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            self._backend=winsound
            self._played=True
            print('[startup-audio] playing OPEN_0.wav',flush=True)
            return True
        except (ImportError,OSError,RuntimeError) as exc:
            logging.getLogger(__name__).warning('启动音乐播放失败：%s',exc)
            return False

    def stop(self):
        if self._backend is not None:
            try:self._backend.PlaySound(None,0)
            except (OSError,RuntimeError):pass
            self._backend=None
