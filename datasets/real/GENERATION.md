# report.md generation cost (C2)

Written by `scripts/gen_real_reports.py` with `LLM.cheap()` and `prompts/report_from_arvo.md`.
Cost uses `REPRO_CHEAP_PRICE_IN/OUT` from `.env`; tokens are exact from the API usage block.

| Folder | Model | Calls | Attempts | Tokens in | Tokens out | Cost (USD) |
|---|---|---|---|---|---|---|
| arvo-11504-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1696 | 657 | 0.0000 |
| arvo-11504-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1198 | 665 | 0.0000 |
| arvo-1454-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1646 | 753 | 0.0000 |
| arvo-1454-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1130 | 701 | 0.0000 |
| arvo-15373-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1675 | 729 | 0.0000 |
| arvo-15373-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1138 | 730 | 0.0000 |
| arvo-35821-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1718 | 784 | 0.0000 |
| arvo-35821-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1176 | 768 | 0.0000 |
| arvo-42487096-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1650 | 680 | 0.0000 |
| arvo-42487096-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1161 | 688 | 0.0000 |
| arvo-43601-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1657 | 559 | 0.0000 |
| arvo-43601-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1155 | 693 | 0.0000 |
| arvo-49546-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1623 | 707 | 0.0000 |
| arvo-49546-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1204 | 609 | 0.0000 |
| arvo-54949-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1673 | 784 | 0.0000 |
| arvo-54949-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1180 | 705 | 0.0000 |
| arvo-56710-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1556 | 705 | 0.0000 |
| arvo-56710-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1152 | 586 | 0.0000 |
| arvo-56893-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1627 | 726 | 0.0000 |
| arvo-56893-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1158 | 641 | 0.0000 |
| arvo-781-text_only | meta-models/muse-spark-open-1026 | 1 | 1 | 1579 | 680 | 0.0000 |
| arvo-781-with_poc | meta-models/muse-spark-open-1026 | 1 | 1 | 1129 | 639 | 0.0000 |
| **total (22)** | | 22 | | 30881 | 15189 | 0.0000 |

Per report: 1403 in / 690 out tokens, $0.0000 on average.
