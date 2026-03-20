# CCDI term endpoint verification report

**Base URL:** `https://sts-qa.cancer.gov/v2`

**Endpoint:** `GET {base}/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{termValue}`

**Input:** `ccdi_enum_terms_for_verification_enriched.csv`

**Rows skipped (no API `term_value`):** 0 (YAML handle could not be resolved from paginated `/terms`; `/term/{termValue}` requires the Term **value**, not the handle.)

**Rows verified (HTTP):** 2663

**Passed:** 2663

**Failed:** 0


**Full results:** `ccdi_term_endpoint_verification_report.csv`
