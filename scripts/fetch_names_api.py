#!/usr/bin/env python3
"""Phase D: propose full given names for persons cited with initials only, from Crossref and
OpenAlex records of the SAME work (looked up by the DOI stored in works.csv).

Read-only on the tables. Writes
  output/api_cache.jsonl              one line per API answer (resumable; never re-asks a DOI)
  output/nomi_proposti_blocco_2.csv   one row per person with a proposal (columns compatible
                                      with `resolve.py apply-names ok --file ...`)

Sources, in order: Crossref /works/{doi} (no key); for DOIs unknown to Crossref (DataCite,
mEDRA, Zenodo...) OpenAlex /works/doi:{doi} (key in the environment variable OPENALEX_API_KEY,
never written to disk).

Trust rule (PIANO_LAVORO.md, phase D): a name is marked for direct application (ok = auto,
level "alta") only when
  - the API record is the same work: title similarity >= 0.6 (or one main title contains the
    other) and year at most 2 apart;
  - exactly one author of that record has the person's surname (same normalised key);
  - that author's given name is spelled out and compatible with ALL the cited initials
    (every initial matched in order, e.g. "J.S." ~ "John S."/"John Stephen");
  - every DOI work of the person that gives a name gives the same one (or a shorter form of it).
Everything else with a candidate name is "media" (ok empty): surname variants, double surnames,
fewer names than initials, title/year doubts, disagreement between works.

Usage
  python3 scripts/fetch_names_api.py fetch [SECONDS]   # ask the APIs (stops after SECONDS, default 150)
  python3 scripts/fetch_names_api.py report            # build the CSV from the cache
  python3 scripts/fetch_names_api.py fetch-title crossref|openalex [SECONDS]
                                                       # search works without DOI by title
  python3 scripts/fetch_names_api.py report-title [FILE] # -> output/FILE (default nomi_proposti_blocco_3.csv)
Standard library only.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
CACHE = OUT / "api_cache.jsonl"
REPORT = OUT / "nomi_proposti_blocco_2.csv"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_article import is_full, norm, surname_key  # noqa: E402

csv.field_size_limit(10**9)
UA = "BibliografiAeC/1.0 (bibliographic data cleaning, Archeologia e Calcolatori)"
SKIP = re.compile(r"not traceable|mononym|placeholder|OpenStreetMap|username|medieval chronicler")


def read(name: str) -> list[dict]:
    with open(OUT / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean_doi(d: str) -> str:
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (d or "").strip(), flags=re.I)
    return d.strip().rstrip(".").lower()


def initials_persons(persons: list[dict]) -> dict[str, dict]:
    """Same selection as missing_names_list.py iniziali."""
    return {p["dcterms:identifier"]: p for p in persons
            if p["o:resource_class"] != "foaf:Organization" and not SKIP.search(p["_notes"])
            and p["foaf:givenName"].strip() and not is_full(p["foaf:givenName"])
            and "ambiguous" not in p["_notes"]}


def targets() -> tuple[dict, dict, dict]:
    """DOI -> work rows, person -> DOI works, persons with initials."""
    persons = read("persons.csv")
    ini = initials_persons(persons)
    by_doi, person_dois = defaultdict(list), defaultdict(set)
    for w in read("works.csv"):
        doi = clean_doi(w["bibo:doi"])
        if not doi or w["_aec_id"]:
            continue
        ids = [x for x in (w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|") if x in ini]
        if ids:
            by_doi[doi].append(w)
            for x in ids:
                person_dois[x].add(doi)
    return by_doi, person_dois, ini


# ---------------------------------------------------------------- cache and API calls

def load_cache() -> dict[tuple[str, str], dict]:
    cache = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                r = json.loads(line)
                cache[(r["source"], r["doi"])] = r
    return cache


def get_json(url: str) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return -1, None


def crossref(doi: str) -> dict:
    code, data = get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"))
    if code != 200 or not data:
        return {"status": code}
    m = data.get("message", {})
    year = None
    for k in ("issued", "published-print", "published-online", "created"):
        parts = (m.get(k) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
            break
    people = [{"given": a.get("given", ""), "family": a.get("family", ""), "role": role}
              for role in ("author", "editor") for a in m.get(role, []) or []]
    title = " ".join((m.get("title") or [""])[:1] + (m.get("subtitle") or [""])[:1]).strip()
    return {"status": 200, "title": title, "year": year, "people": people}


def openalex(doi: str) -> dict:
    key = os.environ.get("OPENALEX_API_KEY", "")
    url = ("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi, safe="/")
           + "?select=title,publication_year,authorships" + (f"&api_key={key}" if key else ""))
    code, data = get_json(url)
    if code != 200 or not data:
        return {"status": code}
    people = []
    for a in data.get("authorships") or []:
        raw = a.get("raw_author_name") or (a.get("author") or {}).get("display_name") or ""
        people.append({"display": (a.get("author") or {}).get("display_name") or "", "raw": raw,
                       "role": "author"})
    return {"status": 200, "title": data.get("title") or "", "year": data.get("publication_year"),
            "people": people}


def fetch(limit: float) -> None:
    by_doi, _, _ = targets()
    cache = load_cache()
    t0, n_cr, n_oa = time.time(), 0, 0
    with open(CACHE, "a", encoding="utf-8") as f:
        for doi in sorted(by_doi):
            if time.time() - t0 > limit:
                print("stopped (time limit)")
                break
            if ("crossref", doi) not in cache:
                r = {"source": "crossref", "doi": doi, **crossref(doi)}
                if r["status"] == -1 or r["status"] == 429 or r["status"] >= 500:
                    print("crossref transient error", r["status"], doi)
                    time.sleep(2)
                    continue
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                cache[("crossref", doi)] = r
                n_cr += 1
                time.sleep(0.15)
            if cache[("crossref", doi)]["status"] != 200 and ("openalex", doi) not in cache:
                r = {"source": "openalex", "doi": doi, **openalex(doi)}
                if r["status"] == -1 or r["status"] == 429 or r["status"] >= 500:
                    print("openalex transient error", r["status"], doi)
                    time.sleep(2)
                    continue
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                cache[("openalex", doi)] = r
                n_oa += 1
                time.sleep(0.15)
    done = sum(1 for d in by_doi if ("crossref", d) in cache and
               (cache[("crossref", d)]["status"] == 200 or ("openalex", d) in cache))
    print(f"asked crossref {n_cr}, openalex {n_oa}; DOIs done {done}/{len(by_doi)}")


# ---------------------------------------------------------------- matching

def gtoks(given: str) -> list[tuple[str, bool]]:
    """('john', True) for a spelled-out name, ('j', False) for an initial.
    'M.L.' -> two initials; 'Ch.'/'Ph.' -> one initial; 'Jean-Paul' -> two names."""
    out = []
    for part in re.split(r"[\s\-‐‑]+", (given or "").strip()):
        pn = norm(part).replace(" ", "")
        if not pn:
            continue
        if "." in part.strip().rstrip("."):
            out += [(c, False) for c in pn]
        elif part.strip().endswith(".") or len(pn) == 1:
            out.append((pn[0], False))
        else:
            out.append((pn, True))
    return out


def cover(cited: str, full: str) -> str:
    """'full' when every cited token is matched in order by `full` (first token of `full`
    spelled out), 'partial' when `full` has fewer tokens, '' when incompatible."""
    a, b = gtoks(cited), gtoks(full)
    if not a or not b or not b[0][1]:
        return ""
    for i, (t, spelled) in enumerate(a):
        if i >= len(b):
            return "partial"
        u = b[i][0]
        if spelled and not (u.startswith(t) or t.startswith(u)):
            return ""
        if not spelled and u[0] != t[0]:
            return ""
    return "full"


def split_display(name: str, family_hint: str) -> tuple[str, str]:
    """OpenAlex gives 'Given Family' strings: cut off the cited surname."""
    n = name.strip()
    key = surname_key(family_hint)
    words = n.split()
    for i in range(1, len(words)):
        if surname_key(" ".join(words[i:])) == key:
            return " ".join(words[:i]), " ".join(words[i:])
    return " ".join(words[:-1]), words[-1] if words else ""


def surname_match(ours: str, theirs: str) -> str:
    a, b = surname_key(ours), surname_key(theirs)
    if not a or not b:
        return ""
    if a == b:
        return "same"
    wa, wb = set(norm(ours).split()), set(norm(theirs).split())
    if wa and wb and (wa <= wb or wb <= wa) and min(len(x) for x in (wa & wb) or {""}) >= 4:
        return "part"          # double surname cited in part
    if min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.85:
        return "variant"
    return ""


def same_name_tokens(short: str, long: str) -> bool:
    """'Elise J.' ~ 'Elise Jakoby', 'Li' !~ 'Linzhi': spelled-out names must be equal,
    initials must match the first letter."""
    a, b = gtoks(short), gtoks(long)
    if len(a) > len(b):
        return False
    for (t, sa), (u, sb) in zip(a, b):
        if sa and sb and t != u:
            return False
        if t[0] != u[0]:
            return False
    return True


def main_title(t: str) -> str:
    return norm(re.split(r"[.:?!]\s", t or "", maxsplit=1)[0])


def same_work(w: dict, rec: dict) -> tuple[bool, str]:
    ta, tb = norm(w["dcterms:title"]), norm(rec.get("title") or "")
    sim = SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0
    ma, mb = main_title(w["dcterms:title"]), main_title(rec.get("title") or "")
    contain = bool(ma and mb and len(min(ma, mb, key=len)) >= 15 and (ma in tb or mb in ta))
    ya = re.match(r"\d{4}", w["dcterms:date"] or "")
    yb = rec.get("year")
    ydiff = abs(int(ya.group()) - int(yb)) if ya and yb else None
    ok = (sim >= 0.6 or contain) and (ydiff is None or ydiff <= 2)
    return ok, f"title sim {sim:.2f}{' (main title contained)' if contain else ''}, year {w['dcterms:date']}/{yb}"


def tidy(given: str) -> str:
    """'John S' -> 'John S.'; keeps the record's spelling otherwise."""
    g = re.sub(r"\s+", " ", given.strip())
    return re.sub(r"(?<![\w.])([A-ZÀ-Ý])(?=\s|$)", r"\1.", g)


