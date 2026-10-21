"""Session metrics: vectorized alignment, whole-session CER, speech activity, DER, cpCER and speaker claims."""

import random

import pytest

from twin.evals.asr import edit_counts
from twin.evals.diarization import (
    Utterance,
    align_counts,
    align_tokens,
    attributed_counts,
    claim_outcome,
    cp_counts,
    diarization_error,
    edit_distance,
    majority_speaker,
    session_counts,
    speech_activity,
)


def test_align_counts_matches_edit_counts_on_random_strings() -> None:
    rng = random.Random(7)
    for _ in range(300):
        ref = rng.choices("abcd", k=rng.randint(0, 12))
        hyp = rng.choices("abcd", k=rng.randint(0, 12))
        assert align_counts(ref, hyp) == edit_counts(ref, hyp), (ref, hyp)
        assert edit_distance(ref, hyp) == sum(edit_counts(ref, hyp))


def test_align_counts_edges() -> None:
    assert align_counts([], []) == (0, 0, 0)
    assert align_counts(list("ab"), []) == (0, 2, 0)
    assert align_counts([], list("ab")) == (0, 0, 2)
    assert align_counts(list("今天开会"), list("今天开灰了")) == (1, 0, 1)


def test_align_tokens_marks_each_reference_token() -> None:
    substituted, deleted, inserted = align_tokens(list("今天开会吧"), list("今开灰吧了"))
    assert substituted == [False, False, False, True, False] and deleted == [False, True, False, False, False]
    assert inserted == 1
    assert align_tokens(list("ab"), []) == ([False, False], [True, True], 0)
    assert align_tokens([], list("ab")) == ([], [], 2)


def test_session_counts_concatenate_in_time_order_and_ignore_speakers() -> None:
    reference = [Utterance(5, 6, "B", "下午好"), Utterance(0, 1, "A", "上午好")]
    hypothesis = [Utterance(0, 1, "S1", "上午好"), Utterance(5, 6, "S1", "下五好")]
    assert session_counts(reference, hypothesis, "strict") == {
        "substitution": 1,
        "deletion": 0,
        "insertion": 0,
        "reference_tokens": 6,
    }


def test_session_counts_nofill_drops_fillers() -> None:
    reference = [Utterance(0, 1, "A", "嗯我们开会")]
    hypothesis = [Utterance(0, 1, "S1", "我们开会吧")]
    assert session_counts(reference, hypothesis, "strict")["reference_tokens"] == 5
    nofill = session_counts(reference, hypothesis, "nofill")
    assert (nofill["substitution"], nofill["deletion"], nofill["insertion"]) == (0, 0, 0)


def test_cp_counts_finds_the_best_speaker_assignment() -> None:
    reference = [Utterance(0, 1, "A", "甲乙丙"), Utterance(1, 2, "B", "丁戊")]
    # Labels swapped relative to the reference and one character wrong: 1 error out of 5.
    hypothesis = [Utterance(0, 1, "S2", "甲乙丙"), Utterance(1, 2, "S1", "丁己")]
    result = cp_counts(reference, hypothesis, "strict")
    assert result["errors"] == 1
    assert result["reference_tokens"] == 5
    assert result["mapping"] == {"S2": "A", "S1": "B"}


def test_cp_counts_charges_merged_speakers() -> None:
    reference = [Utterance(0, 1, "A", "甲乙"), Utterance(1, 2, "B", "丙丁")]
    hypothesis = [Utterance(0, 2, "S1", "甲乙丙丁")]
    # S1 can match only one reference speaker; the other's two characters are insertions plus two deletions.
    assert cp_counts(reference, hypothesis, "strict")["errors"] == 4


def test_cp_counts_extra_hypothesis_speaker_is_all_insertions() -> None:
    reference = [Utterance(0, 1, "A", "甲乙")]
    hypothesis = [Utterance(0, 1, "S1", "甲乙"), Utterance(2, 3, "S2", "丙")]
    assert cp_counts(reference, hypothesis, "strict")["errors"] == 1


def test_der_perfect_and_relabelled_is_zero() -> None:
    reference = [Utterance(0, 2, "A"), Utterance(2, 4, "B")]
    hypothesis = [Utterance(0, 2, "x"), Utterance(2, 4, "y")]
    result = diarization_error(reference, hypothesis, collar=0)
    assert result["der"] == 0
    assert result["mapping"] == {"x": "A", "y": "B"}


