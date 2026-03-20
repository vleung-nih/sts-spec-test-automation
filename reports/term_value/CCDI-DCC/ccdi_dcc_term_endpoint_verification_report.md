# CCDI-DCC term endpoint verification report

**Base URL:** `https://sts-qa.cancer.gov/v2`

**Endpoint:** `GET {base}/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{termValue}`

**Input:** `ccdi_dcc_enum_terms_for_verification_enriched.csv`

**Rows skipped (neither `term_value` nor `enum_value` usable):** 0

**URL term:** `(term_value or '') or (enum_value or '')` must be non-empty after strip (legacy). Prefer API `term_value` from `/terms` when enrich resolved the handle.

**Rows verified (HTTP):** 3954

**Passed:** 3942

**Failed:** 12

## Failed rows (first 50)

| prop_handle | enum_value (handle) | term_value | http_status | notes |
|-------------|---------------------|------------|-------------|-------|
| file_type | cnn |  | 404 | non-200 |
| file_type | cnr |  | 404 | non-200 |
| file_type | mzid |  | 404 | non-200 |
| file_type | mzml |  | 404 | non-200 |
| file_type | parquet |  | 404 | non-200 |
| file_type | psm |  | 404 | non-200 |
| file_type | sf |  | 404 | non-200 |
| file_type | selfsm |  | 404 | non-200 |
| library_strategy | CITE-Seq |  | 404 | non-200 |
| library_source_molecule | Not Applicable |  | 404 | non-200 |
| diagnosis | Chondroma, NOS |  | 404 | non-200 |
| submitted_diagnosis | Chondroma, NOS |  | 404 | non-200 |

**Full results:** `ccdi_dcc_term_endpoint_verification_report.csv`
