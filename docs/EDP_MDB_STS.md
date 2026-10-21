# Extended Definition Properties (EDPs): MDB and STS

This is the end-to-end guide for **Extended Definition Properties**. It is for engineers and data modelers who need one picture of what an EDP is, how it lands in the Metamodel Database (MDB), how the Simple Terminology Server (STS) exposes it, and which MDF and HTTP pieces actually connect a model property to a shared value list.

STS paths below are relative to `/v2`. Example hosts:

| Host | Base URL |
|------|----------|
| sts-dev.cancer.gov | `https://sts-dev.cancer.gov/v2` |
| sts-qa.cancer.gov | `https://sts-qa.cancer.gov/v2` |
| sts-stage.cancer.gov | `https://sts-stage.cancer.gov/v2` |
| sts.cancer.gov | `https://sts.cancer.gov/v2` |

EDP HTTP routes shipped with STS **API version 2.6.0**.

---

## 1. What an EDP is, and what it is for

**EDP** means **Extended Definition Property**. It is a named, versioned list of **permissible values (PVs)** stored once in MDB and served by STS.

Without EDPs, a model copies every allowed string into MDF (`Enum:` with hundreds or thousands of lines). That does not scale for vocabularies such as Uberon (~12k terms), OBIB, or ICD-O. An EDP holds that list **once**. A model property **points at** the EDP instead of duplicating the list. After ingest, STS can return the same shared PVs both as the EDP itself and as that property’s terms.

Each EDP is identified by three fields:

| Field | Meaning | Example |
|-------|---------|---------|
| `origin_name` | Authority | `CRDC` or `caDSR` |
| `origin_id` | Code | `CRDC0002` or `7572817` |
| `origin_version` | Version of **that** list | `1` or `2.0` |

CRDC custom IDs are `CRDC` plus digits (`CRDC0001`). The version string must match MDB exactly (`2.0` is not `2.00`; `3.2` is not `3.20`).


| Kind | `origin_name` | STS catalog | PV list | Legacy `cde-pvs` |
|------|----------------|-------------|---------|------------------|
| caDSR | `caDSR` | `GET /edps/caDSR` | `GET /edp/caDSR/{id}/{ver}/terms` | Yes — same unique PV **labels** |
| CRDC custom | `CRDC` | `GET /edps/CRDC` | `GET /edp/CRDC/{id}/{ver}/terms` | **No** — EDP-only |

CRDC EDPs currently used on the TEST model and on STS:

| origin_id | origin_version | What it is | Approx. PV count | Authored in current `bento-edps`? |
|-----------|----------------|------------|------------------|-----------------------------------|
| CRDC0001 | 1 | Uberon | ~12,854 | **No** — present on STS and consumed by TEST; not in the current `bento-edps` tree or `mdb_edps.yml` |
| CRDC0002 | 1 | OBIB (specimen) | 128 | **Yes** (`obib_terms_valueset`) |
| CRDC0003 | 3.2 | ICD-O morphology | 1,183 | **No** — same as CRDC0001: on STS and TEST, not in current `bento-edps` |
| CRDC0005 | 1 | TEST-model verification EDP (not for production commons) | small | **Yes** (`qa_test_valueset`) |

---

## 2. How it sits in the MDB graph

STS does not invent PV lists. It reads Neo4j.

An EDP in the graph is:

- a **defining term** (the EDP itself — origin, id, version, display value)
- a **value_set**
- **PV terms** (each allowed string)

```text
(edp:term)-[:specifies_value_set]->(vs:value_set)-[:has_term]->(pv:term)
```

When a **model property consumes** the EDP, ingest links that property to the **same** value_set rather than copying thousands of strings onto the property. STS `GET /edp/.../terms` walks the defining term → value_set → PV terms. STS `GET /model/.../property/.../terms` walks the **property’s** value_set. After a correct consume + ingest, those two PV **value** sets match.

**HTTP 404** on `/edp/{origin}/{id}/{version}/terms` means that triple is not in the graph **for that environment** (not loaded, not promoted, or the version string does not match).

---

## 3. Repos involved

