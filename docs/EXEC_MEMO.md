# Memo: Bots Without Labels — where it stands and what to fund next

**Bottom line:** The detector now produces a defensible result on real, labeled botnet traffic — recall 0.998 at precision 0.879 — but it is a ranking tool that tells analysts where to look, not a system that decides who is a bot. Treat its output as triage, not judgment.

## What changed, plainly

We stopped trusting our own synthetic tests. They reported near-perfect scores
because they planted exactly what the detector was built to find — we were grading
ourselves. On real labeled data, the early detector was worse than random (precision
below the base rate). Two design changes fixed that, in order:

1. **Per-entity baselines** — judge each actor against its own behavior. Recovered
   recall (near zero → 0.998), but over-flagged busy-but-legitimate servers.
2. **Graph/hub structure** — only escalate actors that sit in bot-like connectivity.
   This is what bought precision (0.144 → 0.441 → 0.846 after timing calibration, then
   0.879 after decoupling the sparse-timing sentinel from the ML feature matrix) and
   cut false alarms.

These two are the real assets. Everything else is tuning.

## What the evidence supports

- A real, externally-validated operating point on a botnet capture: recall 0.998,
  precision 0.879, 3.6% flag rate.
- A graph signal that catches *diverse* bots — the kind that beat our earlier rules —
  cleanly (every planted bot, no false fires from that rule).
- A method honest about its own limits: thresholds are batch-relative because we have
  no labels to anchor them.

## What not to claim

- Not a fraud verdict. Scores rank suspicion; they are not probabilities and must not
  be sold as accuracy guarantees.
- Synthetic numbers are not field numbers. Necessary for stress-testing, useless as a
  performance claim.
- One win is not generality. The newest result is on a single attack family and one
  log type; we have not shown it transfers.
- Timing features are conditional — they need fine timestamps and quietly do nothing
  (or harm) on coarse logs.

## Decisions to fund next

1. **Cut the remaining false positives.** They come from the older rules, not the new
   graph signal. This is the highest-value work: it is where precision on diverse
   traffic actually gets won.
2. **Prove generality.** Validate the graph signal on a second, independent attack
   family before we describe it as a general capability.
