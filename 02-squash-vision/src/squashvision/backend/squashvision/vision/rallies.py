from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from typing import Sequence

from squashvision.vision.contacts import ContactEvent, ContactType

SERVE_DEAD_TIME_US = 750_000
SERVE_CONFIRM_WINDOW_US = 1_500_000
CONTACT_DEAD_TIME_US = 3_000_000
MISSING_ACTIVITY_END_US = 1_000_000


class RallyState(StrEnum):
    IDLE = "IDLE"
    SERVE_CANDIDATE = "SERVE_CANDIDATE"
    ACTIVE = "ACTIVE"
    TERMINAL_CANDIDATE = "TERMINAL_CANDIDATE"


@dataclass(frozen=True, slots=True)
class ActivitySample:
    timestamp_us: int
    ball_visible: bool
    ball_confidence: float
    player_activity: float

    def __post_init__(self) -> None:
        if self.timestamp_us < 0:
            raise ValueError("activity timestamp must be nonnegative")
        if not all(math.isfinite(value) for value in (self.ball_confidence, self.player_activity)):
            raise ValueError("activity values must be finite")
        if not 0.0 <= self.ball_confidence <= 1.0:
            raise ValueError("ball activity confidence must be between zero and one")
        if not 0.0 <= self.player_activity <= 1.0:
            raise ValueError("player activity must be between zero and one")
        if not self.ball_visible and self.ball_confidence != 0.0:
            raise ValueError("missing ball activity cannot claim ball confidence")

    @property
    def active(self) -> bool:
        return self.ball_visible and self.ball_confidence >= 0.35 and self.player_activity >= 0.2

    @property
    def inactive(self) -> bool:
        return (not self.ball_visible or self.ball_confidence < 0.2) and self.player_activity < 0.2


@dataclass(frozen=True, slots=True)
class RallyBoundary:
    earliest_us: int
    selected_us: int
    latest_us: int
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(dict.fromkeys(self.evidence)))
        if self.earliest_us < 0:
            raise ValueError("rally boundary must be nonnegative")
        if not self.earliest_us <= self.selected_us <= self.latest_us:
            raise ValueError("rally boundary interval must contain its selected timestamp")
        if not self.evidence:
            raise ValueError("rally boundary requires explicit evidence")


@dataclass(frozen=True, slots=True)
class RallyPrediction:
    rally_id: str
    start: RallyBoundary
    end: RallyBoundary
    supporting_contact_ids: tuple[str, ...]
    review_required: bool
    review_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "supporting_contact_ids", tuple(self.supporting_contact_ids))
        object.__setattr__(self, "review_reasons", tuple(dict.fromkeys(self.review_reasons)))
        if not self.rally_id.strip():
            raise ValueError("rally identifier cannot be blank")
        if self.start.selected_us >= self.end.selected_us:
            raise ValueError("rally prediction must have positive duration")
        if not self.supporting_contact_ids:
            raise ValueError("rally prediction requires supporting contacts")
        if len(set(self.supporting_contact_ids)) != len(self.supporting_contact_ids):
            raise ValueError("supporting contact identifiers must be unique")
        if self.review_required != bool(self.review_reasons):
            raise ValueError("rally review flag and reasons must agree")

    @property
    def start_us(self) -> int:
        return self.start.selected_us

    @property
    def end_us(self) -> int:
        return self.end.selected_us


@dataclass(slots=True)
class _RallyStateMachine:
    state: RallyState = RallyState.IDLE
    last_seen_contact_us: int | None = None
    serve: ContactEvent | None = None
    start: RallyBoundary | None = None
    contacts: list[ContactEvent] | None = None
    last_contact_us: int | None = None
    last_active_us: int | None = None
    low_activity_start_us: int | None = None
    serve_activity_count: int = 0
    serve_last_activity_us: int | None = None
    terminal: RallyBoundary | None = None
    terminal_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.contacts is None:
            self.contacts = []

    def reset(self) -> None:
        self.state = RallyState.IDLE
        self.serve = None
        self.start = None
        self.contacts = []
        self.last_contact_us = None
        self.last_active_us = None
        self.low_activity_start_us = None
        self.serve_activity_count = 0
        self.serve_last_activity_us = None
        self.terminal = None
        self.terminal_reasons = ()


def _contact_boundary(contact: ContactEvent, *evidence: str) -> RallyBoundary:
    return RallyBoundary(
        earliest_us=max(0, contact.timestamp_us - contact.uncertainty_us),
        selected_us=contact.timestamp_us,
        latest_us=contact.timestamp_us + contact.uncertainty_us,
        evidence=evidence,
    )


def _rally_id(start: RallyBoundary, end: RallyBoundary, contacts: Sequence[ContactEvent]) -> str:
    payload = "|".join(
        (str(start.selected_us), str(end.selected_us), *(item.contact_id for item in contacts))
    ).encode()
    return f"rally-{hashlib.sha256(payload).hexdigest()[:20]}"


