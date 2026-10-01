# Traderhistorik och nästa steg mot scalping

Version 0.2 samlar källmaterial i en spårbar databas. Den tränar ingen modell och
kör inga order. Offentliga historikblad och strategiförklaringar räcker inte för
att säga att en robot har lärt sig en traders beslut eller kan scalpa lönsamt.

## Kör på Mac

Använd Python 3.11 eller senare och kör från projektets rot. Inga extra
Python-paket behövs. Katalog, original och databas ska ligga utanför Git.
Katalogen `sources.json` kommer från det separata researchpaketet; den innehåller
de åtta granskade källornas exakta URL:er, filnamn och kolumnmappningar.
Exemplen nedan utgår från att det paketet packats upp i `../research/`.

Importera redan hämtade original utan nätverk:

```bash
python3 -m trading_intelligence import-trader-xlsx \
  --catalog ../research/reference/sources.json \
  --raw-dir ../research/raw \
  --receipts-dir ../research/raw \
  --out ../trader-data
python3 -m trading_intelligence publisher-status --out ../trader-data
```

`--source-id ID` kan upprepas för ett urval. `--day-only` utelämnar Swing-bladen
från den körningens omfattning. Äldre importerade Swing-poster finns kvar.

Hämta katalogens exakta offentliga XLSX-exporter till en ny lokal katalog:

```bash
python3 -m trading_intelligence download-trader-sources \
  --catalog ../research/reference/sources.json --out ../new-trader-originals
```

Hämtaren följer endast kontrollerade offentliga Google-exportomdirigeringar,
begränsar svarsstorlek och validerar kalkylbladet före lagring. Den stannar vid
401, 403, 429, HTML-svar eller andra fel och skriver ett kvitto för delresultatet.
Den försöker inte andra vägar, loggar inte in och gör inga automatiska återförsök.
En befintlig giltig fil återanvänds utan nätverk och utan påhittad hämtningstid.
Använd en ny katalog för en ny källsnapshot; befintliga filer skrivs inte över.

Importera granskade bildrader, journaluppgifter och undervisningskort separat:

```bash
python3 -m trading_intelligence import-publisher-evidence ../research/image_records.jsonl \
  --kind image_transactions --source-id grittani_july_image_2020 \
  --assets-root ../research --out ../trader-data
python3 -m trading_intelligence import-publisher-evidence ../research/journal_records.jsonl \
  --kind journal_summaries --source-id grittani_public_journal_details --out ../trader-data
python3 -m trading_intelligence import-publisher-evidence ../research/strategy_cards.json \
  --kind strategy_cards --source-id trader_strategy_teaching --out ../trader-data
```

Filnamnen för journal och strategikort kan skilja sig mellan researchpaket; ange
den faktiska filen. Bildens rapporterade relativa sökväg måste finnas under
`--assets-root`. Originalets PNG-signatur och SHA-256 kontrolleras. Utan
`--assets-root` blir bildraderna uttryckligen märkta som byteverifiering saknas.

## Vad databasen innehåller

| Typ | Betydelse | Begränsning |
|---|---|---|
| Grittani transaktionsrad | Rapporterad datum-, instrument-, kvantitets- och kontantuppgift | Inte en verifierad komplett fillhistorik; intradagstid saknas |
| Hougaard Day | Rapporterat exit-ben, ibland flera för samma entry-länk | Ben slås inte ihop; konfliktande entry-uppgifter markeras |
| Hougaard Swing | Separat rapporterad swingposition | Räknas inte som scalping |
| Bildtransaktion | Manuellt granskad rad med bildlokator | Hash verifierar originalbytes, inte brokerautenticitet |
| Journal | Rapporterad stängd positionssammanfattning | Visningspriser/P&L är inte individuella fills; valuta kan vara okänd |
| Strategikort | Källbelagd undervisning eller retrospektiv beskrivning | Inte en tränad policy, signal eller bevis för faktisk trade |

