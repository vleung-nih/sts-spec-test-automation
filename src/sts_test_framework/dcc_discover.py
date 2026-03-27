"""
Live discovery for CCDI Federation (DCC) API: subjects, samples, files, organizations.

Discovery keys use a ``dcc_`` prefix where they would collide with STS (e.g.
``dcc_subject_name``). Shared keys ``organization`` and ``namespace`` align with
path templates that reuse those segment names.
"""
from __future__ import annotations

from .client import APIClient


def _entity_triple(record: dict) -> tuple[str, str, str] | None:
    """Return (organization, namespace_name, entity_name) from a list row ``id``."""
    id_ = record.get("id")
    if not isinstance(id_, dict):
        return None
    ns = id_.get("namespace")
    if not isinstance(ns, dict):
        return None
    org = ns.get("organization")
    ns_name = ns.get("name")
    ent_name = id_.get("name")
    if org is None or ns_name is None or ent_name is None:
        return None
    return str(org), str(ns_name), str(ent_name)


def discover_dcc(client: APIClient) -> dict:
    """
    Populate path/query inputs for ``generate_cases_dcc``.

    Expects ``client.base_url`` to end with ``/api/v1`` so paths are rooted at
    ``/subject``, ``/sample``, etc.

    Returns:
        Partial dict if list endpoints fail. On success includes ``organization``,
        ``namespace``, ``dcc_subject_name``, per-entity triples, count-field keys,
        and ``dcc_organization_name`` (identifier preferred).
    """
    data: dict = {}
    list_params = {"page": 1, "per_page": 10}

    r_sub = client.get("/subject", list_params)
    if r_sub.status_code != 200:
        return data
    body_sub = r_sub.json()
    if not isinstance(body_sub, dict):
        return data
    rows_sub = body_sub.get("data")
    if not isinstance(rows_sub, list) or not rows_sub:
        return data
    first_sub = rows_sub[0]
    if not isinstance(first_sub, dict):
        return data
    triple = _entity_triple(first_sub)
    if not triple:
        return data
    org, ns, subj_name = triple
    data["organization"] = org
    data["namespace"] = ns
    data["dcc_subject_name"] = subj_name
    data["dcc_subject_count_field"] = "sex"
    data["dcc_sample_count_field"] = "disease_phase"
    data["dcc_file_count_field"] = "type"

    r_samp = client.get("/sample", list_params)
    if r_samp.status_code == 200:
        b_s = r_samp.json()
        if isinstance(b_s, dict):
            dr = b_s.get("data")
            if isinstance(dr, list) and dr and isinstance(dr[0], dict):
                t2 = _entity_triple(dr[0])
                if t2:
                    data["dcc_sample_organization"] = t2[0]
                    data["dcc_sample_namespace"] = t2[1]
                    data["dcc_sample_name"] = t2[2]

    r_file = client.get("/file", list_params)
    if r_file.status_code == 200:
        b_f = r_file.json()
        if isinstance(b_f, dict):
            dr = b_f.get("data")
            if isinstance(dr, list) and dr and isinstance(dr[0], dict):
                t3 = _entity_triple(dr[0])
                if t3:
                    data["dcc_file_organization"] = t3[0]
                    data["dcc_file_namespace"] = t3[1]
                    data["dcc_file_name"] = t3[2]

    r_org = client.get("/organization")
    if r_org.status_code == 200:
        orgs = r_org.json()
        if isinstance(orgs, list) and orgs:
            o0 = orgs[0]
            if isinstance(o0, dict):
                ident = o0.get("identifier")
                name = o0.get("name")
                data["dcc_organization_name"] = str(ident) if ident else (str(name) if name else None)
                if not data.get("dcc_organization_name"):
                    data.pop("dcc_organization_name", None)

    return data
