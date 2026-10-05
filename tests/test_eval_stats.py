"""Compatibility rules for evaluation statistics shared by the legacy reports."""

from collections.abc import Callable

import numpy as np
import pytest

from twin.evals.stats import (
    BOOTSTRAP_ROUNDS,
    bootstrap_grouped,
    bootstrap_numpy_percentile_batched,
    bootstrap_numpy_percentile_min_two,
    bootstrap_numpy_percentile_single_group,
    bootstrap_numpy_percentile_stratified,
    bootstrap_random_order_statistic,
    mcnemar_exact_p,
    wilson_upper_95,
)

VALUES = [0.1, -0.4, 0.2, 0.9, 1.3, 0.45, 0.72, -0.21, 0.33, 0.18, 0.59, 0.87, 0.61, 0.97, 0.44, -0.15, 0.82]


def test_grouped_bootstrap_requires_two_nonempty_groups() -> None:
    assert bootstrap_grouped({}, "s") is None
    assert bootstrap_grouped({"a": [0.5]}, "s") is None
    assert bootstrap_grouped({"a": [0.5], "b": []}, "s") is None
    assert bootstrap_grouped({"a": [0.5], "b": [0.5]}, "s") == (0.5, 0.5)


def test_grouped_bootstrap_determinism_and_mapping_order() -> None:
    groups = {"a": [0.0, 1.0], "b": [0.25], "c": [0.5, 0.75, 1.0]}
    expected = bootstrap_grouped(groups, "种子")
    assert expected is not None
    assert bootstrap_grouped(groups, "种子") == expected
    assert bootstrap_grouped(dict(reversed(list(groups.items()))), "种子") == expected


def test_grouped_bootstrap_weights_by_drawn_case_count() -> None:
    import hashlib

    groups = {"a": [0.0] * 2, "b": [0.5], "c": [1.0] * 7}
    rng = np.random.default_rng(int(hashlib.sha256(b"weighted").hexdigest()[:16], 16))
    values = list(groups.values())
    means = []
    for _ in range(BOOTSTRAP_ROUNDS):
        drawn = [v for i in rng.integers(0, len(values), size=len(values)) for v in values[i]]
        means.append(sum(drawn) / len(drawn))
    lo, hi = np.percentile(means, [2.5, 97.5])
    assert bootstrap_grouped(groups, "weighted") == (float(lo), float(hi))


def test_correlated_group_bootstrap_is_wider_than_independent_cases() -> None:
    groups = {"a": [0.0] * 40, "b": [1.0] * 40}
    grouped = bootstrap_grouped(groups, "s")
    independent = bootstrap_numpy_percentile_min_two([*groups["a"], *groups["b"]], "s")
    assert grouped is not None and independent is not None
    assert grouped == (0.0, 1.0)
    assert grouped[0] < independent[0] < independent[1] < grouped[1]


def test_batched_bootstrap_small_samples() -> None:
    assert bootstrap_numpy_percentile_batched([], 1234) is None
    assert bootstrap_numpy_percentile_batched([0.5], 1234) == (0.5, 0.5)


def test_persona_bootstrap_requires_two_samples() -> None:
    assert bootstrap_numpy_percentile_min_two([], "s") is None
    assert bootstrap_numpy_percentile_min_two([0.5], "s") is None
    assert bootstrap_numpy_percentile_min_two([0.5, 0.5], "s") == (0.5, 0.5)


def test_single_group_bootstrap_small_samples() -> None:
    assert bootstrap_numpy_percentile_single_group([], "s") is None
    assert bootstrap_numpy_percentile_single_group([0.5], "s") == (0.5, 0.5)


def test_stratified_bootstrap_small_samples_and_equal_group_weight() -> None:
    assert bootstrap_numpy_percentile_stratified([], "s") is None
    assert bootstrap_numpy_percentile_stratified([[], []], "s") is None
    assert bootstrap_numpy_percentile_stratified([[], [0.5]], "s") == (0.5, 0.5)
    assert bootstrap_numpy_percentile_stratified([[1.0] * 12, [], [0.0] * 8], "s") == (0.5, 0.5)


def test_random_bootstrap_small_samples() -> None:
    with pytest.raises(ZeroDivisionError):
        bootstrap_random_order_statistic([], "s")
    assert bootstrap_random_order_statistic([0.5], "s") == (0.5, 0.5)


@pytest.mark.parametrize(
    ("bootstrap", "expected"),
    [
        (bootstrap_numpy_percentile_min_two, (0.25230882352941175, 0.6623676470588234)),
        (bootstrap_numpy_percentile_single_group, (0.25230882352941175, 0.6623676470588234)),
        (bootstrap_random_order_statistic, (0.24882352941176472, 0.6723529411764706)),
    ],
)
def test_string_seed_bootstrap_determinism_and_percentile_rule(
    bootstrap: Callable[[list[float], str], tuple[float, float] | None], expected: tuple[float, float]
) -> None:
    assert bootstrap(VALUES, "种子") == expected
    assert bootstrap(VALUES, "种子") == expected


def test_batched_bootstrap_determinism_and_percentile_rule() -> None:
    expected = (0.22877941176470584, 0.6676617647058822)
    assert bootstrap_numpy_percentile_batched(VALUES, 1234) == expected
    assert bootstrap_numpy_percentile_batched(VALUES, 1234) == expected


def test_batched_bootstrap_crosses_the_cell_limit() -> None:
    values = [i / 501 for i in range(501)]
    assert bootstrap_numpy_percentile_batched(values, 1234) == (0.4739569762670268, 0.5247536862402937)


def test_stratified_bootstrap_determinism_and_percentile_rule() -> None:
    groups = [[0.0, 1.0], [0.25, 0.5, 1.0]]
    expected = (0.16666666666666666, 0.9166666666666667)
    assert bootstrap_numpy_percentile_stratified(groups, "s") == expected
    assert bootstrap_numpy_percentile_stratified(groups, "s") == expected


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [(0, 0, 1.0), (1, 0, 1.0), (4, 0, 0.125), (5, 1, 0.21875), (3, 3, 1.0)],
)
def test_mcnemar_exact_values(first: int, second: int, expected: float) -> None:
    assert mcnemar_exact_p(first, second) == expected
    assert mcnemar_exact_p(second, first) == expected


def test_wilson_empty_sample() -> None:
    assert wilson_upper_95(None, 0) is None


@pytest.mark.parametrize(
    ("error_rate", "n", "expected"),
    [(0.0, 20, 0.16112515805281938), (0.2, 20, 0.41601743225189364), (1.0, 20, 1.0), (0.5, 100, 0.5961684696340044)],
)
def test_wilson_known_bounds(error_rate: float, n: int, expected: float) -> None:
    assert wilson_upper_95(error_rate, n) == pytest.approx(expected, abs=1e-15)
