"""教程页面（当前状态：敬请期待）。

页面内容暂时是「敬请期待」，但进场效果保留：整张卡片先从一个小矩形按
OutCubic 长到全尺寸（760ms），长大的过程中画的是自己的快照，所以看起来是
「整张卡片在放大」而不是「边框在动、文字乱跳」——和启动时的加载卡片同一套。
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import (QEasingCurve, Property, QPropertyAnimation,
                            QRectF, Qt, QTimer)

from app.fluent_api import (BodyLabel, CaptionLabel, CardWidget, PushButton,
                            QLabel, QVBoxLayout, QWidget, StrongBodyLabel,
                            TitleLabel, icon)

EXPAND_MS = 760        # 和 app/splash.py 的 EXPAND_MS 保持一致
STAGGER_MS = 90

TITLE = "敬请期待"
SUBTITLE = "教程还在写，先把软件摸着玩。"
DETAIL = ("一句话先记住三件事：左边搜游戏里的中文名（「M4A1」「头盔」「小猫饰品」都行）；"
          "底部分类按钮切换武器 / 配件 / 装备 / 弹药 / 钥匙卡 / 藏品 / 容器 / 角色技能 等；"
          "右侧检查器能切 LOD、UV 通道、渲染风格和灯光，出问题就去「设置 → 数据维护」。")
CREDIT = "软件制作：河豚潘 PufferPan"


class Reveal(QWidget):
    """把内部控件当贴纸放大：动画期间画快照，结束后交回真实控件。"""

    def __init__(self, inner: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = inner
        self._pix = None
        self._grow = 1.0
        self._anim: QPropertyAnimation | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(inner)
        self.setObjectName("revealWrap")

    # ---- 属性动画用的属性（必须是 Qt Property，Python property 动画找不到）---- #
    def get_grow(self) -> float:
        return self._grow

    def set_grow(self, value: float) -> None:
        self._grow = max(0.0, min(1.0, float(value)))
        self.update()

    grow = Property(float, get_grow, set_grow)

    def play(self, delay_ms: int = 0) -> None:
        if self._pix is not None:                     # 正在播，别叠加
            return
        self._pix = self.grab()
        self.setFixedHeight(self.height() or self.sizeHint().height())
        self._inner.setVisible(False)
        anim = QPropertyAnimation(self, b"grow", self)
        anim.setDuration(EXPAND_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._done)
        self._anim = anim

        def _start() -> None:
            self._grow = 0.0
            anim.start()

        QTimer.singleShot(max(0, int(delay_ms)), _start)

    def _done(self) -> None:
        self._pix = None
        self._inner.setVisible(True)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.update()

    def paintEvent(self, event) -> None:                # noqa: N802
        if self._pix is None or self._grow >= 0.999:
            super().paintEvent(event)
            return
        from PySide6.QtGui import QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w = self.width() * (0.32 + 0.68 * self._grow)
        h = self.height() * (0.32 + 0.68 * self._grow)
        target = QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)
        p.setOpacity(min(1.0, 0.25 + 0.75 * self._grow))
        p.drawPixmap(target, self._pix, QRectF(self._pix.rect()))
        p.end()


class TutorialPage(QWidget):
    """教程页（敬请期待）；进场动画复刻启动卡片。"""

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("tutorialPage")
        self.host_window = window
        self._reveals: List[Reveal] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(TitleLabel("教程", self))
        head.addWidget(CaptionLabel("想再看一遍进场动画就点右边「重播」。", self))
        root.addLayout(head)

        bar = QVBoxLayout()
        bar.setSpacing(8)
        self.replay_btn = PushButton(icon("play"), "重播动画", self)
        self.replay_btn.clicked.connect(self.replay)
        bar.addWidget(self.replay_btn, 0, Qt.AlignLeft)
        self.credit = QLabel(CREDIT, self)
        self.credit.setStyleSheet("color:rgba(255,255,255,0.42);font-size:11px;")
        bar.addWidget(self.credit, 0, Qt.AlignRight)
        root.addLayout(bar)

        body = QVBoxLayout()
        body.setSpacing(10)
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 22, 22, 18)
        lay.setSpacing(8)
        big = StrongBodyLabel(TITLE, card)
        big.setStyleSheet("font-size:34px;font-weight:600;letter-spacing:6px;")
        lay.addWidget(big, 0, Qt.AlignHCenter)
        sub = CaptionLabel(SUBTITLE, card)
        lay.addWidget(sub, 0, Qt.AlignHCenter)
        tips = CaptionLabel("（详细的图文教程写好之后会直接放这一页）", card)
        tips.setStyleSheet("color:rgba(255,255,255,0.34);")
        # 内容贴着顶部排，剩下空间留白；不然整页高度会把四行字均匀撑开
        lay.addSpacing(22)
        detail = BodyLabel(DETAIL, card)
        detail.setWordWrap(True)
        detail.setStyleSheet("color:rgba(255,255,255,0.62);")
        lay.addWidget(detail)
        lay.addWidget(tips, 0, Qt.AlignLeft)
        lay.addStretch(1)

        wrap = Reveal(card, self)
        body.addWidget(wrap, 1)
        self._reveals.append(wrap)
        root.addLayout(body, 1)

    # ---- 进场 ------------------------------------------------------------ #
    # 只有「首次启动」才自动放动画（main_window 负责判断），平时切到这一页
    # 就是静态的，免得正式用的时候每点一次都动一遍。
    def showEvent(self, event) -> None:                 # noqa: N802
        super().showEvent(event)
        if getattr(self, "_pending_intro", False):
            self._pending_intro = False
            QTimer.singleShot(60, self.replay)

    def play_intro(self) -> None:
        """立刻放一遍进场动画（首次启动 / 「重播动画」按钮）。"""
        self.replay()

    def replay(self) -> None:
        for i, wrap in enumerate(self._reveals):
            # 先把上一轮还原干净，避免二次播放时高度还是固定的
            wrap._done()
            QTimer.singleShot(i * STAGGER_MS, wrap.play)
