#!/usr/bin/env python3
"""Load the AeC article metadata (data/all_metadata.json) into the working tables.

Creates output/persons.csv and output/works.csv from scratch: run it once, before
any bibliography is parsed, because the parsing step appends to the same tables.

Conventions (see CLAUDE.md):
- identifiers: persons P000001, works W000001 (stored in dcterms:identifier)
- multi-value cells use "|" with no spaces, e.g. "P000012|P000013"
- columns starting with "_" are working columns, never imported into Omeka
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "all_metadata.json"
OUT = ROOT / "output"

WORK_COLUMNS = [
    "dcterms:identifier", "dcterms:type", "dcterms:title", "dcterms:creator", "bibo:editor",
    "dcterms:date", "dcterms:isPartOf", "bibo:volume", "curation:number", "dcat:inSeries",
    "bibo:numVolumes", "bibo:issue", "bibo:pages", "bibo:numPages", "dcterms:language",
    "dcterms:publisher", "dcterms:spatial", "dcterms:rights", "bibo:isbn", "bibo:issn",
    "bibo:doi", "bibo:uri", "dcterms:abstract", "curation:tag", "_aec_id",
]
PERSON_COLUMNS = ["dcterms:identifier", "foaf:familyName", "foaf:givenName", "orcid", "_variants", "_notes"]

JOURNAL = "Archeologia e Calcolatori"
SUPPLEMENTS = "Archeologia e Calcolatori. Supplementi"
JOURNAL_ISSN = "2385-1953|1120-6861"      # online | print
LICENSE = "CC BY-NC-ND 4.0"

# Duplicates checked by hand: dropped id -> kept id (the kept record takes the fuller name)
PERSON_MERGES = {"P001290": "P000438"}     # Anderson, Michael = Anderson, Michael Andrew


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def main() -> None:
    if (OUT / "citations.csv").exists():
        raise SystemExit("output/citations.csv exists: bibliographies have been merged already, "
                         "rebuilding the tables would lose them. Stopped.")
    records = json.loads(SRC.read_text(encoding="utf-8"))
    # Chronological order so that identifiers follow the history of the journal
    records.sort(key=lambda r: (r["publication_year"], "supplements" in r["url"],
                                r["volume_number"], r.get("issue_number") or 0,
                                r.get("firstPage") or 0, r["id"]))
    persons: dict[tuple[str, str], dict] = {}
    works = []

    def person_id(first: str, last: str) -> str:
        k = (key(last), key(first))
        if k not in persons:
            persons[k] = {"dcterms:identifier": f"P{len(persons) + 1:06d}",
                          "foaf:familyName": last, "foaf:givenName": first,
                          "orcid": "", "_variants": "", "_notes": ""}
        return persons[k]["dcterms:identifier"]

    for n, r in enumerate(records, 1):
        is_supp = "supplements" in r["url"]
        creators = [person_id(clean(a["first_name"]), clean(a["last_name"]))
                    for a in r.get("authors") or [] if clean(a.get("last_name"))]
        pages = "-".join(str(p) for p in (r.get("firstPage"), r.get("lastPage")) if p)
        tags = ["src:aec-metadata"]
        if r.get("is_review"):
            tags.append("aec:review")
        if r.get("is_note"):
            tags.append("aec:note")
        works.append({
            "dcterms:identifier": f"W{n:06d}",
            "dcterms:type": "article",
            "dcterms:title": clean(r["title"]),
            "dcterms:creator": "|".join(creators),
            "dcterms:date": r["publication_year"],
            "dcterms:isPartOf": SUPPLEMENTS if is_supp else JOURNAL,
            "bibo:volume": r["volume_number"],
            "bibo:issue": r.get("issue_number") or "",
            "bibo:pages": pages,
            "dcterms:language": r.get("language") or "",
            "dcterms:rights": LICENSE,
            "bibo:issn": "" if is_supp else JOURNAL_ISSN,
            "bibo:doi": r.get("doi") or "",
            "bibo:uri": r["url"],
            "dcterms:abstract": clean(r.get("abstract")),
            "curation:tag": "|".join(tags),
            "_aec_id": r["id"],
        })

    # Apply the manual merges
    by_id = {p["dcterms:identifier"]: p for p in persons.values()}
    for drop, keep in PERSON_MERGES.items():
        gone = by_id.pop(drop)
        kept = by_id[keep]
        kept["_variants"] = "|".join(v for v in (kept["_variants"],
                                     f"{gone['foaf:familyName']}, {gone['foaf:givenName']}") if v)
        for w in works:
            ids = [keep if i == drop else i for i in w["dcterms:creator"].split("|") if i]
            w["dcterms:creator"] = "|".join(dict.fromkeys(ids))
    persons = {k: p for k, p in persons.items() if p["dcterms:identifier"] in by_id}
    suspects = 0

    OUT.mkdir(exist_ok=True)
    for name, cols, rows in (("works.csv", WORK_COLUMNS, works),
                             ("persons.csv", PERSON_COLUMNS, list(persons.values()))):
        with open(OUT / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, restval="")
            w.writeheader()
            w.writerows(rows)
    print(f"works {len(works)} (journal {sum(w['dcterms:isPartOf'] == JOURNAL for w in works)}, "
          f"supplements {sum(w['dcterms:isPartOf'] == SUPPLEMENTS for w in works)}); "
          f"persons {len(persons)} (merged {len(PERSON_MERGES)})")


if __name__ == "__main__":
    main()
