# BibliografiAeC

Turns the bibliographies of *Archeologia e Calcolatori* (AeC) into local CSV tables
(persons, works, citations) to be imported into BiDiAr (Omeka S) in one go.
Everything runs locally; Omeka is not touched until the final import.

## Layout

```
BibliografiAeC/
├── CLAUDE.md
├── .claude/skills/parse-aec-bibliography/SKILL.md   how to process an article (read it first)
├── data/
│   ├── all_metadata.json              AeC article metadata (journal + supplements)
│   ├── persone_zotero.csv             names from the old Zotero library (unique matches trusted)
│   ├── journal/{volume}/{aec_id}.md   bibliography only, one reference per line
│   └── supplements/{volume}/{aec_id}.md
├── scripts/
│   ├── aec_metadata_to_csv.py         all_metadata.json -> works.csv + persons.csv (run once, already done)
│   ├── merge_article.py               output/parsed/{aec_id}.json -> tables (+ audit of new works)
│   ├── audit_duplicates.py            duplicate works/persons across the whole tables (read-only)
│   ├── health_check.py                read-only integrity + citation-link check -> output/health_check.csv
│   ├── find_aec.py                    finds a cited AeC article in all_metadata.json (cited_aec_id)
│   ├── suggest_names.py               full given names from persone_zotero.csv -> output/name_suggestions.csv
│   └── resolve.py                     applies Giacomo's decisions on review.csv
└── output/
    ├── works.csv  persons.csv  citations.csv  review.csv
    ├── review_archive.csv             closed review rows (decision + date)
    ├── decisions.log                  every change made with resolve.py
    ├── archivio/                      applied name/DOI lists (nomi/), API caches (api_cache/), old reports (report/)
    ├── parsed/{aec_id}.json           parsing result of each article (written by Claude)
    └── backup/{timestamp}/            copy of the tables before every merge
```

## Workflow

**Order (decided by Giacomo 19/10/2026):** close the journal first (vols. 24-37), then the
supplements 1-15 (not chronologically interleaved): the Zotero names list does not cover the
supplements, so they are processed last, when most persons already exist. Backups: pruned on 22/10/2026 (Giacomo): kept the named copies, the last copy of each day and the last 50; prune the same way when they grow again. Open points left
over: `name_suggestions.csv` has 3 `unique` proposals not applied (Gero J.S. -> John S.,
Higgs E.S.C. -> Eric S., Landrum J.E. III -> James E.: not confirmed; Joan M. Gero exists but
her initials are J.M.); the other ambiguous names are decided case by case. Before parsing
vols. 25-37 check their MD: most still hold the full text (not only the bibliography), vols.
28 and 31-37 sit in per-issue subfolders (`28.1`, `32_1`...), so `data/journal/{volume}/{aec_id}.md`
may not match.

Volume by volume, **in chronological order** (vol. 1 first), so that a cited AeC article
or an already cited work exists before it is cited again. For each article:

1. Claude reads `data/.../{aec_id}.md` and writes `output/parsed/{aec_id}.json`
   following the skill (parsing, "c.s." search online).
2. `python3 scripts/merge_article.py {aec_id}` assigns identifiers, reuses existing
   persons/works, appends rows, writes doubtful cases to `review.csv`, then audits the new
   works against the whole table (`audit_duplicate` rows). A `certain`/`probable` audit
   row means a duplicate slipped through: stop and tell Giacomo before going on.
3. Claude runs the pre-review of the volume (skill `prereview-aec-volume`): clear cases
   are applied with `resolve.py ... --auto "reason"`, the others go to Giacomo in a short
   report (hybrid mode, decided 19/10/2026).
4. Giacomo answers the report and spot-checks a sample of the `[auto]` decisions.

**Page tolerance (Giacomo, 20/10/2026):** pages of a contribution that differ by up to 2-3 pages in the first and/or last page count as identical (some authors count blank pages before/after the contribution). Not a reason to keep two records apart, nor to send a case to review.