def _finish(machine: _RallyStateMachine) -> RallyPrediction | None:
    if machine.start is None or machine.terminal is None or not machine.contacts:
        machine.reset()
        return None
    end = machine.terminal
    start = machine.start
    if end.selected_us <= start.selected_us:
        machine.reset()
        return None
    reasons: list[str] = list(machine.terminal_reasons)
    for contact in machine.contacts:
        reasons.extend(f"contact:{reason}" for reason in contact.review_reasons)
    contacts = tuple(machine.contacts)
    prediction = RallyPrediction(
        rally_id=_rally_id(start, end, contacts),
        start=start,
        end=end,
        supporting_contact_ids=tuple(item.contact_id for item in contacts),
        review_required=bool(reasons),
        review_reasons=tuple(reasons),
    )
    machine.reset()
    return prediction


def _begin_serve(machine: _RallyStateMachine, contact: ContactEvent) -> None:
    machine.state = RallyState.SERVE_CANDIDATE
    machine.serve = contact
    machine.start = _contact_boundary(contact, "serve_racket")
    machine.contacts = [contact]
    machine.last_contact_us = contact.timestamp_us
    machine.last_active_us = contact.timestamp_us
    machine.low_activity_start_us = None
    machine.serve_activity_count = 0
    machine.serve_last_activity_us = None


def _activate(machine: _RallyStateMachine, evidence: str) -> None:
    assert machine.start is not None
    machine.start = RallyBoundary(
        earliest_us=machine.start.earliest_us,
        selected_us=machine.start.selected_us,
        latest_us=machine.start.latest_us,
        evidence=machine.start.evidence + (evidence,),
    )
    machine.state = RallyState.ACTIVE
    machine.low_activity_start_us = None


def _terminal_from_dead_time(machine: _RallyStateMachine, observed_us: int) -> None:
    assert machine.last_contact_us is not None
    machine.terminal = RallyBoundary(
        earliest_us=machine.last_contact_us,
        selected_us=machine.last_contact_us,
        latest_us=observed_us,
        evidence=("contact_dead_time",),
    )
    machine.terminal_reasons = ("uncertain_contact_dead_time_end",)
    machine.state = RallyState.TERMINAL_CANDIDATE


def _handle_contact(
    machine: _RallyStateMachine, contact: ContactEvent, predictions: list[RallyPrediction]
) -> None:
    while True:
        if machine.state is RallyState.SERVE_CANDIDATE:
            assert machine.serve is not None
            if contact.timestamp_us - machine.serve.timestamp_us > SERVE_CONFIRM_WINDOW_US:
                previous = machine.serve.timestamp_us
                machine.reset()
                machine.last_seen_contact_us = previous
                continue
        if (
            machine.state is RallyState.ACTIVE
            and contact.selected_type is not ContactType.FLOOR
            and machine.last_contact_us is not None
            and contact.timestamp_us - machine.last_contact_us >= CONTACT_DEAD_TIME_US
        ):
            _terminal_from_dead_time(machine, contact.timestamp_us)
            prediction = _finish(machine)
            if prediction is not None:
                predictions.append(prediction)
            continue
        if machine.state is RallyState.TERMINAL_CANDIDATE:
            prediction = _finish(machine)
            if prediction is not None:
                predictions.append(prediction)
            continue
        break

    previous_seen = machine.last_seen_contact_us
    machine.last_seen_contact_us = contact.timestamp_us
    if machine.state is RallyState.IDLE:
        dead_time_sufficient = (
            previous_seen is None
            or contact.timestamp_us - previous_seen >= SERVE_DEAD_TIME_US
        )
        if contact.selected_type is ContactType.RACKET and dead_time_sufficient:
            _begin_serve(machine, contact)
        return

    assert machine.contacts is not None
    machine.contacts.append(contact)
    machine.last_contact_us = contact.timestamp_us
    machine.last_active_us = contact.timestamp_us
    machine.low_activity_start_us = None
    if machine.state is RallyState.SERVE_CANDIDATE:
        if contact.selected_type is ContactType.FRONT_WALL:
            _activate(machine, "front_wall_confirmation")
        elif contact.selected_type is ContactType.RACKET:
            _activate(machine, "next_racket_confirmation")
        return
    if machine.state is RallyState.ACTIVE and contact.selected_type is ContactType.FLOOR:
        machine.terminal = _contact_boundary(contact, "terminal_floor")
        machine.terminal_reasons = ()
        machine.state = RallyState.TERMINAL_CANDIDATE