| Repo | Role |
|------|------|
| [CBIIT/bento-edps](https://github.com/CBIIT/bento-edps) | Author CRDC custom EDP YAML (`model-desc/edp-props.yml` + `model-desc/terms/*.yml`). |
| [CBIIT/bento-mdb](https://github.com/CBIIT/bento-mdb) | `config/mdb_edps.yml` (which EDPs to poll) and GitHub Actions that check, changelog, and apply EDPs to CloudOne / FNL Dev. |
| [CBIIT/bento-mdf](https://github.com/CBIIT/bento-mdf) | MDF reader. Enum **term-references** become `value_set.edp_terms`. `resolve_edps` can fetch STS `/edp/.../terms` when expanding PVs. |
| [CBIIT/bento-sts-monorepo](https://github.com/CBIIT/bento-sts-monorepo) | STS FastAPI: `/edps`, `/edp/.../terms`, `/edps/.../properties`, and model property `/terms`. |
| [CBIIT/ctos-test-model](https://github.com/CBIIT/ctos-test-model) | **TEST** data model — the working Enum→EDP consumers (`model-desc/test-model-props.yml`). |

`bento-mdb-workflow` holds private promotion / model / term automation. The **EDP load** workflows themselves live in **public** `bento-mdb` `.github/workflows/`, not in `bento-mdb-workflow`.

---

## 4. End-to-end data flow

Two pipelines write to the **same** MDB graph. STS does not store its own copy; it only reads that graph.

- **Pipeline A** loads the shared list (the EDP itself).
- **Pipeline B** points a model property at that list. It does **not** copy the PVs.

A property can only consume an EDP that already exists in that environment’s graph. Load first, then ingest the model. Authoring details are in [§5](#5-authoring-a-crdc-edp-bento-edps); consume details are in [§7](#7-how-a-data-modeler-consumes-an-edp).

caDSR lists are already in MDB from the caDSR load. The numbered Pipeline A below is the **CRDC custom** path (`bento-edps` → Dev MDB → later environments). Pipeline B is the same for both origins: an Enum term-reference plus model ingest.

```mermaid
flowchart LR
  author["bento-edps YAML"] --> check["Check New EDPs"]
  check --> gen["Generate EDP Changelog"]
  gen --> apply["Update C1-MDB-DEV EDPs"]
  apply --> promote["Dev then sts-qa stage prod"]
  mdf["Commons or TEST MDF Enum term-ref"] --> ingest["Model ingest"]
  promote --> graph["MDB graph"]
  ingest --> graph
  graph --> sts["STS /edps /edp /model property terms"]
```

### Pipeline A — load the list

1. A data modeler authors the EDP in `bento-edps`: identity (`Origin`, `Code`, `Version`) plus the PV strings (`Enum`) and per-value term files. Merge that to `bento-edps` main.
2. An engineer registers the same identity in `bento-mdb` `config/mdb_edps.yml` (origin, code, property handle, terms files) if this is a **new** EDP. Without that row, the daily poll will not pick it up.
3. **Check New EDPs** (GitHub Action in `bento-mdb`) checks out `bento-edps` and compares it to `mdb_edps.yml`. It runs daily at 22:30 UTC, or on `workflow_dispatch`.
4. If the specs changed, **Generate EDP Changelog** builds changelog XML for the defining term, the value_set, and the PV terms, then uploads it to S3.
5. **Update C1-MDB-DEV EDPs** applies that changelog to CloudOne Dev MDB. The FNL Dev apply is a parallel job in the same family.
6. Promotion copies that graph to later environments (sts-qa, stage, prod). The EDP is not visible on a later host until that environment has been promoted.
7. Confirm on that environment’s STS:
   - `GET /edps/CRDC` includes the defining term (`origin_id` + `origin_version`).
   - `GET /edp/CRDC/{id}/{ver}/terms` returns the PV list (HTTP 200). A 404 means this triple is not in **that** environment’s graph yet, or the version string does not match.

Workflow YAML names and triggers are in [§6](#6-pipeline-workflows-public-bento-mdb).

### Pipeline B — a model uses the list

1. A data modeler adds an **Enum term-reference** on the property (`Origin` + `Code` + `Version` of the EDP). Do **not** paste the PV strings, and do **not** rely on `Term:` for this — `Term:` is metadata only.
2. That MDF is released with the model (for example TEST in `ctos-test-model`).
3. **Model ingest** reads the Enum term-reference (`value_set.edp_terms`) and links the property to the **existing** EDP value_set. It does not copy thousands of PV strings onto the property.
4. Confirm on that environment’s STS:
   - `GET /model/{model}/version/{ver}/node/{node}/property/{prop}/terms` returns the same PV **values** as `/edp/{origin}/{id}/{ver}/terms`.
   - `GET /edps/{origin}/{id}/{ver}/properties` lists this property.

If property `/terms` is empty or a short inline list while `/edp/.../terms` is large, ingest did not consume the EDP (wrong MDF shape, or the EDP was not in the graph yet).

### What you have after both

| You did | Graph | STS shows |
|---------|-------|-----------|
| A only | Defining term + value_set + PV terms | Catalog + `/edp/.../terms`. `/edps/.../properties` does not list your field yet. |
| B only | Property with no shared value_set (or ingest skipped) | Property `/terms` is not the EDP list; `/edp/.../terms` may 404. |
| A then B | Property linked to the **same** value_set | Property `/terms` matches `/edp/.../terms`; the property appears on `/edps/.../properties`. |

---

## 5. Authoring a CRDC EDP (`bento-edps`)

This is how you **create the shared list**. It is not how a commons model consumes it. Consumption is [§7](#7-how-a-data-modeler-consumes-an-edp).

Layout:

```text
bento-edps/
└── model-desc/
    ├── edp-props.yml
    └── terms/
        ├── obib-terms.yml
        └── qa-test-terms.yml
```

`edp-props.yml` declares each EDP under `PropDefinitions`. Required pieces:

- `Ext: true` — marks this entry as an EDP **definition**
- `Term:` — identity of the EDP (`Origin`, `Code`, `Version`, `Value`, `Definition`)
- `Enum:` — the current list of PV **strings**

```yaml
PropDefinitions:
  obib_terms_valueset:
    Desc: Standardized PVs (from OBIB) describing biological specimens
    Ext: true
    Term:
      - Origin: CRDC
        Code: "CRDC0002"
        Version: "1"
        Value: Obib Value Set Reference
        Definition: EDP for OBIB specimen PVs
    Enum:
      - "blood specimen"
      - "bone marrow specimen"
```

`terms/*.yml` adds origin/code/definition metadata for each Enum string, keyed by the same value.

**Adding a new EDP:** new `PropDefinitions` entry, new terms file, PR to `bento-edps` main, add a matching block in `bento-mdb` `config/mdb_edps.yml` (origin, code, property handle, terms files). The daily Check New EDPs poll then sees it.

**Updating PVs:** append to `Enum` (and the terms file) to add; remove from `Enum` to stop advertising a value. **Removing a value from YAML does not yet delete it from MDB.** Old PV terms can remain in the graph until a delete path exists.

The `bento-edps` README section “Referencing an EDP from your model” shows `Term:` plus a **local string** `Enum:` list. That is the shape of **authoring** the EDP (or a mistaken consume example). It is **not** how a commons or TEST property should attach to a shared list. Follow [§7](#7-how-a-data-modeler-consumes-an-edp) instead.

---

## 6. Pipeline workflows (public `bento-mdb`)

These GitHub Actions load CRDC EDPs into Dev MDB. Confirm afterward on STS: a catalog row on `/edps/CRDC` and HTTP 200 on `/edp/CRDC/{id}/{ver}/terms`.

| GitHub Actions name | YAML | What it does |
|---------------------|------|----------------|
| Check New EDPs | `check_new_edps.yml` | Daily 22:30 UTC (and `workflow_dispatch`). Checks out `CBIIT/bento-edps`, compares to `config/mdb_edps.yml`. |
| Generate EDP Changelog | `generate_edp_changelog.yml` | Runs after Check New EDPs succeeds (or dispatch). Builds changelog XML (defining term, value_set, PV terms) and uploads to S3. |
| Update C1-MDB-DEV EDPs | `update_mdb_edps_c1.yml` | Applies that changelog to **CloudOne Dev** MDB (`cloud-one-mdb-dev`). |
| Update FNL-MDB-DEV EDPs | `update_mdb_edps_fnl.yml` | Same family of apply, default `fnl-mdb-dev`. |

Chain: **Check New EDPs** → **Generate EDP Changelog** → **Update C1-MDB-DEV EDPs** (and the FNL apply).

**Promotion** after Dev is the same data-promotion path used for other MDB content (Dev, then later environments). Confirm on that environment’s STS with the same two GETs.

---

## 7. How a data model consumes an EDP

Example TEST data model (`ctos-test-model` `model-desc/test-model-props.yml`).

### 7.1 `Term:` vs `Enum:` (settled)

| MDF section | What it is | Consumes an EDP? | Property `/terms` after ingest |
|-------------|------------|------------------|--------------------------------|
| **`Term:`** | Metadata: which CDE *describes* the property | **No** | Not the EDP list |
| **`Enum:` term-reference** (`Origin` + `Code` + `Version`) | Pointer at a shared MDB value set | **Yes** | Same PV values as `/edp/.../terms` |
| **`Enum:` list of strings** | Private inline value set | **No** | Those strings only — **not** an EDP |

MDB ingest decides EDP linkage from the Enum term-reference (`value_set.edp_terms` / `get_edp_enum_term()` in `bento-mdb`). It does **not** treat `Term:` as the consume.

`Ext: true` belongs on the **EDP definition** in `bento-edps`. TEST consume properties do not set `Ext: true`.

### 7.2 Consume: Enum term-reference

After ingest, the property appears on `/edps/{origin}/{id}/{ver}/properties` and property `/terms` matches `/edp/.../terms`.

```yaml
anatomic_site:
  Desc: Biological specimen anatomic site — CRDC EDP consumer (OBIB)
  Enum:
    - Origin: CRDC
      Code: CRDC0002
      Value: obib value set reference
      Version: "1"
  Strict: false
```

Use the **exact** `Code` and `Version` stored in MDB. `Strict: true` means only values from that list are allowed; `Strict: false` is a looser model choice (TEST uses both to contrast).

### 7.3 Both `Term:` and `Enum:` on one property

Allowed. `Term:` documents the CDE; `Enum:` term-ref is what links the shared value set.

```yaml
sex_at_birth:
  Desc: Person sex at birth — caDSR EDP consumer
  Term:  # metadata only
    - Origin: caDSR
      Code: '7572817'
      Value: Person Sex at Birth Category
      Version: "2.0"
  Enum:  # this consumes the EDP
    - Origin: caDSR
      Code: '7572817'
      Value: Person Sex at Birth Category
      Version: "2.0"
  Strict: true
```

If you keep `Term:` and drop the Enum term-ref, ingest will **not** treat the property as EDP-backed.

### 7.4 Does **not** consume an EDP

**Term-only** Must **not** appear on `/edps/caDSR/.../properties`:

```yaml
cde_term_only:
  Desc: Control — CDE documents the property; Enum does not reference an EDP
  Term:
    - Origin: caDSR
      Code: '6824805'
      Value: unit of measure
      Version: "5.00"
  Type: string
```

**Inline string Enum** Private list; must **not** appear on any `/edps/.../properties`:

```yaml
sample_type:
  Enum:
    - normal
    - tumor
```

---

## 8. STS routes: which URL to use

These five calls are not interchangeable.

| Call | What it returns | Use it for |
|------|-----------------|------------|
| `GET /model/{model}/version/{ver}/node/{node}/property/{prop}/terms` | PVs attached to **this property** after ingest | Allowed values for **this field**. |
| `GET /edp/{origin}/{id}/{ver}/terms` | PVs of the **shared EDP** | The catalog list. Same PV **values** as the property `/terms` **if** that property consumed the EDP. Not a substitute for “this property’s terms” until ingest linked them. |
| `GET /edps/{origin}` | Defining terms for that origin | Catalog / discovery. Not the PV list for one property. |
| `GET /edps/{origin}/{id}/{ver}/properties` | Model properties that consumed this EDP | Reverse lookup. Empty (and the property is Term-only or inline Enum) means this property is **not** EDP-backed. |
| `GET /terms/cde-pvs/{id}/{ver}/pvs` | Legacy caDSR CDE wrappers | Compare unique labels to `/edp/caDSR/.../terms`. **Not** for CRDC000x. |

Examples (`sts-qa.cancer.gov`):

```text
GET https://sts-qa.cancer.gov/v2/edps/CRDC?limit=999999
GET https://sts-qa.cancer.gov/v2/edp/CRDC/CRDC0002/1/terms?limit=999999
GET https://sts-qa.cancer.gov/v2/edps/CRDC/CRDC0002/1/properties
GET https://sts-qa.cancer.gov/v2/edp/caDSR/7572817/2.0/terms
GET https://sts-qa.cancer.gov/v2/model/TEST/version/{latest}/node/sample/property/anatomic_site/terms
```

**After a correct consume + ingest:** the **set of PV `value` strings** on property `/terms` matches `/edp/.../terms` for that triple. If property `/terms` is empty or a short inline list while `/edp/.../terms` is large, the MDF used `Term:` or inline Enum, not an Enum term-ref.

**caDSR labels:** each `cde-pvs` **wrapper’s** unique PV `value` set should equal the EDP unique `value` set. Do not concatenate wrappers into a multiset. Ignore NCIt/synonym rows for that compare.

---

## 9. Pitfalls

- **`Term:` is not consume.** Term-only properties never show up on `/edps/.../properties` and do not get the EDP PV list on property `/terms`.
- **Version strings are exact.** `2.0` vs `2.00`, `3.2` vs `3.20`, `CRDC0001` vs `CRDC_0001`.
- **Listing duplicates vs graph duplicates.** STS `/edps/{origin}` returns one row per term node (`DISTINCT t`), so the same CDE id/version can appear twice with different `value`s. The `edp_edps_unique` test uses the MDB / DATATEAM-508 key `(origin_name, origin_id, origin_version, value)`: two titles for one CDE are not a fail; the same 4-tuple twice is. caDSR is expected to fail until DATATEAM-722 (PR 197) and leftover cleanup land; that is not DATATEAM-736.
- **YAML delete ≠ graph delete.** Removing a PV from `bento-edps` does not automatically detach it in MDB.
- **CRDC0001 / CRDC0003 authoring.** They are on STS and on TEST; they are not in the current `bento-edps` / `mdb_edps.yml` tree.
- **`GET /` version vs image.** API `2.6.0` can be the same on every tier while the STS image differs.

---

