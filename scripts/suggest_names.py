#!/usr/bin/env python3
"""Suggest full given names for persons cited with initials only, from the Zotero list.

Input : data/persone_zotero.csv (export of the old Zotero library: one row per distinct
        name, columns surname, given, form, n_occurrences, zotero_keys, ...)
        output/persons.csv
Output: output/name_suggestions.csv, one row per person whose given name is initials only
        (or missing) and for whom the Zotero list has at least one compatible full name.

The Zotero list comes from the same AeC bibliographies but from an unchecked import. Decision
(Giacomo, 18/10/2026): a UNIQUE compatible full name is trusted and applied; variants,
ambiguous names and persons without given name are only suggestions, decided case by case.
Nothing is written to the tables by this script.

Levels (column `level`)
  unique     one compatible full name in Zotero
  variants   several forms of the same name ("Bruce" / "Bruce C."): the fullest is proposed
  ambiguous  different names ("Elvira" / "Emanuela"): no proposal, alternatives listed
  no_given   the person has no given name at all: every full name with that surname is listed

Usage
  python3 scripts/suggest_names.py
Rows of level "unique" are applied with `resolve.py apply-names unique`; other rows marked in
the `ok` column with `resolve.py apply-names ok`. merge_article.py already uses the unique
names for new persons.
Standard library only.
"""
from __future__ import annotations

import csv
import re
from collections import Counter

from merge_article import OUT, PERSON_COLUMNS, ROOT, WORK_COLUMNS, compatible, is_full, norm, read

ZOTERO = ROOT / "data" / "persone_zotero.csv"
LEVELS = ("unique", "variants", "ambiguous", "no_given")


def clean_given(g: str) -> str:
    """'Mary .L.' -> 'Mary L.', 'Francis C' -> 'Francis C.', extra spaces removed."""
    g = re.sub(r"\s+\.(?=[A-ZÀ-Ý])", " ", g.strip())     # "Mary .L." -> "Mary L."
    g = re.sub(r"\s+\.", ".", g)
    g = re.sub(r"\s+", " ", g)
    return " ".join(t + "." if re.fullmatch(r"[A-ZÀ-Ý]", t) else t for t in g.split(" "))


def load_full() -> dict[str, dict[str, dict]]:
    """Full names of the Zotero list by normalised surname: {surname: {norm given: info}}."""
    if not ZOTERO.exists():
        return {}
    with open(ZOTERO, encoding="utf-8-sig", newline="") as f:
        zotero = list(csv.DictReader(f))
    full: dict[str, dict[str, dict]] = {}
    for z in zotero:
        given = clean_given(z.get("given", ""))
        if z.get("form") != "nome completo" or not norm(given):   # junk such as "."
            continue
        bucket = full.setdefault(norm(z["surname"]), {})
        key = norm(given)
        if key in bucket:                     # same name met twice: add the counts
            bucket[key]["n"] += int(z.get("n_occurrences") or 0)
            bucket[key]["keys"] += "|" + z.get("zotero_keys", "")
        else:
            bucket[key] = {"given": given, "n": int(z.get("n_occurrences") or 0),
                           "keys": z.get("zotero_keys", "")}
    return full


def typo_pair(a: str, b: str) -> bool:
    """Two normalised given names differing by one letter added or dropped inside the name.

    "giulano"/"giuliano", "lura"/"laura", "kartsten"/"karsten": typos of the Zotero import.
    Never at the end ("humbert"/"humberto", "marco"/"marcos") and never a substitution
    ("francesca"/"francesco", "maria"/"marta"): those can be different people.
    """
    if abs(len(a) - len(b)) != 1:
        return False
    short, long_ = sorted((a, b), key=len)
    if len(short) < 4 or short[0] != long_[0]:
        return False
    i = next((k for k in range(len(short)) if short[k] != long_[k]), len(short))
    return i < len(short) and long_[:i] + long_[i + 1:] == short


def fold_typos(occ: dict[str, int]) -> dict[str, int]:
    """Occurrence counts {first name: n} with typo variants merged (typo_pair).

    Used only by the ambiguity check of merge_article.py (fix of 19/10/2026: 28 of 192
    person_ambiguous rows of vols. 1-23 came only from typos of the Zotero list, e.g.
    De Felice G. = "Giulano" (14) / "Giuliano" (16)). It never chooses a name: which
    spelling is right is not known (the most frequent can be the typo), so proposals and
    unique names still come from the list as it is."""
    occ = dict(occ)
    changed = True
    while changed:
        changed = False
        for a in list(occ):
            for b in list(occ):
                if a != b and a in occ and b in occ and typo_pair(a, b):
                    keep, drop = sorted((a, b), key=lambda k: (-occ[k], k))
                    occ[keep] += occ.pop(drop)
                    changed = True
    return occ

def zotero_unique(full: dict, family: str, given: str) -> str:
    """The full given name when the Zotero list has exactly one compatible with `given`."""
    if not given.strip() or is_full(given):
        return ""
    cands = [c for c in full.get(norm(family), {}).values() if compatible(given, c["given"])]
    return cands[0]["given"] if len(cands) == 1 else ""


def main() -> None:
    full = load_full()

    works = read("works.csv", WORK_COLUMNS)
    n_works = Counter(p for w in works for col in ("dcterms:creator", "bibo:editor")
                      for p in w[col].split("|") if p)
    rows = []
    for p in read("persons.csv", PERSON_COLUMNS):
        given = p["foaf:givenName"].strip()
        if is_full(given):
            continue
        cands = list(full.get(norm(p["foaf:familyName"]), {}).values())
        if given:
            cands = [c for c in cands if compatible(given, c["given"])]
        if not cands or all(norm(c["given"]) == norm(given) for c in cands):
            continue                          # nothing new to propose
        cands.sort(key=lambda c: (-len(c["given"].split()), -c["n"]))
        firsts = {norm(c["given"]).split()[0] for c in cands}
        if not given:
            level, proposal = "no_given", ""
        elif len(cands) == 1:
            level, proposal = "unique", cands[0]["given"]
        elif len(firsts) == 1:
            # Prefer the forms with exactly the cited initials ("J." -> "James", not
            # "James W."), then the fullest spelling ("Michael Brian" over "Michael B.")
            from merge_article import initials
            same = [c for c in cands if initials(c["given"]) == initials(given)] or cands
            best = max(same, key=lambda c: (len(c["given"].replace(".", "")), c["n"]))
            level, proposal = "variants", best["given"]
        else:
            level, proposal = "ambiguous", ""
        rows.append({
            "person_id": p["dcterms:identifier"], "family": p["foaf:familyName"],
            "given_now": given, "proposal": proposal, "level": level,
            "alternatives": " / ".join(f"{c['given']} ({c['n']})" for c in cands[:6]),
            "zotero_keys": "|".join(dict.fromkeys(k for c in cands for k in c["keys"].split("|") if k))[:200],
            "works_here": n_works.get(p["dcterms:identifier"], 0), "ok": ""})
    rows.sort(key=lambda r: (LEVELS.index(r["level"]), norm(r["family"])))
    cols = ["person_id", "family", "given_now", "proposal", "level", "alternatives",
            "zotero_keys", "works_here", "ok"]
    with open(OUT / "name_suggestions.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    c = Counter(r["level"] for r in rows)
    print(", ".join(f"{c[l]} {l}" for l in LEVELS) + " -> output/name_suggestions.csv")


if __name__ == "__main__":
    main()
