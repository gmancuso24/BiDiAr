---
name: prereview-aec-volume
description: Pre-review of the open review.csv rows of an AeC volume after parsing (hybrid mode) - Claude applies the clear cases with resolve.py --auto and leaves Giacomo a short report of the doubtful or policy cases. Use after a volume has been parsed and merged, or when asked for the "pre-revisione" / "revisione automatica" of a volume.
---

# Pre-review of a volume (hybrid mode, decided 19/10/2026)

Goal: Giacomo only sees the cases that need him. Claude decides the clear ones, applies them
with `scripts/resolve.py ... --auto "reason"` and writes a report. The scripts stay the
infrastructure (ids, whole-table matching, backups, log); the judgement is Claude's.

## Steps

1. `python3 scripts/resolve.py purge`; list the open rows of the volume.
2. For every row gather the context (show both works / persons: title, authors, editors,
   date, container, volume, pages, series, publisher, uri, which articles cite them; for
   persons, all their works and the names in `data/persone_zotero.csv`). Never read
   works.csv whole: `python3 scripts/show_works.py W… W…` or grep.
3. Classify each row:
   - **AUTO** - the rules below give the answer with no reasonable doubt. Apply it with
     `--auto "short reason"` (merge, set, detach, done). Each auto decision must be one a
     careful bibliographer would take without looking anything up beyond the citations and
     the tables (a quick web check is fine and should be quoted in the reason).
   - **ASK** - anything else: conflicting evidence, a policy case not covered below,
     a merge of persons resting only on initials, any change to a work or person cited
     by more than 5 articles, anything Claude would hesitate to defend.
   When in doubt: ASK. A wrong merge is much more expensive than a question.
   A `merge-work` stopped because each work has persons the other lacks is always ASK
   (`--authors keep|drop` only after Giacomo's choice).
4. Look for errors of the parsing or of the scripts at the same time (placeholder names,
   a chapter attached to its volume, cells filled with data of another work). Fix the ones
   of the current volume (`detach`, `set`, `--auto`), search the whole table for the same
   pattern, and report it: a recurring error means the skill or a script must be fixed.
5. End of volume: `drop-orphans`, `python3 scripts/audit_duplicates.py`, `purge`. Pairs
   flagged "same AeC issue" or "same editors" are whole volumes with different title forms:
   AUTO only when the rules below make them the same work, otherwise ASK.
   A whole-volume record (book/proceedings of an AeC issue or Supplement) flagged against
   the AeC-metadata record of the same issue (`src:aec-metadata`) is AUTO `done`: they are
   kept apart by rule (Giacomo, 20/10/2026). Two whole-volume records of the same issue are
   merged as usual (keep the older id).
6. Report to Giacomo (Italian), short:
   - counts: rows, AUTO, ASK;
   - AUTO decisions grouped by rule, one line each (ids + titles), and a random sample of
     5 of them marked "da controllare a campione";
   - ASK cases numbered and explained in full (titles, authors, years), each with a
     proposal and the alternatives;
   - script/parsing problems found.
   Giacomo's answers are applied normally (without `--auto`). If he finds a wrong AUTO
   decision, undo it, fix the rule here and re-check the other decisions of that rule.

## Decision rules (from Giacomo's decisions, vol. 13-16)

Works - same work, merge (keep the older id):
- Same title (or variants: abbreviation, "Valle"/"Val di", subtitle cited or not, typos),
  same authors/editors, same container, overlapping pages: merge even with year +-1
  (conference year vs publication year, "1997" vs "1998" of the same volume).
- Page ranges that differ by up to 2-3 pages in the first and/or last page (blank pages counted by some authors) are the same pages (Giacomo, 20/10/2026): never a conflict (Reilly 132-139 / 133-140).
- Numbers in the title that are only the volume number of a work already identified by
  series + number ("Discipline umanistiche e informatica 1" = the volume, series n. 87).
- The tome of a volume ("Etrusca et Italica, II") is not another work: merge, keep the
  record without the tome.
- The same web resource / thesaurus / standard cited with different access years or
  publishers of the same body (Getty TGN 1998/2000, MDA thesaurus, MIDAS reprint): merge,
  keep the uri.
- A "c.s." work found later as published = the same work: merge, set the real date.
- Proceedings cited with the years of the meetings ("1991, 1993, voll. 1-2") are the
  published work that collects them (Valdés 1995): merge on the published work.
- An article cited with a series number that is evidently wrong (BAR 834/1575 for S1075)
  is still the same volume when title, editor, year and the cited chapters agree.
- Authors cited as authors in one place and as editors in another for an edited volume:
  merge, keep them as editors.

Works - different, keep separate (`done`):
- Parts / volumes / tomes of a multi-part work (I/II, III.1/III.2, Part I/Part II,
  successive "Rassegna" issues), different years with different journal volumes.
- Different editions of printed works (Munsell 1975/1994, revised): separate. The same text
  reprinted by another publisher (Kosko, Fuzzy Thinking, Hyperion 1993 / Flamingo 1994):
  merge on the first edition (Giacomo, vol. 17).
- Different versions of a standard (CIDOC CRM 1999 vs 2004): separate.
- Same opening words, different subtitle or different authors (Peer-to-Peer books and
  encyclopedia entries, Tiber Valley Project papers, "Engaging place" 1997/1999).
- Two different institutions or web sites.
- A chapter and the volume that contains it: never the same work.

Works - citations of a whole series:
- A line citing a multi-volume series at once ("CIE I-II.2 1975-1986") is linked to the
  single volumes (clone-work/detach + merge into each volume); no record for the series.

Works - cells:
- Corporate pseudo-authors for anonymous publications ("DIGICULT") are not kept as
  creators when the publication names nobody: empty creator/editor.
- A sole editor is not also creator of the volume.

Persons:
- Same surname + compatible initials + same field / same works / same volume edited:
  same person (Exon S. = Sally Exon for CAA97; Greco G. on the Heraion = Giovanna Greco).
  Merge and set the full name when it is certain from the works (not from the Zotero list
  alone when it has several compatible names).
- Same surname + initials in clearly different fields (cognitive psychology vs Phoenician
  studies; 1939 Roman maps vs 2004 librarianship): different persons; give the new one the
  full name only if it is certain (e.g. "I Fenici" 2004 = Corinne Bonnet), otherwise keep
  the initials. Set `_notes` "checked ... different from Pxxxxxx".
- The Zotero list has typos in given names (Keri -> Kayt Brown, William -> Wayne McCall):
  when the works of the person contradict the Zotero name, ASK.
- Initials of the cited form that contradict the table person ("Brown J." for Lock & Brown
  2000, editor Kayt Brown): the citation is wrong if the other citations of the same volume
  agree; fix the editor, AUTO only when 2+ independent citations agree.

- One person record may conflate two people with the same initials (Maetzke G.: Gabriella
  for the Polish excavation papers, Guglielmo for the Volterra urns; Mastronuzzi G.:
  Giuseppe the geologist, Giovanni the archaeologist): look at all the works of the
  candidate before merging, and split (add-person + set) when the fields differ.

c.s. (cs_unresolved):
- Search author + title (and author + key words). Found with the same title, authors and
  container: AUTO (set date, container, volume, pages; tag cs-resolved; quote the source).
- Published with another title or other author order (Tiber Valley 2020): ASK with the
  proposal "update to the published data".
- Not found: AUTO `done "searched: still c.s."`, but list them in the report (Giacomo
  often knows where they ended up).

low_confidence:
- Fix obvious cases (series name, volume/issue split) AUTO when the reading is certain;
  dates or numbers not written in the citation: ASK.
