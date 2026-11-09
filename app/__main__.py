"""`python -m app` entry point."""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QRect


def _open_log():
    """打包版没有控制台，把 stdout/stderr 落到 %LOCALAPPDATA%\\VertexViewer\\logs\\startup.log。"""
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        logdir = os.path.join(base, "VertexViewer", "logs")
        os.makedirs(logdir, exist_ok=True)
        path = os.path.join(logdir, "startup.log")
        fh = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:                                        # noqa: BLE001
        return None
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name, None)
        try:
            if stream is None:
                raise OSError('No console stream')
            os.fstat(stream.fileno())
            stream.flush()
        except (OSError, ValueError, AttributeError):
            setattr(sys, name, fh)
    return fh


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # The offscreen platform plugin looks for fonts in a bogus bundled dir;
    # point it at the real Windows font directory before Qt starts.
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
        os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

    log = _open_log() if getattr(sys, "frozen", False) else None
    try:
        return _run(argv, log)
    except BaseException:                                    # noqa: BLE001
        if log is not None:
            traceback.print_exc(file=log)
            log.flush()
        raise


def _run(argv, log=None) -> int:
    from app.fluent_api import (LEVEL_NAME, SOURCE, QApplication, apply_dark_palette,
                                apply_fluent_theme)

    if log is not None:
        print(f"[vertexviewer] ui level={LEVEL_NAME} source={SOURCE}", file=log)
        try:
            from core import loader as _ld
            from core.version import stamp
            print(f"[vertexviewer] version={stamp()} frozen={getattr(sys, 'frozen', False)}",
                  file=log)
            print("[vertexviewer] " + _ld.search_report().replace("\n", " | "), file=log)
        except Exception as exc:                             # noqa: BLE001
            print(f"[vertexviewer] report failed: {exc}", file=log)

    # 贴图绑定策略（FModel 语义：只按模型/材质自己的目录找）默认开启，
    # 用户可以在「设置 → 材质」里关掉退回全局按名字猜。
    try:
        from core import loader as _loader

        _strict = (_loader._read_config() or {}).get("strict_dirs", True)
        _loader.set_strict_dirs(bool(_strict))
        if log is not None:
            print(f"[vertexviewer] strict_dirs={_loader.STRICT_DIRS}", file=log)
    except Exception:                                       # noqa: BLE001
        pass

    # 支持端排查用：VERTEXVIEWER_DIAG=1 启动就写一份诊断报告（不弹窗、不阻塞）
    if (os.environ.get("VERTEXVIEWER_DIAG") or "").strip() in ("1", "true", "yes"):
        # 延后 2.5s：太早写报告的话 Qt 还没起来，OpenGL 那一栏只能是「未测」；
        # 这时窗口也差不多好了，报告才拿得到显卡/驱动信息。
        def _write_diag() -> None:
            try:
                from core import diag as _diag0
                _p = _diag0.write_report()
                if log is not None:
                    print(f"[diag] 诊断报告 -> {_p}", file=log)
            except Exception:                               # noqa: BLE001
                pass
        try:
            from PySide6.QtCore import QTimer as _QT
            _QT.singleShot(2500, _write_diag)
        except Exception:                                   # noqa: BLE001
            _write_diag()

    # 未捕获异常自动落一份「崩溃-时间.txt」（带完整诊断报告），
    # 别人只要把 logs 里那个文件发回来就能定位，不用来回问。
    try:
        from core import diag as _diag
        _diag.install_excepthook()
    except Exception:                                       # noqa: BLE001
        pass

    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("VertexViewer")
    app.setApplicationDisplayName("VertexViewer · 模型浏览器")
    try:
        apply_fluent_theme(True)
        apply_dark_palette(app, True)
    except Exception:                                       # noqa: BLE001
        if log is not None:
            traceback.print_exc(file=log)
        print("[vertexviewer] theme failed", file=log or sys.stderr)

    from app.activation import require_activation,LicenseGuard
    if not require_activation():
        return 1
    app._license_guard=LicenseGuard(app)
    if len(argv)==3 and argv[1]=='--verify-release':
        from tools.verify_release import run
        return run(argv[2])
    if len(argv)==3 and argv[1]=='--verify-activation':
        from tools.verify_activation import run
        return run(argv[2])
    if len(argv)==3 and argv[1]=='--verify-inspection-hands':
        from tools.verify_inspection_hands import run
        return run(argv[2])
    if len(argv)==3 and argv[1]=='--verify-first-person':
        from tools.verify_first_person import run
        return run(argv[2])
    if len(argv)==3 and argv[1]=='--verify-credits':
        from tools.verify_credits import run
        return run(argv[2])

    from app.startup_audio import StartupAudio
    app._startup_audio=StartupAudio()
    app.aboutToQuit.connect(app._startup_audio.stop)
    app._startup_audio.play()

    from app.main_window import VertexViewerWindow

    # 首次启动：向导要**在加载动画进行中**就弹出来（不是等主窗口露脸之后）。
    # 顺序按需求：加载动画先转起来 → 小窗「等一下…我还没见过你诶」→ 慢慢变大 →
    # 三行截图飞进来 → 三步设置 → 关闭后加载继续，加载完再展开成主窗口。
    _wiz_state = {"active": False, "defer": False}

    def _run_wizard() -> bool:
        try:
            from app import wizard as _wizard

            if not _wizard.needs_wizard() or os.environ.get("VERTEXVIEWER_NOSPLASH_WIZARD"):
                return False
            from PySide6.QtCore import QEventLoop as _QEventLoop

            _wiz = _wizard.WizardWindow()
            _wiz.start()
            _loop = _QEventLoop()
            _wiz.finished.connect(lambda _ok: _loop.quit())
            _loop.exec()
            _wiz.deleteLater()
            if log is not None:
                print("[vertexviewer] wizard done", file=log)
            return True
        except Exception:                                    # noqa: BLE001
            if log is not None:
                traceback.print_exc(file=log)
            return False

    # 小方框必须在**构造主窗口之前**亮出来：VertexViewerWindow 的构造函数要建整棵
    # 导航/模型库控件树（这里要好几秒），先建窗口再显示加载框的话，用户前几秒
    # 面对的是一片什么都没的桌面。
    splash = None
    if not os.environ.get("VERTEXVIEWER_NOSPLASH") and not os.environ.get("VERTEXVIEWER_AUTOSHOT"):
        try:
            from app.splash import SplashWindow
            from PySide6.QtWidgets import QApplication as _QApp

            splash = SplashWindow()
            splash.set_status("正在准备界面…")
            splash.center_on_screen()
            _QApp.processEvents()          # 立刻把这一帧画出来，别等构造函数跑完
        except Exception:                                    # noqa: BLE001
            if log is not None:
                traceback.print_exc(file=log)
            splash = None

    if splash is not None:
        # 让构造函数别急着弹「选游戏目录」，等展开完再问
        VertexViewerWindow._defer_game_dir = True

        # 索引放到后台线程先读：读的过程里进度条要能一条一条往上走，
        # 如果等构造函数里同步读，GUI 线程被占住，加载框就是一张冻住的黑卡。
        import threading as _threading

        from core import loader as _ld0

        _idx = {"done": False, "error": ""}

        def _warm_index():
            try:
                _ld0.index()
            except Exception as exc:                        # noqa: BLE001
                _idx["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                _idx["done"] = True

        _threading.Thread(target=_warm_index, daemon=True, name="dfv-index").start()
        window = None
        # 同时持有 splash 的引用：FluentPy 的 theme 订阅挂在窗口上，
        # 对象一旦被回收就会对已释放的 C++ 对象回调并抛 RuntimeError。
        _splash_build = {"window": None, "splash": splash}
    else:
        window = VertexViewerWindow()
        _splash_build = {"window": window, "splash": splash}
    if splash is not None:
        try:
            splash.set_status("正在读取资产索引…")
        except Exception:                                    # noqa: BLE001
            pass
    if splash is not None:
        # 加载界面：屏幕正中一个小长方形，索引读完后展开成主窗口。
        # 截图/自检/离屏跑的时候用 VERTEXVIEWER_NOSPLASH=1 直接显示窗口。
        try:
            from PySide6.QtCore import QTimer as _QTimer
            from PySide6.QtWidgets import QApplication as _QApp

            import time as _time

            def _target_rect():
                from app import ui_scale as _ui
                win = _splash_build.get("window")
                want_w = win.width() if win is not None else 1500
                want_h = win.height() if win is not None else 940
                w, h = _ui.fit(want_w, want_h)      # 别硬撑 1200×780，小屏会被裁
                screen = _QApp.primaryScreen()
                area = screen.availableGeometry() if screen else QRect(0, 0, w, h)
                return QRect(area.center().x() - w // 2,
                             area.center().y() - h // 2, w, h)

            state = {"opened": False, "ticks": 0, "t0": _time.monotonic(),
                     "built": False, "scheduled": False}
            FADE_WAIT_MS = 220           # 展开 660ms + 淡出 130ms 之后
            MIN_SHOW = 0.75          # 至少露个脸，别一闪而过看不见动画

            def _build_window():
                """索引读完后才建主窗口：构造函数要建整棵控件树，会卡住 GUI。"""
                if state["built"]:
                    return
                state["built"] = True
                try:
                    # 别把「请享用这款软件吧！」盖掉：建窗口要卡住 GUI 一两秒，
                    # 这一两秒里屏幕上就停着那句话，正好。
                    if "请享用" not in getattr(splash, "_status", ""):
                        splash.set_status("正在构建界面…")
                    splash.set_fraction(1.0)
                    _QApp.processEvents()
                except Exception:                            # noqa: BLE001
                    pass
                _splash_build["window"] = VertexViewerWindow()

            def _open(*_a):
                if state["opened"]:
                    return
                # 向导还开着就先记账：等它关了再展开，别让主窗口抢在向导屁股后面冒出来
                if _wiz_state["active"]:
                    _wiz_state["defer"] = True
                    return
                state["opened"] = True
                _build_window()
                win = _splash_build.get("window")
                rect = _target_rect()

                # 主窗口一建出来，浏览器那边排队等着跑的「索引到了 → 给 9397 个
                # 资产建卡片数据 + 排序」就会回到事件循环里执行，实测要 1.4 秒。
                # 如果这时正好开始展开动画，动画定时器会被饿死，用户看到的就是
                # 「小框停在那儿，然后主窗口直接出现」。所以先把这段活干完，
                # 页面上明写「正在整理模型库…」，再开始放大。
                if win is not None:
                    try:
                        # 别再盖掉「请享用这款软件吧！」——它就停在这一帧上，
                        # 用户看得到，直到展开动画开始。
                        _QApp.processEvents()
                    except Exception:                    # noqa: BLE001
                        pass
                    deadline = _time.monotonic() + 8.0
                    browser = getattr(win, "browser", None)
                    while _time.monotonic() < deadline:
                        _QApp.processEvents()
                        if browser is None or getattr(browser, "is_ready", True):
                            break
                        _time.sleep(0.01)
                    _QApp.processEvents()

                def _after():
                    # 主窗口直接落在展开后的矩形上，不然它会跳回自己默认的位置
                    if win is None:
                        return
                    win.setGeometry(rect)
                    win.show()
                    win.raise_()
                    win.activateWindow()
                    # 向导已经在加载阶段走完了，这里只等窗口淡入再问游戏目录
                    _QTimer.singleShot(FADE_WAIT_MS, _ask_dir)

                def _ask_dir():
                    try:
                        win.ensure_game_dir()
                    except Exception:                    # noqa: BLE001
                        pass

                splash.expand_to(rect, done=_after)

            def _poll():
                if state["opened"] or splash is None:
                    return
                state["ticks"] += 1
                info = {}
                try:
                    from core import loader as _ld
                    info = _ld.progress()
                except Exception:                            # noqa: BLE001
                    info = {}
                total = int(info.get("total") or 0)
                done = int(info.get("done") or 0)
                stage = str(info.get("stage") or "")
                detail = str(info.get("detail") or "")
                # 真进度：loader 每读一段就写字节数/条目数，这里只做翻译。
                if not _idx["done"]:
                    if total > 0:
                        frac = max(0.0, min(1.0, done / total))
                        try:
                            splash.set_fraction(frac)
                        except Exception:                # noqa: BLE001
                            pass
                        text = stage or "正在加载…"
                        if detail:
                            text = f"{text} · {detail}"
                        splash.set_status(text)
                    else:
                        splash.set_status(stage or "正在读取资产索引…")
                    if state["ticks"] > 300:             # 约 15s 兜底，别把人卡在黑屏
                        _open()
                    return
                # 索引好了：先把进度拉满、换上「请享用这款软件吧！」，停一下再展开
                try:
                    splash.set_fraction(1.0)
                    splash.set_status("请享用这款软件吧！")
                except Exception:                            # noqa: BLE001
                    pass
                if state["scheduled"]:       # 只排一次，别每 50ms 排一个 _open
                    return
                state["scheduled"] = True
                left = MIN_SHOW - (_time.monotonic() - state["t0"])
                _QTimer.singleShot(int(max(0.0, left) * 1000) + 420, _open)

            poll = _QTimer(splash)
            poll.setInterval(50)
            poll.timeout.connect(_poll)
            poll.start()
            # splash 自己管生命周期，别被 GC 掉
            splash._dfv_poll = poll
            splash._dfv_state = state
            _splash_build["splash"] = splash

            # 让加载动画先转起来，再在它上面弹首次设置向导；索引在后台线程里继续读。
            def _start_wizard():
                if _wiz_state["active"] or state["opened"]:
                    return
                from app.wizard import needs_wizard
                if not needs_wizard():
                    return
                _wiz_state["active"] = True
                # 向导一出来就把加载框收起来，否则那个小蓝卡片会浮在向导的卡片墙上
                try:
                    splash.hide()
                except Exception:                        # noqa: BLE001
                    pass
                try:
                    _run_wizard()
                finally:
                    _wiz_state["active"] = False
                    try:
                        splash.show()
                        splash.raise_()
                    except Exception:                    # noqa: BLE001
                        pass
                    if _wiz_state["defer"]:
                        _wiz_state["defer"] = False
                        # 别在向导的嵌套事件循环里直接展开：等回到外层循环 300ms 再开，
                        # 否则 splash 的展开动画会被这次重入挤掉，主窗口会以默认小尺寸冒出来
                        _QTimer.singleShot(300, _open)

            if not os.environ.get("VERTEXVIEWER_NOSPLASH_WIZARD"):
                _QTimer.singleShot(760, _start_wizard)
        except Exception:                                    # noqa: BLE001
            if log is not None:
                traceback.print_exc(file=log)
            splash = None
            window = VertexViewerWindow()
            _splash_build["window"] = window
            window.show()
    elif _splash_build.get("window") is not None:
        _splash_build["window"].show()
        _run_wizard()
    window = _splash_build.get("window")

    # Headless self-test hook: VERTEXVIEWER_AUTOSHOT=<png> grabs the window after
    # VERTEXVIEWER_AUTOEXIT ms (default 1500) so `python -m app` can be verified
    # under QT_QPA_PLATFORM=offscreen without a human closing it.
    shot = os.environ.get("VERTEXVIEWER_AUTOSHOT")
    if shot:
        from app.fluent_api import QTimer

        delay = int(os.environ.get("VERTEXVIEWER_AUTOEXIT", "1500"))

        def _grab():
            win = _splash_build.get("window")
            if win is None:                       # 索引还没读完就先等一下
                QTimer.singleShot(400, _grab)
                return
            path = os.path.abspath(shot)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            ok = win.grab().save(path)
            print(f"[vertexviewer] autoshot {path} ok={ok}", flush=True)
            if os.environ.get("VERTEXVIEWER_LAYOUT_DUMP") == "1":
                _dump_layout(win, log or sys.stdout)
            if os.environ.get("VERTEXVIEWER_AUTOQUIT", "1") == "1":
                win.close()
                app.quit()

        QTimer.singleShot(delay, _grab)

    return app.exec()


def _dump_layout(window, out) -> None:
    """排查冻结版「导航栏消失 / 窗口一片白」：把关键控件几何和图标状态打出来。"""
    try:
        from app import fluent_api as F
        print(f"[vertexviewer] size={window.size().toTuple()} "
              f"visible={window.isVisible()} dark={F.isDarkTheme()}", file=out)
        nav = getattr(window, "navigationInterface", None)
        print(f"[vertexviewer] nav={type(nav).__name__ if nav else None} "
              f"nav_width={nav.width() if nav else -1} "
              f"nav_items={nav.count() if hasattr(nav, 'count') else '?'}", file=out)
        icon = F.FluentIcon.HOME.icon()
        print(f"[vertexviewer] icon_home_null={icon.isNull()} "
              f"size={icon.availableSizes()[:2]}", file=out)
        for child in window.findChildren(F.QWidget):
            name = child.objectName()
            if name and child.width() > 0:
                print(f"[vertexviewer]   {name}: {child.width()}x{child.height()}"
                      f"@{child.x()},{child.y()} visible={child.isVisible()}", file=out)
    except Exception:                                       # noqa: BLE001
        traceback.print_exc(file=out)


if __name__ == "__main__":
    raise SystemExit(main())
