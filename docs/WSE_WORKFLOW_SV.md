# WSE: originalhistorik, rekonstruktion och fryst utvärdering

Flödet kan läsa en lokal WSELOB-originalfil, bevara dess orderhändelser med
nanosekundsklockor, skapa uttryckligt härledda bid/ask-observationer och köra
development-träning, validation-val och kostnadsstress. Ingen broker är ansluten.

Den faktiska originalhämtningen i denna miljö misslyckades: **ett försök, noll
mottagna bytes**. Originalfilens verkliga HDF-schema har därför inte provkörts
här. Den genomförda provkörningen använder en helt fiktiv HDF-fil. Det är inget
bevis för marknadsedge, verklig marknadsträning eller imitation av Fabio
Valentini eller Sivakumar Jayachandran.

## Installera från projektroten

Använd Python 3.11 eller senare. WSE-läsaren behöver tillägget `wse`, som anger
`h5py==3.16.0`. De vanliga CSV-/BI5-kommandona behöver inte det tillägget.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install '.[wse]'
python3 -m scalper_research --help
```

Behåll original, planer och körresultat utanför Git. Exempelkommandona använder
en katalog under hemkatalogen:

```bash
WSE_WORK="$HOME/trading-data/wse"
python3 -m scalper_research wse-plan --out "$WSE_WORK"
```

Planen skriver `wse-plan/source.contract.json`, `wse-plan/import.spec.json` och
`wse-plan/research.config.json`, med hashkvitton. Befintliga planfiler med andra
bytes skrivs inte över. Konfigurationen är en separat PEKAO-hypotes; EURUSD-
eller XAUUSD-inställningar används inte automatiskt för denna aktie.

Planfiler och körkonfiguration sparas före det lokala forskningsflödets import
och utvärdering. Detta visar arbetsordningen i körningen. Programmet kan inte
avgöra om någon redan har sett historiken eller tidigare testresultat utanför
körningen, och intygar därför inte att testperioden varit osedd.

## Kontrollera mekaniken med fiktiva order

```bash
python3 -m scalper_research native-demo --out "$WSE_WORK/native-demo-01"
```

`native-demo` kräver en ny, tom utdatakatalog. Det skapar syntetiska F/Y/M-
händelser i riktiga HDF-tabeller, läser dem genom samma parser och kör inlärning
och kostnadsstress. Inga originaldata hämtas eller används. En fitted modell
från denna demonstration har lärt ett samband i påhittade data.

## Originalfil och hämtning

Det fasta kontraktet avser **PEKAO/WSELOB-2017 V1**, inte andra instrument eller
hela någon namngiven traders historik:

| Uppgift | Fast kontrakt |
|---|---|
| Originalstorlek | 152 759 953 bytes |
| SHA-256 | `3c418a55a492ebe2e39c8513cd7fc7e3e6827dc1a176af09fdcaad9f3485bae6` |
| Instrument / symbol_idx | PEKAO / 11322 |
| Datakällans angivna licens | CC BY 4.0, med attribution och ändringsbeskrivning |
| Planens valda dagar | 2, 3 och 4 januari 2017 |

Källkontraktet bevarar [depositorposten](https://data.mendeley.com/datasets/3g4mhdp899/1),
DOI `10.17632/3g4mhdp899.1`, attribution till Adam Marszałek och
[licenslänken](https://creativecommons.org/licenses/by/4.0/legalcode.en).
Licensuppgiften innebär inte att klockor, matchingfas, historikens fullständighet
eller simulerade fills har verifierats.

På en miljö där den ordinarie offentliga åtkomsten fungerar finns kommandot:

```bash
python3 -m scalper_research acquire-wse --out "$WSE_WORK/acquisition"
```

Kommandot använder endast den fasta originaladressen, ingen autentisering,
inga omdirigeringar, inga automatiska återförsök och ingen återupptagning av
partialfiler. Det verifierar hela filens storlek och SHA före publicering som
komplett original. Ett redan komplett cacheoriginal verifieras på nytt.
Vid åtkomstfel läses felkvittot; en annan route söks inte automatiskt.

Använd bara `data_path` från ett kvitto med `status="completed"`. Filen
`download.partial` är inte ett dataset och får inte användas för träning.
Om originalfilen redan har tillhandahållits separat kan dess lokala sökväg
anges direkt. Samma strikta SHA-kontroll gäller även då.

## Kör originalflödet från en lokal fil

Ersätt sökvägen nedan med det kompletta originalet. Själva `wse-run` använder
inte nätverket:

```bash
WSE_HDF="/absolut/sokvag/till/PEKAO_lob_2017_zlib.h5"
python3 -m scalper_research wse-run "$WSE_HDF" \
  --spec "$WSE_WORK/wse-plan/import.spec.json" \
  --config "$WSE_WORK/wse-plan/research.config.json" \
  --out "$WSE_WORK/original-run-01"