**Matching rule (never relax it):** every identity check (works and persons) must consider
the whole table. Restricted candidate pools (same author, same volume, AeC only…) are only a
speed-up, never a filter. When a safety rule forbids an automatic merge (different year,
volume, numbers, authors), the case goes to `review.csv`: it is never silently created as a
new record. The same holds for persons: a citation without given name ("LEFEBVRE 1974") is
never attached automatically to a named person (nor the reverse): it gets a new person and a
`person_ambiguous` review row. Likewise when cited initials match the only person in the
table but the Zotero list knows several compatible first names ("Tosi M." = Maria Letizia or
Maurizio), unless the table person accounts for 80%+ of those names in the list or is marked
`initials-ok` in `_notes` (set after Giacomo checked it).
Authors of two works are compared by person id **or by name** (same surname, or a spelling
variant with 5+ letters and similarity >= 0.85, plus compatible given names): placeholders and
variant spellings have their own ids (fix of 19/10/2026, vol. 15 test: 205 existing works
reused instead of 183, 0 wrong). A work with no persons against one with persons is not a
conflict when the title is long (20+ characters).
Typo variants of the Zotero list ("Giulano"/"Giuliano": one letter added or dropped inside
the name, `suggest_names.typo_pair`) count as one name in the ambiguity check (fix of
19/10/2026); they never choose which spelling is applied.
Placeholders (persons created for an ambiguous case, `_notes` = `ambiguous: could be …`) are
never candidates for later citations; within one article the same cited form reuses the same
placeholder (fix of 18/10/2026, vol. 14 had one new person per occurrence). Persons created
while merging an article and left unused (the work already existed with its own persons)
are removed at the end of the article together with their `person_ambiguous` rows.
A short title counts as the main title of a longer one only when the longer title goes on
with a separator ("X. …", "X: …", "X (…)"), and a chapter is never merged automatically
with a book/proceedings (fix of 19/10/2026, vol. 16: Sanders 2002 "Virtual Archaeology and
museums" had been merged into the volume "Virtual Archaeology"; the same for Allen et al. 1990).
A short title also counts as the main title of a longer one that goes on after a comma followed by a capital letter outside parentheses ("Quale futuro per l'Archeologia?, Atti del Workshop…", fix of 20/10/2026, vol. 30), only when the short title has 3+ words; a comma inside a title ("Relazioni tra geomorfologia, processi…") is never a separator.
Two titles with the same main title (before ". ", ": ") but different subtitles are merged
automatically only when the main title has 3+ words; with 1-2 words ("Archaeology: A Very
Short Introduction" / "Archaeology: Theories, Methods and Practice") the case goes to review
(fix of 19/10/2026, vol. 24; test on vols. 1-24: 22 links unchanged, 4 correct links would
now be reviewed, vol. 24 re-merged with the same result except Bahn 2000).
`audit_duplicates.py` also pairs whole volumes whatever their titles: two book/proceedings
records of the same AeC volume (probable if same year) and two with the same 2+ editors and
years at most 1 apart (possible) (fix of 19/10/2026, vol. 24: AeC 7, 13 and 15 had several
records; a whole volume cited with only its first editor is still not found).
A whole AeC issue or Supplement cited as a monograph is its own `proceedings`/`book` record
(`isPartOf` = `Archeologia e Calcolatori`, volume `28`+issue `2` or `Suppl. N`), never merged
with the AeC-metadata record of that issue, which is kept as it is (rule of 20/10/2026).
`find_aec.py` and merge_article.py keep the journal and the Supplements apart: "Suppl. 2"
looks only among the Supplements, a plain "2" only in the journal (fix of 19/10/2026).
Two different entries of the same bibliography are two different works (rule of 19/10/2026,
general check at vol. 23: six wrong merges in vols. 1-23, e.g. a chapter merged into the citing
article itself): merge_article.py never reuses a work already taken by another entry of the
same article unless the two lines are the same entry repeated (similarity >= 0.95: double
bibliographies, OCR variants), never matches the citing article itself, and only prints
"kept apart" (no review row). The audit skips pairs cited by the same article. Known cost:
an author who lists the same book twice in different forms gets two works (rare, accepted).
An AeC article cited with a provisional title is recognised by volume + first page
(`find_aec.py` with volume and page; merge_article.py as a fallback, with a `low_confidence` row).
That fallback is skipped for `book`/`proceedings` references and for page ranges wider than the matched article (fix of 21/10/2026, vol. 37: whole issues/sections such as H2IOSC I-III were attached to the AeC introductions).
`data/persone_zotero.csv` (names from the old Zotero library, same AeC bibliographies):
when it has exactly ONE full name compatible with cited initials, that name is trusted
(decision 18/10/2026): merge_article.py uses it for new persons, `resolve.py apply-names
unique` for existing ones; the cited form stays in `_variants`. Variants, ambiguous names
and persons without given name are only suggestions (`suggest_names.py` ->
`output/name_suggestions.csv`, and grep the surname in `person_ambiguous` reviews): never
apply them without Giacomo's confirmation. `audit_duplicates.py` is the independent check that this
holds; run it at the end of every volume.

Claude never edits the CSV tables by hand (only through the scripts) and never reads `works.csv` whole (it grows to
20,000+ rows): matching and identifiers are the script's job. To look something up,
use `grep` on the tables.

## Articles deliberately not processed

- **267** (vol. 10, Giudice et al. 1999, *L'archivio ceramografico dell'Università di Catania*):
  bibliography too poorly made (bare journal references such as "AEspA 1958, 104-125").
  Decided by Giacomo on 19/10/2026: left without citations, do not come back to it.

## Tables

Conventions:
- identifiers in `dcterms:identifier`: persons `P000001`, works `W000001`; never reused or renumbered
- multi-value cells: `|` with no spaces, e.g. `P000012|P000013` (order = author order)
- columns starting with `_` are working columns, not imported
- UTF-8 with BOM, so that Excel opens the files correctly

**persons.csv**: `dcterms:identifier`, `foaf:familyName`, `foaf:givenName`, `orcid`,
`_variants` (other forms met, `Family, Given|…`), `_notes`. One person, whatever the role:
the same id is used as creator or editor.

**works.csv**: one row per work (AeC articles + every cited work). Columns = properties of
the Omeka template `-ZoteroImport`, minus editorList, shortTitle, foaf:homepage, citedBy:

| column | content |
|---|---|
| `dcterms:identifier` | `W000123` |
| `dcterms:type` | `article`, `book`, `chapter`, `proceedings`, `thesis`, `other`, `conference communication` (talk with no proceedings), `unpublished work` (never published) |
| `dcterms:title` | title as cited (OCR errors corrected) |
| `dcterms:creator`, `bibo:editor` | person ids, `\|`-separated |
| `dcterms:date` | year; `c.s.` only for recent works really in press (tag `cs-unresolved`). Old c.s. that will never appear are retyped `conference communication` / `unpublished work` (Giacomo 22/10/2026), tag `cs-closed`, date = year cited, or empty |
| `dcterms:isPartOf` | **text**: journal or volume title; several levels `\|`-separated (e.g. `Proceedings title\|Journal`) |
| `bibo:volume`, `bibo:issue`, `bibo:pages` | as cited, pages `81-110` |
| `bibo:edition` | edition number when the cited copy is a later edition (e.g. `2`); empty for first editions |
| `dcat:inSeries`, `curation:number` | series title and number |
| `dcterms:publisher`, `dcterms:spatial` | publisher, place of publication |
| `dcterms:language` | ISO 639-2 (`ita`, `eng`, `fre`, `ger`, `spa`) |
| `bibo:doi`, `bibo:uri` | only if in the citation (AeC articles: from metadata) |
| `dcterms:rights`, `bibo:issn`, `dcterms:abstract` | AeC articles only |
| `bibo:numVolumes`, `bibo:numPages`, `bibo:isbn` | normally empty |
| `curation:tag` | working tags (private): `src:aec-{id}`, `cs-resolved`, `cs-unresolved`, `da-verificare` |
| `_aec_id` | AeC article id (AeC articles only) |

`isPartOf` journals and volumes are text, not Omeka items.

**citations.csv**: `citing` (W id of the AeC article), `cited` (W id), `position` (line in
the bibliography), `raw` (citation string, provenance only, not imported), `_citing_aec_id`.

**review.csv** (open rows only): `review_id`, `citing_aec_id`, `position`, `issue`, `details`, `raw`, `done`.
**review_archive.csv**: same columns + `closed_at`.
Issues: `person_ambiguous`, `possible_duplicate`, `cs_unresolved`, `low_confidence`, `bad_type`,
`audit_duplicate`, `audit_person` (from the duplicate audit; details: level, both ids, conflicts).

## Resolving review.csv

Every review row has a progressive numeric `review_id` (never reused), so Giacomo can say
"vediamo la review 22", "le review 30-35" or "la review dell'articolo 5". Always show the
id when listing rows.

Giacomo decides, Claude applies; the only exception is the pre-review, where Claude applies
the cases covered by the rules of the `prereview-aec-volume` skill with `--auto` (logged as
`[auto]` in decisions.log) and leaves everything else to Giacomo. When Giacomo asks to go through the review, show the open rows (`done` empty) one group at a time with
the useful context (grep the rows of the ids involved in works.csv / persons.csv), propose
a decision, and apply only what Giacomo confirms, with `scripts/resolve.py`:

- `merge-person DROP KEEP` — same person (keep the id with the fuller name)
- `merge-work DROP KEEP` — same work (keep the older id). If DROP lists more authors or
  editors than KEEP ("et al."), KEEP gets the full list; if each side has persons the other
  lacks, the command stops and must be repeated with `--authors keep` or `--authors drop`
  after Giacomo's choice (fix of 19/10/2026, vol. 24: co-authors had been lost)
- `detach AEC_ID POSITION` — give one citation its own new work (copy of the cells), when it
  was attached to the wrong work; then fix the new work with `set`
- `rebuild AEC_ID POSITION` — like detach, but the new work is rebuilt from the parsed
  reference with its own persons; then clear with `set` the cells the citation had filled
  in the old work (fill_blanks)
- `set ID COLUMN VALUE` — fix one cell (e.g. date of a "c.s." found later)
- `done REVIEW_ID [NOTE]` — close the row (also `22,25` or `22-30`); also when the answer is
  "they are different".
  The row leaves `review.csv` and goes to `review_archive.csv` with the note and the date.
- `drop-orphans` — remove persons no longer linked to any work (left by `merge-work`);
  run it at the end of every volume review, before `audit_duplicates.py`
- `purge` — archive every row whose `done` cell is filled (decisions Giacomo wrote in Excel,
  or rows closed before this rule existed)

`review.csv` must only contain **open** rows. Run `purge` at the start of every review and
before ending it, then report how many rows are still open. Never delete review rows any
other way. Never apply a merge on your own initiative outside the pre-review rules. Every command is logged in
`output/decisions.log` and preceded by a backup.

## Import order (later)

1. persons; 2. works (creator/editor linked to persons through `dcterms:identifier`);
3. citations as `bibo:cites` on the citing work (Omeka shows the inverse by itself).
The export script for the import will be written when the tables are complete.

## Language

Code comments and documentation in English; talk to Giacomo in Italian.
