"""Strict parameter validation for the v1 API.

Validators are small composable callables ``(value, path) -> normalized value``
that raise ``invalidParams`` with a JSON pointer to the offending input. They
mirror the Anki-Connect v1 contract: unknown properties are rejected, required
properties must be present, and documented defaults are filled in.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

from .errors import ApiError

Validator = Callable[[Any, str], Any]
MISSING = object()
_ID = re.compile(r"[1-9][0-9]{0,18}")


def fail(path: str, message: str) -> ApiError:
    return ApiError("invalidParams", f"{path or '/'}: {message}", {"pointer": path or "/"})


def any_() -> Validator:
    return lambda value, path: value


def string(min_length: int = 0, pattern: str | None = None, exclude: tuple = ()) -> Validator:
    compiled = re.compile(pattern) if pattern else None

    def check(value: Any, path: str) -> str:
        if not isinstance(value, str):
            raise fail(path, "expected a string")
        if len(value) < min_length:
            raise fail(path, "must not be empty")
        if compiled and not compiled.search(value):
            raise fail(path, "has an invalid format")
        if value in exclude:
            raise fail(path, "is not allowed")
        return value
    return check


def integer(minimum: int | None = None, maximum: int | None = None) -> Validator:
    def check(value: Any, path: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise fail(path, "expected an integer")
        if minimum is not None and value < minimum:
            raise fail(path, f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise fail(path, f"must be at most {maximum}")
        return value
    return check


def number(minimum: float | None = None, maximum: float | None = None,
           exclusive_min: float | None = None, exclusive_max: float | None = None) -> Validator:
    def check(value: Any, path: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise fail(path, "expected a number")
        if minimum is not None and value < minimum:
            raise fail(path, f"must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise fail(path, f"must be at most {maximum}")
        if exclusive_min is not None and value <= exclusive_min:
            raise fail(path, f"must be greater than {exclusive_min}")
        if exclusive_max is not None and value >= exclusive_max:
            raise fail(path, f"must be less than {exclusive_max}")
        return value
    return check


def boolean() -> Validator:
    def check(value: Any, path: str) -> bool:
        if not isinstance(value, bool):
            raise fail(path, "expected a boolean")
        return value
    return check


def const(expected: Any) -> Validator:
    def check(value: Any, path: str) -> Any:
        if value != expected or type(value) is not type(expected):
            raise fail(path, f"must be {expected!r}")
        return value
    return check


def enum(*values: Any) -> Validator:
    def check(value: Any, path: str) -> Any:
        if value not in values or isinstance(value, bool) != isinstance(values[0], bool):
            raise fail(path, "must be one of " + ", ".join(map(str, values)))
        return value
    return check


def entity() -> Validator:
    def check(value: Any, path: str) -> str:
        if not isinstance(value, str) or not _ID.fullmatch(value) or int(value) > 9223372036854775807:
            raise fail(path, "expected a positive 64-bit decimal ID string")
        return value
    return check


def array(item: Validator, min_items: int = 0, max_items: int | None = None) -> Validator:
    def check(value: Any, path: str) -> list:
        if not isinstance(value, list):
            raise fail(path, "expected an array")
        if len(value) < min_items:
            raise fail(path, f"needs at least {min_items} item(s)")
        if max_items is not None and len(value) > max_items:
            raise fail(path, f"allows at most {max_items} item(s)")
        return [item(entry, f"{path}/{index}") for index, entry in enumerate(value)]
    return check


def nullable(inner: Validator) -> Validator:
    return lambda value, path: None if value is None else inner(value, path)


def mapping(values: Validator) -> Validator:
    def check(value: Any, path: str) -> dict:
        if not isinstance(value, dict):
            raise fail(path, "expected an object")
        return {key: values(entry, f"{path}/{key}") for key, entry in value.items()}
    return check


def obj(properties: dict[str, tuple[Validator, Any]], *, min_properties: int = 0,
        extra: bool = False, check: Callable[[dict, str], None] | None = None) -> Validator:
    """``properties`` maps a name to ``(validator, default)``; use MISSING for required
    properties and ``None`` (the Python value) wrapped as ``OPTIONAL`` for optional
    properties without a default."""
    def validate(value: Any, path: str) -> dict:
        if not isinstance(value, dict):
            raise fail(path, "expected an object")
        if not extra:
            for key in value:
                if key not in properties:
                    raise fail(f"{path}/{key}", "unknown property")
        if len(value) < min_properties:
            raise fail(path, "must not be empty")
        result = {}
        for name, (validator, default) in properties.items():
            if name in value:
                result[name] = validator(value[name], f"{path}/{name}")
            elif default is MISSING:
                raise fail(f"{path}/{name}", "is required")
            elif default is not OPTIONAL:
                result[name] = default() if callable(default) else default
        if extra:
            for key, entry in value.items():
                result.setdefault(key, entry)
        if check:
            check(result, path)
        return result
    return validate


OPTIONAL = object()


def one_of(*validators: Validator) -> Validator:
    def check(value: Any, path: str) -> Any:
        errors = []
        for validator in validators:
            try:
                return validator(value, path)
            except ApiError as error:
                errors.append(str(error))
        raise fail(path, "does not match any allowed shape")
    return check


def exactly_one(*names: str) -> Callable[[dict, str], None]:
    def check(value: dict, path: str) -> None:
        present = [name for name in names if name in value]
        if len(present) != 1:
            raise fail(path, "requires exactly one of " + ", ".join(names))
    return check


# -- shared shapes -----------------------------------------------------------------------

ID = entity()
IDS = array(ID)
TEXT = string(1)
REFERENCE = one_of(obj({"id": (ID, MISSING)}), obj({"name": (TEXT, MISSING)}))
REFERENCES = array(REFERENCE)
RATING = enum("again", "hard", "good", "easy")
TAGS = array(TEXT)
FIELDS = mapping(string())
SORT = obj({"column": (TEXT, MISSING), "direction": (enum("ascending", "descending"), MISSING)})
LIMIT = integer(1, 1000)
FILENAME = string(1, r"^[^/\\\x00]+$", exclude=(".", ".."))


def _duplicate_check(value: dict, path: str) -> None:
    if value.get("scope") == "deck" and "deck" not in value:
        raise fail(f"{path}/deck", "is required for deck scope")


DUPLICATES = obj({
    "allow": (boolean(), False),
    "scope": (enum("collection", "deck"), "collection"),
    "deck": (REFERENCE, OPTIONAL),
    "includeChildren": (boolean(), False),
    "acrossNoteTypes": (boolean(), False),
}, check=_duplicate_check)

NOTE_INPUT = obj({
    "noteType": (REFERENCE, MISSING),
    "deck": (REFERENCE, MISSING),
    "fields": (FIELDS, MISSING),
    "tags": (TAGS, list),
    "duplicates": (DUPLICATES, OPTIONAL),
    "rejectEmptyQuestions": (boolean(), True),
})

DRAFT_INPUT = obj({
    "noteType": (REFERENCE, MISSING),
    "deck": (REFERENCE, MISSING),
    "fields": (FIELDS, dict),
    "tags": (TAGS, list),
})

NOTE_PATCH = obj({"fields": (FIELDS, OPTIONAL), "tags": (TAGS, OPTIONAL)}, min_properties=1)
EDITOR_PATCH = obj({"deck": (REFERENCE, OPTIONAL), "noteType": (REFERENCE, OPTIONAL),
                    "fields": (FIELDS, OPTIONAL), "tags": (TAGS, OPTIONAL)}, min_properties=1)

FIELD_CONFIG = obj({
    "name": (TEXT, MISSING),
    "fontFamily": (TEXT, "Arial"),
    "fontSize": (integer(1), 20),
    "sticky": (boolean(), False),
    "rtl": (boolean(), False),
    "plainText": (boolean(), False),
    "collapsed": (boolean(), False),
    "excludeFromSearch": (boolean(), False),
    "description": (string(), OPTIONAL),
})
TEMPLATE_CONFIG = obj({
    "name": (TEXT, MISSING),
    "questionHtml": (string(), MISSING),
    "answerHtml": (string(), MISSING),
    "browserQuestionHtml": (string(), ""),
    "browserAnswerHtml": (string(), ""),
    "deck": (nullable(REFERENCE), OPTIONAL),
    "browserFontFamily": (TEXT, "Arial"),
    "browserFontSize": (integer(1), 20),
})
FIELD_PATCH = obj({key: (validator, OPTIONAL) for key, (validator, _) in {
    "name": (TEXT, 0), "fontFamily": (TEXT, 0), "fontSize": (integer(1), 0), "sticky": (boolean(), 0),
    "rtl": (boolean(), 0), "plainText": (boolean(), 0), "collapsed": (boolean(), 0),
    "excludeFromSearch": (boolean(), 0), "description": (string(), 0)}.items()}, min_properties=1)
TEMPLATE_PATCH = obj({key: (validator, OPTIONAL) for key, validator in {
    "name": TEXT, "questionHtml": string(), "answerHtml": string(), "browserQuestionHtml": string(),
    "browserAnswerHtml": string(), "deck": nullable(REFERENCE), "browserFontFamily": TEXT,
    "browserFontSize": integer(1)}.items()}, min_properties=1)
STRUCTURE_EDIT = one_of(
    obj({"op": (const("addField"), MISSING), "field": (FIELD_CONFIG, MISSING), "index": (integer(0), OPTIONAL)}),
    obj({"op": (const("updateField"), MISSING), "name": (TEXT, MISSING), "patch": (FIELD_PATCH, MISSING)}),
    obj({"op": (const("moveField"), MISSING), "name": (TEXT, MISSING), "index": (integer(0), MISSING)}),
    obj({"op": (const("removeField"), MISSING), "name": (TEXT, MISSING)}),
    obj({"op": (const("addTemplate"), MISSING), "template": (TEMPLATE_CONFIG, MISSING), "index": (integer(0), OPTIONAL)}),
    obj({"op": (const("updateTemplate"), MISSING), "name": (TEXT, MISSING), "patch": (TEMPLATE_PATCH, MISSING)}),
    obj({"op": (const("moveTemplate"), MISSING), "name": (TEXT, MISSING), "index": (integer(0), MISSING)}),
    obj({"op": (const("removeTemplate"), MISSING), "name": (TEXT, MISSING)}),
)
NOTE_TYPE_PATCH = obj({"name": (TEXT, OPTIONAL), "css": (string(), OPTIONAL), "sortField": (TEXT, OPTIONAL),
                       "latexHeader": (string(), OPTIONAL), "latexFooter": (string(), OPTIONAL),
                       "latexSvg": (boolean(), OPTIONAL)}, min_properties=1)
CONVERSION_MAPPING = obj({"target": (TEXT, MISSING), "source": (nullable(TEXT), MISSING)})

_STEPS = array(number(exclusive_min=0))
_PRESET_FIELDS: dict[str, Validator] = {
    "learnStepsMinutes": _STEPS, "relearnStepsMinutes": _STEPS,
    "fsrsParameters4": array(number()), "fsrsParameters5": array(number()), "fsrsParameters6": array(number()),
    "newPerDay": integer(0), "newPerDayMinimum": integer(0), "reviewsPerDay": integer(0),
    "leechThreshold": integer(0), "answerTimeLimitSeconds": integer(0),
    "maximumIntervalDays": integer(1), "minimumLapseIntervalDays": integer(1),
    "graduatingGoodDays": integer(1), "graduatingEasyDays": integer(1),
    "initialEase": number(0), "easyMultiplier": number(0), "hardMultiplier": number(0),
    "lapseMultiplier": number(0), "intervalMultiplier": number(0),
    "desiredRetention": number(exclusive_min=0, exclusive_max=1),
    "historicalRetention": number(exclusive_min=0, exclusive_max=1),
    "newInsertOrder": enum("due", "random"),
    "newGatherOrder": enum("deck", "deckThenRandomNotes", "lowestPosition", "highestPosition",
                           "randomNotes", "randomCards"),
    "newSortOrder": enum("template", "none", "templateThenRandom", "randomNoteThenTemplate", "randomCard"),
    "reviewOrder": enum("day", "dayThenDeck", "deckThenDay", "intervalAscending", "intervalDescending",
                        "easeAscending", "easeDescending", "retrievabilityAscending",
                        "retrievabilityDescending", "relativeOverdueness", "random", "added", "reverseAdded"),
    "newMix": enum("mixed", "afterReviews", "beforeReviews"),
    "dayLearningMix": enum("mixed", "afterReviews", "beforeReviews"),
    "leechAction": enum("suspend", "tagOnly"),
    "questionAction": enum("showAnswer", "showReminder"),
    "answerAction": enum("buryCard", "again", "good", "hard", "showReminder"),
    "easyDaysPercentages": array(number(0), 7, 7),
    "ignoreReviewsBefore": string(0, r"^$|^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
    "parameterSearch": string(),
    "questionDisplaySeconds": number(0), "answerDisplaySeconds": number(0),
    "disableAutoplay": boolean(), "showTimer": boolean(), "stopTimerOnAnswer": boolean(),
    "waitForAudio": boolean(), "skipQuestionOnAnswerReplay": boolean(),
    "buryNew": boolean(), "buryReviews": boolean(), "buryDayLearning": boolean(),
}
PRESET_PATCH = obj({key: (validator, OPTIONAL) for key, validator in _PRESET_FIELDS.items()}, min_properties=1)

MEDIA_SOURCE = one_of(obj({"data": (string(), MISSING)}), obj({"path": (TEXT, MISSING)}),
                      obj({"url": (string(1, r"^https?://"), MISSING)}))
MEDIA_SKIP = obj({"algorithm": (enum("md5", "sha256"), MISSING), "digest": (TEXT, MISSING)})
MEMORY = obj({"difficulty": (number(0, 10), MISSING), "stabilityDays": (number(0), MISSING)})
RAW_CARD_PATCH = obj({
    "intervalDays": (integer(0), OPTIONAL), "sm2EasePermille": (integer(0), OPTIONAL),
    "repetitions": (integer(0), OPTIONAL), "lapses": (integer(0), OPTIONAL),
    "remainingSteps": (integer(0), OPTIONAL), "fsrsMemory": (nullable(MEMORY), OPTIONAL),
    "customData": (string(), OPTIONAL),
}, min_properties=1)
INTERVAL = obj({"value": (integer(0), MISSING), "unit": (enum("seconds", "days"), MISSING)})
FACTOR = obj({"encoding": (enum("legacySm2EasePermille", "fsrsNormalizedDifficulty", "unknown"), MISSING),
              "value": (integer(0), MISSING)})
REVIEW_IMPORT = obj({
    "id": (ID, MISSING), "cardId": (ID, MISSING), "rating": (nullable(RATING), MISSING),
    "interval": (INTERVAL, MISSING), "previousInterval": (INTERVAL, MISSING), "factor": (FACTOR, MISSING),
    "elapsedMs": (integer(0), MISSING),
    "kind": (enum("learning", "review", "relearning", "filtered", "manual", "rescheduled"), MISSING),
})
ANSWER = obj({"cardId": (ID, MISSING), "rating": (RATING, MISSING), "stateToken": (TEXT, MISSING),
              "elapsedMs": (integer(0), 0)})
COMMAND = obj({"method": (TEXT, MISSING), "params": (mapping(any_()), dict)})
