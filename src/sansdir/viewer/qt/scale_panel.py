"""Colour-scale side panel: Log/Lin, Min/Max in counts, Auto, Lock, Reset, colour map."""

from __future__ import annotations

import math

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sansdir.viewer.colorscale import COLORMAPS, LOG_FLOOR, ScaleState

MAX_COUNTS = 1e15
LOG_WHEEL_STEPS_PER_DECADE = 10
_SUFFIX = {"k": 1e3, "m": 1e6, "g": 1e9}


class CountBox(QDoubleSpinBox):
    """A count limit. Accepts ``1500``, ``1.5e3`` or ``1.5k``; Enter applies.

    The mouse wheel / arrow keys step it x10^0.1 in log mode (ten steps a
    decade) and by the leading decimal digit in linear mode.
    """

    def __init__(self, tip: str) -> None:
        super().__init__()
        self.log_steps = True
        self.setRange(0.0, MAX_COUNTS)
        self.setDecimals(3)
        self.setKeyboardTracking(False)  # valueChanged on Enter / focus out / step only
        self.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        self.setToolTip(tip)
        self.setMinimumWidth(90)

    def textFromValue(self, value: float) -> str:  # noqa: N802 — Qt override
        return f"{value:.6g}"

    def valueFromText(self, text: str) -> float:  # noqa: N802 — Qt override
        value = parse_count(text)
        return self.value() if value is None else value

    def validate(self, text: str, pos: int) -> object:
        state = (
            QValidator.State.Acceptable
            if parse_count(text) is not None
            else QValidator.State.Intermediate
        )
        return state, text, pos

    def stepBy(self, steps: int) -> None:  # noqa: N802 — Qt override
        if not self.log_steps:
            super().stepBy(steps)
            return
        start = max(self.value(), LOG_FLOOR)
        self.setValue(start * 10.0 ** (steps / LOG_WHEEL_STEPS_PER_DECADE))


def parse_count(text: str) -> float | None:
    """``"1,500"`` / ``"1.5e3"`` / ``"1.5k"`` → 1500.0; ``None`` if not a count."""
    text = text.strip().replace(",", "").replace("_", "")
    scale = 1.0
    if text and text[-1].lower() in _SUFFIX:
        scale = _SUFFIX[text[-1].lower()]
        text = text[:-1]
    try:
        value = float(text) * scale
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0 or value > MAX_COUNTS:
        return None
    return value


class ScalePanel(QWidget):
    """Shows a :class:`ScaleState`; reports what the user changes.

    The main window owns the state and the image: it handles these
    signals, updates the state and calls :meth:`show_state` back.
    """

    log_toggled = Signal(bool)
    limits_edited = Signal(float, float)  # vmin, vmax in counts
    auto_clicked = Signal()
    reset_clicked = Signal()
    lock_toggled = Signal(bool)
    percentiles_edited = Signal(float, float)
    cmap_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.log_button = QPushButton("Log scale")
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("Log / linear colour scale  (L)")
        self.log_button.toggled.connect(self.log_toggled)

        self.max_box = CountBox("Upper limit in counts — type and press Enter, or scroll")
        self.min_box = CountBox("Lower limit in counts — type and press Enter, or scroll")
        self.max_box.valueChanged.connect(self._on_limit)
        self.min_box.valueChanged.connect(self._on_limit)

        self.auto_button = QPushButton("Auto")
        self.auto_button.setToolTip("Limits from percentiles of the image (zeros left out)")
        self.auto_button.clicked.connect(self.auto_clicked)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Limits = full data range")
        self.reset_button.clicked.connect(self.reset_clicked)

        self.plo_box = _percent_box("Auto: lower percentile")
        self.phi_box = _percent_box("Auto: upper percentile")
        self.plo_box.valueChanged.connect(self._on_percentiles)
        self.phi_box.valueChanged.connect(self._on_percentiles)

        self.lock_box = QCheckBox("Lock limits")
        self.lock_box.setToolTip(
            "Keep Min/Max while the TOF range changes, to compare slices.\n"
            "Off: every slice is auto-scaled. Typing or dragging a limit locks it."
        )
        self.lock_box.toggled.connect(self.lock_toggled)

        self.cmap_box = QComboBox()
        self.cmap_box.addItems(list(COLORMAPS))
        self.cmap_box.currentTextChanged.connect(self.cmap_changed)

        limits = QFormLayout()
        limits.addRow("Max", self.max_box)
        limits.addRow("Min", self.min_box)
        buttons = QHBoxLayout()
        buttons.addWidget(self.auto_button)
        buttons.addWidget(self.reset_button)
        percent = QHBoxLayout()
        percent.addWidget(QLabel("Auto"))
        percent.addWidget(self.plo_box)
        percent.addWidget(QLabel("-"))
        percent.addWidget(self.phi_box)

        group = QGroupBox("Colour scale")
        inner = QVBoxLayout(group)
        inner.addWidget(self.log_button)
        inner.addLayout(limits)
        inner.addLayout(buttons)
        inner.addLayout(percent)
        inner.addWidget(self.lock_box)
        inner.addWidget(QLabel("Colour map"))
        inner.addWidget(self.cmap_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)
        layout.addStretch(1)
        self.setFixedWidth(210)

    def show_state(self, state: ScaleState) -> None:
        """Display ``state`` without emitting anything."""
        widgets = (
            self.log_button,
            self.max_box,
            self.min_box,
            self.plo_box,
            self.phi_box,
            self.lock_box,
            self.cmap_box,
        )
        blockers = [QSignalBlocker(w) for w in widgets]
        try:
            self.log_button.setChecked(state.log)
            self.log_button.setText("Log scale" if state.log else "Linear scale")
            for box in (self.min_box, self.max_box):
                box.log_steps = state.log
            self.max_box.setValue(state.vmax)
            self.min_box.setValue(state.vmin)
            self.plo_box.setValue(state.percentiles[0])
            self.phi_box.setValue(state.percentiles[1])
            self.lock_box.setChecked(state.locked)
            self.cmap_box.setCurrentText(state.cmap)
        finally:
            for blocker in blockers:
                blocker.unblock()

    def _on_limit(self) -> None:
        self.limits_edited.emit(self.min_box.value(), self.max_box.value())

    def _on_percentiles(self) -> None:
        self.percentiles_edited.emit(self.plo_box.value(), self.phi_box.value())


def _percent_box(tip: str) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.0, 100.0)
    box.setDecimals(1)
    box.setSingleStep(0.5)
    box.setSuffix(" %")
    box.setKeyboardTracking(False)
    box.setToolTip(tip)
    return box