def _handle_activity(
    machine: _RallyStateMachine, sample: ActivitySample, predictions: list[RallyPrediction]
) -> None:
    if machine.state is RallyState.SERVE_CANDIDATE:
        assert machine.serve is not None
        if sample.timestamp_us - machine.serve.timestamp_us > SERVE_CONFIRM_WINDOW_US:
            machine.reset()
            return
        if sample.active:
            if machine.serve_last_activity_us is None:
                machine.serve_activity_count = 1
            else:
                delta = sample.timestamp_us - machine.serve_last_activity_us
                if delta <= 0:
                    return
                machine.serve_activity_count = (
                    machine.serve_activity_count + 1 if delta <= 500_000 else 1
                )
            machine.serve_last_activity_us = sample.timestamp_us
            if machine.serve_activity_count >= 2:
                _activate(machine, "ball_activity_confirmation")
                machine.last_active_us = sample.timestamp_us
        return

    if machine.state is RallyState.TERMINAL_CANDIDATE:
        prediction = _finish(machine)
        if prediction is not None:
            predictions.append(prediction)
        return
    if machine.state is not RallyState.ACTIVE:
        return

    if sample.active:
        machine.last_active_us = sample.timestamp_us
        machine.low_activity_start_us = None
        return
    if sample.inactive:
        if machine.low_activity_start_us is None:
            machine.low_activity_start_us = sample.timestamp_us
        if sample.timestamp_us - machine.low_activity_start_us >= MISSING_ACTIVITY_END_US:
            machine.terminal = RallyBoundary(
                earliest_us=machine.low_activity_start_us,
                selected_us=machine.low_activity_start_us,
                latest_us=sample.timestamp_us,
                evidence=("extended_missing_ball", "low_player_activity"),
            )
            machine.terminal_reasons = ("missing_ball_end",)
            machine.state = RallyState.TERMINAL_CANDIDATE


def _event_stream(
    contacts: Sequence[ContactEvent], activity: Sequence[ActivitySample]
):
    ordered_contacts = sorted(contacts, key=lambda item: (item.timestamp_us, item.contact_id))
    sorted_activity = sorted(activity, key=lambda item: item.timestamp_us)
    ordered_activity: list[ActivitySample] = []
    for sample in sorted_activity:
        if ordered_activity and sample.timestamp_us == ordered_activity[-1].timestamp_us:
            if sample != ordered_activity[-1]:
                raise ValueError("duplicate activity timestamps contain conflicting evidence")
            continue
        ordered_activity.append(sample)
    contact_index = 0
    activity_index = 0
    while contact_index < len(ordered_contacts) or activity_index < len(ordered_activity):
        if activity_index >= len(ordered_activity) or (
            contact_index < len(ordered_contacts)
            and ordered_contacts[contact_index].timestamp_us
            <= ordered_activity[activity_index].timestamp_us
        ):
            yield ordered_contacts[contact_index].timestamp_us, True, ordered_contacts[contact_index]
            contact_index += 1
        else:
            yield ordered_activity[activity_index].timestamp_us, False, ordered_activity[activity_index]
            activity_index += 1


def segment_rallies(
    contacts: Sequence[ContactEvent], activity: Sequence[ActivitySample]
) -> tuple[RallyPrediction, ...]:
    machine = _RallyStateMachine()
    predictions: list[RallyPrediction] = []
    last_event_us: int | None = None
    for timestamp_us, is_contact, event in _event_stream(contacts, activity):
        last_event_us = timestamp_us
        if is_contact:
            _handle_contact(machine, event, predictions)  # type: ignore[arg-type]
        else:
            if (
                machine.state is RallyState.ACTIVE
                and machine.last_contact_us is not None
                and timestamp_us - machine.last_contact_us >= CONTACT_DEAD_TIME_US
            ):
                _terminal_from_dead_time(machine, timestamp_us)
            _handle_activity(machine, event, predictions)  # type: ignore[arg-type]

    if machine.state is RallyState.TERMINAL_CANDIDATE:
        prediction = _finish(machine)
        if prediction is not None:
            predictions.append(prediction)
    elif machine.state is RallyState.ACTIVE and machine.last_contact_us is not None:
        selected = max(machine.last_contact_us, machine.last_active_us or machine.last_contact_us)
        latest = max(selected, last_event_us or selected)
        machine.terminal = RallyBoundary(
            earliest_us=machine.last_contact_us,
            selected_us=selected,
            latest_us=latest,
            evidence=("end_of_observations",),
        )
        machine.terminal_reasons = ("open_ended_rally",)
        prediction = _finish(machine)
        if prediction is not None:
            predictions.append(prediction)

    ordered = sorted(predictions, key=lambda item: (item.start_us, item.end_us, item.rally_id))
    result: list[RallyPrediction] = []
    for prediction in ordered:
        if result and prediction.start_us < result[-1].end_us:
            raise ValueError("rally predictions overlap; input evidence is inconsistent")
        result.append(prediction)
    return tuple(result)


__all__ = [
    "CONTACT_DEAD_TIME_US",
    "MISSING_ACTIVITY_END_US",
    "SERVE_CONFIRM_WINDOW_US",
    "ActivitySample",
    "RallyBoundary",
    "RallyPrediction",
    "RallyState",
    "segment_rallies",
]
