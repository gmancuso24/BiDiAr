#!/usr/bin/env python3
"""Read-only: lists persons without given name (output/persone_senza_nome.csv) and with
initials only (output/persone_solo_iniziali.csv), each with up to 3 works, for manual completion.
Run from the project root: python3 scripts/missing_names_list.py"""
import csv,sys,re,collections
sys.path.insert(0,'scripts')
from merge_article import is_full
csv.field_size_limit(10**9)
R=lambda n: list(csv.DictReader(open(f'output/{n}',encoding='utf-8-sig')))
ps,ws,cs=R('persons.csv'),R('works.csv'),R('citations.csv')
pw=collections.defaultdict(list)
for w in ws:
    for col,role in (('dcterms:creator','autore'),('bibo:editor','curatore')):
        for x in filter(None,w[col].split('|')): pw[x].append((w,role))
raw={}; ncit=collections.Counter()
for c in cs:
    ncit[c['cited']]+=1; raw.setdefault(c['cited'],c)
ENTE=re.compile(r"(?i)\b(istitut|institut|society|societ|inc\b|ltd|commission|council|survey|consortium|project|team|museum|muse[oi]|universit|minister|soprintend|comitato|fondazione|direction|servizio|service|association|associazione|group|staff|office|agency|centre|center|centro|ente\b|regione|provincia|comune|heritage|unesco|icomos|software|computer|corporation|foundation|press|library|archiv|organi[sz]ation|federal|national|nazional|dipartimento|department|bureau|network|program|iso\b|atlas|cnr|ibm)")
def tipo(p):
    f=p['foaf:familyName']
    if re.search(r"\b[A-Z][a-z]?\.\s*[A-Za-z]*\.?$",f): return 'iniziali nel cognome?'
    if ENTE.search(f) or (f.isupper() and len(f)>2) or len(f.split())>3 or re.search(r"[0-9/&()]",f) or f in('AA.VV.',): return 'ente?'
    PART={'de','di','da','del','della','dei','van','von','der','den','le','la','du','des','dal','dalla','mac','mc','ter','ten','y','e','al','el','dell','d','lo','st','saint'}
    words=re.findall(r"[^\s'’-]+",f)
    if re.search(r"[a-z][A-Z]",f) or (f.isupper()) or esri(f): return 'ente?'
    if len(words)>1 and sum(1 for x in words if x.lower() not in PART and x[:1].isupper())>=2 and '-' not in f and ' y ' not in f: return 'ente? / doppio cognome'
    return 'persona'
def esri(f): return f.lower() in {'esri','google','microsoft','adobe','autodesk','agisoft','oracle','sun','apple','unesco','istat','touring','eagles'}
def desc(w,role):
    t=w['dcterms:title'][:110]
    part=w['dcterms:isPartOf'].split('|')[0][:50]
    s=f"{w['dcterms:identifier']} ({role}) {w['dcterms:date'] or 's.d.'}, {t}"
    if part: s+=f" — {part}"
    if w['bibo:volume']: s+=f" {w['bibo:volume']}"
    return s
def build(rows,fn,extra_cols):
    out=[]
    for p in rows:
        lst=sorted(pw[p['dcterms:identifier']],key=lambda x:-ncit[x[0]['dcterms:identifier']])
        if not lst: continue
        ops=[desc(w,r) for w,r in lst[:3]]+['']*3
        c=raw.get(lst[0][0]['dcterms:identifier'])
        row={'dcterms:identifier':p['dcterms:identifier'],'foaf:familyName':p['foaf:familyName']}
        for k in extra_cols: row[k]=p[k]
        row.update({'_variants':p['_variants'],'tipo_presunto':tipo(p),'n_opere':len(lst),
             'opera_1':ops[0],'opera_2':ops[1],'opera_3':ops[2],
             'citazione_esempio':(f"[AeC {c['_citing_aec_id']}] " + c['raw']) if c else '',
             'nome_proprio_DA_COMPILARE':'','note_DA_COMPILARE':''})
        out.append(row)
    out.sort(key=lambda r:(r['tipo_presunto']!='persona',-r['n_opere'],r['foaf:familyName'].lower()))
    with open(f'output/{fn}','w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(out[0])); wr.writeheader(); wr.writerows(out)
    print(fn,len(out),collections.Counter(r['tipo_presunto'] for r in out))
SKIP=re.compile(r'not traceable|mononym|placeholder|OpenStreetMap|username|medieval chronicler')
ok=lambda p: p['o:resource_class']!='foaf:Organization' and not SKIP.search(p['_notes'])
which = sys.argv[1] if len(sys.argv) > 1 else 'all'   # senza | iniziali | all (senza_nome overwrites the file Giacomo annotates!)
if which in ('senza', 'all'):
    build([p for p in ps if ok(p) and not p['foaf:givenName'].strip()],'persone_senza_nome.csv',[])
if which in ('iniziali', 'all'):
  build([p for p in ps if ok(p) and p['foaf:givenName'].strip() and not is_full(p['foaf:givenName']) and 'ambiguous' not in p['_notes']],'persone_solo_iniziali.csv',['foaf:givenName'])
