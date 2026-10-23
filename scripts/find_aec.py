#!/usr/bin/env python3
"""Find an AeC article in data/all_metadata.json, to fill `cited_aec_id` while parsing.

Usage
  python3 scripts/find_aec.py "D'Andrea" "Il GIS nella produzione delle carte"
  python3 scripts/find_aec.py "" "Presi nella rete"          # title only
  python3 scripts/find_aec.py "Colosi" "Studio integrato..." 11 171   # + volume, first page
  python3 scripts/find_aec.py "Pietroni" "Un ambiente..." "Suppl. 2" 77  # a Supplements volume

Prints the best matches (id, volume, year, pages, authors, title, score). Matching uses the
author's family name (if given) and title similarity; the volume and year of the citation
are NOT used to filter, because authors sometimes cite the wrong volume. When the cited
volume and first page are given, articles with that volume and first page are also listed
(marked "vol+page"), even with a different title: authors and editors sometimes cite a
provisional title (e.g. Colosi et al. 2001, AeC 11, 171). The journal and the Supplements
number their volumes separately: "Suppl. 2" (or "Supplemento 2") looks only among the
Supplements, a plain number only in the journal (fix of 19/10/2026).
Standard library only.
"""
from __future__ import annotations

import json
import sys

from merge_article import ROOT, aec_volume, norm, similarity


def main(argv: list[str]) -> None:
    if len(argv) not in (2, 4):
        sys.exit(__doc__)
    family, title = norm(argv[0]), argv[1]
    suppl, vol = aec_volume(argv[2]) if len(argv) == 4 else (False, "")
    page = str(argv[3]).split("-")[0].strip() if len(argv) == 4 else ""
    arts = json.loads((ROOT / "data" / "all_metadata.json").read_text(encoding="utf-8"))
    hits = []
    for a in arts:
        names = [norm(x.get("last_name", "")) for x in a.get("authors") or []]
        if family and not any(family == n or family in n.split() for n in names):
            continue
        s = similarity(title, a.get("title", ""))
        if s >= 0.6:
            hits.append((s, a))
        elif vol and str(a.get("volume_number")) == vol and str(a.get("firstPage")) == page \
                and ("/supplements/" in (a.get("url") or "")) == suppl:
            hits.append((s, a, "vol+page"))
    hits = [h if len(h) == 3 else (*h, "") for h in hits]
    hits.sort(key=lambda h: -h[0])
    if not hits:
        print("no match")
    for s, a, how in hits[:5]:
        authors = ", ".join(x.get("last_name", "") for x in a.get("authors") or [])
        series = "Suppl. " if "/supplements/" in (a.get("url") or "") else ""
        print(f"{a['id']}\tvol. {series}{a.get('volume_number')}\t{a.get('publication_year')}\t"
              f"{a.get('firstPage')}-{a.get('lastPage')}\t{authors}\t{a.get('title', '')[:90]}\t{s:.2f}{chr(9) + how if how else ''}")


if __name__ == "__main__":
    main(sys.argv[1:])
