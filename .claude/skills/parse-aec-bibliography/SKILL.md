---
name: parse-aec-bibliography
description: Parse the bibliography of one or more Archeologia e Calcolatori articles (data/journal or data/supplements .md files) into output/parsed/{aec_id}.json and merge it into the CSV tables. Use when asked to process, parse or "elaborare" an article, a list of articles or a volume.
---

# Parse an AeC bibliography

Input: `data/journal/{volume}/{aec_id}.md` (or `data/supplements/...`): YAML frontmatter
(`url` ends with the AeC id) + the bibliography, one reference per line.
Output: `output/parsed/{aec_id}.json`, then `python3 scripts/merge_article.py {aec_id}`.

For a volume: process the articles in ascending order of first page (or id), one at a time,
merging each before parsing the next.

## Steps

1. Skip the article if `output/parsed/{aec_id}.json` already exists (say so).
2. Read the .md. Number the non-empty lines from 1: that is `position`.
   A line that is not a reference at all (a note, a heading, an acknowledgement, a caption)
   is excluded in the spec with `{"pos": N, "skip": "reason"}`: it produces no reference and
   is kept under `skipped` in the JSON. Never force it into a reference.
   If a line is clearly the tail of the previous reference (e.g. just `Venezia.`), join
   it to the previous one and note it in `notes`; positions follow the joined list.
3. Parse every reference with the rules below. Look at the whole list before parsing:
   short forms ("in D'ANDRIA 1987, 63-90") refer to another entry of the same list.
4. For each "c.s." / "in corso di stampa" / "in press" / "forthcoming": search the web
   (author + title). If it was published, fill date, container, volume, pages from the
   publication and set `cs.status = "resolved"` with `cs.source`; otherwise
   `date = "c.s."` and `cs.status = "unresolved"`. Do not search for anything else.
   Unresolved c.s. of articles older than ~2017 are not expected to appear any more (Giacomo,
   22/10/2026): after the search, list them for Giacomo, who decides case by case whether they
   become `conference communication` (talk with no proceedings) or `unpublished work` (never
   published); recent works really in press stay `c.s.` / `unresolved`.
5. For every reference that is an AeC article (container "Archeologia e Calcolatori",
   including papers in the proceedings published as AeC 7 and AeC 9, see below), look it up:
   `python3 scripts/find_aec.py "{first author family}" "{title}" {volume} {first page}`
   (or `""` as family for anonymous works; volume and page when cited; a Supplements volume
   as `"Suppl. N"`). A "vol+page" hit
   with the same authors is the same article even if the title differs (provisional title). If one result clearly matches (same author and title; a different
   volume is fine, authors sometimes cite the wrong one), set `cited_aec_id` to its id and,
   if the cited volume or year differ from the metadata, say so in `notes`. Keep all the
   other fields as cited. No clear match: omit `cited_aec_id`.
6. Write the JSON (faster: write a spec without the `raw` lines and run
   `python3 scripts/build_parsed.py {aec_id} spec.json`, which copies `raw` by position and
   checks that no line is missing), run `python3 scripts/merge_article.py {aec_id}`, report its output
   (counts and the new review ids, e.g. "review 47-51").
7. The merge ends with a duplicate audit of the new works against the whole table
   ("+N from the duplicate audit", review rows with issue `audit_duplicate`). If any of
   these rows is `certain` or `probable`, **stop before the next article** and show them
   to Giacomo: a duplicate certainly slipped through and the cause must be understood.
8. If the merge exits with an error, stop and tell Giacomo; never edit the CSVs by hand.

At the end of a volume run `python3 scripts/audit_duplicates.py` (read-only on the tables)
and report its summary line by line.

## Parsing rules

- Transcribe what the citation says; do not complete it from memory or from the web
  (only exception: step 4). Never invent DOIs, URLs, first names, publishers.
- Fix obvious OCR noise (`R1cc1` → `Ricci`, `CARANDIN!` → `Carandini`, `o/` → `of`,
  `Statistica!` → `Statistical`, `0RTON` → `Orton`). If unsure, keep the text and set
  `confidence: "low"`.
