import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from chopper.audio import AudioData


def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp is not None:
        return
    # Separate runs also avoid sharing Windows temp directories with another user.
    root = (config.rootpath / ".artifacts" / "pytest").resolve()
    root.relative_to(config.rootpath.resolve())
    root.mkdir(parents=True, exist_ok=True)
    temporary = TemporaryDirectory(prefix="run-", dir=root)
    config.add_cleanup(temporary.cleanup)
    config.option.basetemp = str(Path(temporary.name) / "data")


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def audio():
    return AudioData(Path("test.wav"), np.zeros((1000, 2)), 1000, "PCM_24")
