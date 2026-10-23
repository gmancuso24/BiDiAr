#!/usr/bin/env python3
"""Look for duplicate works and persons across the WHOLE tables.

This is a safety net independent of the matching logic of merge_article.py: whatever
that logic misses, a pair with the same (or a very similar) title shows up here.

Works: pairs sharing significant title words are compared; each pair gets a level
  certain   same normalised title, same year, shared author, no conflict
  probable  very similar title (>= 0.90), same year, shared author, no conflict
  possible  similar title with a conflict (other year, volume, numbers, authors)
            or a moderately similar title (>= 0.75) with a shared author
Pairs of two AeC metadata articles (_aec_id) are skipped, and so are pairs already
discussed in review.csv / review_archive.csv (both ids in the same row), and pairs cited
by the same AeC article (two entries of one bibliography are two works: rule of 19/10/2026).
Whole volumes are also compared without looking at the title (fix of 19/10/2026, vol. 24:
AeC 7, 13 and 15 and the Foggia 2008 workshop each had two or three records with different
title forms, never paired because the titles share too few words):
  same AeC issue   two book/proceedings records "Archeologia e Calcolatori" with the same
                   volume: probable (same year) or possible
  same editors     two book/proceedings records with the same 2+ editors (by name) and
                   years at most 1 apart: possible
Persons: same family name and same or compatible given names, different ids.
Works without a title are listed apart.

Usage
  python3 scripts/audit_duplicates.py               # report + output/audit_duplicates.csv
  python3 scripts/audit_duplicates.py --to-review   # also add the pairs to review.csv
                                                    # (issues audit_duplicate / audit_person)
merge_article.py calls audit_new_works() after every merge for the works it created.

Read-only on the tables unless --to-review is given (then a backup is made first).
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import re
import shutil
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher

from merge_article import (ARCHIVE_COLUMNS, identifier_conflicts, MAYBE_WORK, OUT, PERSON_COLUMNS, REVIEW_COLUMNS,
                           SAME_WORK, WORK_COLUMNS, aec_volume, compatible, first_volume, initials, is_full, norm,
                           numbers, read, same_name, shared_persons, similarity, surname_key,
                           title_tokens, work_persons)

PAIR_ISSUES = {"possible_duplicate", "audit_duplicate", "person_ambiguous", "audit_person"}
LEVELS = ("certain", "probable", "possible")


def decided_pairs(rows: list[dict]) -> set[frozenset]:
    """Pairs of ids that already appear together in a review row (open or closed)."""
    done = set()
    for r in rows:
        if r.get("issue") not in PAIR_ISSUES:
            continue
        ids = set(re.findall(r"[WP]\d{6}", r.get("details", "")))
        for a, b in itertools.combinations(sorted(ids), 2):
            done.add(frozenset((a, b)))
    return done


def classify(a: dict, b: dict, by_id: dict[str, dict] | None = None) -> tuple[str | None, float, list[str]]:
    """Level of a pair of works (None = not a candidate), similarity, conflicts."""
    ta, tb = a["dcterms:title"], b["dcterms:title"]
    na, nb = norm(ta), norm(tb)
    if not na or not nb:
        return None, 0.0, []
    exact = na == nb and len(na) >= 10
    if exact:
        sim = 1.0
    else:
        if SequenceMatcher(None, na, nb).real_quick_ratio() < MAYBE_WORK and not (
                na.startswith(nb) or nb.startswith(na)):
            return None, 0.0, []
        sim = similarity(ta, tb)
        if sim < MAYBE_WORK:
            return None, sim, []
    # A chapter and the volume that contains it are different works, even with a nearly
    # identical title (e.g. the editors' own chapter "Interpreting space" in the book
    # "Interpreting Space: GIS and Archaeology")
    for x, y in ((a, b), (b, a)):
        cont = norm(x["dcterms:isPartOf"])
        if x["dcterms:type"] == "chapter" and cont and cont == norm(y["dcterms:title"]):
            return None, sim, ["chapter and its containing volume"]
    conflicts = []
    da, db = a["dcterms:date"], b["dcterms:date"]
    if da and db and da != db:
        conflicts.append(f"different year {da}/{db}")
    va, vb = first_volume(a["bibo:volume"]), first_volume(b["bibo:volume"])
    if va and vb and va != vb:
        conflicts.append(f"different volume {va}/{vb}")
    if numbers(ta) != numbers(tb):
        conflicts.append("different numbers in title")
    conflicts += identifier_conflicts(a["bibo:doi"], a["bibo:uri"], b["bibo:doi"], b["bibo:uri"],
                                      not (a.get("_aec_id") or b.get("_aec_id")))
    ca, ea = work_persons(a)
    cb, eb = work_persons(b)
    # shared by id or by name (same surname + compatible given names), as in merge_article
    if ca and cb:
        shared = bool(shared_persons(ca, cb, by_id))
    elif (ca | ea) and (cb | eb):
        shared = bool(shared_persons(ca | ea, cb | eb, by_id))
    else:
        # both anonymous, or one side anonymous with a long title (as in merge_article)
        shared = not (ca | ea | cb | eb) or min(len(na), len(nb)) >= 20
    if not shared:
        conflicts.append("no shared author")
        # same rule as merge_article.score(): different authors only with a (nearly)
        # identical title in the same year, or an identical long title
        if not (exact and len(na) >= 20) and (any(c.startswith("different year") for c in conflicts)
                                               or sim < SAME_WORK):
            return None, sim, conflicts
    if not conflicts and exact:
        return "certain", sim, []
    if not conflicts and sim >= SAME_WORK:
        return "probable", sim, []
    if sim >= SAME_WORK or (shared and sim >= MAYBE_WORK):
        return "possible", sim, conflicts
    return None, sim, conflicts


WHOLE = {"book", "proceedings"}


def volume_keys(w: dict) -> list[tuple]:
    """Keys grouping whole-volume records that may be one work whatever their titles."""
    if w["dcterms:type"] not in WHOLE:
        return []
    keys = []
    parts = [norm(x) for x in w["dcterms:isPartOf"].split("|") if x.strip()]
    # Supplements keep their own number: "Suppl. 11" and "Suppl. 12" are different issues
    # (fix of 20/10/2026: first_volume() cut both to "suppl" and paired all Supplements)
    is_suppl, vol = aec_volume(w["bibo:volume"], w["dcterms:isPartOf"])
    if parts and parts[-1] == "archeologia e calcolatori" and vol:
        keys.append(("aec", ("S" + vol) if is_suppl else vol))
    eds = [e for e in w["bibo:editor"].split("|") if e]
    if len(eds) >= 2:
        keys.append(("eds", len(eds)))
    return keys


def same_volume(a: dict, b: dict, key: tuple, by_id: dict[str, dict]) -> tuple[str | None, list[str]]:
    """Level of two whole volumes grouped by volume_keys (None = not a candidate)."""
    ya, yb = a["dcterms:date"], b["dcterms:date"]
    years = [int(y) for y in (ya, yb) if re.fullmatch(r"\d{4}", y)]
    if key[0] == "aec":
        if len(years) == 2 and years[0] == years[1]:
            return "probable", [f"same AeC issue (vol. {key[1]}), different titles"]
        return "possible", [f"same AeC issue (vol. {key[1]})", f"different year {ya}/{yb}"]
    if len(years) < 2 or abs(years[0] - years[1]) > 1:
        return None, []
    ea = [by_id[e] for e in a["bibo:editor"].split("|") if e in by_id]
    eb = [by_id[e] for e in b["bibo:editor"].split("|") if e in by_id]
    if len(ea) != len(eb) or len(ea) < 2:
        return None, []
    if all(any(x["dcterms:identifier"] == y["dcterms:identifier"] or same_name(x, y) for y in eb) for x in ea):
        return "possible", ["same editors, different titles"] + ([f"different year {ya}/{yb}"] if ya != yb else [])
    return None, []


def cited_by(citations: list[dict]) -> dict[str, set[str]]:
    """Work id -> ids of the AeC articles citing it."""
    out: dict[str, set[str]] = {}
    for c in citations:
        out.setdefault(c["cited"], set()).add(c["_citing_aec_id"])
    return out


def work_pairs(works: list[dict], only: set[str] | None = None,
               skip: set[frozenset] = frozenset(), persons: list[dict] | None = None,
               citing: dict[str, set[str]] | None = None) -> list[dict]:
    """Candidate duplicate pairs; with `only`, pairs involving at least one of those ids.

    `citing` (from cited_by): pairs cited by the same article are skipped."""
    # An AeC article counts as "cited by itself": a pair made of the article and a work
    # cited in its own bibliography (same title: the article and its web site/database)
    # is not a duplicate (fix of 20/10/2026, vol. 27 art. 844)
    citing = {k: set(v) for k, v in (citing or {}).items()}
    for w in works:
        if w.get("_aec_id"):
            citing.setdefault(w["dcterms:identifier"], set()).add(str(w["_aec_id"]))
    by_id = {p["dcterms:identifier"]: p for p in persons or []}
    by_token: dict[str, list[int]] = {}
    toks = [title_tokens(w["dcterms:title"]) for w in works]
    for i, ts in enumerate(toks):
        for t in ts:
            by_token.setdefault(t, []).append(i)
    by_title: dict[str, list[int]] = {}
    for i, w in enumerate(works):
        by_title.setdefault(norm(w["dcterms:title"]), []).append(i)
    out, seen = [], set()
    targets = [i for i, w in enumerate(works) if only is None or w["dcterms:identifier"] in only]
    for i in targets:
        if not toks[i]:
            cands = set(by_title.get(norm(works[i]["dcterms:title"]), [])) if norm(works[i]["dcterms:title"]) else set()
        else:
            need = min(len(toks[i]), 2)
            hits = Counter(j for t in toks[i] for j in by_token[t])
            cands = {j for j, n in hits.items() if n >= need}
            cands |= set(by_title.get(norm(works[i]["dcterms:title"]), []))
        for j in cands:
            if j == i:
                continue
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            a, b = works[key[0]], works[key[1]]
            if a["_aec_id"] and b["_aec_id"]:
                continue
            if frozenset((a["dcterms:identifier"], b["dcterms:identifier"])) in skip:
                continue
            if citing.get(a["dcterms:identifier"], set()) & citing.get(b["dcterms:identifier"], set()):
                continue
            level, sim, conflicts = classify(a, b, by_id)
            if level:
                out.append({"kind": "work", "level": level, "id_a": a["dcterms:identifier"],
                            "id_b": b["dcterms:identifier"], "similarity": f"{sim:.2f}",
                            "conflicts": "; ".join(conflicts),
                            "a": f"{a['dcterms:title'][:70]} ({a['dcterms:date']})",
                            "b": f"{b['dcterms:title'][:70]} ({b['dcterms:date']})"})
    # Whole volumes with different titles (see volume_keys)
    groups: dict[tuple, list[int]] = {}
    for i, w in enumerate(works):
        for k in volume_keys(w):
            groups.setdefault(k, []).append(i)
    target_set = set(targets)
    # pairs already reported by the title comparison (a pair compared there and found not
    # similar enough must still be compared here)
    reported = {frozenset((r["id_a"], r["id_b"])) for r in out}
    for k, members in sorted(groups.items(), key=lambda kv: kv[0][0] != "aec"):
        for i, j in itertools.combinations(members, 2):
            if i not in target_set and j not in target_set:
                continue
            key = (min(i, j), max(i, j))
            a, b = works[key[0]], works[key[1]]
            pair = frozenset((a["dcterms:identifier"], b["dcterms:identifier"]))
            if pair in reported or pair in skip or a["_aec_id"] and b["_aec_id"]:
                continue
            if citing.get(a["dcterms:identifier"], set()) & citing.get(b["dcterms:identifier"], set()):
                continue
            level, conflicts = same_volume(a, b, k, by_id)
            if level:
                reported.add(pair)
                out.append({"kind": "work", "level": level, "id_a": a["dcterms:identifier"],
                            "id_b": b["dcterms:identifier"],
                            "similarity": f"{similarity(a['dcterms:title'], b['dcterms:title']):.2f}",
                            "conflicts": "; ".join(conflicts),
                            "a": f"{a['dcterms:title'][:70]} ({a['dcterms:date']})",
                            "b": f"{b['dcterms:title'][:70]} ({b['dcterms:date']})"})
    out.sort(key=lambda r: (LEVELS.index(r["level"]), -float(r["similarity"])))
    return out


def person_pairs(persons: list[dict], skip: set[frozenset] = frozenset()) -> list[dict]:
    by_family: dict[str, list[dict]] = {}
    for p in persons:
        by_family.setdefault(norm(p["foaf:familyName"]), []).append(p)
    out = []
    for fam, ps in by_family.items():
        if not fam:
            continue
        for a, b in itertools.combinations(ps, 2):
            if frozenset((a["dcterms:identifier"], b["dcterms:identifier"])) in skip:
                continue
            ga, gb = a["foaf:givenName"], b["foaf:givenName"]
            na_, nb_ = norm(ga), norm(gb)
            if is_full(ga) and is_full(gb) and not (na_.startswith(nb_) or nb_.startswith(na_)):
                continue                        # "Valentina" / "Veronica": different people
            if na_ == nb_:
                level = "certain"
            elif initials(ga) and initials(gb) and compatible(ga, gb):
                level = "possible"
            else:
                continue
            out.append({"kind": "person", "level": level, "id_a": a["dcterms:identifier"],
                        "id_b": b["dcterms:identifier"], "similarity": "", "conflicts": "",
                        "a": f"{a['foaf:familyName']}, {ga}", "b": f"{b['foaf:familyName']}, {gb}"})
    out.sort(key=lambda r: LEVELS.index(r["level"]))
    return out


def audit_new_works(t, new_ids: list[str], aec_id: str) -> int:
    """Called by merge_article.py: add review rows for the new works of one article."""
    if not new_ids:
        return 0
    archived = read("review_archive.csv", ARCHIVE_COLUMNS)
    skip = decided_pairs(t.review + archived)
    n = 0
    for r in work_pairs(t.works, set(new_ids), skip, t.persons, cited_by(t.citations)):
        t.add_review({"aec_id": aec_id, "position": "", "raw": ""}, "audit_duplicate",
                     f"{r['level']}: {r['id_a']} vs {r['id_b']} (sim {r['similarity']}"
                     + (f"; {r['conflicts']}" if r["conflicts"] else "") + f") {r['a']} | {r['b']}")
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to-review", action="store_true")
    args = ap.parse_args()
    works = read("works.csv", WORK_COLUMNS)
    persons = read("persons.csv", PERSON_COLUMNS)
    review = read("review.csv", REVIEW_COLUMNS)
    archive = read("review_archive.csv", ARCHIVE_COLUMNS)
    skip = decided_pairs(review + archive)
    from merge_article import CITATION_COLUMNS
    citations = read("citations.csv", CITATION_COLUMNS)
    wp = work_pairs(works, skip=skip, persons=persons, citing=cited_by(citations))
    pp = person_pairs(persons, skip)
    untitled = [w["dcterms:identifier"] for w in works if not norm(w["dcterms:title"])]
    rows = pp + wp
    cols = ["kind", "level", "id_a", "id_b", "similarity", "conflicts", "a", "b"]
    with open(OUT / "audit_duplicates.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    for kind, lst in (("persons", pp), ("works", wp)):
        c = Counter(r["level"] for r in lst)
        print(f"{kind}: " + ", ".join(f"{c[l]} {l}" for l in LEVELS))
    print(f"works without title: {len(untitled)}" + (f" ({', '.join(untitled[:10])}"
          + (", ..." if len(untitled) > 10 else "") + ")" if untitled else ""))
    print("details: output/audit_duplicates.csv")
    if args.to_review and rows:
        dest = OUT / "backup" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest.mkdir(parents=True)
        for name in ("review.csv", "review_archive.csv"):
            if (OUT / name).exists():
                shutil.copy2(OUT / name, dest / name)
        last = max((int(r["review_id"]) for r in review + archive if r["review_id"].isdigit()), default=0)
        for r in rows:
            last += 1
            review.append({"review_id": last, "citing_aec_id": "", "position": "",
                           "issue": f"audit_{'person' if r['kind'] == 'person' else 'duplicate'}",
                           "details": f"{r['level']}: {r['id_a']} vs {r['id_b']}"
                           + (f" (sim {r['similarity']}" + (f"; {r['conflicts']}" if r["conflicts"] else "") + ")"
                              if r["kind"] == "work" else "") + f" {r['a']} | {r['b']}",
                           "raw": "", "done": ""})
        with open(OUT / "review.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, restval="", extrasaction="ignore")
            w.writeheader()
            w.writerows(review)
        print(f"{len(rows)} rows added to review.csv")


if __name__ == "__main__":
    main()
