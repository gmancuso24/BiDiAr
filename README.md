<p align="center">
  <a href="https://bidiar.cnr.it">
    <img src="https://chloe.cnr.it/files/asset/98b0ac7e780e80229e99af06b5dbf99502d1c2f8.jpg" alt="BiDiAr – Bibliography of Digital Archaeology" width="320">
  </a>
</p>

<h1 align="center">AeC Bibliography – Curated Tables for BiDiAr</h1>

<p align="center">
  Final, import-ready tables of the <em>Archeologia e Calcolatori</em> (AeC) bibliography,
  prepared for the <a href="https://bidiar.cnr.it">Bibliography of Digital Archaeology (BiDiAr)</a>.
</p>

---

## Table of contents

- [About](#about)
- [Context: BiDiAr and H2IOSC](#context-bidiar-and-h2iosc)
- [What this repository contains](#what-this-repository-contains)
- [Data model](#data-model)
- [Tables](#tables)
- [Processing workflow](#processing-workflow)
- [Zotero library](#zotero-library)
- [Related repositories](#related-repositories)
- [Coverage and status](#coverage-and-status)
- [Licence](#licence)
- [How to cite](#how-to-cite)
- [Contacts and acknowledgements](#contacts-and-acknowledgements)

---

## About

This repository hosts the **definitive tables** produced by converting the entire bibliography of the journal *Archeologia e Calcolatori* (AeC) into structured bibliographic metadata. The tables are designed to be imported into **BiDiAr**, the open-access Bibliography of Digital Archaeology, in order to describe the references cited in AeC and to build and manage the **citation network** between works.

In short, starting from the reference lists printed at the end of each AeC article, the workflow produces:

- a table of **works** (bibliographic records);
- a table of **people** (authors and editors, disambiguated and, where possible, with full names and ORCID);
- a table of **citations** (which work cites which), expressed through stable internal identifiers.

> **Scope of this repository.** The repository holds the working tables of the project (`output/`), the parsing results of every article, the scripts and the project instructions used to build them. The raw Markdown bibliographies and metadata (`data/`), the automatic backups of the tables and the API caches are **not** versioned here, because they live elsewhere or can be regenerated (see [Related repositories](#related-repositories)).

## Context: BiDiAr and H2IOSC

[**BiDiAr**](https://bidiar.cnr.it) (*Bibliography of Digital Archaeology*) is an open-access bibliographic database that collects, organises and enriches references related to digital methods and tools in archaeology. It is built on Zotero and integrated into the DHeLO infrastructure; it indexes scientific literature with structured metadata, linking bibliographic entries to associated datasets, projects and software, and it traces the development of digital archaeology over time. The platform currently holds over 10,000 records and is published through [Omeka S](https://omeka.org/s/) in the [CHLOE – Cultural Heritage Linked Open data Environment](https://chloe.cnr.it/s/BiDiAr).

BiDiAr was developed within [**H2IOSC**](https://www.h2iosc.cnr.it) (*Humanities and Cultural Heritage Italian Open Science Cloud*), the PNRR project federating the four Italian nodes of the European research infrastructures CLARIN-IT, DARIAH-IT, E-RIHS.it and OPERAS-IT. E-RIHS.it is coordinated by [CNR-ISPC](https://www.ispc.cnr.it) (Institute of Heritage Science).

Useful entry points:

- Website: <https://bidiar.cnr.it> (Omeka S site: <https://chloe.cnr.it/s/BiDiAr>)
- Bibliographic search: <https://chloe.cnr.it/s/BiDiAr/BibliographicSearch>
- Zotero group library: <https://www.zotero.org/groups/5293298/bidiar/library>

## What this repository contains

```text
.
├── README.md
├── LICENSE
├── CLAUDE.md                  # project rules: workflow, matching rules, table conventions
├── PASSAGGIO_CONSEGNE.md      # handover notes: status, working habits, open points
├── PIANO_LAVORO.md            # work plan
├── .claude/
│   └── skills/
│       ├── parse-aec-bibliography/   # how to parse the bibliography of one article
│       └── prereview-aec-volume/     # automatic pre-review of a volume's review rows
├── scripts/                   # Python tools (they only read/write the tables via these scripts)
│   ├── aec_metadata_to_csv.py        # AeC metadata -> initial works/persons tables
│   ├── build_parsed.py               # builds output/parsed/{aec_id}.json from a compact spec
│   ├── merge_article.py              # parsed article -> tables (+ duplicate audit)
│   ├── resolve.py                    # applies review decisions (merge, detach, set, done, purge...)
│   ├── audit_duplicates.py           # read-only duplicate audit of works and persons
│   ├── health_check.py               # read-only integrity and citation-link check
│   ├── find_aec.py                   # finds a cited AeC article in the metadata
│   ├── show_works.py                 # read-only: prints works compactly (authors, container, citing articles)
│   ├── suggest_names.py              # full given names from the Zotero names list
│   ├── fetch_names_api.py            # proposes full given names from Crossref/OpenAlex records (via DOI)
│   └── missing_names_list.py         # lists persons with no given name or initials only
└── output/
    ├── works.csv                     # bibliographic records (AeC articles + cited works)
    ├── persons.csv                   # authors and editors
    ├── citations.csv                 # citing -> cited links
    ├── review.csv                    # open review rows
    ├── review_archive.csv            # closed review rows (decision + date)
    ├── decisions.log                 # log of every change made with resolve.py
    ├── cs_non_risolti.md             # unresolved "c.s." / in-press references
    ├── health_check.csv              # latest output of health_check.py
    ├── audit_duplicates.csv          # latest output of audit_duplicates.py
    └── parsed/                       # one JSON per article: parsing result of its bibliography
```

Not versioned (see `.gitignore`): `data/` (AeC metadata, Zotero names list, Markdown bibliographies), `output/backup/` (copy of the tables before every merge) and `output/archivio/` (applied name lists, API caches, old reports).

The tables currently live in `output/` under their working names (`persons.csv`, not `people.csv`). The export script that will produce the import-ready files for Omeka S is still to be written.

## Data model

The tables follow the structure of the Omeka S import template used by BiDiAr (the *ZoteroImport* resource template), based on standard vocabularies (Dublin Core Terms, BIBO, FOAF). The main design choices are:

- **Internal identifier.** Each work and each person has a stable internal identifier (`dcterms:identifier` for works; a person ID for people), assigned during the workflow and used as the primary key to link tables.
- **People in a single table.** Authors and editors are stored together in `people`, with no creator/editor distinction at that level. In `works`, the `creators` and `editors` columns hold **lists of person IDs separated by `|`** (no spaces).
- **Citations as links between identifiers.** Citations are recorded only in the *cites* direction (`bibo:cites`); the inverse relation (*cited by*) is derived by the platform.
- **Containers as text.** The container of a work (journal, volume, collection – `isPartOf`) is kept as a **text value**: no separate records are created for cited journals or series.
- **Controlled type vocabulary.** `dcterms:type` uses a reduced controlled vocabulary.
- **Journal metadata.** AeC ISSN: 2385-1953 (online), 1120-6861 (print).
- **Licence of the records:** CC BY-NC-ND 4.0.

### Import order in Omeka S

Because tables reference each other through identifiers, they must be imported in this order:

1. **People** (authors/editors)
2. **Works** (records)
3. **Citations**

## Tables

> The column lists below are a summary; the authoritative field mapping is the one of the BiDiAr import template and the table conventions in `CLAUDE.md`. Columns starting with `_` are working columns and are not imported.
> <!-- TODO: complete with the final column names after the last export. -->

### `works`

One row per distinct bibliographic work (cited by at least one AeC article, or an AeC article itself).

| Field | Description |
|---|---|
| `dcterms:identifier` | Internal primary key of the work |
| `dcterms:title` | Title |
| `creators` / `editors` | Person IDs separated by `\|` (see `people`) |
| `dcterms:date` | Year of publication |
| `dcterms:type` | Resource type (reduced vocabulary) |
| `dcterms:isPartOf` | Container (journal, volume, series) as text |
| … | Further fields as per the import template |

### `people`

One row per distinct person (author or editor).

| Field | Description |
|---|---|
| person ID | Internal primary key |
| family name / given name | Name parts; full given names added where they could be reliably established |
| `ORCID` | ORCID iD, where available |

### `citations`

One row per citation link.

| Field | Description |
|---|---|
| citing work | Identifier of the citing work (AeC article) |
| cited work | Identifier of the cited work |

Citing AeC articles are identified through the **URL of the article on the AeC website** (older volumes do not have a DOI).

## Processing workflow

The tables are the end result of a multi-step process, carried out **volume by volume** in chronological order, starting from volume 1 of AeC.

1. **Source.** Reference lists of AeC articles, extracted from the PDFs into Markdown (one reference per line). These raw files are not distributed here.
2. **Parsing.** Each reference is parsed into structured metadata with the help of an LLM-based workflow (Claude Code in a dedicated working folder, with project-specific instructions and scripts), starting from a small **gold standard** of normalised references (bibliographies of 9 AeC articles, one per five-year period, about 100 references).
3. **Deduplication.** Works are compared against the whole dataset assembled so far, not only against the current volume. Two different entries in the same bibliography are always treated as distinct works; multi-volume works cited together are linked to the individual volumes.
4. **People disambiguation.** Author and editor names are normalised and merged into the `people` table; full names are completed using an author list exported from the Zotero library where a single compatible full name exists, and handled case by case when variants or ambiguities occur.
5. **Review.** Ambiguous cases are reviewed by a human; clear cases are resolved automatically to keep the manual workload sustainable.
6. **Export.** Final CSV tables (`works`, `people`, `citations`) ready for import in Omeka S.

Known limitations:

- Fixed sections without a bibliography are left without citations for the time being; in-text citations may be recovered in a later pass from the full Markdown texts.
- Citations pointing only to a journal (without the individual contribution) are kept as they are.
- Forthcoming references ("c.s." / "in press") are verified online where possible.
- Records already present in BiDiAr are replaced by the new ones: no reconciliation is performed with the existing records.

<!-- TODO: add here the final statistics (works, people, citations) and the date of the last export. -->

## Zotero library

All records included in BiDiAr are collected, openly accessible, in the dedicated [BiDiAr Zotero group library](https://www.zotero.org/groups/5293298/bidiar/library). Each entry on the BiDiAr website links to the corresponding Zotero record, so the bibliography can be explored both on the website and in Zotero.

<!-- TODO: describe how the tables in this repository relate to the Zotero library (e.g. which records are exported to it, if any). -->

## Related repositories

- **Bibliographies (AeC reference lists):** <!-- TODO: add link to the repository -->
- **AeC corpus / Markdown texts:** <!-- TODO: add link, if public -->
- **Processing tools:** the `scripts/` and `.claude/skills/` folders of this repository.

## Coverage and status

| Item | Status |
|---|---|
| AeC journal volumes | <!-- TODO --> |
| AeC supplements | <!-- TODO --> |
| Last update | <!-- TODO --> |

## Licence

- **Data:** CC BY-NC-ND 4.0 — <https://creativecommons.org/licenses/by-nc-nd/4.0/> <!-- TODO: confirm for the repository -->
- **Code (if any):** <!-- TODO -->

## How to cite

<!-- TODO: add the recommended citation (authors, year, title, version, DOI/URL). -->

## Contacts and acknowledgements

Work carried out at **CNR-ISPC** (Institute of Heritage Science), within the **PNRR H2IOSC** project, as part of the Open Digital Archaeology Hub.

Further reading on BiDiAr:

- *DHeLO and BiDiAr: new digital resources within the H2IOSC Project* — <https://chloe.cnr.it/s/BiDiAr/item/11047>
- *An open system for textual, visual, and bibliographic resources: the Open Digital Archaeology Hub* — <https://chloe.cnr.it/s/BiDiAr/item/13608>
- *Merging Knowledge and Tools in Heritage Science and Digital Archaeology. Practices from H2IOSC WP2* — <https://chloe.cnr.it/s/BiDiAr/item/15014>

<!-- TODO: add contact person / email and the H2IOSC funding acknowledgement text. -->
