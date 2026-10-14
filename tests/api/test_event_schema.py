"""The packaged JSON Schema for v1 events, and the suite-wide check that every event a
test's sink receives validates against it (API-R24, API-R25, API-R26, TST-R18)."""

from pathlib import Path

import pytest
from conftest import RecordingSink, validate_event

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    plan_batch,
    run_batch,
)


def recorded_events(pdf: Path) -> list[dict[str, object]]:
    sink = RecordingSink()
    plan = plan_batch([InputSpec(pdf)], DiscoveryOptions())
    run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)
    return sink.events


@pytest.mark.ac("TST-AC12")
def test_a_sink_receiving_an_event_without_v_fails_the_test_naming_type_and_field() -> None:
    event = {"type": "conversion_started", "t": 0.5, "id": 0}

    with pytest.raises(pytest.fail.Exception) as failure:
        RecordingSink()(event)

    message = str(failure.value)
    assert "conversion_started" in message
    assert "'v'" in message


@pytest.mark.ac("TST-AC12")
def test_schema_validation_fails_a_run_whose_sink_gets_a_malformed_event(
    novel_pdf: Path,
) -> None:
    """The check sits in the sink itself, so a malformed event fails the test even when
    the core calls the sink: pytest's failure is not swallowed as an internal error."""

    def drop_v(event: dict[str, object]) -> None:
        RecordingSink()({key: value for key, value in event.items() if key != "v"})

    plan = plan_batch([InputSpec(novel_pdf)], DiscoveryOptions())
    with pytest.raises(pytest.fail.Exception, match="batch_started"):
        run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), drop_v)


@pytest.mark.ac("API-AC14")
def test_an_unknown_extra_field_validates_but_v_2_does_not(novel_pdf: Path) -> None:
    events = recorded_events(novel_pdf)
    finished = events[-1]
    assert finished["type"] == "batch_finished"

    validate_event({**finished, "added_in_a_later_release": {"x": 1}})
    with pytest.raises(pytest.fail.Exception, match="'v'"):
        validate_event({**finished, "v": 2})


@pytest.mark.ac("API-AC14")
def test_an_unknown_event_type_validates_against_the_envelope_alone() -> None:
    validate_event({"v": 1, "type": "added_in_a_later_release", "t": 1.0, "anything": [1]})
    with pytest.raises(pytest.fail.Exception):
        validate_event({"v": 1, "type": "added_in_a_later_release", "t": -1})


@pytest.mark.ac("API-AC14")
def test_a_known_event_type_must_match_its_own_definition() -> None:
    with pytest.raises(pytest.fail.Exception, match="progress"):
        validate_event({"v": 1, "type": "progress", "t": 0.1, "id": 0, "stage": "analyse"})
    with pytest.raises(pytest.fail.Exception, match="conversion_finished"):
        validate_event(
            {"v": 1, "type": "conversion_finished", "t": 0.1, "id": 0, "source": "rel.pdf"}
        )
