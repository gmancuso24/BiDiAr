# Build output/parsed/{aec_id}.json from a compact spec: the "raw" field is copied from the .md by position.
# A spec entry {"pos": N, "skip": "reason"} excludes a line that is not a reference.
# Usage: python3 scripts/build_parsed.py AEC_ID spec.json  (spec = list of references with "pos" instead of "position"/"raw")
import json,sys,re,glob,os
aid=sys.argv[1]; spec=json.load(open(sys.argv[2],encoding='utf-8'))
src=next(f for f in glob.glob(f'data/*/*/{aid}.md'))
txt=open(src,encoding='utf-8').read().split('\n')
def bib_lines(txt):
  # non-empty lines after the frontmatter; in full-text files only the bibliography section
  # (from the first heading containing biblio/reference/literatur to the end, sub-sections included);
  # figure lines ("![...](...)" and ">*caption*") are never references
  c=0;body=[]
  for l in txt:
    if l.strip()=='---' and c<2: c+=1; continue
    if c>=2: body.append(l)
  if c==0: body=list(txt)   # file without frontmatter (e.g. 1368): use every line
  start=None
  for i,l in enumerate(body):
    if re.match(r'#{1,6}\s.*(biblio|reference|référence|literatur|riferimenti)',l,re.I): start=i; break
  if start is not None: body=body[start+1:]
  elif any(l.startswith('#') for l in body): return []   # full text with no bibliography heading: nothing to parse
  return [l.strip() for l in body if l.strip() and not l.startswith('#') and not l.startswith('![') and not l.startswith('>*')]
lines=bib_lines(txt)
if not lines: sys.exit('no bibliography section found in '+src)
refs=[];skipped=[]
for r in spec:
  # {"pos": N, "skip": "reason"}: the line is not a reference (note, heading, acknowledgement...);
  # it is covered but produces no reference, and is recorded under "skipped"
  if 'skip' in r: skipped.append({'position':r['pos'],'raw':lines[r['pos']-1],'reason':r['skip']}); continue
  p=r.pop('pos'); r={'position':p,'raw':lines[p-1],**r}
  refs.append(r)
miss=set(range(1,len(lines)+1))-{r['position'] for r in refs}-{k['position'] for k in skipped}
if miss: sys.exit(f'missing positions {sorted(miss)}')
out={'citing_aec_id':int(aid),'source_file':src,'references':refs,**({'skipped':skipped} if skipped else {})}
dst=f'output/parsed/{aid}.json'
if os.path.exists(dst): sys.exit('exists')
json.dump(out,open(dst,'w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('written',dst,len(refs),'refs',f'({len(skipped)} lines skipped)' if skipped else '')
