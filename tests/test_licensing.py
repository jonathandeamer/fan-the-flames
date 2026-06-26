from pathlib import Path

SRC = Path("telnet_server.py").read_text()
README = Path("README.md").read_text()


def test_header_keeps_original_author_and_marks_modification():
    assert "Michael Lazar" in SRC  # original author retained (GPL)
    assert "Modified" in SRC  # modification notice present
    assert "2026" in SRC


def test_joan_stark_and_wave_credit_removed():
    assert "Joan Stark" not in SRC
    assert "Ride the Wave" not in SRC


def test_readme_states_fork_and_credits():
    assert "GPL" in README
    assert "ride-the-wave" in README  # links the upstream fork source
    assert "lavat" in README  # credits the technique
    assert "Fan the Flames" in README
