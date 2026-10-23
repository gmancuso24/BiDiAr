#!/usr/bin/env python3
"""Read-only health check of the working tables before the Omeka import.

Checks structure (ids, formats, references between tables), coverage (every MD has a
parsed JSON, every parsed reference has a citation) and the correctness of each citation
link: the parsed reference at (citing article, position) is compared with the cited work
(year, authors/editors surnames, title). Writes output/health_check.csv with one row per
finding; never touches the tables.

Usage: python3 scripts/health_check.py
"""
from __future__ import annotations
import csv, glob, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_article import norm, similarity, surname_key, main_title  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
csv.field_size_limit(10**9)

def read(n):
    with open(OUT / n, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

works, persons, cits = read("works.csv"), read("persons.csv"), read("citations.csv")
review = read("review.csv")
F = []  # findings
def add(level, check, ident, details):
    F.append({"level": level, "check": check, "id": ident, "details": details})

# ---------------------------------------------------------------- persons
P = {}
for p in persons:
    i = p["dcterms:identifier"]
    if not re.fullmatch(r"P\d{6}", i): add("error", "person_id_format", i, "")
    if i in P: add("error", "person_id_duplicate", i, "")
    P[i] = p
    if not p["foaf:familyName"].strip(): add("error", "person_no_family", i, p["foaf:givenName"])
    for c in ("foaf:familyName", "foaf:givenName"):
        v = p[c]
        if v != v.strip() or "  " in v: add("warn", "person_whitespace", i, f"{c}={v!r}")
        if p.get("o:resource_class") != "foaf:Organization" and re.search(r"[0-9|;]", v): add("warn", "person_odd_chars", i, f"{c}={v!r}")
    if p.get("o:resource_class") != "foaf:Organization" and p["foaf:familyName"].isupper() and len(p["foaf:familyName"]) > 3:
        add("warn", "person_uppercase", i, p["foaf:familyName"])
exact = defaultdict(list)
for p in persons:
    if p["foaf:givenName"].strip() and "ambiguous" not in p["_notes"]:
        exact[(surname_key(p["foaf:familyName"]), norm(p["foaf:givenName"]))].append(p["dcterms:identifier"])
for k, ids in exact.items():
    if len(ids) > 1: add("warn", "person_same_full_name", "|".join(ids), f"{k[0]}, {k[1]}")

# ---------------------------------------------------------------- works
TYPES = {"article", "book", "chapter", "proceedings", "thesis", "other",
         "conference communication", "unpublished work"}   # last two added 22/10/2026 (old c.s.)
LANGS = {"ita", "eng", "fre", "ger", "spa"}
W = {}; used_p = Counter(); aec = {}
for w in works:
    i = w["dcterms:identifier"]
    if not re.fullmatch(r"W\d{6}", i): add("error", "work_id_format", i, "")
    if i in W: add("error", "work_id_duplicate", i, "")
    W[i] = w
    if w["dcterms:type"] not in TYPES: add("error", "work_bad_type", i, w["dcterms:type"])
    if not w["dcterms:title"].strip(): add("warn", "work_no_title", i, w["dcterms:isPartOf"][:80])
    for col in ("dcterms:creator", "bibo:editor"):
        ids = [x for x in w[col].split("|") if x] if w[col] else []
        if w[col] and (w[col] != w[col].strip() or "" in w[col].split("|")):
            add("error", "work_bad_multivalue", i, f"{col}={w[col]!r}")
        if len(ids) != len(set(ids)): add("warn", "work_repeated_person", i, f"{col}={w[col]}")
        for x in ids:
            used_p[x] += 1
            if x not in P: add("error", "work_missing_person", i, f"{col}: {x}")
    d = w["dcterms:date"]
    if d and not re.fullmatch(r"(1[5-9]|20)\d\d([a-z])?|c\.s\.", d): add("warn", "work_odd_date", i, d)
    if not d: add("info", "work_no_date", i, w["dcterms:title"][:80])
    if d == "c.s." and "cs-unresolved" not in w["curation:tag"]: add("warn", "cs_without_tag", i, "")
    l = w["dcterms:language"]
    if l and not all(x in LANGS or re.fullmatch(r"[a-z]{3}", x) for x in l.split("|")): add("warn", "work_odd_language", i, l)
    if w["bibo:pages"] and not re.fullmatch(r"[\divxlcIVXLC]+(\s*-\s*[\divxlcIVXLC]+)?(,\s*[\divxlcIVXLC]+(\s*-\s*[\divxlcIVXLC]+)?)*", w["bibo:pages"]):
        add("info", "work_odd_pages", i, w["bibo:pages"])
    if w["dcterms:type"] in ("chapter", "article") and not w["dcterms:isPartOf"]:
        add("info", "work_part_without_container", i, f'{w["dcterms:type"]}: {w["dcterms:title"][:80]}')
    for col in w:
        if col and w[col] != w[col].strip(): add("info", "work_whitespace", i, col)
    if w["_aec_id"]:
        if w["_aec_id"] in aec: add("error", "aec_id_duplicate", i, f'{w["_aec_id"]} also {aec[w["_aec_id"]]}')
        aec[w["_aec_id"]] = i
for i in P:
    if not used_p[i]: add("warn", "person_orphan", i, f'{P[i]["foaf:familyName"]}, {P[i]["foaf:givenName"]}')

# ---------------------------------------------------------------- citations
cited_by = Counter(); per_art = defaultdict(lambda: defaultdict(list))
for n, c in enumerate(cits, 2):
    ci, cd, a = c["citing"], c["cited"], c["_citing_aec_id"]
    if ci not in W: add("error", "cit_missing_citing", f"row {n}", ci); continue
    if cd not in W: add("error", "cit_missing_cited", f"row {n}", cd); continue
    if W[ci]["_aec_id"] != a: add("error", "cit_citing_mismatch", f"row {n}", f"{ci} has aec {W[ci]['_aec_id']}, row says {a}")
    if ci == cd: add("error", "cit_self", f"row {n}", f"{a} pos {c['position']}")
    grp = per_art[a][c["position"]]
    if any(x["cited"] == cd for x in grp): add("error", "cit_duplicate_row", f"{a}:{c['position']}", cd)
    grp.append(c)
    cited_by[cd] += 1
pair = Counter((c["citing"], c["cited"]) for c in cits)
for (ci, cd), n in pair.items():
    if n > 1: add("info", "cit_same_work_twice", f"{W[ci]['_aec_id']}", f"{cd} cited {n} times")
for i, w in W.items():
    if not w["_aec_id"] and not cited_by[i]: add("warn", "work_orphan", i, w["dcterms:title"][:80])

# ---------------------------------------------------------------- parsed vs MD vs citations
mds = {Path(f).stem: f for f in glob.glob(str(ROOT / "data/journal/**/*.md"), recursive=True)}
parsed = {}
for f in glob.glob(str(OUT / "parsed/*.json")):
    d = json.load(open(f, encoding="utf-8")); parsed[str(d["citing_aec_id"])] = d
for a, f in sorted(mds.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
    if a not in parsed: add("info", "md_without_parsed", a, str(Path(f).relative_to(ROOT)))
for a in parsed:
    if a not in aec: add("error", "parsed_article_not_in_works", a, "")
pos_ref = {}
for a, d in parsed.items():
    refs = defaultdict(list)
    for r in d.get("references", []): refs[str(r["position"])].append(r)
    got = per_art.get(a, {})
    for p_ in refs:
        if p_ not in got: add("error", "ref_without_citation", f"{a}:{p_}", refs[p_][0]["raw"][:100])
        elif len(got[p_]) != len(refs[p_]):
            add("warn", "ref_count_differs", f"{a}:{p_}", f"{len(refs[p_])} parsed refs, {len(got[p_])} citations: {refs[p_][0]['raw'][:100]}")
    for p_ in got:
        if p_ not in refs: add("error", "citation_without_ref", f"{a}:{p_}", got[p_][0]["raw"][:100])
    for p_, rl in refs.items():
        for k, r in enumerate(rl):
            if p_ in got and k < len(got[p_]):
                pos_ref[(a, p_, k)] = (r, got[p_][k])
                if norm(got[p_][k]["raw"]) != norm(r["raw"]): add("error", "raw_differs", f"{a}:{p_}", "")
for a in per_art:
    if a not in parsed: add("error", "citations_without_parsed", a, "")

# ---------------------------------------------------------------- link correctness
def surnames(ids):
    return {surname_key(P[x]["foaf:familyName"]) for x in ids if x in P}
def year(s):
    m = re.match(r"(\d{4})", s or ""); return m.group(1) if m else ""
link_stats = Counter()
for (a, p_, k), (r, c) in pos_ref.items():
    if c["cited"] not in W: continue
    w = W[c["cited"]]; probs = []
    ry, wy = year(r.get("date", "")), year(w["dcterms:date"])
    if ry and wy and ry != wy:
        probs.append(f"year {ry}≠{wy}")
    rp = {surname_key(x.get("family", "")) for x in r.get("creators", []) + r.get("editors", []) if x.get("family")}
    wp = surnames([x for x in (w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|") if x])
    if rp and wp and not (rp & wp):
        from difflib import SequenceMatcher as SM
        if not any(SM(None, x, y).ratio() >= 0.8 for x in rp for y in wp):
            probs.append(f"authors {sorted(rp)}≠{sorted(wp)}")
    rt, wt = r.get("title", ""), w["dcterms:title"]
    if rt and wt:
        s = similarity(rt, wt)
        if s < 0.75 and norm(main_title(rt)) != norm(main_title(wt)) and not (norm(rt) in norm(wt) or norm(wt) in norm(rt)):
            probs.append(f"title sim {s:.2f}")
    if r.get("cited_aec_id") and w["_aec_id"] != str(r["cited_aec_id"]):
        probs.append(f"cited_aec_id {r['cited_aec_id']}→{w['_aec_id'] or c['cited']}")
    rty = r.get("type"); wty = w["dcterms:type"]
    if {rty, wty} in ({"chapter", "book"}, {"chapter", "proceedings"}, {"article", "book"}):
        probs.append(f"type {rty}≠{wty}")
    link_stats["checked"] += 1
    if probs:
        link_stats["flagged"] += 1
        lvl = "warn" if (len(probs) > 1 or any(x.startswith(("authors", "cited_aec")) for x in probs)) else "info"
        add(lvl, "link_mismatch", f"{a}:{p_}", f'{c["cited"]} | {"; ".join(probs)} | ref: {r["raw"][:140]} | work: {wt[:100]} ({w["dcterms:date"]})')

# ---------------------------------------------------------------- report
with open(OUT / "health_check.csv", "w", encoding="utf-8-sig", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=["level", "check", "id", "details"]); wr.writeheader(); wr.writerows(F)
print(f"works {len(works)}  persons {len(persons)}  citations {len(cits)}  parsed {len(parsed)}  MD {len(mds)}  open review {len(review)}")
print(f"AeC articles in works: {len(aec)}  cited works: {len(cited_by)}  links checked {link_stats['checked']}, flagged {link_stats['flagged']}")
for (lvl, chk), n in sorted(Counter((x['level'], x['check']) for x in F).items()):
    print(f"{lvl:5} {chk:32} {n}")
