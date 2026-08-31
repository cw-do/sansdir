"""Registry-level tests for the USANS commands.

Dispatch goes through :class:`~sansdir.commands.registry.CommandRegistry`
against the in-memory ``FakeApp`` — no Textual, no OnCat, no engine. Where
a real ``reduceUSANS`` would run, a stub shell script stands in.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from sansdir.commands.builtins import build_default_registry
from tests.test_phase1_commands import FakeApp, FakePanel, bind_registry
from tests.usans.conftest import FakeRun, write_arn


@pytest.fixture
def app(tmp_path: Path) -> FakeApp:
    left = tmp_path / "work"
    right = tmp_path / "other"
    left.mkdir()
    right.mkdir()
    return FakeApp(
        left=FakePanel(cwd=left),
        right=FakePanel(cwd=right),
        instrument="USANS",
    )


def _stub_engine(tmp_path: Path, body: str = "exit 0\n") -> Path:
    script = tmp_path / "stub-reduceUSANS"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _config(tmp_path: Path, monkeypatch, **usans: object) -> None:
    """Point $SANSDIR_CONFIG at a throwaway TOML with a [usans] section."""
    body = "[usans]\n" + "".join(
        f"{k} = {v!r}\n" if isinstance(v, str) else f"{k} = {str(v).lower()}\n"
        for k, v in usans.items()
    )
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("SANSDIR_CONFIG", str(path))


# ---------------------------------------------------------------------------
# instrument.set
# ---------------------------------------------------------------------------


async def test_instrument_set_switches_mode(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    assert await reg.dispatch("instrument.set", name="usans") == "USANS"
    assert app.instrument_mode == "USANS"
    assert await reg.dispatch("instrument.set", name="eqsans") == "EQSANS"
    assert app.instrument_mode == "SANS"


async def test_instrument_set_without_a_name_reports_the_current_one(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    assert await reg.dispatch("instrument.set") == "USANS (USANS mode)"


async def test_instrument_set_warns_on_an_unknown_instrument(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("instrument.set", name="NOPE")
    assert any("not a name sansdir knows" in n for n in app.notifications)


async def test_instrument_alias_is_registered(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    assert reg.get("instrument").name == "instrument.set"


# ---------------------------------------------------------------------------
# usans.init_table
# ---------------------------------------------------------------------------


async def test_init_table_writes_csv_and_note(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)

    written = await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))

    csv_path = Path(written)
    assert csv_path == app.left.cwd / "IPTS-1_setup.csv"
    assert csv_path.is_file()
    note = app.left.cwd / "IPTS-1_NOTE.md"
    assert note.is_file()
    body = csv_path.read_text(encoding="utf-8")
    assert "b,emptyBanjo,1003,4,0.1" in body
    assert "alignment" not in body, "pre-start block must not reach the CSV"
    assert "Transmission runs" in note.read_text(encoding="utf-8")


async def test_init_table_respects_out_dir(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)
    target = tmp_path / "elsewhere"

    written = await reg.dispatch(
        "usans.init_table", start_run=1003, out_dir=str(target), data_dir=str(data_dir_5x)
    )
    assert Path(written).parent == target


async def test_init_table_refreshes_both_panes(
    app: FakeApp, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)
    before = (app.left.refresh_count, app.right.refresh_count)
    await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))
    assert (app.left.refresh_count, app.right.refresh_count) > before


async def test_init_table_reads_the_ipts_from_the_pane_path(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat
) -> None:
    """No catalog needed: sitting in IPTS-37679/shared is enough."""
    shared = tmp_path / "IPTS-37679" / "shared"
    shared.mkdir(parents=True)
    app.left.cwd = shared
    stub_oncat.runs = runs_5x
    reg = build_default_registry(app=app)

    written = await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))

    assert stub_oncat.calls == [("IPTS-37679", "USANS")]
    assert Path(written) == shared / "IPTS-37679_setup.csv"


async def test_init_table_shows_the_fetched_catalog_on_the_right_pane(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat
) -> None:
    shared = tmp_path / "IPTS-37679" / "shared"
    shared.mkdir(parents=True)
    app.left.cwd = shared
    stub_oncat.runs = runs_5x
    reg = build_default_registry(app=app)

    await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))

    assert app.catalog is not None
    assert app.catalog[0] == "IPTS-37679"
    assert app.catalog_instrument == "USANS"


async def test_init_table_reuses_a_loaded_catalog_without_refetching(
    app: FakeApp, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat
) -> None:
    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)

    await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))

    assert stub_oncat.calls == [], "the loaded run list should have been reused"


async def test_init_table_prefers_the_pane_path_over_a_stale_catalog(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat
) -> None:
    """The CSV lands in the cwd, so the cwd's IPTS is the one that counts."""
    shared = tmp_path / "IPTS-37679" / "shared"
    shared.mkdir(parents=True)
    app.left.cwd = shared
    app.catalog = ("IPTS-11111", runs_5x)
    stub_oncat.runs = runs_5x
    reg = build_default_registry(app=app)

    written = await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))

    assert stub_oncat.calls == [("IPTS-37679", "USANS")]
    assert Path(written).name == "IPTS-37679_setup.csv"


