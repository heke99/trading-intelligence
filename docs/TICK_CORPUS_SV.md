# Större tickhistorik: granskad införsel

Den nya delen löser filstorlek och spårbar uppdelning, inte bristen på originaldata. Den är helt lokal och skickar inga order. Marknadsdata, traders affärer och undervisning förblir olika posttyper.

## Vad som går att göra

`shard-ticks` arkiverar en lokal CSV oförändrad och delar dess validerade bid/ask-rader i mindre filer. Två format stöds:

- `utc_bidask_csv_v1`: marknadskontraktets UTC-ms-CSV med rubrik `time_msc,bid,ask`, valfri `symbol` och explicit metadata.
- `histdata_generic_ascii_tick_v1`: lokal, uppackad Generic ASCII-CSV med motsvarande spec, fast EST och originalfilens SHA-256. Den befintliga HistData-specen används, men nu kan CSV:n vara större än 32 MiB.

Originalfilen får vara högst 1 GiB. Spec/metadata får vara högst 64 KiB. Högst 4 096 delar publiceras per införsel. Varje del begränsas till 500 000 rader och 32 MiB; lägre gränser kan väljas. Buffertar växer inte med hela originalfilens storlek. Dessa är resursgränser, inte påståenden om verifierad flerårstäckning.

För varje körning finns ett separat kvitto. Original-CSV och originalmetadata/spec arkiveras med SHA-256 och läsrättigheter `0400`. Valideringen använder arkivkopiorna. Kopiornas hash kontrolleras igen före publicering. Detta är spårbarhet mot de lokalt mottagna bytena, inte bevis för utgivarens autenticitet eller rådatas licens.

## Delningsregler

Delning sker vid UTC-midnatt eller när nästa tidsgrupp skulle överskrida rad-/bytegränsen. Alla på varandra följande rader med samma millisekund stannar i samma del. Radordning och bokstavliga decimalpriser bevaras. Ingen sortering, prisavrundning, påhittad millisekund, deduplicering eller luckfyllning görs.

En tidsgrupp större än vald kapacitet ger `CORPUS_EQUAL_CLOCK_GROUP_TOO_LARGE`. Gränsen måste då väljas om inom de fasta maximigränserna; gruppen kapas inte tyst. En bakåtgående klocka, korsad bid/ask, felaktig källhash, för stor fysisk rad eller blandade symboler avvisas. Formatet är uttryckligen en fysisk rad per post: tomma och flerradiga CSV-poster accepteras inte.

Varje del får egen CSV, metadata och hashar. Delens metadata anger originalets hash samt första/sista fysiska källrad. Kopplingen är:

`original physical row = shard physical row - 2 + corpus_source_first_physical_row`

HistDatas ursprungliga klock- och volymfält finns kvar i originalarkivet. Volymen blir ingen modellfeature och ingen aggressorsida eller orderflow konstrueras ur den. UTC-konvertering följer befintlig spec; den är inte ett antagande om användarens brokerklocka.

En färdig datasetkatalog publiceras först när hela originalet klarat validering. Vid fel eller avbrott finns kvitto och eventuella kompletta originalarkiv kvar, men inga delar annonseras som godkänd dataset. Ofullständiga arbetsfiler kan ligga kvar i körningens `.staging`; de är inte träningsunderlag.

## Körning

Från projektet, med original och resultat utanför Git:

```bash
python -m scalper_research shard-ticks /absolute/private/ticks.csv \
  --evidence /absolute/private/market.metadata.json \
  --source-format utc_bidask_csv_v1 \
  --out /absolute/private/corpus

python -m scalper_research shard-ticks /absolute/private/DAT_ASCII.csv \
  --evidence /absolute/private/histdata.spec.json \
  --source-format histdata_generic_ascii_tick_v1 \
  --out /absolute/private/corpus

python -m scalper_research verify-tick-corpus \
  /absolute/private/corpus/tick-corpus-runs/RUN_ID/manifest.json
```

Sökvägarna ovan är exempel, inte levererade original eller verkliga körnings-ID:n. Kvittofältet `manifest_path` ger den faktiska sökvägen. Körningen kräver inga API-nycklar. Verktyget hämtar eller packar inte upp ZIP-filer och gör inga nätanrop.

Verifieraren läser endast datasetkatalogen bredvid manifestet. Filnamn, ordning och symlänkar kontrolleras. Den validerar varje dels kvoter och metadata, hashar, radantal, källradintervall och strikt stigande delgränser. Den kontrollerar delarnas integritet mot ett **lokalt, osignerat** kvitto, inte deras koppling tillbaka till utgivarens original. Den läser inte råarkiv via sökvägar i manifestet; `raw_source_rechecked=false` är därför uttryckligt. Delar ska inte användas om denna kontroll misslyckas.

## Vad rapporten inte betyder

Rapporten visar observerade UTC-dagar, första/sista kvot, dubblettantal, största observerade tidsavstånd och antal tidsavstånd över en uttrycklig rapporttröskel. De första 50 sådana avståndens ändpunkter sparas; totalantalet räknas över hela filen. Ett avstånd kan vara helg, stängd session, låg aktivitet eller databortfall. Utan produktspecifik sessions-/helgdagskalender klassificeras det inte som saknad data. Första och sista datum bevisar inte full periodtäckning.

Detta inför **inte** sammanhängande träning över alla delar. Ett separat `tick-run` på varje del återställer tillstånd och gör en separat utvecklings-/validerings-/testuppdelning. Flera sådana körningar får inte summeras och kallas en corpus-tränad modell eller oberoende sluttest. Projektionshinkar och framtida etikettfönster över delgränserna kräver en separat, fryst streamingtränare med dokumenterade reset-/purge-/holdoutregler. Det återstår.

`training_ready`, `full_history_verified`, `broker_verified`, `rights_verified`, `model_trained`, `real_market_model_trained`, `expert_trade_history` och `forward_verified` förblir falska. Ursprungliga användningsassertioner och proveniens behålls; teknisk införsel skapar inget tillstånd att träna.

## Verifiering

Offline-tester täcker båda formaten, UTC-midnatt, samma millisekund vid kapacitetsgräns, exakta decimalsträngar, radkoppling, hashfel, förändrat arkiv, avbrott, felaktiga rättighets-/beredskapspåståenden, symlänkar och CLI. En helt fiktiv fil med 510 001 rader och mer än 32 MiB körs igenom både delning och verifiering. Inga tester eller CI-körningar använder verkliga traderexporter, marknadshämtningar eller nycklar.

Se [databeredskap](DATA_READINESS_2026-10-02_SV.md) för vad som fortfarande behövs innan verklig träning.
