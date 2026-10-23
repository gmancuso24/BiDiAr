# Passaggio di consegne – BibliografiAeC (21/10/2026)

Documento per chi prosegue il lavoro (e per il suo Claude). Da leggere **insieme a `CLAUDE.md`**,
che resta la fonte per workflow, regole di matching e struttura delle tabelle. Qui c'è solo
quello che in `CLAUDE.md` non c'è: stato, abitudini di lavoro e punti aperti.

## Come iniziare
1. Aprire Claude Code **dentro questa cartella** (così legge `CLAUDE.md` e le skill in `.claude/skills/`).
2. Primo messaggio suggerito: *"Leggi CLAUDE.md e PASSAGGIO_CONSEGNE.md, poi dimmi a che punto siamo."*
3. Lavorare **una persona alla volta** sulla cartella: `works.csv` e `persons.csv` hanno ID
   progressivi (W/P), due copie modificate in parallelo non si possono riunire.
4. `output/backup/` (~30 GB) è la rete di sicurezza dei merge: non serve copiarla per spostare
   il lavoro, ma non va cancellata finché si lavora (pulizia solo verso ~50 GB, vedi `CLAUDE.md`).

## Stato al 21/10/2026
- Tabelle: ~17.600 righe in `works.csv`, ~17.800 in `persons.csv`, ~21.100 in `citations.csv`.
- **Journal**: vol. 1–34 elaborati. **Restano i vol. 35 (79 file), 36 (48), 37 (23).**
- **Supplementi 1–15**: non iniziati (ordine deciso: prima il journal, poi i supplementi, perché la
  lista nomi Zotero non li copre).
- `review.csv`: **0 righe aperte** (ultima purge/drop-orphans 21/10 alle 07:33).
  `review_archive.csv` contiene le righe chiuse (~2.480).
- Alcuni file dei vol. 9, 14, 15 risultano senza `parsed/*.json` (2, 5 e 3 file): da controllare
  se sono articoli senza bibliografia/rubriche (vedi `CLAUDE.md`) o dimenticanze.
- Articolo **267** deliberatamente non elaborato (vedi `CLAUDE.md`): non tornarci.
- Dopo l'ultimo volume elaborato, verificare che sia stato fatto `audit_duplicates.py` e `drop-orphans`.

## Prima di parsare i vol. 35–37
- Controllare i MD: molti contengono ancora il testo completo (non solo la bibliografia) e i vol.
  28 e 31–37 stanno in sottocartelle per fascicolo (`28.1`, `32_1`…): `data/journal/{volume}/{aec_id}.md`
  può non corrispondere. (Nota: l'elenco aggiornato delle cartelle è in `data/journal/`.)
- Ordine: sempre cronologico, un volume alla volta: parsing → `merge_article.py` → pre-revisione
  (skill `prereview-aec-volume`) → report a chi decide → `audit_duplicates.py` + `drop-orphans`.

## Come si lavora (preferenze emerse nelle sessioni)
- **Chi decide**: finora le decisioni sui casi dubbi le ha prese Giacomo; Claude applica. Se ora decide
  la collega, va scritto qui sotto, altrimenti Claude continuerà a rivolgersi a "Giacomo":
  - Decisore dei casi dubbi da ora: ______________________
- **Mai** modificare i CSV a mano: solo tramite gli script (`merge_article.py`, `resolve.py`).
- Regola d'oro del matching: ogni verifica di identità guarda **tutta** la tabella; i casi vietati
  dalle regole di sicurezza vanno in `review.csv`, mai creati in silenzio come record nuovi.
- **Priorità**: non presentare centinaia di casi da disambiguare per volume (la revisione umana
  stanca diventa acritica). Modalità ibrida: Claude applica con `--auto` i casi chiari, il resto
  va in un report breve.
- **Formato della revisione**: casi numerati e spiegati per esteso nel testo (titoli, autori, anni),
  con una proposta di decisione; non solo ID da cercare nei CSV. Mostrare sempre il `review_id`.
- Ogni revisione: `resolve.py purge` all'inizio e alla fine, poi dire quante righe restano aperte.
- Tolleranza pagine: 2–3 pagine di differenza in prima/ultima pagina contano come uguali.
- Lingua: commenti di codice e documentazione in inglese; conversazione in italiano.

## Punti aperti
- `output/name_suggestions.csv`: 3 proposte `unique` **non applicate** perché non confermate:
  Gero J.S. → John S.; Higgs E.S.C. → Eric S.; Landrum J.E. III → James E.
  (Joan M. Gero esiste ma ha iniziali J.M.). Gli altri nomi ambigui si decidono caso per caso.
- Le rubriche fisse senza bibliografia (es. GIS, Internet e multimedia, statistica applicata) restano
  senza citazioni; le citazioni nel testo si recupereranno in una passata unica successiva dai MD completi.
- Citazioni che rimandano solo a una rivista (senza i singoli contributi): non gestite, si lasciano così.
- I `cs-unresolved` ("c.s."/in press non risolti) sono elencati in `output/cs_non_risolti.md`.
- Da fare alla fine: script di export per l'import in Omeka S (ordine: persone → opere → citazioni
  come `bibo:cites`). Nessuna riconciliazione con i record già presenti in BiDiAr (verranno sostituiti).

## Decisioni principali già prese (riassunto)
- Una opera in più volumi citata insieme si collega ai singoli volumi distinti; il tomo non rende
  un'opera diversa.
- Due voci diverse della stessa bibliografia sono sempre opere distinte (regola automatica).
- Un nome completo unico compatibile con le iniziali nella lista Zotero si applica direttamente;
  varianti e ambigui solo con conferma.
- Elenco completo e cronologico delle modifiche: `output/decisions.log`.
