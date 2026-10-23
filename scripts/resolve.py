#!/usr/bin/env python3
"""Apply Giacomo's decisions on review.csv to the working tables.

Every command backs up the tables (output/backup/{timestamp}/) and appends a line to
output/decisions.log, so each change can be traced and undone.

Commands
  merge-person DROP KEEP     P-ids: DROP becomes KEEP in all works, DROP row removed,
                             its name kept among KEEP's variants
  merge-work DROP KEEP       W-ids: citations of DROP point to KEEP, empty cells of KEEP
                             filled from DROP, DROP row removed. Creators/editors: when
                             DROP lists more persons than KEEP ("Gillespie et al." vs the
                             full list) KEEP gets the full list, in DROP's order, with
                             KEEP's ids for the persons both have (same id or same name).
                             When each side has persons the other lacks, the command stops:
                             repeat it with --authors keep (KEEP's list) or --authors drop
                             (DROP's list)
  add-person FAMILY GIVEN    create a new person (next free P-id, never one already used in
                             decisions.log) and print its id; refuses if the name exists
  clone-work ID              W-id: new work with the same cells and the same citations as ID
                             (next free W-id, never one already used in decisions.log); use it
                             when one cited line stands for several works, then fix each with set
  detach AEC_ID POSITION     the citation at POSITION of article AEC_ID gets its own new work
                             (copy of the cells of the work it pointed to, next free W-id);
                             use it when a citation was attached to the wrong work, then fix
                             the new work with set
  rebuild AEC_ID POSITION    like detach, but the new work is built from the parsed reference
                             (output/parsed/{AEC_ID}.json) with its own persons, as a merge
                             would have created it: use it when a citation was merged into the
                             wrong work; then clear with set the cells it had filled in the
                             old work
  set ID COLUMN VALUE        change one cell of a work (W...) or person (P...)
  done REVIEW_ID [NOTE]      close review row(s): moved from review.csv to
                             review_archive.csv with the note. REVIEW_ID can be a list
                             ("22,23,25") or a range ("22-30")
  apply-names unique|ok [--file CSV]
                             set the given names proposed in output/name_suggestions.csv
                             (or in CSV, e.g. nomi_proposti_blocco_2.csv: same columns
                             person_id, given_now, proposal, level, ok; optional source)
                             (run suggest_names.py first): "unique" = every row of level
                             unique, "ok" = the rows marked in the ok column. The old form
                             stays among the variants
  mark-auto-names SOURCE...  fill name_note with AUTO_NAME_NOTE (the given name was assigned
                             automatically and not checked by hand) for every person whose
                             _notes say "given name from SOURCE" (e.g. crossref, openalex,
                             web, "Zotero list"); the pseudo-source "split" also marks the
                             persons created by a split with a spelled given name.
                             apply-names fills name_note by itself
  set-dois --file CSV        fill bibo:doi of works from CSV (columns work_id, doi, source,
                             evidence), only where bibo:doi is still empty; each work is
                             listed in the log with its source
  set-class CLASS ID...      persons: set o:resource_class (foaf:Person or foaf:Organization) on
                             the given P-ids; "set-class foaf:Person --empty" fills every
                             person whose class is still empty. For an Organization the whole
                             name sits in foaf:familyName, foaf:givenName stays empty
  drop-orphans               remove persons no longer used as creator or editor by any work
                             (left behind by merge-work); each removed name is logged
  purge                      move every row of review.csv whose "done" cell is filled
                             (e.g. decisions written in Excel) to review_archive.csv

Option --auto "REASON" (any command): the decision was taken by Claude in the pre-review
without asking Giacomo; the log line starts with [auto] and carries the reason, so these
decisions can be listed (grep "\[auto\]" output/decisions.log) and spot-checked.

review.csv therefore only ever holds open rows.

Examples
  python3 scripts/resolve.py merge-person P002010 P000018
  python3 scripts/resolve.py merge-work W001502 W000233
  python3 scripts/resolve.py set W001480 dcterms:date 1992
  python3 scripts/resolve.py add-person Lockyear Kris
  python3 scripts/resolve.py done 22 "same as Carandini 1981"
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from merge_article import (ARCHIVE_COLUMNS, CITATION_COLUMNS, OUT, PERSON_COLUMNS,
                           REVIEW_COLUMNS, WORK_COLUMNS, read, same_name, write)

AUTO_NAME_NOTE = ("The given name of this person was assigned by an automated procedure and has "
                  "not been checked by hand: it may contain errors.")

TABLES = {"works.csv": WORK_COLUMNS, "persons.csv": PERSON_COLUMNS,
          "citations.csv": CITATION_COLUMNS, "review.csv": REVIEW_COLUMNS,
          "review_archive.csv": ARCHIVE_COLUMNS}


def backup() -> None:
    dest = OUT / "backup" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest.mkdir(parents=True)
    for name in TABLES:
        if (OUT / name).exists():
            shutil.copy2(OUT / name, dest / name)


def log(line: str) -> None:
    with open(OUT / "decisions.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{line}\n")
    print(line)


def find(rows: list[dict], ident: str) -> dict:
    row = next((r for r in rows if r["dcterms:identifier"] == ident), None)
    if row is None:
        sys.exit(f"{ident} not found")
    return row


def replace_ids(cell: str, drop: str, keep: str) -> str:
    ids = [keep if i == drop else i for i in cell.split("|") if i]
    return "|".join(dict.fromkeys(ids))


def next_work_number(works: list[dict]) -> int:
    """Next free W number, never one already used in decisions.log."""
    used = [int(n) for n in re.findall(r"W(\d{6})", (OUT / "decisions.log").read_text(encoding="utf-8"))] \
        if (OUT / "decisions.log").exists() else []
    return max([int(w["dcterms:identifier"][1:]) for w in works] + used, default=0) + 1


def rebuild(aec: str, pos: str, auto: str) -> None:
    """Give one citation a new work built from its parsed reference (see the docstring)."""
    import json
    from merge_article import PARSED, TYPES, Tables       # local module, same folder
    t = Tables()
    hit = [c for c in t.citations if c["_citing_aec_id"] == aec and c["position"] == pos]
    if len(hit) != 1:
        sys.exit(f"{len(hit)} citations found for article {aec} position {pos}")
    data = json.loads((PARSED / f"{aec}.json").read_text(encoding="utf-8"))
    ref = next((r for r in data["references"] if str(r["position"]) == pos), None)
    if ref is None:
        sys.exit(f"position {pos} not in output/parsed/{aec}.json")
    if ref.get("type") not in TYPES:
        ref["type"] = "other"
    ctx = {"aec_id": aec, "position": pos, "raw": ref["raw"]}
    creators = [t.person(n, ctx) for n in ref.get("creators") or []]
    editors = [t.person(n, ctx) for n in ref.get("editors") or []]
    wid = f"W{next_work_number(t.works):06d}"
    w = t.add_work(ref, creators, editors, [f"src:aec-{aec}"])
    w["dcterms:identifier"] = wid
    old = hit[0]["cited"]
    hit[0]["cited"] = wid
    backup()
    t.save()
    msg = f"rebuild {aec}#{pos}: {old} -> new {wid} '{w['dcterms:title'][:60]}'"
    if auto:
        msg = f"[auto] {msg} -- {auto}"
    log(msg)


def complete_persons(keep_cell: str, drop_cell: str, by_id: dict[str, dict]) -> tuple[str, list[str], bool]:
    """Person list of the kept work after a merge-work.

    Returns (new cell, ids added from DROP, conflict). Fix of 19/10/2026 (vol. 24: merging
    a full "Gillespie, Kahle, Walker" record into a "Gillespie et al." one lost two
    co-authors, then removed by drop-orphans).
    """
    k_ids = [i for i in keep_cell.split("|") if i]
    d_ids = [i for i in drop_cell.split("|") if i]
    if not k_ids or not d_ids:
        return keep_cell, [], False

    def match(d: str) -> str:
        for k in k_ids:
            if k == d or (k in by_id and d in by_id and same_name(by_id[k], by_id[d])):
                return k
        return ""

    pairs = [(d, match(d)) for d in d_ids]
    added = [d for d, k in pairs if not k]
    if not added:
        return keep_cell, [], False
    if set(k_ids) - {k for _, k in pairs}:
        return keep_cell, added, True
    out: list[str] = []
    for d, k in pairs:
        if (k or d) not in out:
            out.append(k or d)
    return "|".join(out), added, False


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    authors = ""
    names_file = "name_suggestions.csv"
    if "--file" in argv:
        i = argv.index("--file")
        if i + 1 >= len(argv):
            sys.exit("--file needs a CSV path")
        names_file = argv[i + 1]
        del argv[i:i + 2]
    if "--authors" in argv:
        i = argv.index("--authors")
        if i + 1 >= len(argv) or argv[i + 1] not in ("keep", "drop"):
            sys.exit("--authors needs keep or drop")
        authors = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    auto = ""
    if "--auto" in argv:
        i = argv.index("--auto")
        if i + 1 >= len(argv) or not argv[i + 1].strip():
            sys.exit("--auto needs a reason")
        auto = argv[i + 1].strip()
        argv = argv[:i] + argv[i + 2:]
    cmd, args = argv[0], argv[1:]
    if cmd == "rebuild" and len(args) == 2:
        return rebuild(args[0], args[1], auto)
    t = {name: read(name, cols) for name, cols in TABLES.items()}
    works, persons, cites, review, archive = (t["works.csv"], t["persons.csv"], t["citations.csv"],
                                              t["review.csv"], t["review_archive.csv"])

    def close(rows: list[dict]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            review.remove(r)
            archive.append({**r, "closed_at": now})

    if cmd == "merge-person" and len(args) == 2:
        drop, keep = args
        gone, kept = find(persons, drop), find(persons, keep)
        n = 0
        for w in works:
            for col in ("dcterms:creator", "bibo:editor"):
                if drop in w[col].split("|"):
                    w[col] = replace_ids(w[col], drop, keep)
                    n += 1
        variants = [v for v in kept["_variants"].split("|") if v]
        for v in [f"{gone['foaf:familyName']}, {gone['foaf:givenName']}"] + \
                 [v for v in gone["_variants"].split("|") if v]:
            if v not in variants:
                variants.append(v)
        kept["_variants"] = "|".join(variants)
        persons.remove(gone)
        msg = f"merge-person {drop} -> {keep} ({n} cells updated)"
    elif cmd == "merge-work" and len(args) == 2:
        drop, keep = args
        gone, kept = find(works, drop), find(works, keep)
        by_id = {p["dcterms:identifier"]: p for p in persons}
        notes = []
        for col in ("dcterms:creator", "bibo:editor"):
            cell, added, conflict = complete_persons(kept[col], gone[col], by_id)
            if conflict and not authors:
                show = lambda c: ", ".join(f"{i} {by_id[i]['foaf:familyName']}" if i in by_id else i
                                           for i in c.split("|") if i)
                sys.exit(f"{col} differ: {keep} has [{show(kept[col])}], {drop} has [{show(gone[col])}].\n"
                         f"Nothing changed. Repeat with --authors keep or --authors drop.")
            if conflict and authors == "drop":
                kept[col] = gone[col]
                notes.append(f"{col} taken from {drop}")
            elif added and not conflict:
                kept[col] = cell
                notes.append(f"{col} completed with " + ", ".join(added))
        for col in WORK_COLUMNS:
            if not kept[col] and gone[col] and col != "dcterms:identifier":
                kept[col] = gone[col]
        n = 0
        for c in cites:
            if c["cited"] == drop:
                c["cited"] = keep
                n += 1
        works.remove(gone)
        msg = f"merge-work {drop} -> {keep} ({n} citations updated" + "".join(f"; {x}" for x in notes) + ")"
    elif cmd == "add-person" and len(args) == 2:
        family, given = args
        if any(p["foaf:familyName"] == family and p["foaf:givenName"] == given for p in persons):
            sys.exit(f"{family}, {given} already exists")
        used = [int(n) for n in re.findall(r"P(\d{6})", (OUT / "decisions.log").read_text(encoding="utf-8"))] \
            if (OUT / "decisions.log").exists() else []
        n = max([int(p["dcterms:identifier"][1:]) for p in persons] + used, default=0) + 1
        pid = f"P{n:06d}"
        persons.append({**{c: "" for c in PERSON_COLUMNS}, "dcterms:identifier": pid,
                        "foaf:familyName": family, "foaf:givenName": given,
                        "o:resource_class": "foaf:Person"})
        msg = f"add-person {pid} {family}, {given}"
    elif cmd == "clone-work" and len(args) == 1:
        src = find(works, args[0])
        used = [int(n) for n in re.findall(r"W(\d{6})", (OUT / "decisions.log").read_text(encoding="utf-8"))] \
            if (OUT / "decisions.log").exists() else []
        n = max([int(w["dcterms:identifier"][1:]) for w in works] + used, default=0) + 1
        wid = f"W{n:06d}"
        works.append({**src, "dcterms:identifier": wid})
        for c in [c for c in cites if c["cited"] == args[0]]:
            cites.append({**c, "cited": wid})
        msg = f"clone-work {args[0]} -> {wid}"
    elif cmd == "detach" and len(args) == 2:
        aec, pos = args
        hit = [c for c in cites if c["_citing_aec_id"] == aec and c["position"] == pos]
        if len(hit) != 1:
            sys.exit(f"{len(hit)} citations found for article {aec} position {pos}")
        src = find(works, hit[0]["cited"])
        used = [int(n) for n in re.findall(r"W(\d{6})", (OUT / "decisions.log").read_text(encoding="utf-8"))] \
            if (OUT / "decisions.log").exists() else []
        n = max([int(w["dcterms:identifier"][1:]) for w in works] + used, default=0) + 1
        wid = f"W{n:06d}"
        works.append({**src, "dcterms:identifier": wid})
        hit[0]["cited"] = wid
        msg = f"detach {aec}#{pos}: {src['dcterms:identifier']} -> new {wid}"
    elif cmd == "set" and len(args) == 3:
        ident, col, value = args
        rows = works if ident.startswith("W") else persons
        row = find(rows, ident)
        if col not in row or col == "dcterms:identifier":
            sys.exit(f"column {col} cannot be set")
        old, row[col] = row[col], value
        msg = f"set {ident} {col}: {old!r} -> {value!r}"
    elif cmd == "done" and len(args) >= 1:
        wanted = set()
        for part in args[0].split(","):
            a, _, b = part.partition("-")
            wanted.update(str(i) for i in range(int(a), int(b or a) + 1))
        note = " ".join(args[1:]) or "done"
        hits = [r for r in review if r["review_id"] in wanted]
        missing = wanted - {r["review_id"] for r in hits}
        if missing:
            sys.exit(f"review id not open: {', '.join(sorted(missing, key=int))}")
        for r in hits:
            r["done"] = note
        close(hits)
        msg = f"done {args[0]}: {note} ({len(hits)} rows archived)"
    elif cmd == "apply-names" and len(args) == 1 and args[0] in ("unique", "ok"):
        import csv
        path = Path(names_file) if "/" in names_file else OUT / names_file
        with open(path, encoding="utf-8-sig", newline="") as f:
            sugg = list(csv.DictReader(f))
        chosen = [r for r in sugg if r["proposal"].strip() and
                  (r["level"] == "unique" if args[0] == "unique" else r["ok"].strip())]
        by_id = {p["dcterms:identifier"]: p for p in persons}
        n, changed = 0, []
        for r in chosen:
            p = by_id.get(r["person_id"])
            if not p or p["foaf:givenName"] != r["given_now"]:   # changed since the suggestion
                continue
            old_form = f"{p['foaf:familyName']}, {p['foaf:givenName']}"
            variants = [v for v in p["_variants"].split("|") if v]
            if old_form not in variants:
                variants.append(old_form)
            p["_variants"] = "|".join(variants)
            p["foaf:givenName"] = r["proposal"].strip()
            note = f"given name from {r['source']} ({path.name})" if r.get("source") else \
                "given name from Zotero list"
            p["_notes"] = f"{p['_notes']}; {note}" if p["_notes"] else note
            p["name_note"] = AUTO_NAME_NOTE
            changed.append(f"{r['person_id']} {old_form} -> {r['proposal'].strip()}")
            n += 1
        msg = f"apply-names {args[0]}: {n} given names set from {path.name}: " + "; ".join(changed)
    elif cmd == "mark-auto-names" and args:
        def spelled(given: str) -> bool:
            return any(len(t) > 1 for t in re.split(r"[.\s-]+", given))
        hits = []
        for p in persons:
            sources = [s.strip() for s in re.findall(r"given name from ([^;(]+?)(?= \(|;|$)", p["_notes"])]
            if any(s in args for s in sources) or ("split" in args and "split " in p["_notes"]
                                                   and not sources and spelled(p["foaf:givenName"])):
                if p["name_note"] != AUTO_NAME_NOTE:
                    p["name_note"] = AUTO_NAME_NOTE
                    hits.append(p["dcterms:identifier"])
        msg = f"mark-auto-names {' | '.join(args)}: name_note set on {len(hits)} persons"
    elif cmd == "set-dois" and not args and names_file != "name_suggestions.csv":
        import csv
        path = Path(names_file) if "/" in names_file else OUT / names_file
        with open(path, encoding="utf-8-sig", newline="") as f:
            found = list(csv.DictReader(f))
        by_id = {w["dcterms:identifier"]: w for w in works}
        done = []
        for r in found:
            w = by_id.get(r["work_id"])
            if w is None or w["bibo:doi"].strip() or not r["doi"].strip():
                continue
            w["bibo:doi"] = r["doi"].strip()
            done.append(f"{r['work_id']} {r['doi'].strip()} ({r['source']}: {r['evidence']})")
        msg = f"set-dois: {len(done)} DOIs set from {path.name}: " + "; ".join(done)
    elif cmd == "set-class" and len(args) >= 2:
        cls, ids = args[0], args[1:]
        if cls not in ("foaf:Person", "foaf:Organization"):
            sys.exit("class must be foaf:Person or foaf:Organization")
        if ids == ["--empty"]:
            targets = [p for p in persons if not p["o:resource_class"].strip()]
        else:
            targets = [find(persons, i) for i in ids]
        for p in targets:
            p["o:resource_class"] = cls
        msg = f"set-class {cls}: {len(targets)} persons" + (
            "" if ids == ["--empty"] else " (" + ", ".join(ids) + ")" if len(ids) <= 12 else "")
    elif cmd == "drop-orphans" and not args:
        used = {i for w in works for col in ("dcterms:creator", "bibo:editor")
                for i in w[col].split("|") if i}
        orphans = [p for p in persons if p["dcterms:identifier"] not in used]
        for p in orphans:
            persons.remove(p)
        names = "; ".join(f"{p['dcterms:identifier']} {p['foaf:familyName']}, {p['foaf:givenName']}"
                          for p in orphans)
        msg = f"drop-orphans: {len(orphans)} persons removed ({names})"
    elif cmd == "purge" and not args:
        hits = [r for r in review if r["done"].strip()]
        close(hits)
        msg = f"purge: {len(hits)} closed rows archived, {len(review)} still open"
    else:
        sys.exit(__doc__)

    backup()
    for name, cols in TABLES.items():
        write(name, cols, t[name])
    if auto:
        msg = f"[auto] {msg} -- {auto}"
    log(msg)


if __name__ == "__main__":
    main(sys.argv[1:])
