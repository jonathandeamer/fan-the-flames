from importlib.metadata import version
from pathlib import Path


def test_module_imports():
    import telnet_server  # noqa: F401


def test_runtime_lock_matches_tested_telnetlib3():
    requirements = (Path(__file__).parent.parent / "requirements.txt").read_text().splitlines()
    pin = next(line for line in requirements if line.startswith("telnetlib3=="))
    assert pin == f"telnetlib3=={version('telnetlib3')}"
