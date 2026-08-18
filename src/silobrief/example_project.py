from __future__ import annotations

from pathlib import Path

from silobrief.path_safety import has_link_like_component


class ExampleProjectError(Exception):
    pass


_TASK_1_LOG = 'sb log parcel_practice/labels.py --comment "Callers pass uppercase positionally."'
_TASK_1_BRIEF = (
    'sb brief "Append an optional separator to format_label. Preserve positional callers and apply '
    'uppercase last. Return a readable diff and focused unittests." '
    "--out .silobrief/exports/task-01-modify.md"
)
_TASK_2_LOG = (
    'sb log parcel_practice/pricing.py --comment "Weight is a positive whole number in kg."'
)
_TASK_2_BRIEF = (
    'sb brief "Add delivery_surcharge with the documented weight rules. Return a readable diff and '
    'focused unittests." --out .silobrief/exports/task-02-add.md'
)
_TASK_3_LOG = (
    'sb log parcel_practice/references.py --comment "New callers provide the primary reference."'
)
_TASK_3_BRIEF = (
    'sb brief "Remove the legacy fallback and all references to it. Preserve stripped primary '
    'values and ValueError behavior. Return a readable diff and focused unittests." '
    "--out .silobrief/exports/task-03-remove.md"
)

_README = f"""# siloBrief guided practice

This synthetic Python project lets you practise the complete siloBrief workflow without using a
real repository. It contains no organization data, credentials, network calls, or dependencies.

## Prepare the project

Run these commands from this directory:

```console
sb setup .
sb init
python -m unittest discover -s tests
```

The initial tests must pass. The example command only created these files; it did not run siloBrief
or change the exercises for you.

For each task:

1. Read the task and record its approved fact with `sb log`.
2. Use `sb search` to inspect candidates.
3. Use `sb brief` to review source and create a Markdown brief.
4. Send only the generated brief to an external AI assistant.
5. Review and apply the proposed code and tests yourself.
6. Run `python -m unittest discover -s tests`.
7. Run `sb init` again before starting the next task.

## Task 1: Modify label formatting

- Target: `parcel_practice/labels.py`, function `format_label`
- Goal: append an optional `separator: str = ""` argument and insert it between a non-empty prefix
  and the reference.
- Constraints: existing positional callers keep their behavior; uppercase remains the last
  operation.
- Expected change: the target function and focused tests only.

```console
{_TASK_1_LOG}
{_TASK_1_BRIEF}
```

## Task 2: Add a pricing function

- Target: `parcel_practice/pricing.py`
- Goal: add `delivery_surcharge(weight_kg: int) -> int`.
- Rules: reject values below 1; return 0 through 5 kg; return 2 units for every kg above 5.
- Expected change: one new function and focused tests.

```console
{_TASK_2_LOG}
{_TASK_2_BRIEF}
```

## Task 3: Remove the legacy fallback

- Target: `parcel_practice/references.py`, function `choose_reference`
- Goal: remove `legacy_reference` and the `legacy` argument and branch from `choose_reference`.
- Rules: return a stripped primary reference or raise `ValueError` when it is missing or blank.
- Expected change: remove the function and all references to it, then update focused tests.

```console
{_TASK_3_LOG}
{_TASK_3_BRIEF}
```

Review every generated Markdown file before sharing it. This project is an exercise, not a security
or export-approval test.
"""

_FILES = (
    ("README.md", _README),
    (
        "parcel_practice/__init__.py",
        """from __future__ import annotations

from parcel_practice.labels import format_label
from parcel_practice.pricing import base_price
from parcel_practice.references import choose_reference

__all__ = ["base_price", "choose_reference", "format_label"]
""",
    ),
    (
        "parcel_practice/labels.py",
        """from __future__ import annotations


def format_label(reference: str, prefix: str = "", uppercase: bool = False) -> str:
    label = f"{prefix}{reference}"
    return label.upper() if uppercase else label
""",
    ),
    (
        "parcel_practice/pricing.py",
        """from __future__ import annotations


_BASE_PRICES = {"local": 5, "regional": 8, "remote": 12}


def base_price(zone: str) -> int:
    try:
        return _BASE_PRICES[zone]
    except KeyError as error:
        raise ValueError(f"unknown delivery zone: {zone}") from error
""",
    ),
    (
        "parcel_practice/references.py",
        """from __future__ import annotations


def legacy_reference(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def choose_reference(primary: str | None, legacy: str | None) -> str:
    if primary is not None and primary.strip():
        return primary.strip()
    fallback = legacy_reference(legacy)
    if fallback is not None:
        return fallback
    raise ValueError("a tracking reference is required")
""",
    ),
    ("tests/__init__.py", ""),
    (
        "tests/test_labels.py",
        """from __future__ import annotations

import unittest

from parcel_practice.labels import format_label


class FormatLabelTests(unittest.TestCase):
    def test_joins_prefix_and_reference(self) -> None:
        self.assertEqual(format_label("123", "PKG-"), "PKG-123")

    def test_applies_uppercase_last(self) -> None:
        self.assertEqual(format_label("abc", "pkg-", True), "PKG-ABC")
""",
    ),
    (
        "tests/test_pricing.py",
        """from __future__ import annotations

import unittest

from parcel_practice.pricing import base_price


class BasePriceTests(unittest.TestCase):
    def test_returns_known_zone_price(self) -> None:
        self.assertEqual(base_price("regional"), 8)

    def test_rejects_unknown_zone(self) -> None:
        with self.assertRaises(ValueError):
            base_price("ocean")
""",
    ),
    (
        "tests/test_references.py",
        """from __future__ import annotations

import unittest

from parcel_practice.references import choose_reference


class ChooseReferenceTests(unittest.TestCase):
    def test_prefers_and_strips_primary(self) -> None:
        self.assertEqual(choose_reference("  new-123  ", "old-123"), "new-123")

    def test_uses_legacy_when_primary_is_blank(self) -> None:
        self.assertEqual(choose_reference(" ", " old-123 "), "old-123")

    def test_rejects_missing_references(self) -> None:
        with self.assertRaises(ValueError):
            choose_reference(None, None)
""",
    ),
)


def create_example_project(target: Path) -> int:
    if has_link_like_component(target):
        raise ExampleProjectError("example path must not contain a symbolic link or reparse point")
    if target.exists():
        if not target.is_dir():
            raise ExampleProjectError("example path must be a directory")
        try:
            if any(target.iterdir()):
                raise ExampleProjectError("example directory must be empty")
        except OSError as error:
            raise ExampleProjectError(f"cannot inspect example directory: {error}") from error
    else:
        try:
            target.mkdir(parents=True)
        except OSError as error:
            raise ExampleProjectError(f"cannot create example directory: {error}") from error

    try:
        for relative, content in _FILES:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
    except OSError as error:
        raise ExampleProjectError(f"cannot write example project: {error}") from error
    return len(_FILES)
