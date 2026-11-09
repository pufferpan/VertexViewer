"""Verify populated credits, literal messages, scrolling and native controls."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def run(output):
    from PySide6.QtCore import QEventLoop,QRect,Qt,QTimer
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication,QLabel
    from fluentpy import widgets as W
    from unittest.mock import patch
    from app.credits import CreditsWindow
    from app.fluent_api import apply_dark_palette,apply_fluent_theme
    from app.wizard import CONFIG
    from core.version import stamp
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_fluent_theme(True);apply_dark_palette(app,True)
    def wait(ms):
        loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()
    config=Path(CONFIG);before=config.read_bytes() if config.exists() else None
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    expected=['HL-Flame','或记','LeaveN1ght','TF-注册表','William730','夏初辰','夕枫明月',
              '姓邓的小馒头','尤里的喵卡雷龙','圆润的比尔']
    window=CreditsWindow();window.setAttribute(Qt.WA_DontShowOnScreen)
    finished=[];window.finished.connect(lambda:finished.append(True))
    window.start();native=QRect(window.geometry());wait(1200)
    assert window._opened and window.geometry()==native and window.surfaceRect==window.rect()
    assert [e['name'] for e in window.entries]==expected
    assert window.bg.row_count()==3
    assert type(window.back_button) is W.AccentButton and type(window.panel) is W.SimpleCardWidget
    assert type(window.scroll.verticalScrollBar()) is W.FluentScrollBar
    labels=window.list_body.findChildren(QLabel)
    literal=next(e['description'] for e in window.entries if e['name']=='William730')
    label=next(l for l in labels if l.text()==literal)
    assert label.textFormat()==Qt.PlainText and '<think>' in label.text() and '</think>' in label.text()
    assert all(l.textFormat()==Qt.PlainText for l in labels)
    links=window.list_body.findChildren(W.HyperlinkButton);assert len(links)==1
    with patch.object(QDesktopServices,'openUrl',return_value=True) as opened:
        links[0].click();assert opened.call_count==1
        assert opened.call_args.args[0].toString()=='https://github.com/XDDXMT'
    scroll=window.scroll.verticalScrollBar();assert scroll.maximum()>0
    window.grab().save(str(out/'credits-top.png'))
    scroll.setValue(scroll.maximum()//2);wait(80)
    window.grab().save(str(out/'credits-middle.png'))
    scroll.setValue(scroll.maximum());wait(80)
    window.grab().save(str(out/'credits-bottom.png'))
    last=next(l for l in labels if l.text()==window.entries[-1]['description'])
    assert window.scroll.viewport().rect().contains(last.mapTo(window.scroll.viewport(),last.rect().center()))
    window.back_button.click();wait(500)
    assert not window.isVisible() and finished==[True]
    early=CreditsWindow();early.setAttribute(Qt.WA_DontShowOnScreen);early.start();wait(60)
    early.close();wait(450);assert not early.isVisible()
    assert before==(config.read_bytes() if config.exists() else None)
    window.deleteLater();early.deleteLater();app.processEvents()
    report=dict(version=stamp(),entries=10,names_in_order=expected,literal_messages=True,github_link=True,
                native_fluent_controls=True,all_rows_scrollable=True,three_screenshot_rows=True,
                fixed_native_window=True,close_during_animation=True,settings_unchanged=True)
    (out/'credits-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(run(sys.argv[1] if len(sys.argv)>1 else 'work/credits-source'))
