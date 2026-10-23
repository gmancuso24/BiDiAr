# Read-only: show works compactly (authors, editors, container, citing articles).
# Usage: python3 scripts/show_works.py W000123 W000456 ...
import csv,sys,collections
W={r['dcterms:identifier']:r for r in csv.DictReader(open('output/works.csv',encoding='utf-8-sig'))}
P={r['dcterms:identifier']:r for r in csv.DictReader(open('output/persons.csv',encoding='utf-8-sig'))}
C=collections.defaultdict(list)
for r in csv.DictReader(open('output/citations.csv',encoding='utf-8-sig')): C[r['cited']].append(r['_citing_aec_id'])
def nm(ids): return '; '.join(f"{P[i]['foaf:familyName']}, {P[i]['foaf:givenName']}" if i in P else i for i in ids.split('|') if i)
for i in sys.argv[1:]:
  w=W.get(i)
  if not w: print(i,'MISSING'); continue
  print(f"{i} [{w['dcterms:type']}] {w['dcterms:date']} | {w['dcterms:title']} | au: {nm(w['dcterms:creator'])} | ed: {nm(w['bibo:editor'])} | in: {w['dcterms:isPartOf']} v{w['bibo:volume']} pp{w['bibo:pages']} | ser: {w['dcat:inSeries']} {w['curation:number']} | {w['dcterms:publisher']} {w['dcterms:spatial']} | uri {w['bibo:uri']} | cited by {C[i]}")
