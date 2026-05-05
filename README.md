# sansdir

A fast, keyboard-driven terminal file manager for Small-Angle Neutron Scattering
(SANS) data on the ORNL analysis cluster. Inspired by the DOS-era **MDIR**.

> **Status**: pre-alpha. Under active construction. See
> [`TASKS.md`](./TASKS.md) for current phase.

---

## Why

SANS users on the analysis cluster spend a lot of time:

- Hopping between `IPTS-*` directories
- Quickly plotting `*Iq.dat`, `*Iqxqy.dat`, `*trans*.txt` to triage runs
- Peeking at NeXus metadata (shear, temperature, …) across many runs
- Zipping a result set to email to a collaborator

GUI tools require X11 forwarding and feel sluggish over SSH. `sansdir` runs in
any terminal, has no display-server requirement, and gives sub-second response.

---

## Features (target)

- **Dual-pane** MDIR / Norton-style file browser with tag-based selection
- F5/F6 copy/move from active pane → opposite pane (the classic MDIR workflow)
- Direct path entry, fuzzy folder browser, OnCat IPTS keyword search
- Folder & file ops: create / rename / copy / move / delete / zip / mail
- 1D plotting for 2/3/4-column `*Iq.dat` in a real **matplotlib window** (log/lin axes)
- Transmission plotting for `*trans*.txt` (wavelength axis)
- 2D plotting for 4/6-column `*Iqxqy.dat`, including multi-file tile mode with shared/independent colorbars
- NeXus `.nxs.h5` total-detector heatmap
- HDF5 metadata inspector + batch extraction across many runs to TSV/CSV
- *(planned, optional)* **Natural-language layer** — type `\ plot the I(q) of all the trans-corrected runs` and the LLM translates to a sequence of registered commands for you to confirm

---

## Install (development)

```bash
git clone <repo-url> sansdir
cd sansdir
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sansdir version
```

Python 3.10+ required.

---

## Run

```bash
sansdir              # opens TUI in current directory
sansdir /SNS/EQSANS  # opens at specific path
sansdir extract --keys DASlogs/temperature/value *.nxs.h5  # batch metadata, no TUI
```

---

## Configuration

Default config is written to `~/.config/sansdir/config.toml` on first run.
Edit it to customize themes, key bindings, default plot backend, OnCat
instrument, etc. See [`PLANNING.md`](./PLANNING.md) §9.

---

## Project documents

- [`CLAUDE.md`](./CLAUDE.md) — instructions for the AI coding agent
- [`PLANNING.md`](./PLANNING.md) — architecture & data formats
- [`TASKS.md`](./TASKS.md) — phased implementation checklist

---

## Author

Changwoo Do — Neutron Scattering Division, Oak Ridge National Laboratory
(`doc1@ornl.gov`).

## License

TBD.

