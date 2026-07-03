"""Generality guard: CTU-13 scenario 3 (Rbot) -- a second, independent family.

Scenario 1 (Neris) showed that connectivity asymmetry (``asymmetric_degree``)
recovers a diverse directional bot. The open question this benchmark answers is
whether that *recall* win generalises beyond the family the rule was developed
against. Scenario 3 is the Rbot botnet (a different malware family, a different
capture), wired through the same wrapper.

What the measurement found (reported, not tuned):

* The **recall generalises**: ``asymmetric_degree`` recovers Rbot too
  (recall ~0.985), so the directional-asymmetry signal is not Neris-specific.
* But the rule's **Neris-level cleanliness does not generalise**: on this
  capture ``asymmetric_degree`` over-fires (fire-precision ~0.056 vs 1.000 on
  Neris), so overall precision stays low (~0.056) and the flag rate is high.
  The ``DEGREE_ASYMMETRY`` / degree-floor constants are documented in
  ``rules.py`` as limited-evidence guardrails, and Rbot is evidence they are
  not scale-free. This is a detector-generality gap tracked for a separate
  decision -- *not* fixed here, and deliberately not tuned around.

So this guard pins the generality *recall* win and the rare-attack shape, but --
exactly like the sc1 guard -- does **not** pin overall precision.

The flow file is gitignored, large (640 MB, above the 400 MB ceiling), and an
opt-in local fetch, so this test skips unless it is present; download
instructions are in :mod:`evaluation.ctu13_bot_benchmark`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.ctu13_bot_benchmark import SCENARIOS, _scenario_label, run
from tests.conftest import assert_ctu13_rare_attack_recall

SC3_BINETFLOW = SCENARIOS["sc3"]["binetflow"]


def test_scenario_label_does_not_mislabel_binetflow_override() -> None:
    # CLI labelling guard (no data needed): a --binetflow override must NOT
    # inherit the default sc1 heading. The sc3 capture, even with the default
    # --scenario sc1, must be labelled sc3 so copied evidence names the right
    # CTU family; an unknown path gets an explicit custom heading.
    assert _scenario_label("sc1", None) == SCENARIOS["sc1"]["name"]
    assert _scenario_label("sc3", None) == SCENARIOS["sc3"]["name"]
    sc3_label = _scenario_label("sc1", SCENARIOS["sc3"]["binetflow"])
    assert sc3_label == SCENARIOS["sc3"]["name"]
    assert "scenario 3" in sc3_label and "scenario 1" not in sc3_label
    custom = _scenario_label("sc1", Path("data/unknown_capture.binetflow"))
    assert "custom" in custom and "scenario 1" not in custom


@pytest.mark.skipif(
    not Path(SC3_BINETFLOW).exists(),
    reason=(
        f"CTU-13 sc3 binetflow {SC3_BINETFLOW} not present "
        "(opt-in local fetch; see evaluation.ctu13_bot_benchmark)"
    ),
)
def test_ctu13_sc3_recall_generalises() -> None:
    report = run(SC3_BINETFLOW)

    # Same mix shape, sub-second premise, and recall guard as sc1. The generality
    # win is that the diverse directional bot is still recovered on a second,
    # independent family. Precision is NOT pinned -- on this capture
    # asymmetric_degree over-fires, capping precision; that is a tracked
    # detector-generality gap (mirrors the sc1 guard).
    assert_ctu13_rare_attack_recall(report)
