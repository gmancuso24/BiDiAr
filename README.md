<p align="center">
  <a href="https://bidiar.cnr.it">
    <img src="https://chloe.cnr.it/files/asset/98b0ac7e780e80229e99af06b5dbf99502d1c2f8.jpg" alt="BiDiAr – Bibliography of Digital Archaeology" width="320">
  </a>
</p>

<h1 align="center">BiDiAr – Bibliography of Digital Archaeology</h1>

<p align="center">
  Structured bibliographic records and citation network of the
  <a href="https://bidiar.cnr.it">Bibliography of Digital Archaeology (BiDiAr)</a>.
</p>

---

## Table of contents

- [About](#about)
- [Sources](#sources)
- [Repository structure](#repository-structure)
- [Data tables](#data-tables)
- [Exports](#exports)
- [Citation graph](#citation-graph)
- [Data model](#data-model)
- [How the data are built](#how-the-data-are-built)
- [Context: BiDiAr and H2IOSC](#context-bidiar-and-h2iosc)
- [Licence](#licence)
- [How to cite](#how-to-cite)
- [Contacts and acknowledgements](#contacts-and-acknowledgements)

---

## About

This repository is the **open data deposit** of BiDiAr. It holds, in plain tabular form, the bibliographic records and the **citation network** built from the reference lists of scholarly publications in digital archaeology: every article of a source is linked to the works it cites, and every cited work becomes a structured, deduplicated record.

The dataset is made of three linked tables:

- **works** – bibliographic records (the source articles and the works they cite);
- **persons** – authors, editors and organisations, disambiguated and, where possible, with full names and ORCID;
- **citations** – which work cites which.

Every work is also provided as a formatted bibliographic citation, and the whole dataset is exported for **Zotero** (CSL-JSON). The same records are published online in BiDiAr.

The dataset grows **source by source**: new journals and series are added to the same tables, with the same identifiers and conventions, so that a work cited by several sources is a single record.

## Sources

### *Archeologia e Calcolatori* — the founding source

The citation network of BiDiAr starts from [***Archeologia e Calcolatori***](https://www.archcalc.cnr.it) (AeC), the peer-reviewed open access journal established in 1990 by Mauro Cristofani and Riccardo Francovich, directed by Paola Moscati from 1990 to 2022 and now edited by Alessandra Caravale, published by CNR – Institute of Heritage Science (ISPC) with All'Insegna del Giglio.

For more than thirty-five years AeC has been an international observatory on the theory and methods of computing applied to archaeology, and one of the first journals of the field worldwide. Its reference lists trace, volume after volume, how digital archaeology took shape: the works its authors read, discussed and built upon. Turning the whole of them into linked data makes that history explorable — who cited whom, which works became foundational, how topics and communities changed over time. It is a fitting first source for a bibliography of digital archaeology, and it was made possible by the journal's long-standing commitment to open access (OAI-PMH since 2005, CC BY-NC-ND 4.0).

### Coverage

| Source | Scope | Citing articles | Status |
|---|---|---:|---|
| [*Archeologia e Calcolatori*](https://www.archcalc.cnr.it/volumes/journal/)| vol. 1–37 (1990–2026) | 990 | ✅ Processed |
| [*Archeologia e Calcolatori* - Supplements](https://www.archcalc.cnr.it/volumes/supplements/)| Suppl. 1–15 | – | ⏳ Planned |
| [*Groma. Documenting Archaeology*](https://archaeopresspublishing.com/ojs/index.php/groma/) | – | – | ⏳ Planned |

Overall: 20,555 works (19,718 of them cited at least once), 21,560 persons and organisations (432 with ORCID), 25,123 citation links. Last update: 26 October 2026.

## Repository structure

```text
.
├── data/                         # ★ the dataset
│   ├── works.csv
│   ├── persons.csv
│   ├── citations.csv
│   └── citations_rendered.jsonl  # formatted citation of every work
├── exports/
│   └── zotero/
│       └── zotero_all.json       # CSL-JSON, importable in Zotero
└── docs/                         # web pages (GitHub Pages)
    └── citation_graph.html       # interactive citation network
```

## Data tables

All tables are UTF-8 CSV (with BOM), comma-separated. Multiple values within a cell are separated by `|` (no spaces). **Columns whose name starts with `_` are working columns** kept for traceability; they are not published in BiDiAr.

| File | Rows | Content |
|---|---:|---|
| [`data/works.csv`](data/works.csv) | 20,555 | One row per distinct work |
| [`data/persons.csv`](data/persons.csv) | 21,560 | One row per person or organisation |
| [`data/citations.csv`](data/citations.csv) | 25,123 | One row per citation link |
| [`data/citations_rendered.jsonl`](data/citations_rendered.jsonl) | 20,555 | Formatted citation of every work |

### `works.csv`

| Column | Description |
|---|---|
| `dcterms:identifier` | Primary key of the work (`W000001`…) |
| `dcterms:type` | Resource type (reduced controlled vocabulary) |
| `dcterms:title` | Title |
| `dcterms:creator` / `bibo:editor` | Person IDs (`P…`) separated by `\|` |
| `dcterms:date` | Year of publication |
| `dcterms:isPartOf` | Container (journal, volume, collection) as text |
| `bibo:volume`, `curation:number`, `bibo:issue`, `bibo:pages`, `bibo:numPages`, `bibo:numVolumes`, `bibo:edition` | Citation details |
| `dcat:inSeries` | Series |
| `dcterms:publisher`, `dcterms:spatial` | Publisher and place of publication |
| `dcterms:language` | Language (ISO 639-2) |
| `dcterms:rights` | Licence of the work (source articles) |
| `bibo:isbn`, `bibo:issn`, `bibo:doi`, `bibo:uri` | Identifiers and URL |
| `dcterms:abstract` | Abstract (source articles) |
| `curation:tag` | Provenance tag of the record |
| `_aec_id` | ID of the article in its source (currently AeC) |
| `_zotero_type` | Zotero item type used for the export |

### `persons.csv`

| Column | Description |
|---|---|
| `dcterms:identifier` | Primary key (`P000001`…) |
| `foaf:familyName` / `foaf:givenName` | Name parts |
| `o:resource_class` | `foaf:Person` or `foaf:Organization` |
| `orcid` | ORCID iD, where available |
| `name_note` | Set when the given name was attributed automatically (may contain errors) |
| `_variants`, `_notes` | Name forms found in the sources; working notes |

### `citations.csv`

| Column | Description |
|---|---|
| `citing` | ID of the citing work (a source article) |
| `cited` | ID of the cited work |
| `position` | Position of the reference in the citing article's bibliography |
| `raw` | Reference as printed in the article |
| `_citing_aec_id` | ID of the citing article in its source (currently AeC) |

### `citations_rendered.jsonl`

One JSON object per line, `{"id": "W…", "cit": "…"}`: the work as a bibliography entry in the BiDiAr citation style, generated with citeproc-js. It is the same text published in BiDiAr as `dcterms:bibliographicCitation`.

## Exports

### Zotero – `exports/zotero/zotero_all.json`

All works as a **CSL-JSON** array, importable in Zotero via *File → Import*. The `id` of each item is the work identifier (`W…`) of `works.csv`.

### Omeka S

The records are published in BiDiAr (Omeka S, CHLOE environment), imported in the order persons → works → citations (`bibo:cites` on the citing work). Programmatic access is through the Omeka S REST API of the site (`https://chloe.cnr.it/api/items`).

## Citation graph

[`docs/citation_graph.html`](https://gmancuso24.github.io/BiDiAr/citation_graph.html) is an interactive view of the whole citation network, built with [D3.js](https://d3js.org). Online: <https://gmancuso24.github.io/BiDiAr/citation_graph.html>

- **Nodes** are works, coloured by Zotero item type (`_zotero_type`) and sized by the number of citations received; citing articles have a white outline.
- **Edges** follow the *cites* direction only (citing → cited).
- **Search** by title (also author or year): choosing a result zooms to the work.
- **Click** on a work to see what it cites and what cites it; the legend hides or shows each type.

The page is a single self-contained file (data and D3 embedded), so it also works offline: download it and open it in a browser. The layout is precomputed with `d3-force`, so the graph opens immediately and keeps the same arrangement every time. The online version is published from the `docs/` folder through GitHub Pages.

## Data model

- **Stable identifiers.** Works (`W…`) and persons (`P…`) have internal identifiers used as keys between tables; they are never reused or renumbered when new sources are added.
- **One table for people.** Authors and editors are stored together; the role is given by the work column (`dcterms:creator` or `bibo:editor`).
- **Citations in one direction.** Only *cites* (`bibo:cites`) is recorded; *cited by* is derived by the platform.
- **Containers as text.** Journals, volumes and series cited are kept as text values, not as separate records.
- **Source articles.** Citing articles carry the metadata of their journal (abstract, licence, ISSN, URL or DOI).
- **Vocabularies.** Dublin Core Terms, BIBO and FOAF, following the BiDiAr Omeka S resource template.

## How the data are built

Each source is processed issue by issue, in chronological order, so that a work already cited exists before it is cited again:

1. **Extraction.** The reference lists of the articles are extracted from the PDFs into plain text, one reference per line.
2. **Parsing.** Each reference is parsed into structured metadata with an LLM-assisted workflow and checked against the article metadata of the source.
3. **Deduplication.** Every new work and person is matched against the **whole** dataset, not only the current source; uncertain matches are never merged automatically.
4. **Name completion.** Given names are completed from earlier bibliographic data, Crossref/OpenAlex records and targeted searches; ORCIDs are added where they can be matched reliably.
5. **Review.** Ambiguous cases are reviewed by a human; clear cases are resolved by documented rules.

Known limitations: given names attributed automatically are flagged in `name_note`; sections without a bibliography have no citations; citations pointing only to a journal (without the contribution) are kept as such.

## Context: BiDiAr and H2IOSC

[**BiDiAr**](https://bidiar.cnr.it) (*Bibliography of Digital Archaeology*) is an open-access bibliographic database that collects, organises and enriches references related to digital methods and tools in archaeology. It is built on Zotero and integrated into the DHeLO infrastructure; it indexes scientific literature with structured metadata, linking bibliographic entries to associated datasets, projects and software, and it traces the development of digital archaeology over time. It is published through [Omeka S](https://omeka.org/s/) in the [CHLOE – Cultural Heritage Linked Open data Environment](https://chloe.cnr.it/s/BiDiAr).

BiDiAr was developed within [**H2IOSC**](https://www.h2iosc.cnr.it) (*Humanities and Cultural Heritage Italian Open Science Cloud*), the PNRR project federating the four Italian nodes of the European research infrastructures CLARIN-IT, DARIAH-IT, E-RIHS.it and OPERAS-IT. E-RIHS.it is coordinated by [CNR-ISPC](https://www.ispc.cnr.it) (Institute of Heritage Science).

Useful entry points:

- Website: <https://bidiar.cnr.it> (Omeka S site: <https://chloe.cnr.it/s/BiDiAr>)
- Bibliographic search: <https://chloe.cnr.it/s/BiDiAr/BibliographicSearch>
- Zotero group library: <https://www.zotero.org/groups/5293298/bidiar/library>

## Licence

The dataset (tables, exports and the citation graph) is released under the
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/)
licence (CC BY-NC-SA 4.0); see [`LICENSE`](LICENSE).

You are free to share and adapt the data for non-commercial purposes, provided that you give
appropriate credit (see [How to cite](#how-to-cite)) and distribute your contributions under the same licence.

Content taken from the sources keeps its original licence. In particular, the abstracts and the
metadata of the *Archeologia e Calcolatori* articles (`dcterms:abstract`, `dcterms:rights`) are
reproduced unchanged from the journal, which publishes them under
[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/).

## How to cite

If you use these data, please cite the dataset through its Zenodo DOI:

> Mancuso G.,(2026). *BiDiAr – Bibliography of Digital Archaeology. Open Data* (version 1.0.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23676252

The DOI above always resolves to the latest release; each release also has its own DOI,
listed on the Zenodo page, to cite the exact version you used.

Please also acknowledge the sources of the citation data, in particular
*Archeologia e Calcolatori* (https://www.archcalc.cnr.it), and, for the platform, [paper on BiDiAr].

## Contacts and acknowledgements

Work carried out at **CNR-ISPC** (Institute of Heritage Science), within the **PNRR IR H2IOSC** project.
