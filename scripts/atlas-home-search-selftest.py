#!/usr/bin/env python3
"""Synthetic gates for the two opt-in `HomeIndex` candidate-search lanes."""

from __future__ import annotations

from atlas_home import HomeIndex


def fixture() -> HomeIndex:
    index = HomeIndex.__new__(HomeIndex)
    index.rows = {
        "Demo.target": {
            "name": "Demo.target",
            "module": "Demo",
            "kind": "theorem",
            "uses_statement": ["Demo.needsDiv", "Demo.needsZero", "Demo.needsTopology"],
            "uses_proof": [],
        },
        "Demo.multi": {
            "name": "Demo.multi",
            "module": "Demo",
            "kind": "theorem",
            "uses_statement": ["Demo.needsDiv", "Demo.needsZero", "Demo.needsTopology"],
            "uses_proof": [],
            "requirements_statement": [
                {"source": "Demo.needsDiv", "class": "Div", "carrier": 0},
                {"source": "Demo.needsZero", "class": "Zero", "carrier": 0},
                {"source": "Demo.needsTopology", "class": "Topology", "carrier": 2},
            ],
        },
        "Demo.classClaim": {
            "name": "Demo.classClaim",
            "module": "Demo",
            "kind": "theorem",
            "is_instance": False,
            "uses_statement": ["Demo.needsDiv", "Demo.needsZero"],
            "uses_proof": [],
            "requirements_statement": [
                {"source": "Demo.needsDiv", "class": "Div", "carrier": 0},
                {"source": "Demo.needsZero", "class": "Zero", "carrier": 0},
            ],
        },
        "Demo.registered": {
            "name": "Demo.registered",
            "module": "Demo",
            "kind": "theorem",
            "is_instance": True,
            "uses_statement": ["Demo.needsDiv", "Demo.needsZero"],
            "uses_proof": [],
            "requirements_statement": [
                {"source": "Demo.needsDiv", "class": "Div", "carrier": 0},
                {"source": "Demo.needsZero", "class": "Zero", "carrier": 0},
            ],
        },
        "Demo.legacyProducer": {
            "name": "Demo.legacyProducer",
            "module": "Demo",
            "kind": "theorem",
            "uses_statement": ["Demo.needsDiv", "Demo.needsZero"],
            "uses_proof": [],
            "requirements_statement": [
                {"source": "Demo.needsDiv", "class": "Div", "carrier": 0},
                {"source": "Demo.needsZero", "class": "Zero", "carrier": 0},
            ],
        },
        "Demo.nonTheoremProducer": {
            "name": "Demo.nonTheoremProducer",
            "module": "Demo",
            "kind": "def",
            "is_instance": False,
            "uses_statement": ["Demo.needsDiv", "Demo.needsZero"],
            "uses_proof": [],
            "requirements_statement": [
                {"source": "Demo.needsDiv", "class": "Div", "carrier": 0},
                {"source": "Demo.needsZero", "class": "Zero", "carrier": 0},
            ],
        },
    }
    # In Demo.target's ContinuousLike application, b2 is the structural carrier and b0 is
    # its synthesized Topology instance. The frozen rule selects b0; the search rule uses
    # ContinuousLike's parameter roles and selects b2.
    index.binders = {
        "Source": [("d", None, [], 0)],
        "Target": [("d", None, [], 0)],
        "Distractor": [("d", None, [], 0)],
        "Div": [("d", None, [], 0)],
        "Zero": [("d", None, [], 0)],
        "Topology": [("d", None, [], 0)],
        "ContinuousLike": [
            ("d", None, [], 0),
            ("t", "Topology", [("b", 0)], 1),
            ("t", "Div", [("b", 1)], 2),
        ],
        "Demo.target": [
            ("i", None, [], 0),
            ("t", "Source", [("b", 0)], 1),
            ("t", "Topology", [("b", 1)], 2),
            ("t", "ContinuousLike", [("b", 2), ("b", 0), ("o", 0)], 3),
        ],
        "Demo.multi": [
            ("i", None, [], 0),
            ("t", "Source", [("b", 0)], 1),
            ("i", None, [], 2),
            ("t", "Topology", [("b", 0)], 3),
        ],
        "Demo.classClaim": [
            ("i", None, [], 0),
            ("t", "Source", [("b", 0)], 1),
        ],
        "Demo.registered": [
            ("i", None, [], 0),
            ("t", "Source", [("b", 0)], 1),
        ],
        "Demo.legacyProducer": [
            ("i", None, [], 0),
            ("t", "Source", [("b", 0)], 1),
        ],
        "Demo.nonTheoremProducer": [
            ("i", None, [], 0),
            ("t", "Source", [("b", 0)], 1),
        ],
        "Demo.needsDiv": [("t", "Div", [("b", 0)], 1)],
        "Demo.needsZero": [("t", "Zero", [("b", 0)], 1)],
        "Demo.needsTopology": [("t", "Topology", [("b", 0)], 1)],
    }
    index.concl = {}
    index.classes = {
        "Source", "Target", "Distractor", "Div", "Zero", "Topology", "ContinuousLike"
    }
    index.produces_class = {
        "Demo.classClaim", "Demo.registered", "Demo.legacyProducer",
        "Demo.nonTheoremProducer",
    }
    index.parents = {
        "Source": {"Target", "Distractor"},
        "Target": {"Div", "Zero"},
        "Distractor": {"Div"},
    }
    index.projection_like = set()
    index.forgetful = set()
    index._anc_cache = {}
    index.parse_errors = 0
    return index