async def test_init_table_gives_up_when_no_ipts_can_be_found(app: FakeApp, stub_oncat) -> None:
    """No IPTS in the path, no catalog, and nobody to prompt -> stop."""
    reg = build_default_registry(app=app)
    assert await reg.dispatch("usans.init_table", start_run=1) is None
    assert stub_oncat.calls == []


async def test_init_table_reports_an_empty_oncat_result(
    app: FakeApp, tmp_path: Path, stub_oncat
) -> None:
    shared = tmp_path / "IPTS-37679" / "shared"
    shared.mkdir(parents=True)
    app.left.cwd = shared
    stub_oncat.runs = []
    reg = build_default_registry(app=app)

    assert await reg.dispatch("usans.init_table", start_run=1) is None
    assert any("no USANS runs" in n for n in app.notifications)


async def test_init_table_asks_before_overwriting(
    app: FakeApp, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)
    existing = app.left.cwd / "IPTS-1_setup.csv"
    existing.write_text("DO NOT CLOBBER\n", encoding="utf-8")
    app.confirm_response = False

    assert await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x)) is None
    assert existing.read_text(encoding="utf-8") == "DO NOT CLOBBER\n"
    assert app.confirm_messages


async def test_init_table_surfaces_warnings(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun]
) -> None:
    """No data dir → the CSV is unverified, and the user is told so."""
    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)
    await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(tmp_path / "missing"))
    assert any("unverified" in n for n in app.notifications)


# ---------------------------------------------------------------------------
# usans.reduce
# ---------------------------------------------------------------------------


def _good_csv(app: FakeApp, data_dir: Path) -> Path:
    path = app.left.cwd / "IPTS-1_setup.csv"
    path.write_text(
        "# USANS reduction table for IPTS-1\nb,E,100,4,0.1\ns,S0,104,4,0.1\n",
        encoding="utf-8",
    )
    write_arn(data_dir, [*range(100, 108)])
    return path


