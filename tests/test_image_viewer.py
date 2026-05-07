"""Image viewer (``Enter``-on-image flow)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sansdir.plot import image as image_mod


@pytest.fixture(autouse=True)
def headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sansdir.plot import backend

    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


def _write_png(path: Path) -> Path:
    import matplotlib.image as mpimg

    arr = (np.random.default_rng(0).random((8, 12, 3)) * 255).astype("uint8")
    mpimg.imsave(path, arr)
    return path


def test_is_image_recognises_common_extensions(tmp_path: Path) -> None:
    assert image_mod.is_image(tmp_path / "x.png")
    assert image_mod.is_image(tmp_path / "x.JPG")
    assert image_mod.is_image(tmp_path / "x.tiff")
    assert not image_mod.is_image(tmp_path / "x.txt")
    assert not image_mod.is_image(tmp_path / "x.svg")  # vector, not raster


def test_make_image_figure_renders_imshow(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    f = _write_png(tmp_path / "demo.png")
    fig = image_mod.make_image_figure(f)
    ax = fig.axes[0]
    assert len(list(ax.get_images())) == 1
    assert ax.get_title() == "demo.png"
    plt.close(fig)


def test_plot_image_headless_writes_png(tmp_path: Path) -> None:
    f = _write_png(tmp_path / "demo.png")
    out, _info = image_mod.plot_image([f])
    assert out is not None
    assert out.exists()


# ---------------------------------------------------------------------------
# Smart-Enter — directory cd vs image plot vs everything else
# ---------------------------------------------------------------------------


async def test_enter_on_image_dispatches_plot_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pressing Enter on a *.png cursor row routes through ``plot.image``."""
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory

    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    _write_png(left / "demo.png")
    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )
    seen: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    real_dispatch = app.registry.dispatch

    async def spy(name: str, /, **kwargs):  # type: ignore[no-untyped-def]
        seen.append((name, dict(kwargs)))
        if name == "plot.image":
            return None  # short-circuit; no need to spawn matplotlib
        return await real_dispatch(name, **kwargs)

    monkeypatch.setattr(app.registry, "dispatch", spy)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor lands on the lone file (skip the ``..`` row).
        await pilot.press("down")
        await pilot.pause()
        assert app.active_panel.cursor_path is not None
        assert app.active_panel.cursor_path.name == "demo.png"
        await pilot.press("enter")
        await pilot.pause()
        # Smart-Enter detected the image and dispatched ``plot.image``.
        names = [n for n, _ in seen]
        assert "plot.image" in names
        await pilot.press("q")


async def test_enter_on_directory_still_cds(tmp_path: Path) -> None:
    """Smart-Enter must not regress the classic dir-into behaviour."""
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory

    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    sub = left / "child"
    sub.mkdir()
    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert app.active_panel.cursor_path == sub
        await pilot.press("enter")
        await pilot.pause()
        assert app.active_panel.cwd == sub
        await pilot.press("q")
