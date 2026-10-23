"""Fictional demo fixtures. These are not live machine readings."""

from datetime import UTC, datetime

OBSERVED_AT = "2026-01-15T14:30:00Z"
FIXTURE_REVISION = "demo-2026-01-15"


def envelope(payload: dict, found: bool = True) -> dict:
    return {
        "ok": True,
        "found": found,
        "demo": True,
        "mock": True,
        "source": "manualmind-demo-mcp",
        "disclaimer": "FICTIONAL sample. Not live telemetry and not a real OEM system.",
        "observed_at": OBSERVED_AT,
        "fixture_revision": FIXTURE_REVISION,
        "generated_at": datetime.now(UTC).isoformat(),
        **payload,
    }


def not_found(message: str) -> dict:
    return envelope({"message": message}, found=False)


MACHINES = {
    ("rainer", "r200"): {
        "manufacturer": "Rainer",
        "model": "R200",
        "equipment_type": "CNC milling machine",
        "demo_machine_id": "R200-DEMO-01",
        "description": "Fictional vertical machining center used only in the ManualMind demo.",
        "manual_revision": "C",
        "manual_title": "Rainer R200 CNC Milling Machine Manual",
    },
    ("rainer", "r500"): {
        "manufacturer": "Rainer",
        "model": "R500",
        "equipment_type": "conveyor controller",
        "demo_machine_id": "R500-DEMO-01",
        "description": "Fictional conveyor controller used only in the ManualMind demo.",
        "manual_revision": "B",
        "manual_title": "Rainer R500 Conveyor Controller Manual",
    },
    ("acme industrial", "p300"): {
        "manufacturer": "Acme Industrial",
        "model": "P300",
        "equipment_type": "centrifugal pump",
        "demo_machine_id": "P300-DEMO-01",
        "description": "Fictional process pump used only in the ManualMind demo.",
        "manual_revision": "D",
        "manual_title": "Acme Industrial P300 Pump Manual",
    },
    ("acme", "p300"): {
        "manufacturer": "Acme Industrial",
        "model": "P300",
        "equipment_type": "centrifugal pump",
        "demo_machine_id": "P300-DEMO-01",
        "description": "Fictional process pump used only in the ManualMind demo.",
        "manual_revision": "D",
        "manual_title": "Acme Industrial P300 Pump Manual",
    },
}

ERRORS = {
    ("rainer", "r200", "E104"): {
        "error_code": "E104",
        "title": "Coolant flow",
        "meaning": "Coolant flow is below the Rev C low-flow trip.",
        "trip_setpoint": "1.5 bar gauge at the coolant manifold",
        "manual_revision": "C",
        "sample_checks": [
            "Confirm the coolant pump is running.",
            "Read manifold pressure. Rev C trips at 1.5 bar.",
            "Inspect the strainer after lockout/tagout.",
        ],
    },
    ("rainer", "r200", "E221"): {
        "error_code": "E221",
        "title": "Spindle overheat",
        "meaning": "Spindle temperature exceeded the Rev C alarm threshold of 85 deg C.",
        "manual_revision": "C",
        "sample_checks": [
            "Read the spindle temperature display.",
            "Confirm coolant is reaching the spindle jacket.",
            "Stop the spindle and allow it to cool before any inspection.",
        ],
    },
    ("rainer", "r500", "C310"): {
        "error_code": "C310",
        "title": "Motor overload",
        "meaning": "Conveyor drive current exceeded the Rev B overload band.",
        "manual_revision": "B",
        "sample_checks": [
            "Read drive current on the controller display.",
            "Inspect the belt path for a jam without reaching into a moving conveyor.",
            "Check the photoeye alignment described in the sensor section.",
        ],
    },
    ("acme industrial", "p300", "P042"): {
        "error_code": "P042",
        "title": "Low discharge pressure",
        "meaning": "Discharge pressure is below the Rev D low-pressure alarm of 2.8 bar.",
        "manual_revision": "D",
        "sample_checks": [
            "Read suction and discharge gauges.",
            "Confirm the suction valve is open and the strainer is clear after isolation.",
            "Compare seal temperature with the 70 deg C alarm.",
        ],
    },
}