async def test_reduce_runs_the_engine_and_reports_the_output(
    app: FakeApp, tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "autoreduce"
    csv = _good_csv(app, data_dir)
    engine = _stub_engine(tmp_path, 'echo done > "$3/UN_S0_det_1_lb.txt"\n')
    _config(tmp_path, monkeypatch, reduce_command=str(engine))
    reg = build_default_registry(app=app)
    out = tmp_path / "output"

    result = await reg.dispatch(
        "usans.reduce", path=str(csv), data_dir=str(data_dir), output_dir=str(out)
    )

    assert result == str(out)
    assert (out / "UN_S0_det_1_lb.txt").is_file()
    assert any("reduced 1 curves" in n for n in app.notifications)


async def test_reduce_offers_to_show_the_output_in_the_other_pane(
    app: FakeApp, tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "autoreduce"
    csv = _good_csv(app, data_dir)
    _config(tmp_path, monkeypatch, reduce_command=str(_stub_engine(tmp_path)))
    reg = build_default_registry(app=app)
    out = tmp_path / "output"

    await reg.dispatch("usans.reduce", path=str(csv), data_dir=str(data_dir), output_dir=str(out))
    assert app.right.cwd == out


async def test_reduce_uses_the_cursor_when_no_path_is_given(
    app: FakeApp, tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "autoreduce"
    app.left.cursor_path = _good_csv(app, data_dir)
    _config(tmp_path, monkeypatch, reduce_command=str(_stub_engine(tmp_path)))
    reg = build_default_registry(app=app)

    result = await reg.dispatch(
        "usans.reduce", data_dir=str(data_dir), output_dir=str(tmp_path / "out")
    )
    assert result is not None


async def test_reduce_refuses_a_table_without_a_background(
    app: FakeApp, tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "autoreduce"
    write_arn(data_dir, [100])
    csv = app.left.cwd / "bad.csv"
    csv.write_text("s,S0,100,4,0.1\n", encoding="utf-8")
    _config(tmp_path, monkeypatch, reduce_command=str(_stub_engine(tmp_path, "exit 9\n")))
    reg = build_default_registry(app=app)

    assert (
        await reg.dispatch(
            "usans.reduce", path=str(csv), data_dir=str(data_dir), output_dir=str(tmp_path / "o")
        )
        is None
    )
    assert any("no background row" in n for n in app.notifications)


# ---------------------------------------------------------------------------
# `r` with no setup table under the cursor -> offer to build one
# ---------------------------------------------------------------------------


def _in_ipts(app: FakeApp, tmp_path: Path) -> Path:
    shared = tmp_path / "IPTS-37679" / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    app.left.cwd = shared
    return shared


async def test_reduce_offers_to_generate_for_a_non_csv(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat, monkeypatch
) -> None:
    shared = _in_ipts(app, tmp_path)
    other = shared / "notes.txt"
    other.write_text("hello", encoding="utf-8")
    stub_oncat.runs = runs_5x
    _config(tmp_path, monkeypatch, data_dir_template=str(data_dir_5x))
    reg = bind_registry(app)

    written = await reg.dispatch("usans.reduce", path=str(other))

    assert Path(written) == shared / "IPTS-37679_setup.csv"
    assert Path(written).is_file()
    assert any("not a USANS setup table" in m for m in app.confirm_messages)


async def test_reduce_offers_to_generate_when_nothing_is_under_the_cursor(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat, monkeypatch
) -> None:
    _in_ipts(app, tmp_path)
    stub_oncat.runs = runs_5x
    _config(tmp_path, monkeypatch, data_dir_template=str(data_dir_5x))
    reg = bind_registry(app)

    assert await reg.dispatch("usans.reduce") is not None
    assert any("No setup table selected" in m for m in app.confirm_messages)


async def test_reduce_offers_to_generate_for_an_unrelated_csv(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat, monkeypatch
) -> None:
    """A .csv the cursor happened to land on is not a half-built table."""
    shared = _in_ipts(app, tmp_path)
    data = shared / "UN_S0_det_1_lb.csv"
    data.write_text("1e-4,12.0,0.3\n", encoding="utf-8")
    stub_oncat.runs = runs_5x
    _config(tmp_path, monkeypatch, data_dir_template=str(data_dir_5x))
    reg = bind_registry(app)

    assert await reg.dispatch("usans.reduce", path=str(data)) is not None


async def test_reduce_generates_but_does_not_reduce(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat, monkeypatch
) -> None:
    """The review gate: `r` stops after writing the table.

    The engine must not run — the NOTE's restart / block-size / background
    warnings are exactly what the second `r` is there to let you read first.
    """
    shared = _in_ipts(app, tmp_path)
    other = shared / "notes.txt"
    other.write_text("hello", encoding="utf-8")
    stub_oncat.runs = runs_5x
    engine = _stub_engine(tmp_path, f"touch {tmp_path / 'ENGINE_RAN'}\n")
    _config(tmp_path, monkeypatch, reduce_command=str(engine), data_dir_template=str(data_dir_5x))
    reg = bind_registry(app)

    await reg.dispatch("usans.reduce", path=str(other))

    assert not (tmp_path / "ENGINE_RAN").exists()
    assert any("press r again to reduce" in n for n in app.notifications)


async def test_reduce_shows_the_generated_table_in_the_other_pane(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat, monkeypatch
) -> None:
    shared = _in_ipts(app, tmp_path)
    stub_oncat.runs = runs_5x
    _config(tmp_path, monkeypatch, data_dir_template=str(data_dir_5x))
    reg = bind_registry(app)

    await reg.dispatch("usans.reduce")

    assert app.viewer_calls == [shared / "IPTS-37679_setup.csv"]


async def test_reduce_does_not_name_a_directory_in_the_offer(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat, monkeypatch
) -> None:
    """The cursor usually sits on ``..``; don't accuse a directory."""
    shared = _in_ipts(app, tmp_path)
    app.left.cursor_path = shared.parent
    stub_oncat.runs = runs_5x
    _config(tmp_path, monkeypatch, data_dir_template=str(data_dir_5x))
    reg = bind_registry(app)

    await reg.dispatch("usans.reduce")

    assert any("No setup table selected" in m for m in app.confirm_messages)
    assert not any("IPTS-37679 is not" in m for m in app.confirm_messages)


async def test_reduce_declining_the_offer_writes_nothing(
    app: FakeApp, tmp_path: Path, stub_oncat
) -> None:
    shared = _in_ipts(app, tmp_path)
    app.confirm_response = False
    reg = bind_registry(app)

    assert await reg.dispatch("usans.reduce") is None
    assert list(shared.iterdir()) == []
    assert stub_oncat.calls == []


async def test_reduce_does_not_offer_to_regenerate_a_broken_table(
    app: FakeApp, tmp_path: Path, monkeypatch
) -> None:
    """A real table that fails validation must be fixed, not clobbered.

    You are mid-edit; regenerating would throw the corrections away.
    """
    shared = _in_ipts(app, tmp_path)
    csv = shared / "IPTS-37679_setup.csv"
    csv.write_text("s,S0,100,4,0.1\ns,S1,104,4,0.1\n", encoding="utf-8")
    _config(tmp_path, monkeypatch, reduce_command=str(_stub_engine(tmp_path)))
    reg = bind_registry(app)

    assert await reg.dispatch("usans.reduce", path=str(csv)) is None
    assert any("no background row" in n for n in app.notifications)
    assert app.confirm_messages == [], "must not offer to regenerate"
    assert csv.read_text(encoding="utf-8").startswith("s,S0,100,4,0.1")


async def test_reduce_reports_a_failing_engine(app: FakeApp, tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "autoreduce"
    csv = _good_csv(app, data_dir)
    engine = _stub_engine(tmp_path, 'echo "FileNotFoundError: USANS_104_monitor" >&2\nexit 1\n')
    _config(tmp_path, monkeypatch, reduce_command=str(engine))
    reg = build_default_registry(app=app)

    assert (
        await reg.dispatch(
            "usans.reduce",
            path=str(csv),
            data_dir=str(data_dir),
            output_dir=str(tmp_path / "out"),
        )
        is None
    )
    assert any("exited 1" in n and "FileNotFoundError" in n for n in app.notifications)


async def test_reduce_reports_a_missing_engine(app: FakeApp, tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "autoreduce"
    csv = _good_csv(app, data_dir)
    _config(
        tmp_path,
        monkeypatch,
        pixi_manifest=str(tmp_path / "nowhere"),
    )
    monkeypatch.setattr("shutil.which", lambda _name: None)
    reg = build_default_registry(app=app)

    assert (
        await reg.dispatch(
            "usans.reduce",
            path=str(csv),
            data_dir=str(data_dir),
            output_dir=str(tmp_path / "out"),
        )
        is None
    )
    assert any("not found" in n for n in app.notifications)


async def test_reduce_passes_logbin_through(app: FakeApp, tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "autoreduce"
    csv = _good_csv(app, data_dir)
    # The stub records its own argv so we can assert on the -l flag.
    engine = _stub_engine(tmp_path, f'echo "$@" > {tmp_path / "argv.txt"}\n')
    _config(tmp_path, monkeypatch, reduce_command=str(engine))
    reg = build_default_registry(app=app)

    await reg.dispatch(
        "usans.reduce",
        path=str(csv),
        data_dir=str(data_dir),
        output_dir=str(tmp_path / "out"),
        logbin=False,
    )
    assert "-l" not in (tmp_path / "argv.txt").read_text(encoding="utf-8").split()

    await reg.dispatch(
        "usans.reduce",
        path=str(csv),
        data_dir=str(data_dir),
        output_dir=str(tmp_path / "out"),
        logbin=True,
    )
    assert "-l" in (tmp_path / "argv.txt").read_text(encoding="utf-8").split()


# ---------------------------------------------------------------------------
# Registry hygiene
# ---------------------------------------------------------------------------


async def test_usans_commands_are_not_registered_without_an_app() -> None:
    """The app-agnostic registry (schema export, cold start) stays minimal."""
    reg = build_default_registry(app=None)
    names = {c.name for c in reg.all()}
    assert "usans.reduce" not in names
    assert "usans.init_table" not in names


def test_usans_commands_are_registered_in_both_modes(app: FakeApp) -> None:
    """Switching to SANS must not unregister the USANS commands.

    Only the *keys* are mode-scoped; ``:usans reduce`` keeps working so a
    user who forgot to switch isn't met with "unknown command".
    """
    app.instrument = "EQSANS"
    names = {c.name for c in build_default_registry(app=app).all()}
    assert {"usans.init_table", "usans.reduce", "instrument.set"} <= names


def test_reduce_is_marked_dangerous(app: FakeApp) -> None:
    """It spawns an external process and writes files — the LLM layer must confirm."""
    assert build_default_registry(app=app).get("usans.reduce").danger


async def test_init_table_is_reachable_from_the_command_line(
    app: FakeApp, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    """``:usans-init 1003`` parses to the same dispatch the key does."""
    from sansdir.commands.parser import parse_command_line

    app.catalog = ("IPTS-1", runs_5x)
    reg = build_default_registry(app=app)
    cmd, kwargs = parse_command_line("usans-init 1003", reg)
    assert cmd.name == "usans.init_table"
    assert kwargs["start_run"] == 1003


async def test_init_table_writes_beside_the_file_pane_not_the_catalog(
    app: FakeApp, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    """Tabbing onto the catalog must not redirect the CSV.

    ``i`` cds the *file* pane into ``<IPTS>/shared`` and puts the catalog
    opposite it. Tabbing to the catalog makes that slot active, but its
    hidden FilePanel's cwd is incidental — the CSV belongs next to the
    directory the user actually navigated to.
    """
    app.catalog = ("IPTS-1", runs_5x)
    app.active_id = "right"
    app.active_slot_is_catalog = True
    reg = build_default_registry(app=app)

    written = await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))
    assert Path(written).parent == app.left.cwd


async def test_init_table_lands_the_cursor_on_the_new_csv(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat
) -> None:
    """The file just written is what F4 / r act on next."""
    shared = _in_ipts(app, tmp_path)
    app.left.cursor_path = shared.parent  # parked on ``..``
    stub_oncat.runs = runs_5x
    reg = build_default_registry(app=app)

    written = await reg.dispatch("usans.init_table", start_run=1003, data_dir=str(data_dir_5x))

    assert app.left.cursor_path == Path(written)


async def test_init_table_leaves_the_cursor_alone_when_writing_elsewhere(
    app: FakeApp, tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path, stub_oncat
) -> None:
    """out_dir pointing somewhere else must not move a cursor that can't follow."""
    _in_ipts(app, tmp_path)
    parked = app.left.cwd / "somefile.txt"
    parked.write_text("", encoding="utf-8")
    app.left.cursor_path = parked
    stub_oncat.runs = runs_5x
    reg = build_default_registry(app=app)

    await reg.dispatch(
        "usans.init_table",
        start_run=1003,
        out_dir=str(tmp_path / "elsewhere"),
        data_dir=str(data_dir_5x),
    )

    assert app.left.cursor_path == parked
