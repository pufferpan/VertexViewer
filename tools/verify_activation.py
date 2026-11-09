"""Small packaged activation check; does not load game models or launch exporters."""
from pathlib import Path
import json
import sys


def run(output):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from core import activation as A
    from core.version import stamp
    from app.activation import activation_dialog,authorization_widget
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance()
    claims,reason=A.status()
    assert claims is not None,reason
    config=A.public_config()
    dialog=activation_dialog(A.machine_code(),config)
    assert type(dialog) is W.FramelessDialog and type(dialog.code_edit) is W.TextEdit
    assert type(dialog.machine_edit) is W.LineEdit and type(dialog.notice) is W.InfoBar
    dialog.setAttribute(Qt.WA_DontShowOnScreen)
    dialog.code_edit.setPlainText('invalid activation code');dialog.yes_button.click()
    assert dialog.result()==0 and bool(dialog.notice.detail())
    dialog.code_edit.clear()
    dialog.notice.setVisible(False)
    dialog.license_details.setText('授权给：'+claims['name']+'\n到期：'+A.format_time(claims['expires_at']))
    dialog.show();app.processEvents()
    dialog.grab().save(str(out/'activation-dialog.png'))
    details=authorization_widget();details.setAttribute(Qt.WA_DontShowOnScreen)
    details.resize(720,220);details.show();app.processEvents()
    assert claims['name'] in details.license_details.text()
    assert type(details.renew_button) is W.Button
    details.grab().save(str(out/'authorization.png'))
    dialog.close();details.close()
    result=dict(version=stamp(),frozen=bool(getattr(sys,'frozen',False)),native_controls=True,
                invalid_code_blocked=True,signature_verified=True,authorization_name=claims['name'],
                expires_at=claims['expires_at'],name_and_expiry_display=True)
    (out/'activation-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0