```

Körningen arkiverar specifikation och konfiguration, importerar de valda
dagarna, tränar endast på development och fryser validation-valet före test
och kostnadsstress. Om originalet saknar förväntade tabeller eller stödda
fält, rekonstruktionen saknar användbara quotes eller inlärningen saknar
tillräckliga avslut/utfallsklasser blir körningen blockerad eller misslyckad.
Programmet skapar inte ersättningshistorik för att få den att gå igenom.

Att koden klarar syntetiska HDF-tabeller intygar inte att denna originalfil
har just den layouten. Kontrollera originalkörningens egna kvitton innan
resultaten beskrivs som beräknade på originalet.

## Klockor och orderbok

Originalets `time` är UTC-epoch i **nanosekunder** enligt depositorbeskrivningen.
Fältet avser tid då meddelandet skickades i systemet. Det är varken en styrkt
broker-mottagningstid eller en exekveringstid. Ursprungliga rader, lika ns-
klockor och eventuellt HDF-index bevaras; radordningen blir inte en verifierad
exchangesekvens eller tidsprioritet i kön.

Orderidentiteten omfattar instrument, `order_date` och `order_id`. F återställer
boken, Y återsänder/upsertar order, A lägger till, M modifierar och D tar bort.
Modifierade fält med källans sentinel `-1` behåller tidigare styrkta värden.
Sida 5, short sell, ligger på asksidan. Visad `volume` aggregeras per pris;
`agg_volume` adderas inte en gång för varje order. M och D blir inte labels för
genomförda affärer.

Formatet har ingen dokumenterad slutmarkör för återsändning eller styrkt
kontinuerlig matchingfas. Därför är första följande icke-Y-händelse en uttrycklig
bootstrap-hypotes. Ostödd ordertyp, okänd identitet, felaktig bok eller native
datagap kan blockera boktillståndet fram till ny F. Alla sådana antaganden
redovisas; rekonstruerade nivåer intygar inte exekverbar likviditet eller köplats.

Planens sampling är 1 000 ms. En quote märks med den **avslutade bucketens
UTC-gräns**, och innehåller endast tidigare native händelser. Den får inga
framtida priser. Sista ofullbordade bucket utelämnas. Buckets med reset,
återsändning, ensidig/korsad eller annan ostödd bok utelämnas också.
Detta är en härledd sampledserie, inte native ticks med påhittade unika klockor.
En serie med en sekund mellan observationerna kan inte verifiera subsekunds-
latens, köplats eller exekverbarhet. Exempelvis kan stress från 100 till 200 ms
ge samma simulerade fills när båda väntar på nästa sekundquote. Matchingfasen
är fortfarande okänd.

För denna serie måste `max_quote_gap_ms` vara högst 1 000. Metadata anger
motsvarande krav även för andra sampleperioder. Replay, inlärning, paper och
stress avvisar en vidare tolerans, så utelämnade buckets inte överbryggas med
gamla signaler eller väntande entries. Native eventgap och quotegap är olika
kontroller. Planens native-gräns är 60 000 ms; den skapar inte utfyllnadsquotes.

## Hypotes, kostnader och utvärdering

Planen använder egen rolling-breakout-regel med **en PEKAO-unit**, multiplier 1
och P&L i **PLN**. Antagna grundkostnader är 0,02 PLN per unit och sida,
slippage 0,01 prisunit per sida och latens 100 ms. Dessa är förregistrerade
forskningsantaganden, inga verifierade brokerpriser, minimiavgifter, lånevillkor
eller rekommenderade handelsinställningar. Ingen konto-FX, marginalmodell eller
portföljexponering beräknas.

Den 2 januari är development, den 3 januari validation och den 4 januari test,
med gränser i UTC. Varje period börjar flat och utan tidigare signalhistorik.
Modellens labels är avslut från vår egen hypotetiska baslinje efter de antagna
kostnaderna. De beskriver inte Fabios eller Sivakumars beslut.

Efter development-fit väljer endast validation en tröskel ur det fasta urvalet.
Samma vikter och frysta tröskel används sedan i fem förutbestämda scenarier:
grundkostnader, dubbla fees, dubbel slippage, dubbel latens och kombinationen.
Baslinje utan modell och reject-all redovisas separat. Ingen stressvariant väljs
automatiskt som vinnare och ingen modell tränas om på testet.
Kostnadsstress visar känslighet i denna simulation; den bevisar varken edge
eller fungerande forwardhandel.

Vid dataslut ligger öppna positioner kvar som orealiserade. Realiserad net P&L
och ending equity med uppskattad liquidation är separata mått. Positiva siffror
eller ett tekniskt genomfört flöde slår inte på acceptansflaggor.

## Separata kommandon och kvitton

För att granska importen eller återanvända en tidigare fryst modell finns även:

```bash
python3 -m scalper_research import-wse "$WSE_HDF" \
  --spec "$WSE_WORK/wse-plan/import.spec.json" --out "$WSE_WORK/import-only"

python3 -m scalper_research stress /absolut/sokvag/till/quotes.csv \
  --metadata /absolut/sokvag/till/quotes.metadata.json \
  --config "$WSE_WORK/wse-plan/research.config.json" \
  --model /absolut/sokvag/till/selected_model.json \
  --threshold 0.5 --out "$WSE_WORK/stress-only"
```

Byt exemplets `0.5` mot tröskeln i den faktiska frysta selection-filen.
`selected_model.json` kräver sitt hashmatchade `selection.json` i samma katalog.
Ändrade vikter, fel konfiguration eller fel tränings-/valideringsgränser kan
inte återanvända ett annat modellvals kvitto.

Kvittona skiljer på hämtning, native import, fitted modell, fryst selection och
kostnadsstress. `completed` betyder att det aktuella tekniska steget genomförts.
`training_ready`, `full_history_verified`, `replay_accepted`, `forward_verified`
och `trading_enabled` förblir `false`. Det återstår faktisk originalvalidering,
oberoende marknadsutvärdering och brokerdemo innan detta kan beskrivas som en
verifierad scalper.