def report() -> None:
    by_doi, person_dois, ini = targets()
    cache = load_cache()
    persons = {p["dcterms:identifier"]: p for p in read("persons.csv")}
    surname_count = defaultdict(int)
    for p in persons.values():
        surname_count[surname_key(p["foaf:familyName"])] += 1
    person_works = defaultdict(set)
    for w in read("works.csv"):
        for x in (w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|"):
            if x in ini:
                person_works[x].add(w["dcterms:identifier"])
    full_names = defaultdict(list)          # (surname key, norm given) -> existing full persons
    for p in persons.values():
        if is_full(p["foaf:givenName"]):
            full_names[(surname_key(p["foaf:familyName"]), norm(p["foaf:givenName"]))].append(
                p["dcterms:identifier"])
    rows, stats = [], defaultdict(int)
    for pid, dois in sorted(person_dois.items()):
        p = ini[pid]
        found = []                          # (given, level-reason list, source, doi, evidence)
        for doi in sorted(dois):
            rec = cache.get(("crossref", doi))
            src = "crossref"
            if not rec or rec["status"] != 200:
                rec, src = cache.get(("openalex", doi)), "openalex"
            if not rec or rec["status"] != 200:
                stats["doi not found"] += 1
                continue
            for w in by_doi[doi]:
                if pid not in (w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|"):
                    continue
                ok_work, wev = same_work(w, rec)
                cands = []
                for a in rec["people"]:
                    if src == "crossref":
                        given, family = a["given"], a["family"]
                    else:
                        given, family = split_display(a["display"] or a["raw"], p["foaf:familyName"])
                    sm = surname_match(p["foaf:familyName"], family)
                    if not sm:
                        continue
                    cv = cover(p["foaf:givenName"], given)
                    odd_cited = re.search(r"\.[a-zà-ÿ]", p["foaf:givenName"])   # "M.ichalis"
                    if cv == "partial" and not odd_cited and \
                            len(gtoks(p["foaf:givenName"])) - len(gtoks(given)) <= 3:
                        # keep the cited initials the source does not spell out: "G.J." + "Geert" -> "Geert J."
                        rest = gtoks(p["foaf:givenName"])[len(gtoks(given)):]
                        given = tidy(given) + " " + " ".join(t[0].upper() + "." for t, _ in rest)
                        cv = "full"
                    if cv:
                        cands.append((tidy(given), family, sm, cv))
                if not cands:
                    stats["no compatible author in record"] += 1
                    continue
                doubts = []
                if len({c[0] for c in cands}) > 1:
                    doubts.append("several compatible authors: " + "; ".join(c[0] for c in cands))
                g, family, sm, cv = cands[0]
                if sm != "same":
                    doubts.append(f"surname {sm}: {family}")
                if cv != "full":
                    doubts.append("fewer names than cited initials")
                if not ok_work:
                    doubts.append("work doubtful")
                found.append((g, doubts, src, doi, f"{w['dcterms:identifier']} = {src} {doi} ({wev}): "
                              f"{family}, {g}"))
        if not found:
            continue
        names = sorted({f[0] for f in found}, key=lambda n: (len(gtoks(n)), len(n)), reverse=True)
        longest = names[0]
        agree = all(same_name_tokens(n, longest) for n in names)
        doubts = sorted({d for f in found for d in f[1]})
        if not agree:
            doubts.append("works disagree: " + " / ".join(names))
        if re.search(r"(^|\s)[a-zà-ÿ]", longest):
            doubts.append("odd given name in the source (particle or 'and')")
        covered = {f[4].split(" = ")[0] for f in found}
        common = surname_count[surname_key(p["foaf:familyName"])] >= 5
        if (common and len(gtoks(p["foaf:givenName"])) == 1
                and len(person_works[pid] - covered) > 0):
            doubts.append(f"common surname, single initial: {len(person_works[pid] - covered)} "
                          "other works not confirmed by the source")
        if sum(s for _, s in gtoks(longest)) <= sum(s for _, s in gtoks(p["foaf:givenName"])):
            stats["nothing new (name already spelled out)"] += 1
            continue
        clean = [f for f in found if not f[1]]
        dup = [x for x in full_names.get((surname_key(p["foaf:familyName"]), norm(longest)), [])
               if x != pid]
        if dup:
            doubts.append("same full name already in the table: " + "|".join(dup))
        level = "alta" if agree and not doubts and clean else "media"
        stats[level] += 1
        rows.append({
            "person_id": pid, "family": p["foaf:familyName"], "given_now": p["foaf:givenName"],
            "proposal": longest if agree else "", "level": level,
            "source": "+".join(sorted({f[2] for f in found})),
            "doubts": "; ".join(doubts),
            "same_name_exists": "|".join(dup),
            "evidence": " || ".join(f[4] for f in found)[:900],
            "n_doi_works": len(dois),
            "ok": "auto" if level == "alta" else "",
        })
    rows.sort(key=lambda r: (r["level"] != "alta", r["family"].lower()))
    with open(REPORT, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["person_id"])
        wr.writeheader()
        wr.writerows(rows)
    print(f"{REPORT.name}: {len(rows)} persons; " + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    print("with an existing person of the same full name:", sum(1 for r in rows if r["same_name_exists"]))


# ---------------------------------------------------------------- search by title (no DOI)
#
# For works without DOI of persons with initials only and 2+ works. The API is asked for the
# work by its title (+ first surnames); the answer is accepted as the SAME work only under
# stricter conditions than the DOI route, since a title search can return a different work:
#   - title similarity >= 0.90 (title + subtitle), or same main title of 25+ characters with
#     similarity >= 0.75;
#   - years at most 1 apart when both are known;
#   - at least one co-author/editor of our work found in the record (works with 2+ persons);
#     single-person works need the same year and similarity >= 0.95.
# Answers are cached in output/api_cache_title.jsonl (key: source + work id); the report is
# output/nomi_proposti_blocco_3.csv, same columns as blocco_2.

# A second machine can work through the list from the end (REVERSE=1) into its own cache
# file (CACHE_SUFFIX=_cloud -> api_cache_title_cloud.jsonl); every api_cache_title*.jsonl is read.
TITLE_CACHE = OUT / f"api_cache_title{os.environ.get('CACHE_SUFFIX', '')}.jsonl"
REPORT_TITLE = OUT / "nomi_proposti_blocco_3.csv"
# Persons with at least MIN_WORKS works (default 2); MIN_WORKS=1 also takes the persons
# cited in one work only, whose name cannot spread to works of somebody else.
MIN_WORKS = int(os.environ.get("MIN_WORKS", "2"))


def pure_initials(given: str) -> bool:
    return not any(spelled for _, spelled in gtoks(given))


def title_targets() -> tuple[dict, dict, dict, dict]:
    """work id -> work, person -> work ids (works without DOI), persons, all persons by id."""
    persons = read("persons.csv")
    by_id = {p["dcterms:identifier"]: p for p in persons}
    ini = {k: p for k, p in initials_persons(persons).items() if pure_initials(p["foaf:givenName"])}
    pw = defaultdict(set)
    works = {}
    for w in read("works.csv"):
        works[w["dcterms:identifier"]] = w
        for x in set((w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|")):
            if x in ini:
                pw[x].add(w["dcterms:identifier"])
    person_works = {x: {i for i in ids if not clean_doi(works[i]["bibo:doi"]) and works[i]["dcterms:title"]}
                    for x, ids in pw.items() if len(ids) >= MIN_WORKS}
    person_works = {x: ids for x, ids in person_works.items() if ids}
    target = {i: works[i] for ids in person_works.values() for i in ids}
    return target, person_works, ini, by_id


def work_persons(w: dict, by_id: dict) -> list[dict]:
    ids = [x for x in (w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|") if x in by_id]
    return [by_id[x] for x in dict.fromkeys(ids)]


def load_title_cache() -> dict[tuple[str, str], dict]:
    cache = {}
    for path in sorted(OUT.glob("api_cache_title*.jsonl")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                r = json.loads(line)
                cache[(r["source"], r["work"])] = r
    return cache


def crossref_title(w: dict, people: list[dict]) -> dict:
    q = " ".join([w["dcterms:title"][:250]] + [p["foaf:familyName"] for p in people[:2]])
    url = ("https://api.crossref.org/works?rows=3&select=DOI,title,subtitle,author,editor,issued,type"
           "&query.bibliographic=" + urllib.parse.quote(q))
    code, data = get_json(url)
    if code != 200 or not data:
        return {"status": code}
    items = []
    for m in data.get("message", {}).get("items", []):
        parts = (m.get("issued") or {}).get("date-parts") or [[None]]
        year = parts[0][0] if parts and parts[0] else None
        items.append({
            "doi": m.get("DOI", ""), "year": year,
            "title": " ".join((m.get("title") or [""])[:1] + (m.get("subtitle") or [""])[:1]).strip(),
            "people": [{"given": a.get("given", ""), "family": a.get("family", ""), "role": role}
                       for role in ("author", "editor") for a in m.get(role, []) or []]})
    return {"status": 200, "items": items}


def openalex_title(w: dict) -> dict:
    key = os.environ.get("OPENALEX_API_KEY", "")
    t = re.sub(r"[,:;|!?()\"«»\[\]]", " ", w["dcterms:title"])[:200]
    url = ("https://api.openalex.org/works?per-page=3&select=doi,title,publication_year,authorships"
           "&filter=title.search:" + urllib.parse.quote(t) + (f"&api_key={key}" if key else ""))
    code, data = get_json(url)
    if code != 200 or not data:
        return {"status": code}
    items = []
    for m in data.get("results", []):
        items.append({
            "doi": (m.get("doi") or "").replace("https://doi.org/", ""), "year": m.get("publication_year"),
            "title": m.get("title") or "",
            "people": [{"display": (a.get("author") or {}).get("display_name") or "",
                        "raw": a.get("raw_author_name") or "", "role": "author"}
                       for a in m.get("authorships") or []]})
    return {"status": 200, "items": items}


def fetch_title(source: str, limit: float) -> None:
    target, person_works, ini, by_id = title_targets()
    cache = load_title_cache()
    accepted = accepted_works(target, by_id, cache)
    t0, n = time.time(), 0
    with open(TITLE_CACHE, "a", encoding="utf-8") as f:
        for wid in sorted(target, reverse=bool(os.environ.get("REVERSE"))):
            if time.time() - t0 > limit:
                print("stopped (time limit)")
                break
            if (source, wid) in cache:
                continue
            if source == "openalex-title" and wid in accepted:
                continue                      # Crossref already found it
            w = target[wid]
            r = crossref_title(w, work_persons(w, by_id)) if source == "crossref-title" else openalex_title(w)
            if r["status"] in (-1, 429) or r["status"] >= 500:
                print(source, "transient error", r["status"], wid)
                time.sleep(5)
                continue
            r = {"source": source, "work": wid, **r}
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            cache[(source, wid)] = r
            n += 1
            time.sleep(0.3)
    left = sum(1 for wid in target if (source, wid) not in cache
               and not (source == "openalex-title" and wid in accepted))
    print(f"{source}: asked {n}; works left {left} of {len(target)}")


def record_people(item: dict, family_hint: str) -> list[tuple[str, str]]:
    out = []
    for a in item["people"]:
        if "family" in a:
            out.append((a["given"], a["family"]))
        else:
            out.append(split_display(a["display"] or a["raw"], family_hint))
    return out


def strict_same_work(w: dict, item: dict, people: list[dict]) -> tuple[bool, str]:
    ta, tb = norm(w["dcterms:title"]), norm(item.get("title") or "")
    if not ta or not tb:
        return False, "no title"
    sim = SequenceMatcher(None, ta, tb).ratio()
    ma, mb = main_title(w["dcterms:title"]), main_title(item.get("title") or "")
    main_ok = len(ma) >= 25 and ma == mb and sim >= 0.75
    ya = re.match(r"\d{4}", w["dcterms:date"] or "")
    yb = item.get("year")
    ydiff = abs(int(ya.group()) - int(yb)) if ya and yb else None
    rec_surnames = {surname_key(f) for _, f in record_people(item, "")}
    rec_surnames |= {surname_key(f.split()[-1]) for _, f in record_people(item, "") if f}
    others = [p for p in people]
    found = sum(1 for p in others if surname_key(p["foaf:familyName"]) in rec_surnames
                or any(surname_match(p["foaf:familyName"], f) for _, f in record_people(item, p["foaf:familyName"])))
    ev = f"title sim {sim:.2f}, year {w['dcterms:date']}/{yb}, persons found {found}/{len(others)}"
    if not (sim >= 0.90 or main_ok):
        return False, ev
    if ydiff is not None and ydiff > 1:
        return False, ev
    if len(others) >= 2 and found < 2:
        return False, ev
    if len(others) == 1 and not (ydiff == 0 and sim >= 0.95 and found == 1):
        return False, ev
    return True, ev


def best_item(w: dict, rec: dict | None, people: list[dict]) -> tuple[dict | None, str]:
    if not rec or rec.get("status") != 200:
        return None, ""
    for item in rec.get("items", []):
        ok, ev = strict_same_work(w, item, people)
        if ok:
            return item, ev
    return None, ""


def accepted_works(target: dict, by_id: dict, cache: dict) -> set[str]:
    return {wid for wid, w in target.items()
            if best_item(w, cache.get(("crossref-title", wid)), work_persons(w, by_id))[0]}


def time_gap(confirmed: set[str], others: set[str], works: dict) -> int:
    """Largest distance in years between an unconfirmed work and the confirmed span
    (0 when dates are missing): a person whose works span 60 years may be two persons."""
    def year(i: str) -> int | None:
        m = re.match(r"\d{4}", works[i]["dcterms:date"] or "")
        return int(m.group()) if m else None
    ys = [y for y in map(year, confirmed) if y]
    if not ys:
        return 0
    lo, hi = min(ys), max(ys)
    return max([max(lo - y, y - hi, 0) for y in map(year, others) if y] or [0])


def report_title() -> None:
    target, person_works, ini, by_id = title_targets()
    cache = load_title_cache()
    surname_count = defaultdict(int)
    for p in by_id.values():
        surname_count[surname_key(p["foaf:familyName"])] += 1
    full_names = defaultdict(list)
    for p in by_id.values():
        if is_full(p["foaf:givenName"]):
            full_names[(surname_key(p["foaf:familyName"]), norm(p["foaf:givenName"]))].append(
                p["dcterms:identifier"])
    works_by_id = {w["dcterms:identifier"]: w for w in read("works.csv")}
    all_works = defaultdict(set)
    for w in works_by_id.values():
        for x in set((w["dcterms:creator"] + "|" + w["bibo:editor"]).split("|")):
            if x in ini:
                all_works[x].add(w["dcterms:identifier"])
    rows, stats = [], defaultdict(int)
    for pid, wids in sorted(person_works.items()):
        p = ini[pid]
        found = []
        for wid in sorted(wids):
            w = target[wid]
            people = work_persons(w, by_id)
            item, ev, src = None, "", ""
            for s in ("crossref-title", "openalex-title"):
                item, ev = best_item(w, cache.get((s, wid)), people)
                if item:
                    src = s
                    break
            if not item:
                stats["work not found"] += 1
                continue
            cands = []
            for given, family in record_people(item, p["foaf:familyName"]):
                sm = surname_match(p["foaf:familyName"], family)
                if not sm:
                    continue
                cv = cover(p["foaf:givenName"], given)
                if cv == "partial" and len(gtoks(p["foaf:givenName"])) - len(gtoks(given)) <= 3:
                    rest = gtoks(p["foaf:givenName"])[len(gtoks(given)):]
                    given = tidy(given) + " " + " ".join(t[0].upper() + "." for t, _ in rest)
                    cv = "full"
                if cv:
                    cands.append((tidy(given), family, sm, cv))
            if not cands:
                stats["no compatible author in record"] += 1
                continue
            doubts = []
            if len({c[0] for c in cands}) > 1:
                doubts.append("several compatible authors: " + "; ".join(c[0] for c in cands))
            g, family, sm, cv = cands[0]
            if sm != "same":
                doubts.append(f"surname {sm}: {family}")
            if cv != "full":
                doubts.append("fewer names than cited initials")
            found.append((g, doubts, src.split("-")[0], item.get("doi", ""),
                          f"{wid} = {src} {item.get('doi', '')} ({ev}): {family}, {g}"))
        if not found:
            continue
        names = sorted({f[0] for f in found}, key=lambda n: (len(gtoks(n)), len(n)), reverse=True)
        longest = names[0]
        agree = all(same_name_tokens(n, longest) for n in names)
        doubts = sorted({d for f in found for d in f[1]})
        if not agree:
            doubts.append("works disagree: " + " / ".join(names))
        if re.search(r"(^|\s)[a-zà-ÿ]", longest):
            doubts.append("odd given name in the source (particle or 'and')")
        covered = {f[4].split(" = ")[0] for f in found}
        unconfirmed = all_works[pid] - covered          # DOI works included
        common = surname_count[surname_key(p["foaf:familyName"])] >= 5
        if common and len(gtoks(p["foaf:givenName"])) == 1 and unconfirmed:
            doubts.append(f"common surname, single initial: {len(unconfirmed)} "
                          "other works not confirmed by the source")
        gap = time_gap(covered, unconfirmed, works_by_id)
        if gap > 25:
            doubts.append(f"other works {gap} years away from the confirmed ones")
        dup = [x for x in full_names.get((surname_key(p["foaf:familyName"]), norm(longest)), [])
               if x != pid]
        if dup:
            doubts.append("same full name already in the table: " + "|".join(dup))
        level = "alta" if agree and not doubts else "media"
        stats[level] += 1
        rows.append({
            "person_id": pid, "family": p["foaf:familyName"], "given_now": p["foaf:givenName"],
            "proposal": longest if agree else "", "level": level,
            "source": "+".join(sorted({f[2] for f in found})) + " (title search)",
            "doubts": "; ".join(doubts), "same_name_exists": "|".join(dup),
            "evidence": " || ".join(f[4] for f in found)[:900],
            "n_doi_works": len(person_works[pid]),
            "ok": "auto" if level == "alta" else "",
        })
    rows.sort(key=lambda r: (r["level"] != "alta", r["family"].lower()))
    with open(REPORT_TITLE, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["person_id"])
        wr.writeheader()
        wr.writerows(rows)
    print(f"{REPORT_TITLE.name}: {len(rows)} persons of {len(person_works)}; "
          + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "fetch":
        fetch(float(sys.argv[2]) if len(sys.argv) > 2 else 150)
    elif len(sys.argv) == 2 and sys.argv[1] == "report":
        report()
    elif len(sys.argv) >= 3 and sys.argv[1] == "fetch-title" and sys.argv[2] in ("crossref", "openalex"):
        fetch_title(sys.argv[2] + "-title", float(sys.argv[3]) if len(sys.argv) > 3 else 150)
    elif len(sys.argv) in (2, 3) and sys.argv[1] == "report-title":
        if len(sys.argv) == 3:              # one file per pass, so earlier reports are kept
            REPORT_TITLE = OUT / sys.argv[2]
        report_title()
    else:
        sys.exit(__doc__)
