"""Shared pytest fixtures.

Most tests should use the synthetic fixtures defined here so the suite can
run anywhere (CI, laptop, cluster) without depending on the multi-hundred-MB
real NeXus files. The ``real_nexus_path`` fixture is provided for manual
smoke tests against an actual SNS file when one is present locally; it
auto-skips the test when the file is absent (which it always is in CI,
since ``tests/data/*.nxs.h5`` is gitignored).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

DATA_DIR: Path = Path(__file__).parent / "data"


@pytest.fixture
def synthetic_nexus(tmp_path: Path) -> Path:
    """A tiny synthetic NeXus file mimicking SNS conventions.

    Layout follows PLANNING.md §4.4:

    - ``/entry/instrument/bank{1,2}/data`` (16x16 uint32 pixel array)
    - ``/entry/instrument/bank{1,2}/total_counts`` (scalar)
    - ``/entry/DASlogs/{temperature,shear}/value`` (10-sample time series)
    - ``/entry/DASlogs/{temperature,shear}/time``
    - ``/entry/sample/name``

    The file lives under ``tmp_path`` so each test gets a fresh copy.
    Total size is a few KB — cheap to regenerate.
    """
    # h5py is a runtime dep; importing here keeps it out of the registry-test
    # import path, preserving the sub-300 ms cold start budget.
    import h5py

    rng = np.random.default_rng(seed=42)
    path = tmp_path / "EQSANS_synthetic.nxs.h5"
    with h5py.File(path, "w") as f:
        entry = f.create_group("entry")
        instrument = entry.create_group("instrument")
        for n in (1, 2):
            bank = instrument.create_group(f"bank{n}")
            data = rng.poisson(lam=10, size=(16, 16)).astype("uint32")
            bank.create_dataset("data", data=data)
            bank.create_dataset("total_counts", data=np.uint64(data.sum()))
        daslogs = entry.create_group("DASlogs")
        for name, mean, sigma in (("temperature", 298.15, 0.05), ("shear", 1.5, 0.01)):
            log = daslogs.create_group(name)
            values = rng.normal(loc=mean, scale=sigma, size=10).astype("float64")
            log.create_dataset("value", data=values)
            log.create_dataset("time", data=np.linspace(0.0, 600.0, 10))
        sample = entry.create_group("sample")
        sample.create_dataset("name", data=np.bytes_("synthetic-sample"))
    return path


@pytest.fixture
def iq_3col_path() -> Path:
    """Path to the bundled 3-col Iq fixture (small, committed to VCS)."""
    return DATA_DIR / "test_2o5m2o5a_Iq.dat"


@pytest.fixture
def iq_4col_path() -> Path:
    """Path to the bundled 4-col Iq fixture (small, committed to VCS)."""
    return DATA_DIR / "NG7_ORNL_B1_All_4col.dat"


@pytest.fixture
def real_nexus_path() -> Path:
    """Path to the real EQSANS NeXus fixture if present locally.

    Skips the test when absent — the file is gitignored due to size.
    """
    p = DATA_DIR / "EQSANS_172749.nxs.h5"
    if not p.exists():
        pytest.skip(
            "real EQSANS NeXus fixture not present (gitignored; "
            "see tests/data/README.md for how to obtain it)"
        )
    return p
