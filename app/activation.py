"""Native FluentPy activation gate, license details and running expiry checks."""
import time
from fluentpy import widgets as W
from PySide6.QtCore import QObject,QTimer,Qt,QUrl
from PySide6.QtGui import QDesktopServices,QFont
from PySide6.QtWidgets import QApplication,QLabel,QWidget,QHBoxLayout,QVBoxLayout
from core import activation as licensing


def _notice(bar,message):
    bar.set_detail(message)
    bar.setVisible(bool(message))


def activation_dialog(machine,config,reason='',parent=None,*,clock=None):
    clock=clock or time.time
    dialog=W.FramelessDialog('激活 VertexViewer','复制本机机器码交给软件提供者，再粘贴包含授权名称和有效期的激活码。',parent)
    dialog.setAttribute(Qt.WA_QuitOnClose,False)
    dialog.setYesButtonText('激活并启动');dialog.setCancelButtonText('退出' if parent is None else '取消')
    dialog.add_content_widget(QLabel('本机机器码',dialog))
    row=QWidget(dialog);layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
    machine_edit=W.LineEdit(machine,show_clear_button=False,parent=dialog)
    machine_edit.setReadOnly(True);machine_edit.setMinimumWidth(420)
    machine_edit.setFont(QFont('Consolas',10));machine_edit.setCursorPosition(0)
    copy=W.Button('复制机器码',dialog)
    copy.clicked.connect(lambda:(QApplication.clipboard().setText(machine),copy.setText('已复制')))
    layout.addWidget(machine_edit,1);layout.addWidget(copy)
    dialog.add_content_widget(row)
    site=W.Button('打开签发网页（管理者）',dialog)
    site.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(config['issuer_url']+'?product=VertexViewer')))
    dialog.add_content_widget(site)
    dialog.add_content_widget(QLabel('激活码',dialog))
    code=W.TextEdit(dialog);code.setPlaceholderText('粘贴完整的 DFVA1. 开头激活码');code.setFixedHeight(110)
    dialog.add_content_widget(code)
    details=QLabel('授权名称、签发时间和有效期均由激活码自动识别。',dialog)
    details.setTextFormat(Qt.PlainText);details.setWordWrap(True)
    dialog.add_content_widget(details)
    notice=W.InfoBar('授权提示',reason,dialog,tone='warning',orientation='vertical',closable=False)
    notice.setVisible(bool(reason));dialog.add_content_widget(notice)
    dialog.yes_button.clicked.disconnect()
    dialog.yes_button.setAutoDefault(False);dialog.yes_button.setDefault(False)

    def activate():
        try:
            claims=licensing.save_license(code.toPlainText(),machine,licensing.unb64(config['public_key']),now=clock())
        except (licensing.ActivationError,OSError) as exc:
            _notice(notice,str(exc));dialog.adjustSize();code.setFocus();return
        dialog.claims=claims
        dialog.accept()

    def edited():
        token=code.toPlainText().strip()
        dialog.yes_button.setEnabled(bool(token))
        try:
            claims=licensing.verify(token,machine,licensing.unb64(config['public_key']),now=clock())
            details.setText('授权给：'+claims['name']+'\n签发：'+licensing.format_time(claims['issued_at'])+
                            '\n到期：'+licensing.format_time(claims['expires_at']))
            _notice(notice,'')
        except licensing.ActivationError:
            details.setText('授权名称、签发时间和有效期均由激活码自动识别。')

    dialog.yes_button.clicked.connect(activate)
    code.textChanged.connect(edited)
    dialog.yes_button.setEnabled(False)
    dialog.machine_edit=machine_edit;dialog.code_edit=code;dialog.copy_button=copy
    dialog.notice=notice;dialog.license_details=details
    return dialog


def require_activation(reason='',*,clock=None):
    clock=clock or time.time
    try:
        config=licensing.public_config();machine=licensing.machine_code()
        try:
            licensing.saved_license(machine,licensing.unb64(config['public_key']),now=clock(),touch=True)
            return True
        except (licensing.ActivationError,OSError) as exc:
            reason=reason or str(exc)
    except licensing.ActivationError as exc:
        dialog=W.FramelessDialog('无法启动激活',str(exc))
        dialog.setYesButtonText('退出');dialog.cancel_button.hide();dialog.exec();return False
    dialog=activation_dialog(machine,config,reason,clock=clock)
    app=QApplication.instance();previous=app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    try:
        if dialog.exec()!=dialog.DialogCode.Accepted: return False
        licensing.saved_license(machine,licensing.unb64(config['public_key']),now=clock(),touch=True)
        return True
    except (licensing.ActivationError,OSError):
        return False
    finally:
        dialog.deleteLater();app.setQuitOnLastWindowClosed(previous)


class LicenseGuard(QObject):
    """Keep expiry enforced when the app stays open and the wall clock changes."""
    def __init__(self,app):
        super().__init__(app)
        self.app=app;self.wall_start=time.time();self.mono_start=time.monotonic()
        self.timer=QTimer(self);self.timer.timeout.connect(self.check)
        self._schedule(licensing.status(now=self.current_time())[0])

    def current_time(self):
        return max(time.time(),self.wall_start+max(0,time.monotonic()-self.mono_start))

    def _schedule(self,claims):
        delay=30000
        if claims and claims['expires_at'] is not None:
            delay=min(delay,max(1,int((claims['expires_at']-self.current_time())*1000)))
        self.timer.start(delay)

    def check(self):
        self.timer.stop()
        claims,reason=licensing.status(now=self.current_time(),touch=True)
        if claims is None:
            windows=[(w,w.isEnabled()) for w in self.app.topLevelWidgets() if w.isVisible()]
            for window,_ in windows: window.setEnabled(False)
            if not require_activation(reason,clock=self.current_time):
                self.app.closeAllWindows();self.app.quit();return
            for window,enabled in windows: window.setEnabled(enabled)
            claims=licensing.status(now=self.current_time())[0]
        self._schedule(claims)


def authorization_widget(parent=None):
    box=QWidget(parent);layout=QVBoxLayout(box);layout.setContentsMargins(14,12,14,12)
    layout.addWidget(QLabel('激活与授权',box))
    detail=QLabel(box);detail.setTextFormat(Qt.PlainText);detail.setWordWrap(True)
    detail.setTextInteractionFlags(Qt.TextSelectableByMouse);layout.addWidget(detail)
    row=QHBoxLayout();copy=W.Button('复制机器码',box);renew=W.Button('更换激活码 / 续期',box)
    row.addWidget(copy);row.addWidget(renew);row.addStretch();layout.addLayout(row)

    def refresh():
        claims,reason=licensing.status()
        detail.setText(('授权给：'+claims['name']+'\n签发时间：'+licensing.format_time(claims['issued_at'])+
                       '\n到期时间：'+licensing.format_time(claims['expires_at'])) if claims else reason)

    def activate():
        try:
            dialog=activation_dialog(licensing.machine_code(),licensing.public_config(),parent=box.window())
            dialog.setYesButtonText('保存激活码');dialog.exec();dialog.deleteLater()
        except licensing.ActivationError as exc:
            detail.setText(str(exc));return
        refresh()
        guard=getattr(QApplication.instance(),'_license_guard',None)
        if guard is not None:guard.check()

    copy.clicked.connect(lambda:QApplication.clipboard().setText(licensing.machine_code()))
    renew.clicked.connect(activate)
    box.license_details=detail;box.renew_button=renew;box.copy_button=copy
    timer=QTimer(box);timer.setInterval(30000);timer.timeout.connect(refresh);timer.start()
    box._license_timer=timer
    refresh()
    return box
