# CDS term endpoint verification report

**Base URL:** `https://sts-qa.cancer.gov/v2`

**Endpoint:** `GET {base}/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{termValue}`

**Input:** `cds_enum_terms_for_verification_enriched.csv`

**Note:** `termValue` in the URL is the YAML **enum_value** (CDS legacy behavior; no `/terms` handle→value enrichment).

**Rows verified:** 9329

**Passed:** 9329

**Failed:** 0


**Full results:** `cds_term_endpoint_verification_report.csv`
