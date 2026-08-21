from __future__ import annotations

from pathlib import Path

from silobrief.path_safety import has_link_like_component


class ExampleProjectError(Exception):
    pass


_BOUNDARY = 'sb ignore internal --as "Private carrier contract rules" --alias carrier-boundary'
_TASK_LOG = 'sb log pricing.py --comment "Weight is a positive whole number in kilograms."'
_TASK_PROMPT = (
    "Add a 1000-unit remote-area surcharge to calculate_shipping_price. Apply it after the weight "
    "surcharge. Preserve the Flask response shape and return a readable diff and focused unittests."
)
_TASK_SEARCH = f'sb search "{_TASK_PROMPT}"'
_TASK_BRIEF = f'sb brief "{_TASK_PROMPT}" --out .silobrief/exports/remote-surcharge.md'

_README = f"""# siloBrief guided practice

This synthetic Flask project shows how to prepare a code change without sharing a private module.
It contains no organization data, credentials, or external API calls.

## Prepare the project

Run these commands from this directory:

```console
python -m pip install -r requirements.txt
python -m unittest discover -s tests
sb setup .
{_BOUNDARY}
sb init
```

The initial tests must pass. The example command only created these files; it did not run siloBrief
or make the change for you. The ignored `internal/` directory still exists so the generated app and
tests can run, but siloBrief must not read its source during indexing.

## Guided maintenance task

The Flask endpoint calls `shipping.py`, which uses the public price calculation and a private
carrier contract adjustment. Add a 1000-unit surcharge for the `remote` zone after the weight
surcharge. Keep the API response shape unchanged.

Record the approved weight rule, inspect the candidates, and create one brief:

```console
{_TASK_LOG}
{_TASK_SEARCH}
{_TASK_BRIEF}
```

During review, select `calculate_shipping_price` as source and inspect its related callers and
tests. Include the public `carrier-boundary` description, but do not approve source that requires
`EXPOSE`. The final brief should contain the public pricing code and boundary description without
the ignored file or its identifiers.

Send only the generated brief to an external AI assistant. Review any proposed patch yourself, run
the tests, and run `sb init` again after changing the example. This project is an exercise, not a
security scanner or export-approval tool.
"""

_FILES = (
    ("README.md", _README),
    ("requirements.txt", "Flask>=3.1,<4\n"),
    (
        "app.py",
        """from __future__ import annotations

from flask import Flask, Response, jsonify, request

from shipping import quote_shipping


def create_app() -> Flask:
    app = Flask(__name__)

    @app.post("/shipping/quote")
    def shipping_quote() -> Response | tuple[Response, int]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "a JSON object is required"}), 400
        try:
            quote = quote_shipping(payload.get("zone"), payload.get("weight_kg"))
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(quote)

    return app
""",
    ),
    (
        "shipping.py",
        """from __future__ import annotations

from internal.carrier_contract import apply_contract_adjustment
from pricing import calculate_shipping_price


def quote_shipping(zone: object, weight_kg: object) -> dict[str, int | str]:
    if not isinstance(zone, str):
        raise TypeError("zone must be a string")
    if type(weight_kg) is not int:
        raise TypeError("weight_kg must be an integer")
    public_price = calculate_shipping_price(zone, weight_kg)
    final_price = apply_contract_adjustment(zone, public_price)
    return {"zone": zone, "weight_kg": weight_kg, "amount": final_price}
""",
    ),
    (
        "pricing.py",
        """from __future__ import annotations

_BASE_PRICES = {"local": 5000, "regional": 8000, "remote": 12000}


def calculate_shipping_price(zone: str, weight_kg: int) -> int:
    if weight_kg < 1:
        raise ValueError("weight_kg must be at least 1")
    try:
        base = _BASE_PRICES[zone]
    except KeyError as error:
        raise ValueError(f"unknown zone: {zone}") from error
    weight_surcharge = max(weight_kg - 5, 0) * 500
    return base + weight_surcharge
""",
    ),
    ("internal/__init__.py", ""),
    (
        "internal/carrier_contract.py",
        """from __future__ import annotations

# INTERNAL_CONTRACT_CANARY_7F4A
_CONTRACT_CREDITS = {"regional": 250, "remote": 400}

def apply_contract_adjustment(zone: str, amount: int) -> int:
    return max(amount - _CONTRACT_CREDITS.get(zone, 0), 0)
""",
    ),
    ("tests/__init__.py", ""),
    (
        "tests/test_app.py",
        """from __future__ import annotations

import unittest

try:
    from app import create_app
except ModuleNotFoundError as error:
    if error.name != "flask":
        raise
    create_app = None


@unittest.skipIf(create_app is None, "install requirements.txt to test the Flask endpoint")
class ShippingApiTests(unittest.TestCase):
    def test_returns_a_shipping_quote(self) -> None:
        assert create_app is not None
        client = create_app().test_client()

        response = client.post("/shipping/quote", json={"zone": "local", "weight_kg": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"amount": 5000, "weight_kg": 2, "zone": "local"},
        )
""",
    ),
    (
        "tests/test_pricing.py",
        """from __future__ import annotations

import unittest

from pricing import calculate_shipping_price


class ShippingPriceTests(unittest.TestCase):
    def test_returns_the_zone_base_price(self) -> None:
        self.assertEqual(calculate_shipping_price("local", 2), 5000)

    def test_adds_the_weight_surcharge_above_five_kilograms(self) -> None:
        self.assertEqual(calculate_shipping_price("remote", 7), 13000)

    def test_rejects_an_unknown_zone(self) -> None:
        with self.assertRaises(ValueError):
            calculate_shipping_price("ocean", 2)
""",
    ),
    (
        "tests/test_shipping.py",
        """from __future__ import annotations

import unittest

from shipping import quote_shipping


class ShippingQuoteTests(unittest.TestCase):
    def test_applies_the_private_contract_adjustment_last(self) -> None:
        self.assertEqual(
            quote_shipping("regional", 2),
            {"amount": 7750, "weight_kg": 2, "zone": "regional"},
        )

    def test_rejects_a_non_integer_weight(self) -> None:
        with self.assertRaises(TypeError):
            quote_shipping("local", "2")
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
