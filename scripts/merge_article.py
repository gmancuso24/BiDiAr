#!/usr/bin/env python3
"""Merge the parsed bibliography of one AeC article into the working tables.

Input : output/parsed/{aec_id}.json, written by Claude (format in
        .claude/skills/parse-aec-bibliography/SKILL.md)
Output: output/works.csv, persons.csv, citations.csv, review.csv (rows appended;
        existing rows are never rewritten, only empty cells of reused works are filled)

Every run first copies the four tables to output/backup/{timestamp}/.

Matching (find_work) always considers the WHOLE works table: candidates are gathered
through indexes (shared person, shared title words, AeC works, cited_aec_id) that only
speed the search up; no work is ever excluded a priori. When a candidate is similar but a
safety rule forbids an automatic merge (different year, volume, numbers, authors...), the
new work goes to review.csv with the reasons. After the merge, audit_duplicates.py checks
the new works against the whole table as an independent safety net.

Usage
  python scripts/merge_article.py 5            # one article
  python scripts/merge_article.py 5 6 7        # several, in the given order
  python scripts/merge_article.py 5 --dry-run  # show what would happen, write nothing

Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
PARSED = OUT / "parsed"

WORK_COLUMNS = [
    "dcterms:identifier", "dcterms:type", "dcterms:title", "dcterms:creator", "bibo:editor",
    "dcterms:date", "dcterms:isPartOf", "bibo:volume", "curation:number", "dcat:inSeries",
    "bibo:numVolumes", "bibo:issue", "bibo:pages", "bibo:numPages", "bibo:edition", "dcterms:language",
    "dcterms:publisher", "dcterms:spatial", "dcterms:rights", "bibo:isbn", "bibo:issn",
    "bibo:doi", "bibo:uri", "dcterms:abstract", "curation:tag", "_aec_id",
]
PERSON_COLUMNS = ["dcterms:identifier", "foaf:familyName", "foaf:givenName", "o:resource_class",
                  "orcid", "_variants", "_notes", "name_note"]
# o:resource_class: foaf:Person or foaf:Organization (added 22/10/2026). For an Organization the
# whole name is kept in foaf:familyName and foaf:givenName stays empty.
CITATION_COLUMNS = ["citing", "cited", "position", "raw", "_citing_aec_id"]
REVIEW_COLUMNS = ["review_id", "citing_aec_id", "position", "issue", "details", "raw", "done"]
ARCHIVE_COLUMNS = REVIEW_COLUMNS + ["closed_at"]
TYPES = {"article", "book", "chapter", "proceedings", "thesis", "other",
         "conference communication", "unpublished work"}   # last two added 22/10/2026 (old c.s.)

# JSON field -> works.csv column (single values)
FIELD_MAP = {
    "type": "dcterms:type", "title": "dcterms:title", "date": "dcterms:date",
    "volume": "bibo:volume", "issue": "bibo:issue", "pages": "bibo:pages", "edition": "bibo:edition",
    "series": "dcat:inSeries", "series_number": "curation:number",
    "publisher": "dcterms:publisher", "place": "dcterms:spatial",
    "language": "dcterms:language", "doi": "bibo:doi", "uri": "bibo:uri",
}
SAME_WORK = 0.90      # title similarity to reuse an existing work
MAYBE_WORK = 0.75     # between MAYBE and SAME: new work + review row
SAME_LINE = 0.95      # two lines of one bibliography this similar are the same entry repeated


# ---------------------------------------------------------------- helpers

def norm(s: str) -> str:
    # Typographic apostrophes/quotes first: dropped by the ASCII step they would glue words
    # together ("D’Andrea" -> "dandrea" instead of "d andrea", "dell’impatto" -> "dellimpatto")
    s = re.sub(r"[\u2018\u2019\u201a\u201b\u02bc\u00b4`\u201c\u201d\u00ab\u00bb]", " ", str(s or ""))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def similarity(a: str, b: str) -> float:
    a_raw, b_raw = a, b
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    # A cited short title is often the main title of a longer one ("X" vs "X. Subtitle")
    short, long_ = sorted((a, b), key=len)
    prefix = 0.95 if len(short) >= 12 and long_.startswith(short + " ") and subtitle_follows(a_raw, b_raw) else 0.0
    return max(ratio, prefix)


def subtitle_follows(a: str, b: str) -> bool:
    """True when the longer title goes on after the shorter one with a separator
    ("X. Subtitle", "X: subtitle", "X (Arezzo 2000)", "X 1"), not with plain words:
    "Virtual Archaeology and museums" is another work than "Virtual Archaeology"
    (fix of 19/10/2026, vol. 16: a chapter had been merged into the volume).
    """
    short, long_ = sorted((str(a or ""), str(b or "")), key=lambda s: len(norm(s)))
    n = len(norm(short).split())
    words = list(re.finditer(r"[^\W_]+", long_))
    if len(words) <= n:
        return True
    gap = long_[words[n - 1].end():words[n].start()]
    return bool(re.search(r"[.:;(\[\u2013\u2014,-]", gap)) or words[n].group().isdigit()


def norm_uri(u: str) -> str:
    """Scheme, "www.", fragment and trailing slash do not make two URLs different."""
    u = re.sub(r"^https?://(www\.)?", "", str(u or "").strip().lower())
    return u.split("#")[0].rstrip("/")


def norm_doi(d: str) -> str:
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", str(d or "").strip().lower())


def identifier_conflicts(doi_a: str, uri_a: str, doi_b: str, uri_b: str, check_uri: bool = True) -> list[str]:
    """Two different DOIs / URLs on works that both have one: different works (a web page
    "Peer-to-Peer" in Webopedia is not the one in Wikipedia). `check_uri` is off when one
    side is an AeC article, whose URI comes from the journal metadata, not from a citation."""
    out = []
    a, b = norm_doi(doi_a), norm_doi(doi_b)
    if a and b and a != b:
        out.append("different DOI")
    a, b = norm_uri(uri_a), norm_uri(uri_b)
    if check_uri and a and b and a != b:
        out.append("different URI")
    return out


def numbers(s: str) -> set[str]:
    """Arabic numerals and upper-case Roman numerals of a title ("II", "VIII", "Destro I").

    The first word is skipped (Italian article "I"), and lone "C"/"L" are ignored
    ("a.C.", "l'archeologia").
    """
    s = str(s or "")
    found = set(re.findall(r"\d+", s))
    words = re.findall(r"[A-Za-z]+", s)
    for w in words[1:]:
        if re.fullmatch(r"[IVXLC]+", w) and w not in ("C", "L"):
            found.add(w)
    return found


def main_title(s: str) -> str:
    return re.split(r"[.:;]\s", str(s or ""), maxsplit=1)[0]


def comma_head(s: str) -> str:
    """Text before the first comma followed by a capital letter, when the comma is outside
    parentheses; "" if there is none."""
    s = str(s or "")
    depth = 0
    for i, ch in enumerate(s):
        depth += (ch in "([") - (ch in ")]")
        if ch == "," and depth == 0 and s[i + 1:i + 3].strip()[:1].isupper():
            return s[:i]
    return ""


def main_title_match(a: str, b: str) -> str:
    """Compare the main titles (before ". ", ": ", "; ") of two titles.

    "same"  : same main title (10+ characters) and either one title is the bare main title
              (a short citation of a longer title) or the main title has 3+ words, so it
              identifies the work on its own ("The easier, the better: …")
    "short" : same main title of 1-2 words, both titles going on with different subtitles:
              not enough to merge, a review row instead (fix of 19/10/2026, vol. 24: Bahn
              2000 "Archaeology: A Very Short Introduction" had been merged into Renfrew &
              Bahn 2000 "Archaeology: Theories, Methods and Practice")
    ""      : different main titles
    """
    ma, mb = norm(main_title(a)), norm(main_title(b))
    if len(ma) < 10 or ma != mb:
        # A title that is the bare head of the other one before a comma + capital letter
        # ("Quale futuro per l'Archeologia?" / "Quale futuro per l'Archeologia?, Atti del
        # Workshop ..."; fix of 20/10/2026, vol. 30). Only the bare-title case: a comma
        # inside a title ("Relazioni tra geomorfologia, processi ...") is not a separator.
        for x, y in ((a, b), (b, a)):
            head = comma_head(y)
            if head and len(norm(x)) >= 10 and len(norm(x).split()) >= 3 and norm(x) == norm(head):
                return "same"
        return ""
    if norm(a) == ma or norm(b) == mb or len(ma.split()) >= 3:
        return "same"
    return "short"


# Frequent words (it, en, fr, de, es) ignored when looking for title words in common
STOPWORDS = set("""
alla alle allo agli dalla dalle dallo dagli della delle dello degli nella nelle nello negli
sulla sulle sullo sugli come anche dopo tra fra loro questo questa
with from their this that into about between under over upon
dans pour avec sous leur leurs entre vers
eine einer eines einem einen eines oder sind nach
para como entre sobre desde
""".split())


def title_tokens(s: str) -> set[str]:
    """Significant normalised words of a title (4+ letters, not stopwords)."""
    return {t for t in norm(s).split() if len(t) >= 4 and t not in STOPWORDS}


def work_persons(w: dict) -> tuple[set[str], set[str]]:
    """(creators, editors) person ids of a work."""
    return ({p for p in w["dcterms:creator"].split("|") if p},
            {p for p in w["bibo:editor"].split("|") if p})


def first_volume(v) -> str:
    return norm(str(v or "").split(".")[0])


def aec_volume(vol, is_part_of="") -> tuple[bool, str]:
    """(supplement?, number) of a cited AeC volume: "Suppl. 2", "Supplemento 2" or a
    container "Archeologia e Calcolatori. Supplementi" -> (True, "2"); "28.2" -> (False, "28").
    The journal and the Supplements have their own volume numbers, so a volume + page
    lookup must compare both (fix of 19/10/2026, vol. 24: "Suppl. 2" found nothing)."""
    v = str(vol or "").strip()
    m = re.match(r"(?i)supp?l\w*\.?\s*(\d+)", v)
    if m:
        return True, m.group(1)
    return "supplement" in norm(is_part_of), first_volume(v)


def is_full(given: str) -> bool:
    """True when the given name is spelled out ('Paola'), False for initials ('P.')."""
    return bool(given) and all(len(p) > 1 for p in re.split(r"[\s.\-]+", given) if p) and "." not in given


def initials(given: str) -> str:
    return "".join(p[0] for p in re.split(r"[\s.\-]+", norm(given)) if p)


def compatible(given_a: str, given_b: str) -> bool:
    """'P.' ~ 'Paola', 'M.L.' ~ 'Maria Letizia', '' ~ anything."""
    ia, ib = initials(given_a), initials(given_b)
    return not ia or not ib or ia.startswith(ib) or ib.startswith(ia)


SAME_SURNAME = 0.85   # surname similarity for spelling variants (Hugget/Huggett, Grieg/Greig)


def surname_key(family: str) -> str:
    return norm(family).replace(" ", "")


def same_name(a: dict, b: dict) -> bool:
    """Two person rows that can be the same person by name alone.

    Same surname (or a close spelling variant, 5+ letters) and compatible given names
    ('P.' ~ 'Paola', '' ~ anything; two spelled-out names must agree). Used only to compare
    the authors of two works whose titles already match: placeholders and variant spellings
    are separate person ids, so comparing ids alone hides real duplicates (vol. 15:
    Barceló placeholders, 'Hugget J.', 'Hodder J.', 'Grieg-Smith').
    """
    fa, fb = surname_key(a["foaf:familyName"]), surname_key(b["foaf:familyName"])
    if not fa or not fb:
        return False
    if fa != fb and not (min(len(fa), len(fb)) >= 5
                         and SequenceMatcher(None, fa, fb).ratio() >= SAME_SURNAME):
        return False
    ga, gb = a["foaf:givenName"], b["foaf:givenName"]
    if is_full(ga) and is_full(gb):
        na, nb = norm(ga), norm(gb)
        return na.startswith(nb) or nb.startswith(na)
    return compatible(ga, gb)


def shared_persons(ids_a: set[str], ids_b: set[str], by_id: dict[str, dict] | None) -> str:
    """'id' when the two sets share a person id, 'name' when they only share a person by
    name (see same_name), '' otherwise."""
    if ids_a & ids_b:
        return "id"
    if by_id:
        pa = [by_id[i] for i in ids_a if i in by_id]
        pb = [by_id[i] for i in ids_b if i in by_id]
        if any(same_name(x, y) for x in pa for y in pb):
            return "name"
    return ""


def read(name: str, columns: list[str]) -> list[dict]:
    path = OUT / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:                      # columns added after the file was written
        for c in columns:
            r.setdefault(c, "")
    return rows


def write(name: str, columns: list[str], rows: list[dict]) -> None:
    with open(OUT / name, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def next_id(rows: list[dict], prefix: str) -> str:
    n = max((int(r["dcterms:identifier"][1:]) for r in rows), default=0)
    return f"{prefix}{n + 1:06d}"


# ---------------------------------------------------------------- merge

class Tables:
    def __init__(self):
        self.works = read("works.csv", WORK_COLUMNS)
        self.persons = read("persons.csv", PERSON_COLUMNS)
        self.citations = read("citations.csv", CITATION_COLUMNS)
        self.review = read("review.csv", REVIEW_COLUMNS)
        # Review ids are progressive over open and archived rows and never reused
        archived = read("review_archive.csv", ARCHIVE_COLUMNS)
        self.last_review_id = max((int(r["review_id"]) for r in self.review + archived
                                   if r.get("review_id", "").isdigit()), default=0)
        self.person_by_family: dict[str, list[dict]] = {}
        self.person_by_id: dict[str, dict] = {p["dcterms:identifier"]: p for p in self.persons}
        for p in self.persons:
            self.person_by_family.setdefault(norm(p["foaf:familyName"]), []).append(p)
        # Indexes used only to gather candidates quickly: matching itself considers any
        # work reachable through any of them, never a single "section" of the table
        self.works_by_person: dict[str, list[dict]] = {}
        self.works_by_token: dict[str, list[dict]] = {}
        self.work_by_aec_id: dict[str, dict] = {}
        self.aec_works: list[dict] = []
        for w in self.works:
            self._index_work(w)
        from suggest_names import load_full      # local module (data/persone_zotero.csv)
        self.zotero = load_full()
        # Placeholders created for ambiguous persons in the article being merged, keyed by
        # (aec_id, family, given): the same cited form in the same article is one person
        self.placeholders: dict[tuple[str, str, str], str] = {}

    def _index_work(self, w: dict) -> None:
        creators, editors = work_persons(w)
        for p in (creators | editors) or {"-"}:
            self.works_by_person.setdefault(p, []).append(w)
        for tok in title_tokens(w["dcterms:title"]):
            self.works_by_token.setdefault(tok, []).append(w)
        if w["_aec_id"]:
            self.work_by_aec_id[w["_aec_id"]] = w
        if w["_aec_id"] or "archeologia e calcolatori" in norm(w["dcterms:isPartOf"]):
            self.aec_works.append(w)

    def save(self) -> None:
        write("works.csv", WORK_COLUMNS, self.works)
        write("persons.csv", PERSON_COLUMNS, self.persons)
        write("citations.csv", CITATION_COLUMNS, self.citations)
        write("review.csv", REVIEW_COLUMNS, self.review)

    # -- persons
    def person(self, name: dict, ctx: dict) -> str:
        family, given = name.get("family", "").strip(), name.get("given", "").strip()
        key = (str(ctx["aec_id"]), norm(family), norm(given))
        if key in self.placeholders:          # same cited form already met in this article
            return self.placeholders[key]
        # Placeholders of earlier ambiguous cases are not real candidates: counting them
        # would make every later citation of the same form ambiguous again (one new
        # person per occurrence, as happened in vol. 14)
        same = [p for p in self.person_by_family.get(norm(family), [])
                if not p["_notes"].startswith("ambiguous:")]
        # A missing given name is never matched automatically against a named person (and
        # vice versa): "LEFEBVRE 1974" must not silently become Bastien Lefebvre. Such
        # cases get a new person and a review row listing the possible matches.
        named = [p for p in same if p["foaf:givenName"].strip()]
        blank = [p for p in same if not p["foaf:givenName"].strip()]
        if given:
            cands = [p for p in named if compatible(given, p["foaf:givenName"])]
            loose = blank
        else:
            cands, loose = blank, named
        # Initials matching the only person in the table: if the Zotero list knows several
        # compatible first names ("Tosi M." = Maria Letizia or Maurizio), the match is not
        # safe: new person + review instead of a silent attribution
        # Only when the person in the table is not clearly the usual one: its first name must
        # account for at least 80% of the compatible occurrences in the list (Forte M. =
        # Maurizio in almost every case; Tosi M. = Maurizio 18 times, Maria Letizia 2)
        # A person marked "initials-ok" in _notes was checked by Giacomo: no Zotero check
        # Skipped when the person in the table itself has initials only: its "first name"
        # is not in the list by construction, and the same cited form met again (same
        # volume or another) is the same person, not a new ambiguity (vol. 21: Ratte,
        # Fonseca, Lenoble, Fidanoski, Kockelmann, Pinilla)
        if len(cands) == 1 and given and not is_full(given) \
                and is_full(cands[0]["foaf:givenName"]) \
                and "initials-ok" not in cands[0]["_notes"]:
            occ: dict[str, int] = {}
            for c in self.zotero.get(norm(family), {}).values():
                if compatible(given, c["given"]):
                    parts = norm(c["given"]).split()
                    if not parts:  # Zotero record without a usable given name
                        continue
                    occ[parts[0]] = occ.get(parts[0], 0) + c["n"]
            mine = (norm(cands[0]["foaf:givenName"]).split() or [""])[0]
            from suggest_names import fold_typos, typo_pair     # local module
            occ = fold_typos(occ)
            mine = next((k for k in occ if k == mine or typo_pair(k, mine)), mine)
            total = sum(occ.values())
            if len(occ) > 1 and total and occ.get(mine, 0) / total < 0.8:
                ctx = {**ctx, "zotero_alt": " / ".join(f"{k} ({v})" for k, v in sorted(occ.items()))}
                cands, loose = [], cands
        if len(cands) == 1:
            p = cands[0]
            old = p["foaf:givenName"]
            # Keep the fuller form: spelled-out names beat initials, more names beat fewer
            better = (is_full(given) and not is_full(old)) or \
                     (is_full(given) == is_full(old) and len(initials(given)) > len(initials(old)))
            if norm(given) != norm(old):
                variant = f"{family}, {old if better else given}"
                if better:
                    p["foaf:givenName"] = given
                known = p["_variants"].split("|") if p["_variants"] else []
                if variant not in known:
                    p["_variants"] = "|".join(known + [variant])
            return p["dcterms:identifier"]
        pid = next_id(self.persons, "P")
        p = {"dcterms:identifier": pid, "foaf:familyName": family, "foaf:givenName": given,
             "o:resource_class": "foaf:Person", "orcid": "", "_variants": "", "_notes": ""}
        # Initials only: take the full name when the Zotero list has exactly one compatible
        # (decision 18/10/2026); the cited form stays among the variants
        # Only for a person with no possible match at all: when the person is ambiguous the
        # cited form is kept (the Zotero name goes in the review row), otherwise the new
        # person would look identical to an existing one and hide the ambiguity
        from suggest_names import zotero_unique
        fuller = zotero_unique(self.zotero, family, given)
        if fuller and (cands or loose):
            ctx = {**ctx, "zotero": fuller}
            fuller = ""
        if fuller:
            p["foaf:givenName"] = fuller
            p["_variants"] = f"{family}, {given}"
            p["_notes"] = "given name from Zotero list (unique match)"
        if len(cands) > 1 or (not cands and loose):
            pool = cands if len(cands) > 1 else loose
            ids = "|".join(c["dcterms:identifier"] for c in pool)
            why = "" if len(cands) > 1 else " (given name missing on one side: not compared)"
            p["_notes"] = f"ambiguous: could be {ids}"
            hint = f"; Zotero suggests '{ctx['zotero']}'" if ctx.get("zotero") else ""
            if ctx.get("zotero_alt"):
                why = f" (initials compatible with several names in the Zotero list: {ctx['zotero_alt']})"
            self.add_review(ctx, "person_ambiguous", f"{family}, {given} -> new {pid}; candidates {ids}{why}{hint}")
            self.placeholders[key] = pid
        self.persons.append(p)
        self.person_by_id[pid] = p
        self.person_by_family.setdefault(norm(family), []).append(p)
        return pid

    # -- works
    def candidates(self, ref: dict, creators: list[str], editors: list[str]) -> list[dict]:
        """Works worth comparing with ref, gathered from the whole table.

        Union of: works sharing any person (creator or editor, any position), works sharing
        significant title words (two, or one for one-word titles), and every AeC work when
        the citation is an AeC article. Nothing else filters the table.
        """
        found: dict[int, dict] = {}
        for p in (creators + editors) or ["-"]:
            for w in self.works_by_person.get(p, []):
                found[id(w)] = w
        toks = title_tokens(ref.get("title", ""))
        if toks:
            need = min(len(toks), 2)
            hits: Counter = Counter()
            pool: dict[int, dict] = {}
            for tok in toks:
                for w in self.works_by_token.get(tok, []):
                    hits[id(w)] += 1
                    pool[id(w)] = w
            for k, n in hits.items():
                if n >= need:
                    found[k] = pool[k]
        if "archeologia e calcolatori" in norm(" ".join(ref.get("is_part_of") or [])):
            for w in self.aec_works:
                found[id(w)] = w
        return list(found.values())

    def score(self, ref: dict, w: dict, creators: list[str], editors: list[str]) -> tuple[float, list[str]]:
        """Title similarity, capped below SAME_WORK when a safety rule applies.

        Returns (score, reasons): the reasons say why an automatic merge was refused, so
        that review.csv shows them.
        """
        title, date = ref.get("title", ""), str(ref.get("date") or "")
        s = similarity(title, w["dcterms:title"])
        short_main = False
        mt = main_title_match(title, w["dcterms:title"])
        if mt == "same":
            s = max(s, 0.95)
        elif mt == "short" and s < MAYBE_WORK + 0.05:
            s, short_main = MAYBE_WORK + 0.05, True
        if s < MAYBE_WORK:
            return s, []
        reasons = []
        if short_main:
            reasons.append("same short main title, different subtitles")
        # Different numbers in the titles ("... I" / "... II", "Report 3" / "Report 4")
        if numbers(title) != numbers(w["dcterms:title"]):
            reasons.append("different numbers in title")
        # "c.s." against a dated work: different papers that merely share the main title
        if (date == "c.s.") != (w["dcterms:date"] == "c.s."):
            reasons.append("c.s. vs dated")
        # Two different publication years (other edition, other paper)
        if re.fullmatch(r"\d{4}", date) and re.fullmatch(r"\d{4}", w["dcterms:date"]) \
                and date != w["dcterms:date"]:
            reasons.append(f"different year {date}/{w['dcterms:date']}")
        # Different volume (vol. II / vol. III of a work, or an AeC volume cited wrongly)
        va, vb = first_volume(ref.get("volume")), first_volume(w["bibo:volume"])
        if va and vb and va != vb:
            reasons.append(f"different volume {va}/{vb}")
        # Different DOI or URI: different works (web pages, reports with the same title)
        reasons += identifier_conflicts(ref.get("doi", ""), ref.get("uri", ""), w["bibo:doi"],
                                        w["bibo:uri"], not w.get("_aec_id"))
        # A chapter against an edited volume with the same opening words: the chapter of a
        # volume is never the volume itself (fix of 19/10/2026)
        types = {ref.get("type", ""), w["dcterms:type"]}
        if "chapter" in types and types & {"book", "proceedings"} and len(types) == 2:
            reasons.append(f"type {ref.get('type', '')}/{w['dcterms:type']}")
        # Authors: shared creator if both have creators, otherwise any shared person.
        # A person is shared by id or by name (same surname + compatible given names):
        # placeholders and spelling variants have their own ids
        wc, we = work_persons(w)
        rc, re_ = set(creators), set(editors)
        if rc and wc:
            if not shared_persons(rc, wc, self.person_by_id):
                reasons.append("no shared author")
        elif (rc | re_) and (wc | we):
            if not shared_persons(rc | re_, wc | we, self.person_by_id):
                reasons.append("no shared author/editor")
        elif (rc | re_) or (wc | we):
            # One side anonymous (thesauri, standards, corporate works cited with or without
            # the body): not a conflict for a long title, still one for short generic ones
            if len(norm(title)) < 20:
                reasons.append("no shared author/editor")
        # Different authors are worth a review only with a (nearly) identical title in the
        # same year, or an identical long title: otherwise "Introduzione" (2015) by X would
        # be flagged against every "Introduzione" by anybody else
        if any(r.startswith("no shared") for r in reasons):
            exact_long = len(norm(title)) >= 20 and norm(title) == norm(w["dcterms:title"])
            year_conflict = any(r.startswith("different year") for r in reasons)
            if not exact_long and (year_conflict or s < SAME_WORK):
                return 0.0, []
        if reasons:
            s = min(s, SAME_WORK - 0.01)
        return s, reasons

    def find_work(self, ref: dict, creators: list[str], editors: list[str],
                  exclude: set[str] = frozenset()) -> tuple[dict | None, dict | None, list[str]]:
        """Return (same_work, possible_work, reasons) looking at the whole works table.

        `exclude`: works that cannot be this reference (the citing article itself, works
        already taken by another entry of the same bibliography)."""
        best, score, why = None, 0.0, []
        for w in self.candidates(ref, creators, editors):
            if w["dcterms:identifier"] in exclude:
                continue
            s, reasons = self.score(ref, w, creators, editors)
            if s > score:
                best, score, why = w, s, reasons
        if best and score >= SAME_WORK:
            return best, None, []
        if best and score >= MAYBE_WORK:
            return None, best, why
        return None, None, []

    def add_work(self, ref: dict, creators: list[str], editors: list[str], tags: list[str]) -> dict:
        w = {c: "" for c in WORK_COLUMNS}
        w["dcterms:identifier"] = next_id(self.works, "W")
        for field, col in FIELD_MAP.items():
            w[col] = str(ref.get(field) or "").strip()
        w["dcterms:creator"] = "|".join(creators)
        w["bibo:editor"] = "|".join(editors)
        w["dcterms:isPartOf"] = "|".join(x.strip() for x in ref.get("is_part_of") or [] if x.strip())
        w["curation:tag"] = "|".join(tags)
        self.works.append(w)
        self._index_work(w)
        return w

    def fill_blanks(self, w: dict, ref: dict, editors: list[str]) -> None:
        for field, col in FIELD_MAP.items():
            if not w[col] and ref.get(field):
                w[col] = str(ref[field]).strip()
        if not w["bibo:editor"] and editors:
            w["bibo:editor"] = "|".join(editors)
        if not w["dcterms:isPartOf"] and ref.get("is_part_of"):
            w["dcterms:isPartOf"] = "|".join(ref["is_part_of"])

    def aec_by_volume_page(self, ref: dict) -> dict | None:
        """AeC article (from metadata) with the cited volume and first page, if exactly one."""
        suppl, vol = aec_volume(ref.get("volume"), " ".join(ref.get("is_part_of") or []))
        page = str(ref.get("pages") or "").split("-")[0].strip()
        if not vol or not page:
            return None
        # A whole issue/section cited as a monograph (book/proceedings, or a page range
        # clearly wider than the article) is never one of the issue's articles
        # (fix of 21/10/2026, vol. 37: Baldoni 2021, H2IOSC I-III).
        if ref.get("type") in ("book", "proceedings"):
            return None
        def last(pg: str) -> int | None:
            m = re.findall(r"\d+", pg.split("-")[-1]) if "-" in pg else []
            return int(m[0]) if m else None
        cited_last = last(str(ref.get("pages") or ""))
        hits = [w for w in self.aec_works if w["_aec_id"]
                and aec_volume(w["bibo:volume"], w["dcterms:isPartOf"]) == (suppl, vol)
                and w["bibo:pages"].split("-")[0].strip() == page
                and not (cited_last and last(w["bibo:pages"]) and cited_last > last(w["bibo:pages"]) + 3)]
        return hits[0] if len(hits) == 1 else None

    def drop_unused_persons(self, before: set[str], aec_id: str) -> list[str]:
        """Remove persons created while merging this article that no work uses.

        Happens when a person is created for a citation and the work then turns out to
        exist already with its own persons. Their person_ambiguous rows go too (they were
        never saved, so no id is lost)."""
        used = set()
        for w in self.works:
            for col in ("dcterms:creator", "bibo:editor"):
                used.update(x for x in w[col].split("|") if x)
        drop = [p["dcterms:identifier"] for p in self.persons
                if p["dcterms:identifier"] not in before and p["dcterms:identifier"] not in used]
        if not drop:
            return []
        gone = set(drop)
        self.persons = [p for p in self.persons if p["dcterms:identifier"] not in gone]
        for fam, lst in self.person_by_family.items():
            self.person_by_family[fam] = [p for p in lst if p["dcterms:identifier"] not in gone]
        self.review = [r for r in self.review if not (
            str(r["citing_aec_id"]) == str(aec_id) and r["issue"] == "person_ambiguous"
            and any(f"-> new {pid};" in r["details"] for pid in gone))]
        self.placeholders = {k: v for k, v in self.placeholders.items() if v not in gone}
        return drop

    def add_review(self, ctx: dict, issue: str, details: str) -> None:
        self.last_review_id += 1
        self.review.append({"review_id": self.last_review_id, "citing_aec_id": ctx["aec_id"], "position": ctx["position"],
                            "issue": issue, "details": details, "raw": ctx["raw"], "done": ""})


def merge(aec_id: str, t: Tables) -> dict:
    data = json.loads((PARSED / f"{aec_id}.json").read_text(encoding="utf-8"))
    citing = next((w for w in t.works if w["_aec_id"] == str(aec_id)), None)
    if not citing:
        sys.exit(f"article {aec_id} is not in works.csv (_aec_id)")
    if any(c["_citing_aec_id"] == str(aec_id) for c in t.citations):
        sys.exit(f"article {aec_id} is already merged: restore a backup to merge it again")
    # Placeholder or empty names left by parsing ("family"/"given" copied from the schema,
    # fix of 19/10/2026, vol. 16 art. 414): refuse the whole article before any change
    bad = [(r["position"], n) for r in data["references"]
           for n in (r.get("creators") or []) + (r.get("editors") or [])
           if not str(n.get("family", "")).strip()
           or str(n.get("family", "")).strip().lower() in ("family", "surname", "name")
           # "Given" is a real surname (M. Given): a placeholder only if the given name is one too
           or (str(n.get("family", "")).strip().lower() == "given"
               and str(n.get("given", "")).strip().lower() in ("", "given", "family"))
           or str(n.get("given", "")).strip().lower() in ("given", "family")]
    if bad:
        sys.exit(f"invalid person names in output/parsed/{aec_id}.json: {bad[:5]}")
    stats = {"refs": 0, "new_works": 0, "reused_works": 0, "review": 0, "kept_apart": []}
    # Same-bibliography rule (19/10/2026, general check at vol. 23): two different entries
    # of one bibliography are two different works for the author who listed them, so a
    # work already taken by another entry is never reused, unless the two lines are the
    # same entry repeated (double bibliographies, OCR variants: similarity >= SAME_LINE).
    # No review row: the decision is automatic and only printed. The citing article is
    # never a candidate for its own references.
    used: dict[str, list[str]] = {}

    def taken(w: dict | None, raw: str) -> bool:
        if not w:
            return False
        wid = w["dcterms:identifier"]
        if wid == citing["dcterms:identifier"]:
            return True
        lines = used.get(wid)
        return bool(lines) and all(similarity(raw, x) < SAME_LINE for x in lines)

    persons_before = {p["dcterms:identifier"] for p in t.persons}
    new_ids: list[str] = []
    review_before = len(t.review)
    for ref in data["references"]:
        ctx = {"aec_id": aec_id, "position": ref["position"], "raw": ref["raw"]}
        stats["refs"] += 1
        if ref.get("type") not in TYPES:
            t.add_review(ctx, "bad_type", f"type '{ref.get('type')}' replaced with 'other'")
            ref["type"] = "other"
        creators = [t.person(n, ctx) for n in ref.get("creators") or []]
        editors = [t.person(n, ctx) for n in ref.get("editors") or []]
        tags = [f"src:aec-{aec_id}"]
        cs = (ref.get("cs") or {}).get("status")
        if cs:
            tags.append(f"cs-{cs}")
        if ref.get("confidence") == "low":
            tags.append("da-verificare")
            t.add_review(ctx, "low_confidence", ref.get("notes", ""))
        if cs == "unresolved":
            t.add_review(ctx, "cs_unresolved", ref.get("notes", ""))
        same, maybe, why = None, None, []
        cited_aec = str(ref.get("cited_aec_id") or "").strip()
        if cited_aec:                       # AeC article identified while parsing
            same = t.work_by_aec_id.get(cited_aec)
            if not same:
                t.add_review(ctx, "low_confidence", f"cited_aec_id {cited_aec} not found in works.csv")
        if not same and "archeologia e calcolatori" in norm(" ".join(ref.get("is_part_of") or [])):
            same = t.aec_by_volume_page(ref)
            if same:
                t.add_review(ctx, "low_confidence",
                             f"AeC article matched by volume + first page: {same['dcterms:identifier']} "
                             f"(aec {same['_aec_id']}) '{same['dcterms:title'][:80]}'; cited title differs")
        if same and taken(same, ref["raw"]):
            same = None
        if not same:
            exclude = {wid for wid in used if taken({"dcterms:identifier": wid}, ref["raw"])}
            exclude.add(citing["dcterms:identifier"])
            first, _, _ = t.find_work(ref, creators, editors)
            same, maybe, why = t.find_work(ref, creators, editors, exclude)
            if first and first["dcterms:identifier"] in exclude:
                stats["kept_apart"].append((ref["position"], first["dcterms:identifier"]))
        if same:
            t.fill_blanks(same, ref, editors)
            work = same
            stats["reused_works"] += 1
        else:
            work = t.add_work(ref, creators, editors, tags)
            new_ids.append(work["dcterms:identifier"])
            stats["new_works"] += 1
            if maybe:
                t.add_review(ctx, "possible_duplicate",
                             f"new {work['dcterms:identifier']} looks like {maybe['dcterms:identifier']}: "
                             f"{maybe['dcterms:title'][:80]}"
                             + (f" [not merged: {'; '.join(why)}]" if why else ""))
        used.setdefault(work["dcterms:identifier"], []).append(ref["raw"])
        t.citations.append({"citing": citing["dcterms:identifier"], "cited": work["dcterms:identifier"],
                            "position": ref["position"], "raw": ref["raw"], "_citing_aec_id": aec_id})
    stats["dropped_persons"] = t.drop_unused_persons(persons_before, aec_id)
    stats["new_ids"] = new_ids
    stats["review"] = len(t.review) - review_before
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aec_ids", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    t = Tables()
    first_new = t.last_review_id
    if not args.dry_run:
        backup = OUT / "backup" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup.mkdir(parents=True)
        for name in ("works.csv", "persons.csv", "citations.csv", "review.csv"):
            if (OUT / name).exists():
                shutil.copy2(OUT / name, backup / name)
    from audit_duplicates import audit_new_works     # local module, same folder
    for aec_id in args.aec_ids:
        s = merge(aec_id, t)
        n_audit = audit_new_works(t, s["new_ids"], aec_id)
        print(f"{aec_id}: {s['refs']} references, {s['new_works']} new works, "
              f"{s['reused_works']} reused, {s['review']} rows to review"
              + (f" (+{n_audit} from the duplicate audit)" if n_audit else "")
              + (f"; {len(s['dropped_persons'])} unused new persons removed" if s["dropped_persons"] else "")
              + (f"; kept apart (same bibliography): "
                 + ", ".join(f"#{pos} not {wid}" for pos, wid in s["kept_apart"]) if s["kept_apart"] else ""))
    new_ids = [r["review_id"] for r in t.review if int(r["review_id"]) > first_new]
    if new_ids:
        print(f"new review ids: {new_ids[0]}-{new_ids[-1]}" if len(new_ids) > 1 else f"new review id: {new_ids[0]}")
    if args.dry_run:
        print("dry run: nothing written")
    else:
        t.save()


if __name__ == "__main__":
    main()
