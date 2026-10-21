"""Status-bar loading panel: what is happening, how far, how long, and Cancel."""

from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QWidget,
)

from sansdir.viewer.cube import STAGE_LOADING, STAGE_PREVIEW
from sansdir.viewer.qt.loader import STAGE_CACHE_READ, STAGE_CACHE_WRITE

ETA_MIN_SECONDS = 1.0  # don't guess a finish time from less than this…
ETA_MIN_FRACTION = 0.03  # …or from less than this much of the run


def format_count(n: float) -> str:
    """``7.67e9`` → ``7.67 G``; ``745353`` → ``745 k``."""
    for scale, unit in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if n >= scale:
            value = n / scale
            return f"{value:.2f} {unit}" if value < 10 else f"{value:.0f} {unit}"
    return f"{n:.0f}"


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"


def eta_seconds(done: float, total: float, elapsed: float) -> float | None:
    """Remaining time at the current rate, once there is enough to go on."""
    if total <= 0 or done <= 0 or elapsed < ETA_MIN_SECONDS or done / total < ETA_MIN_FRACTION:
        return None
    return (total - done) * elapsed / done


class LoadProgress(QWidget):
    """``[stage text] [=====  37%] [Cancel]``; hidden when nothing is loading."""

    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.label = QLabel()
        self.bar = QProgressBar()
        self.bar.setFixedWidth(180)
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p%")
        self.cancel = QToolButton()
        self.cancel.setText("Cancel")
        self.cancel.setToolTip("Stop loading (Esc)")
        self.cancel.clicked.connect(self.cancel_requested.emit)
        divider = QFrame()  # keeps the stage text apart from the info label
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.addWidget(divider)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addWidget(self.cancel)
        self._stage = ""
        self._stage_start = 0.0
        self.percent: int | None = None
        self.hide()

    def start(self, name: str) -> None:
        self._stage = ""
        self._busy(f"Opening {name}…")
        self.show()

    def finish(self) -> None:
        self.percent = None
        self.hide()

    def _busy(self, text: str) -> None:
        """No numbers to show: a moving bar plus what we are waiting for."""
        self.percent = None
        self.bar.setRange(0, 0)
        self.label.setText(text)

    def update_stage(self, stage: str, done: float, total: float) -> None:
        if stage != self._stage:
            self._stage = stage
            self._stage_start = time.perf_counter()
        if stage == STAGE_CACHE_READ:
            self._busy("Reading cached histogram…")
        elif stage == STAGE_CACHE_WRITE:
            self._busy("Saving to cache — next open is instant…")
        elif stage == STAGE_PREVIEW:
            self._busy(f"Preview: sampling {format_count(total)} events…")
        elif stage == STAGE_LOADING:
            fraction = done / total if total else 1.0
            self.percent = int(fraction * 100)
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(fraction * 1000))
            text = f"Loading {format_count(done)} / {format_count(total)} events"
            eta = eta_seconds(done, total, time.perf_counter() - self._stage_start)
            if eta is not None:
                text += f" · ~{format_duration(eta)} left"
            self.label.setText(text)