def main() -> int:
    index = fixture()
    assert index.instance_binders("Demo.target") == [
        ("Source", 0), ("Topology", 0), ("ContinuousLike", 2)
    ]
    assert index.home("Demo.target") == {"skipped": "multi-carrier", "carriers": 2}
    assert index.parameter_aware_instance_binders("Demo.target") == [
        ("Source", 0), ("Topology", 0), ("ContinuousLike", 0)
    ]
    result = index.statement_candidates("Demo.target")
    assert result is not None and "skipped" not in result
    by_class = {binder["class"]: binder for binder in result["binders"]}
    assert by_class["Source"] == {
        "class": "Source",
        "verdict": "candidates",
        "reached": ["Div", "Zero"],
        "candidates": ["Target"],
    }
    assert by_class["Topology"]["verdict"] == "at-home"
    assert by_class["ContinuousLike"]["verdict"] == "unused"
    assert index.statement_candidates("Demo.multi") == {
        "skipped": "multi-carrier", "carriers": 2
    }
    attached = index.carrier_statement_candidates("Demo.multi")
    assert attached is not None and "skipped" not in attached
    by_class = {binder["class"]: binder for binder in attached["binders"]}
    assert by_class["Source"] == {
        "class": "Source",
        "carrier": 0,
        "verdict": "candidates",
        "reached": ["Div", "Zero"],
        "candidates": ["Target"],
    }
    assert by_class["Topology"] == {
        "class": "Topology",
        "carrier": 2,
        "verdict": "at-home",
        "candidates": [],
    }
    assert index.carrier_statement_candidates("Demo.target") == {
        "skipped": "no-carrier-evidence"
    }
    # The two frozen methods retain the blanket class-producing guard. The opt-in carrier
    # lane may judge only an explicit non-instance; registered and legacy rows stay safe.
    assert index.home("Demo.classClaim") == {"skipped": "produces-a-class"}
    assert index.statement_candidates("Demo.classClaim") == {"skipped": "produces-a-class"}
    class_claim = index.carrier_statement_candidates("Demo.classClaim")
    assert class_claim is not None and class_claim["binders"] == [{
        "class": "Source",
        "carrier": 0,
        "verdict": "candidates",
        "reached": ["Div", "Zero"],
        "candidates": ["Target"],
    }]
    assert index.carrier_statement_candidates("Demo.registered") == {
        "skipped": "produces-a-class"
    }
    assert index.carrier_statement_candidates("Demo.legacyProducer") == {
        "skipped": "produces-a-class"
    }
    assert index.carrier_statement_candidates("Demo.nonTheoremProducer") == {
        "skipped": "produces-a-class"
    }
    print("atlas_home statement search: roles + carrier-attached cover enumeration  OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