Den manuella provkörningen av researchpaketet 2026-10-01 gav 5 444 XLSX-rader
(4 689 Grittani, 621 Hougaard Day och 134 Swing), 41 bildrader, 20 journalposter
och 7 strategikort. Detta är 5 512 källobservationer inklusive undervisningskort,
inte 5 512 unika verifierade trades. Omimport av samma material gav inga nya
semantiska versioner. Original kördes bara lokalt; tester och CI använder
uteslutande fiktiva data. Publik nätverkshämtning har testats med syntetisk
transport, inte på nytt mot originalkällorna i denna leverans.

XLSX-urvalet är strikt: Hougaard Day kräver en Long/Short-rad med rapporterat
instrument och entrypris; Grittani kräver datum och instrument efter rubrikraden.
Manifestet visar urvalsregler, valda radantal och samtliga icke valda, icke tomma
radnummer per blad. Övriga rader finns i originalet men är inte egna normaliserade
poster. Detta är därför inget intyg om fullständig historik.

29 XLSX-rader har ofullständig eller negativ rapporterad kronologi. Därutöver
saknar många poster intradagstid eller verifierad tidszon. Antalet tidskarantäner
är alltså inte ett mått på antalet träningsbara rader. Alla poster och körningar
har `training_ready=false`, `full_history_verified=false` och inga handelsfunktioner.
Fabio Valentini och Sivakumar Jayachandrans undervisningsmaterial är inlagt som
strategikort; någon komplett verifierad fillhistorik för dem finns inte här.

## Spårbarhet och omimport

`history.sqlite3` innehåller separata `publisher_*`-tabeller. Källorna blir inte
C2-strategier. Körningarna finns i `publisher-runs/<id>/manifest.json` och
`observations.jsonl`; C2 behåller sina egna tabeller, `runs/` och `status`-kommando.

Originalbytes namnges med SHA-256. Om ZIP-paketering eller Excel-stilar ändras
utan ändrade cellvärden skapas en ny källsnapshot men ingen ny radversion.
Semantiken inkluderar råvärden, XML-celltyper, formler och Excels datumsystem;
formler räknas inte ut. Ändrad rad eller adapterpolicy ger en ny historisk version.
En ändrad källrad kräver granskning även efter ytterligare omimport. Ingen version
väljs automatiskt som den senaste sanningen och ingen rad raderas automatiskt.

Fysisk radlokator är inte ett stabilt trade-ID när källan flyttar eller lägger till
rader. Två identiska fysiska rader bevaras separat. Äldre versioners JSON behåller
sin första proveniens; en körnings `observations.jsonl` och snapshot visar just
den körningens original. Misslyckade körningars delresultat finns kvar för granskning
men utesluts ur `completed_publisher_records`.

Importtid, publiceringstid, hämtningstid och tradetid är olika uppgifter. Originalets
hämtningstid fylls endast från ett entydigt hashmatchat kvitto. Filens mtime och
importklockan används aldrig som ersättning. Lokala datum/minutklockor omvandlas
inte till UTC utan belägg. Signed quantity är inte positionsriktning och kontantbelopp
är inte P&L. Rapporterad relativ stake blir inte absolut positionsstorlek eller risk.

## Nästa byggsteg

1. **Marknadsdata och replay:** välj marknad/instrument och anskaffa tillåten bid/ask-
   eller tickhistorik med verifierad tidszon, instrumentvillkor och kostnader.
   Candledata kan användas för en enklare prototyp, men bevisar inte scalpingfills.
2. **Första regelstrategin:** skriv explicita entry-, exit-, stop-, sessions- och
   riskregler. Källornas undervisning blir hypoteser att pröva; saknade regler
   dokumenteras och får inte tillskrivas tradern.
3. **Tidsordnad utvärdering:** separera utvecklingsperiod från senare orörd testperiod,
   beräkna spread, avgifter, slippage och eventuell latens; kontrollera läckage och
   stabilitet över olika perioder. Bestäm acceptanskriterier innan testet.
4. **Demo:** först efter godkänd replay kopplas en separat demokomponent med
   positionsgränser, stopp och full loggning. Livetrading är ett senare beslut.

En första robot bör börja med tydliga regler. Maskininlärning kan läggas till när
det finns tillräckliga tillåtna, tidsriktiga data och en fungerande jämförelsemodell.
Den nuvarande databasen ger undersökningsmaterial; den har inte lärt roboten att scalpa.
