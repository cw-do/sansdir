"""Small dialogs for the mask tools: dead/hot threshold, bank/tube spec."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QInputDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from sansdir.viewer.masking import threshold_cells

SPEC_HELP = (
    "Mask whole tubes by number. Separate entries with spaces or commas.\n\n"
    "  t<N>   display column N (the x readout), 0-191:   t50   t10-15\n"
    "  b<N>   DAS block N, counted from 0 (0-47) — the raw file's\n"
    "         bank<N+1>_events, NOT Mantid's bank numbers:   b3   b5-7\n\n"
    "Each run of columns becomes an editable rectangle."
)


class ThresholdDialog(QDialog):
    """Mask dead (counts ≤ low) and/or hot (counts ≥ high) pixels of the current image."""

    def __init__(self, image: np.ndarray, tof_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mask dead / hot pixels")
        self.image = image
        positive = image[image > 0]
        top = float(positive.max()) if positive.size else 1.0

        self.low_box = QCheckBox("Dead: counts ≤")
        self.low_box.setChecked(True)
        self.low = _count_box(0.0)
        self.high_box = QCheckBox("Hot: counts ≥")
        self.high = _count_box(top)
        self.count = QLabel()
        for widget in (self.low_box, self.high_box):
            widget.toggled.connect(self._update)
        for box in (self.low, self.high):
            box.valueChanged.connect(self._update)

        grid = QGridLayout()
        grid.addWidget(self.low_box, 0, 0)
        grid.addWidget(self.low, 0, 1)
        grid.addWidget(self.high_box, 1, 0)
        grid.addWidget(self.high, 1, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Mask")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Counts in the image on screen ({tof_text})."))
        layout.addLayout(grid)
        layout.addWidget(self.count)
        layout.addWidget(buttons)
        self._update()

    def limits(self) -> tuple[float | None, float | None]:
        low = self.low.value() if self.low_box.isChecked() else None
        high = self.high.value() if self.high_box.isChecked() else None
        return low, high

    def _update(self) -> None:
        low, high = self.limits()
        n = int(threshold_cells(self.image, low=low, high=high).sum())
        self.count.setText(f"{n:,} pixels match")


def _count_box(value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.0, 1e15)
    box.setDecimals(2)
    box.setValue(value)
    box.setKeyboardTracking(False)
    return box


def ask_spec(parent: QWidget, previous: str = "") -> str | None:
    """The ``b3 t10-12`` spec, or ``None`` if cancelled."""
    text, ok = QInputDialog.getText(parent, "Mask tubes", SPEC_HELP, text=previous)
    return text if ok else None