def test_der_components_without_collar() -> None:
    reference = [Utterance(0, 4, "A"), Utterance(4, 8, "B")]
    # 1 s of A missed, B's last 2 s given to A's label (confusion), 1 s of speech after the end (false alarm).
    hypothesis = [Utterance(1, 4, "x"), Utterance(4, 6, "y"), Utterance(6, 9, "x")]
    result = diarization_error(reference, hypothesis, collar=0)
    assert result["missed"] == pytest.approx(1.0)
    assert result["confusion"] == pytest.approx(2.0)
    assert result["false_alarm"] == pytest.approx(1.0)
    assert result["reference_speech"] == pytest.approx(8.0)
    assert result["der"] == pytest.approx(4 / 8)


def test_der_counts_overlap_per_speaker() -> None:
    reference = [Utterance(0, 4, "A"), Utterance(2, 4, "B")]
    hypothesis = [Utterance(0, 4, "x")]
    result = diarization_error(reference, hypothesis, collar=0)
    assert result["missed"] == pytest.approx(2.0)  # two speakers in 2-4 s, one hypothesis speaker
    assert result["der"] == pytest.approx(2 / 6)


def test_der_collar_excludes_boundaries() -> None:
    reference = [Utterance(0, 4, "A")]
    hypothesis = [Utterance(0.2, 4, "x")]
    assert diarization_error(reference, hypothesis, collar=0)["missed"] == pytest.approx(0.2)
    assert diarization_error(reference, hypothesis, collar=0.25)["der"] == 0


def test_speech_activity_is_speaker_agnostic() -> None:
    reference = [Utterance(0, 2, "A"), Utterance(2, 4, "B")]
    hypothesis = [Utterance(0, 3, "S1"), Utterance(5, 6, "S1")]
    result = speech_activity(reference, hypothesis, collar=0)
    assert result["missed"] == pytest.approx(1.0)
    assert result["false_alarm"] == pytest.approx(1.0)
    assert result["missed_rate"] == pytest.approx(0.25)


def test_claims_use_the_majority_reference_speaker() -> None:
    reference = [Utterance(0, 6, "A"), Utterance(6, 8, "B")]
    hypothesis = [Utterance(0, 7, "S1"), Utterance(7, 8, "S2")]
    assert majority_speaker(reference, hypothesis, "S1") == "A"
    assert majority_speaker(reference, hypothesis, "S3") is None
    assert claim_outcome(reference, hypothesis, ["S1"], "A") == "correct"
    assert claim_outcome(reference, hypothesis, ["S2"], "A") == "wrong"
    assert claim_outcome(reference, hypothesis, ["S1", "S2"], "A") == "wrong"
    assert claim_outcome(reference, hypothesis, [], "A") == "none"


def test_attributed_counts_score_target_words_and_misattribution() -> None:
    reference = [Utterance(0, 2, "A", "我说两句"), Utterance(2, 4, "B", "你来说")]
    # The claimed speaker covers A's turn and half of B's: its second segment is all B's speech.
    hypothesis = [Utterance(0, 2, "S1", "我说两句"), Utterance(2, 3, "S1", "你来"), Utterance(3, 4, "S2", "说")]
    result = attributed_counts(reference, hypothesis, ["S1"], "A", "strict")
    assert result["reference_tokens"] == 4
    assert (result["substitution"], result["deletion"], result["insertion"]) == (0, 0, 2)
    assert result["claimed_tokens"] == 6
    assert result["misattributed_tokens"] == pytest.approx(2.0)


def test_attributed_counts_split_errors_on_utterances_that_overlap_nobody() -> None:
    # A's first turn is alone, the second overlaps B; the claimed text drops one alone word and one overlapped word.
    reference = [Utterance(0, 2, "A", "开会了"), Utterance(3, 5, "A", "先说预算"), Utterance(4, 5, "B", "好")]
    hypothesis = [Utterance(0, 2, "S1", "开会"), Utterance(3, 5, "S1", "先说预")]
    result = attributed_counts(reference, hypothesis, ["S1"], "A", "strict")
    assert (result["isolated_tokens"], result["isolated_errors"]) == (3, 1)
    assert (result["reference_tokens"], result["deletion"]) == (7, 2)
