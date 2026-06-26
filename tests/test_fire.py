import random

from telnet_server import FireState, step_fire


def test_firestate_dimensions():
    state = FireState(cols=10, rows=4)
    assert state.cols == 10
    assert state.rows == 4
    assert state.height == 8
    assert len(state.heat) == 80
    assert set(state.heat) == {0}


def test_step_heats_bottom_row_and_stays_in_range():
    random.seed(0)
    state = FireState(cols=8, rows=3)  # height 6
    step_fire(state, cooling=18)
    bottom = state.heat[(state.height - 1) * state.cols :]
    assert all(230 <= v <= 255 for v in bottom)
    assert all(0 <= v <= 255 for v in state.heat)


def test_step_is_deterministic_under_seed():
    random.seed(42)
    a = FireState(cols=6, rows=3)
    step_fire(a, cooling=12)
    random.seed(42)
    b = FireState(cols=6, rows=3)
    step_fire(b, cooling=12)
    assert a.heat == b.heat


def test_flames_cool_toward_the_top():
    random.seed(1)
    state = FireState(cols=12, rows=5)
    for _ in range(30):  # let the fire establish
        step_fire(state, cooling=18)
    top_row_avg = sum(state.heat[: state.cols]) / state.cols
    bottom_row_avg = sum(state.heat[(state.height - 1) * state.cols :]) / state.cols
    assert top_row_avg < bottom_row_avg
