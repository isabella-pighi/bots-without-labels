# Bots Without Labels Roadmap

This roadmap captures the remaining work for Bots Without Labels. It is written for a
wide technical audience: engineers, data scientists, product reviewers, and
stakeholders who need to understand why a change matters before deciding
whether to prioritise it.

Bots Without Labels already has a working production path: it parses raw click logs,
builds behavioural features, combines rules with an Extended Isolation Forest
anomaly score, writes `predictions.tsv`, and serves a local review dashboard.
The next improvements should make the system more stable across datasets, more
explainable to reviewers, and safer to use operationally.

## How To Read This Roadmap

| Priority | Meaning |
|---|---|
| P1 | Highest-value follow-up. Improves correctness, explainability, or operational safety. |
| P2 | Important but less urgent. Usually improves robustness, stability, or monitoring. |
| P3 | Optional or future-facing. Useful when more data, labels, credentials, or production context exist. |
| Done | Completed work kept here to preserve project history and design intent. |

The project uses unlabelled data. That means items involving probability,
precision, recall, or supervised learning should be treated carefully. Until
trusted labels exist, the system can estimate operational confidence, but it
cannot honestly claim measured fraud accuracy.

Section 8 of the report (`docs/analysis_report.md`, "Generalisation,
Shortcomings, And Future Work") is the business-facing summary of this roadmap.
Keep the two in sync: when a priority changes here, update the report's
future-work table, and vice versa.

## P1: Make Existing Detection More Stable And Explainable

### 1. Add Local Domain Reputation Signals

Behavioural detection is the core of Bots Without Labels, but domain reputation can add
useful context. The safest first step is a local, versioned blocklist rather
than live provider lookups.

For example, if a clicked domain appears on a known malware or botnet command
and control list, that should increase risk. It should not automatically decide
`is_bot`, because reputation data can be stale or broad.

**Proposed work:**

- Add an optional local domain reputation file.
- Include fields such as domain, provider, category, severity, and notes.
- Add a heuristic score contribution when a clicked domain matches.
- Preserve the reputation reason in explanations.
- Keep the pipeline fully runnable offline.

**Acceptance examples:**

- A test blocklist can flag `example-bad-domain.test` without network access.
- The event explanation says which reputation source and category matched.
- A reputation match boosts risk but does not bypass the combined scoring logic.

### 2. Explain ML Tail Events With Feature Deviations

The Extended Isolation Forest can identify unusual events, but an anomaly score
alone is not enough for a reviewer. The system should say which features made
an ML-only event stand out.

For example, an event may be in the ML tail because it combines high
query/domain repetition, high same-second density, and unusual time-to-click
reuse. Showing those feature deviations makes the ML decision easier to audit.

**Proposed work:**

- For high-anomaly events, store the top feature deviations from the batch
  baseline.
- Keep the explanation model-agnostic: explain unusual feature values rather
  than internal tree paths.
- Add the deviations to `sample_events.json`, the dashboard, and the report.

**Acceptance examples:**

- An ML-only flagged event includes a short explanation such as "query/domain
  pair frequency is in the top 1% of the batch".
- The explanation does not depend on private internals of the `isotree` model.
- The dashboard can compare heuristic reasons with ML feature deviations.

### 3. Use Robust Scaling For Heavy-Tailed Features

Click-log features are often heavy-tailed. A few domains or queries may appear
thousands of times while most appear once. Standard scaling can still leave
extreme values dominating the model.

**Proposed work:**

- Compare the current standardisation with robust scaling or quantile
  transforms.
- Measure how much the top flagged population changes.
- Keep the existing approach unless the new transform improves explanation or
  stability.

**Acceptance examples:**

- The comparison shows overlap and disagreement between current and candidate
  scaling.
- The report explains whether the change reduces over-reliance on raw volume.
- The production setting remains deterministic and reproducible.

## P2: Improve Context, Drift Awareness, And Batch Robustness

### 4. Normalise High-Volume Signals By Available Context

High-volume traffic is not always fraudulent. A legitimate campaign, region, or
inventory source can create concentrated traffic. The heuristic rules should
use available context where possible.

**Proposed work:**

- Normalise high-volume signals by fields such as domain, region, browser, OS,
  country, hour, or any future campaign/inventory metadata.
- Avoid assuming metadata exists when it is not present in the current dataset.

**Example:**

If a domain is globally popular across many devices and regions, that is less
suspicious than the same volume concentrated in one narrow
region/browser/OS/query cluster.

### 5. Validate Hostname And Apex-Domain Behaviour

Bots Without Labels keeps lowercased full host values for audit and now also derives
apex-domain features for ownership-level repetition. This reduces subdomain
fragility without erasing host-specific behaviour. The remaining work is to
validate how those two views behave across future batches.

**Proposed work:**

- Compare host-level behaviour with apex-domain grouping.
- Show where the two views agree and where they produce different high-volume
  or repeated query/domain evidence.
- Keep both views visible in reports and diagnostics until evidence supports a
  narrower production policy.

**Example:**

If `www.example.com`, `m.example.com`, and `shop.example.com` behave
differently, preserving full hostnames may protect useful signal. If they move
together across batches, the apex-domain view helps reviewers understand shared
ownership and reduces evasion through subdomain rotation.

### 6. Add Rolling Burst Features

The current system includes same-second and pseudo-session burst signals. It
should also capture rolling windows over multiple time spans.

**Proposed work:**

- Add 1-second, 10-second, and 60-second rolling windows.
- Start with query/domain and device-cluster groups.
- Keep the implementation deterministic and testable.

**Example:**

A bot may avoid exact same-second bursts by spreading clicks every two seconds.
A 60-second rolling window can still reveal the regular automated pattern.

### 7. Cache Domain Reputation Lookups

If live reputation providers are added later, the pipeline must not call a
provider once per event. That would be slow, expensive, and likely to hit rate
limits.

**Proposed work:**

- Query unique domains once per run.
- Cache results with a configurable time-to-live.
- Store provider, category, severity, and lookup timestamp.
- Keep live lookups disabled by default.

### 8. Weight Reputation Categories Differently

Not all reputation matches should carry the same weight. Malware, phishing, or
botnet command and control categories should usually matter more than a broad
"low reputation" category.

**Proposed work:**

- Map reputation categories to score weights.
- Preserve the provider category in explanations.
- Add an allowlist stage so legitimate domains can be protected from stale or
  overly broad reputation signals.

### 9. Calibrate Thresholds Against Historical Batches

Current thresholds are batch-relative. That is appropriate for a self-contained
dataset, but production use would benefit from historical stability.

**Proposed work:**

- Save compact run history: flagged rate, score quantiles, top reasons, top
  domains, and tier counts.
- Compare each new run with previous baselines.
- Warn when traffic or score distributions drift sharply.

**Example:**

If the bot rate jumps from 2.5% to 12% between runs, the dashboard should make
that visible before anyone treats the new output as normal.

## P3: Future Work That Needs More Evidence Or External Context

### 10. Add Optional Live Reputation Providers

Live providers such as Google Safe Browsing, Google Web Risk, Spamhaus DBL, or
SURBL could add stronger threat intelligence when credentials and usage terms
allow it.

**Constraints:**

- Keep live lookups optional and disabled by default.
- Never require credentials to run the local project.
- Use cached unique-domain lookups, not per-event calls.
- Document provider terms and data handling before enabling the feature.

### 11. Introduce A Labelled Cost Function For Threshold Decisions

The current `99th` percentile is the operational baseline for this project
delivery because the earlier flag rate was above the expected 1% target. This
is still an unsupervised operating point, not a measured optimum.

Once labelled validation data exist, Bots Without Labels should move from a static
percentile anchor to an explicit business utility function. That function
should assign costs to the two error types:

- false positive: legitimate human traffic is flagged as bot traffic
- false negative: bot traffic is missed and allowed through

With calibrated probabilities, the decision rule would be:

```text
P(bot | x) * C_FN > (1 - P(bot | x)) * C_FP
```

Where `P(bot | x)` is the calibrated probability that event `x` is bot traffic,
`C_FN` is the cost of missing bot traffic, and `C_FP` is the cost of wrongly
flagging human traffic. The equivalent action threshold is:

```text
tau = C_FP / (C_FP + C_FN)
```

This must not be applied directly to today's raw EIF or combined scores. Those
scores are rank-order anomaly signals, not calibrated probabilities.

**Proposed work:**

- Collect labelled review outcomes across `suppress`, `quarantine`, and
  high-scoring `monitor` traffic.
- Agree business cost weights for false positives and false negatives.
- Calibrate scores into probabilities using a trusted validation set.
- Tune the mitigation threshold against expected cost.
- Keep the current `99th` percentile baseline until labels and cost weights
  justify a replacement.

**Example:**

The immediate middle ground is the threshold sensitivity table in the report
and dashboard. It shows the business what happens without changing production
code:

| Threshold percentile | Business posture | Estimated human false-positive risk | Primary characteristics captured |
|---|---|---|---|
| 95th | Broader capture for infrastructure protection | High | Broad behavioural shifts and moderate-speed anomalies |
| 97.5th | Wider review net | Moderate | Blended mechanical indicators and high-velocity clusters |
| 99th | Current operational anchor | Low | Extreme anomalies and stronger timing or repetition evidence |
| 99.5th | Strictest review population | Very low | Strictest structural automation and scripted repetition patterns |

If protecting human user experience is the priority, the future cost function
may push the threshold above the `99th` percentile. If infrastructure or
ad-fraud exposure is the priority, it may justify a lower threshold closer to
the `95th` percentile. The current sensitivity table exposes this operational
trade-off around the submitted baseline.

**Future production path:**

- Proxy and baseline validation: monitor threshold behaviour against known-good
  traffic slices, such as highly verified logged-in accounts, to map the
  false-positive cliff.
- Weak supervision and manual review: combine consensus-style weak supervision
  with targeted inspection of sampled tails to gain directional validation
  data.
- Probability calibration: use isotonic regression or Platt scaling on a
  validated holdout to convert anomaly scores into probability estimates,
  enabling formal cost-utility thresholding in production.

### 12. Add Labelled Validation

The most important future improvement is labelled validation. Labels could come
from manual review, invalid-traffic feedback, chargebacks, confirmed abuse
reports, or trusted campaign investigations.

With labels, Bots Without Labels could move from operational confidence estimates to
measured precision, recall, calibration, threshold optimisation, and the
cost-function work described above.

**Proposed work:**

- Sample events across `suppress`, `quarantine`, and `monitor` tiers.
- Collect reviewer labels and reasons.
- Train or evaluate supervised models only when label quality is good enough.
- Keep the current rules plus EIF path as the production baseline until labels
  justify a replacement.

### 13. Add Graph Features On Stable Identifiers

The current features describe each click largely on its own. Once stable links
such as IP address, user, or account become available, graph features could
surface coordinated behaviour that per-event signals miss.

**Proposed work:**

- When stable identifiers exist, build a click graph linking events through
  shared identifiers, domains, and query/domain pairs.
- Derive features such as shared-identifier fan-out, connected-component size,
  and repeated edges between the same entities.
- Keep this optional and disabled when no stable identifier is present, so the
  current schema-only path is unaffected.

**Example:**

Many clicks that look unremarkable alone can form a tight cluster once linked by
a shared IP or account, revealing a coordinated campaign that event-level
scoring would rate as borderline.

## Completed Work

These items are done and retained here because they explain why the current
pipeline looks the way it does.

| Area | Completed item | Why it mattered |
|---|---|---|
| Anomaly classifier | Added `is_sub_200ms_click` | Makes sub-human reaction timing explicit for ML, not only the rules layer. |
| Anomaly classifier | Added 10-second pseudo-session burst density | Captures coordinated click patterns that exact same-second counts can miss. |
| Anomaly classifier | Added query entropy | Helps distinguish natural-looking query text from synthetic or random strings. |
| Anomaly classifier | Removed raw `kp` and `sld` values while retaining aggregate counts | Keeps low-cardinality identifiers out as numeric values, while preserving `log_kp_count` and `log_sld_count` as categorical context features. |
| Anomaly classifier | Consolidated production scoring on Extended Isolation Forest | Removes alternate backend drift and keeps output semantics consistent. |
| Explainability | Added structured rule contributions | Gives stable rule IDs, labels, weights, observed values, and thresholds for audits. |
| Rules classifier | Added concentrated `ct` context as supporting evidence | Lets the rules layer use country-like concentration only when paired with repeated query behaviour and clustering. |
| Rules classifier | Made count-based heuristic thresholds adaptive | Keeps repeated-query, domain, device, same-second, country, and exact time-to-click rules stable across different batch sizes by comparing counts with the current population while retaining conservative fixed guardrails for small inputs. |
| Rules classifier | Split strong and supporting rule evidence | Prevents weaker contextual signals from accumulating into the same meaning as direct mechanical or replay evidence, while still showing reviewers how each rule contributed to the final score. |
| Decision logic | Added `suppress`, `quarantine`, and `monitor` tiers | Turns scores into practical actions without pretending unlabelled data has measured precision. |
| Decision logic | Added method disagreement buckets | Makes rules/ML agreement and disagreement visible for review. |

## Suggested Next Slice

The best next implementation slice is:

1. feature-deviation explanations for ML tail events
2. local domain reputation signals
3. context-normalised high-volume signals

Those three items improve the current system without requiring external
credentials, live services, or labels. They also make the dashboard and report
more defensible because reviewers can see not just that an event was flagged,
but why the system considered the evidence strong.