- Names: `family` in normal case (`ALOIA` → `Aloia`, keep particles: `De Santo`,
  `D'Andria`, `Beltran Lloris`); `given` as cited (`N.`, `M.L.`, `Paola`).
  `AA.VV.` / `Aa.Vv.` → no creators. Institutions as editors (e.g. "a cura dell'Istituto
  Nazionale di Archeologia…") → `family` = full institution name, `given` = "".
- `editors`: editors of the cited work itself (edited book, proceedings) **or** of the
  volume containing a chapter ("in R. FRANCOVICH, R. PARENTI (edd.), …"). For a short
  form ("in Moscati, Orlandi 2019") copy editors and container title from the referred entry.
- `title`: without markdown (`*…*`), without quotes or guillemets, no trailing punctuation.
- `is_part_of` (list, outer level last): journal title without «», volume title for a
  chapter, `["Proceedings title", "Journal"]` for a paper in proceedings published as a
  journal issue. Empty for books.
- AeC monographic issues: AeC 7 (1996) = *III International Symposium on Computing and
  Archaeology - Roma 22-25 novembre 1995* (Giacomo's choice of 19/10/2026, work W004366,
  even when cited as "III Convegno Internazionale di Archeologia e Informatica") and AeC 9 (1998) = *Methodological Trends and Future Perspectives in the
  Application of GIS in Archaeology*. A paper cited "in P. Moscati (ed.), III Convegno…"
  is an AeC article: `type: article`, `is_part_of: ["{proceedings title}", "Archeologia e
  Calcolatori"]`, `volume: "7"` (or `"9"`), plus `cited_aec_id` (step 5). The whole volume
  cited as such is `type: proceedings` with the same `is_part_of` and volume. Use the
  same form every time, whatever the citation looks like.
- Whole AeC volume cited as a monograph (rule of Giacomo, 20/10/2026): any monographic
  journal issue (e.g. 28.2, KAINUA 2017) or Supplement cited as a whole ("Garagnani S.,
  Gaucci A. (eds.) 2017, Knowledge, analysis…, «Archeologia e Calcolatori», 28.2") is a
  separate whole-volume work, never the AeC-metadata record of that issue (those records,
  even when titled like the volume and typed `article`, stay as they are): `type:
  proceedings` for conference volumes, `book` otherwise; editors as cited; `is_part_of:
  ["Archeologia e Calcolatori"]`; `volume` `"28"` + `issue` `"2"`, or `"Suppl. N"`; no
  `cited_aec_id`. Its papers stay AeC articles with their own `cited_aec_id`.
- `type`: `article` (in a journal), `book` (monograph or edited book), `chapter`
  (contribution in a volume, including proceedings), `proceedings` (whole proceedings
  volume), `thesis`, `other` (reports, maps, software, web pages, internal notes…).
- `date`: the year of the citation (`1987b` → `1987`); `c.s.` see step 4.
- `volume` / `issue`: as cited (`28.2` → volume `28`, issue `2`; `Suppl. 9` → volume `Suppl. 9`).
- `edition`: only if stated in the citation or known to be a reprint/new edition cited by the author (`II ed.` → `2`).
- `pages`: `81-110` (hyphen, no "pp."); a single page is fine.
- `series` / `series_number`: e.g. `BAR International Series` / `2177`,
  `Quaderni di informatica e beni culturali` / `9`.
- `language`: ISO 639-2 from the title (`ita`, `eng`, `fre`, `ger`, `spa`).
- `doi` / `uri`: only if written in the citation; `doi` without `https://doi.org/`.
- `xref`: position of the referred entry for short forms, otherwise omit.
- `confidence`: `"low"` when any field is a guess; explain in `notes`.

## JSON format

```json
{
  "citing_aec_id": 5,
  "source_file": "data/journal/1/5.md",
  "references": [
    {
      "position": 11,
      "raw": "GOTTARELL! A. 1987, Tecniche di documentazione dello scavo archeologico: introduzione alla videometria digitali:t.zata, in D'ANDRIA 1987, 63-90.",
      "type": "chapter",
      "creators": [{"family": "Gottarelli", "given": "A."}],
      "editors": [{"family": "D'Andria", "given": "F."}],
      "date": "1987",
      "title": "Tecniche di documentazione dello scavo archeologico: introduzione alla videometria digitalizzata",
      "is_part_of": ["Informatica e archeologia classica. Atti del Convegno Internazionale. Lecce 12-13 Maggio 1986"],
      "pages": "63-90",
      "place": "Galatina",
      "language": "ita",
      "xref": 7,
      "confidence": "high"
    },
    {
      "position": 18,
      "raw": "SILVESTRINI M., PIGNOCCHI G. c.s., L'insediamento dell'età del Bronzo di Moscosi di Cingoli (MC), in corso di stampa.",
      "type": "other",
      "creators": [{"family": "Silvestrini", "given": "M."}, {"family": "Pignocchi", "given": "G."}],
      "date": "c.s.",
      "title": "L'insediamento dell'età del Bronzo di Moscosi di Cingoli (MC)",
      "language": "ita",
      "cs": {"status": "unresolved"},
      "notes": "searched author + title: no publication found",
      "confidence": "high"
    }
  ]
}
```

Allowed keys per reference: `position`, `raw` (exact line, required), `type`, `creators`,
`editors`, `date`, `title`, `is_part_of`, `volume`, `issue`, `edition`, `pages`, `series`,
`series_number`, `publisher`, `place`, `language`, `doi`, `uri`, `xref`, `cited_aec_id`
(number, AeC id of a cited AeC article, step 5), `cs` (`status`, `source`), `confidence`,
`notes`. Omit empty keys.