STATUS = {
    "R200-DEMO-01": {
        "machine_id": "R200-DEMO-01",
        "manufacturer": "Rainer",
        "model": "R200",
        "state": "idle",
        "alarms": [],
        "coolant_flow_lpm": 18.4,
        "coolant_pressure_bar": 2.1,
        "spindle_temp_c": 41,
        "note": "Sample snapshot. Pressure is above the Rev C 1.5 bar trip, so E104 is not active in this fixture.",
    },
    "R500-DEMO-01": {
        "machine_id": "R500-DEMO-01",
        "manufacturer": "Rainer",
        "model": "R500",
        "state": "running",
        "alarms": [],
        "belt_speed_m_min": 12.0,
        "motor_current_a": 6.4,
        "note": "Sample snapshot. Current is inside the Rev B 9.5 A overload band.",
    },
    "P300-DEMO-01": {
        "machine_id": "P300-DEMO-01",
        "manufacturer": "Acme Industrial",
        "model": "P300",
        "state": "running",
        "alarms": ["P042"],
        "discharge_pressure_bar": 2.1,
        "seal_temp_c": 62,
        "note": "Sample snapshot. Discharge pressure is below the Rev D 2.8 bar alarm.",
    },
}

HISTORY = {
    "R200-DEMO-01": [
        {
            "date": "2025-11-02",
            "work": "Replaced coolant strainer. Demo CMMS record only.",
            "source": "demo-cmms",
        },
        {
            "date": "2025-08-19",
            "work": "Spindle temperature sensor calibration check. Demo CMMS record only.",
            "source": "demo-cmms",
        },
    ],
    "R500-DEMO-01": [
        {
            "date": "2025-10-11",
            "work": "Aligned infeed photoeye. Demo CMMS record only.",
            "source": "demo-cmms",
        }
    ],
    "P300-DEMO-01": [
        {
            "date": "2025-09-30",
            "work": "Replaced mechanical seal. Demo CMMS record only.",
            "source": "demo-cmms",
        }
    ],
}

LIMITS = {
    ("rainer", "r200"): {
        "model": "R200",
        "manual_revision": "C",
        "coolant_trip_bar": 1.5,
        "spindle_alarm_deg_c": 85,
        "max_spindle_rpm": 8000,
    },
    ("rainer", "r500"): {
        "model": "R500",
        "manual_revision": "B",
        "overload_amps": 9.5,
        "max_belt_speed_m_min": 18,
        "min_photoeye_margin_mm": 12,
    },
    ("acme industrial", "p300"): {
        "model": "P300",
        "manual_revision": "D",
        "low_pressure_alarm_bar": 2.8,
        "seal_temp_alarm_deg_c": 70,
        "max_flow_m3_h": 42,
    },
}


def _key(manufacturer: str, model: str) -> tuple[str, str]:
    return ((manufacturer or "").strip().lower(), (model or "").strip().lower())


def machine_information(manufacturer: str, model: str) -> dict:
    info = MACHINES.get(_key(manufacturer, model))
    if not info:
        return not_found("No demo machine matches that manufacturer and model.")
    return envelope(info)


def error_code(manufacturer: str, model: str, code: str) -> dict:
    normalized = (code or "").strip().upper()
    info = ERRORS.get((*_key(manufacturer, model), normalized))
    if not info:
        return not_found(f"No demo fixture for error code {normalized or '(blank)'}.")
    return envelope(info)


def maintenance_history(machine_id: str) -> dict:
    rows = HISTORY.get((machine_id or "").strip().upper())
    if rows is None:
        return not_found("No demo maintenance history for that machine id.")
    return envelope({"machine_id": machine_id.strip().upper(), "records": rows})


def operating_limits(model: str, manufacturer: str = "") -> dict:
    target = (model or "").strip().lower()
    for (maker, machine), limits in LIMITS.items():
        if machine == target and (not manufacturer or maker == manufacturer.strip().lower() or maker.startswith(manufacturer.strip().lower())):
            return envelope({"manufacturer": maker, **limits})
    for (maker, machine), limits in LIMITS.items():
        if machine == target:
            return envelope({"manufacturer": maker, **limits})
    return not_found("No demo operating limits for that model.")


def machine_status(machine_id: str) -> dict:
    info = STATUS.get((machine_id or "").strip().upper())
    if not info:
        return not_found("No demo status snapshot for that machine id.")
    return envelope(info)
