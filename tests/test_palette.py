from telnet_server import BG_PALETTE, FG_PALETTE, fire_rgb


def test_ramp_endpoints_and_stops():
    assert fire_rgb(0) == (0, 0, 0)  # coldest -> black
    assert fire_rgb(128) == (255, 0, 0)  # mid -> red
    assert fire_rgb(255) == (255, 255, 255)  # hottest -> white


def test_ramp_clamps_out_of_range():
    assert fire_rgb(-50) == (0, 0, 0)
    assert fire_rgb(999) == (255, 255, 255)


def test_palettes_have_256_entries_and_correct_escapes():
    assert len(FG_PALETTE) == 256
    assert len(BG_PALETTE) == 256
    assert FG_PALETTE[255] == "\x1b[38;2;255;255;255m"
    assert BG_PALETTE[0] == "\x1b[48;2;0;0;0m"
