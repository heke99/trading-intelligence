# Scalper: sammanhängande offlineflöde v0.4

Kod för import, tidsordnad träning, fryst utvärdering och beständig simulering är
byggd. Provkörningen använder **påhittade priser**. Komplett historik för Fabio
Valentini och Sivakumar Jayachandran, verifierad marknadsträning och brokerdemo
är ännu inte genomförda. Det finns ingen orderkoppling till en broker.

## Vad varje steg faktiskt gör

| Steg | Implementerat | Bevis som återstår |
|---|---|---|
| Traderhistorik | Befintliga läsande C2/publisher-importer bevarar källor och revisioner | Kompletta personliga fills, omfattning, klockor och beslut för de två traderna |
| Marknadsimport | UTC-ms CSV med bid/ask; lokal BI5 med uttrycklig skala och tidsbas | Tillåtet originaldataset, rätt instrument, sammanhängande täckning |
| Strategi | Egen rolling-breakout-hypotes; datakrav för namngivna traders visas separat | Objektiva versionsbundna regler och beslutslabels för imitation |
| Inlärning | Deterministisk logistisk regression på avslutade development-utfall | Verifierade marknadsdata och träning på rätt marknad |
| Validering | Fem förregistrerade trösklar utvärderas genom full replay | Robusthet över marknadsregimer och kostnadsantaganden |
| Test | Vald fryst modell testas efter valideringsvalet; ingen omträning | Oanvänd marknadsperiod och dokumenterade acceptanskriterier |
| Lokal paper | Fryst modell, SQLite, omstart, väntande fills och beständigt stopp | Brokerdemo, orderbekräftelser och verklig forward-observation |

En genomförd syntetisk provkörning är ett funktionstest. `training_ready`,
`full_history_verified`, `replay_accepted`, `forward_verified` och
`trading_enabled` förblir `false`.

## Kör hela funktionstestet

Python 3.11 eller senare; runtime använder standardbiblioteket.

```bash
python -m scalper_research all-demo --out ../scalper-all-demo
python -m scalper_research learning-status --out ../scalper-all-demo/learning
python -m scalper_research paper-status --out ../scalper-all-demo/paper
python -m scalper_research strategy-audit
```

`all-demo` kräver en ny utdatakatalog. Tre fiktiva handelssessioner skapas, där
development, validation och test ligger på olika dagar. Den tredje dagens redan
historiska testquotes matas även genom en lokal append-fil efter modellens
tränings-/valideringsgräns. Detta är ingen ny oberoende testperiod eller faktisk
forwardhandel. Efter stopp och senare quotes är simuleringen stängd utan
väntande order. Kvitton innehåller alla falska handels- och evidensflaggor.

## Träna på ett tillåtet originaldataset

```bash
python -m scalper_research import-quotes private/quotes.csv \
  --metadata private/market.json --out ../research
python -m scalper_research learn private/quotes.csv \
  --metadata private/market.json --config private/config.json --out ../research
```

CSV kräver `time_msc,bid,ask`: positiv bid/ask, ask minst bid och verifierbar
UTC-epoch i millisekunder. Den tidigare replay-guiden beskriver komplett metadata
och konfigurationsformat. Symbol, prisvaluta och instrumentenheter måste matcha
execution-config. Samma tidsstämpel i flera rader bevaras vid import, men blockerar
den här replayn eftersom ordningen inom millisekunden inte är styrkt. Ticks får
inte sorteras eller aggregeras för att dölja detta.

För `user_supplied_unverified` behövs både `usage_rights` och separat
`training_usage_rights` med värdet `user_asserted_permitted`, samt dokumenterad
`rights_evidence` respektive `training_rights_evidence`. Dessa är användarens
påståenden; programmet verifierar inte en licens. Öppen webbåtkomst eller rätt att
backtesta räcker inte i sig till ett verifierat träningsunderlag.

### Labels och features

Labels är **hypotetiska avslut från den egna baslinjestrategin efter konfigurerade
kostnader**. De är inte Fabios eller Sivakumars beslut. Endast avslut strikt före
development-gränsen, utan quality-flaggor, får en label. Öppna positioner,
väntande entries och gap får inga påhittade avslut. Vinst över noll ger label 1;
noll och förlust ger label 0. Underlaget är villkorat på baslinjens positions-
och riskstatus; det täcker inte alla möjliga handelsbeslut.

Featureordningen är side, spread/stop, breakout/stop, channel/stop,
signed-momentum/stop och volatility/stop. De beräknas från aktuell quote och
tidigare quotes innan den aktuella läggs till historiken. Fast klippning vid ±20
används; ingen skalning anpassas till framtida data.

Optimisering: 500 full-batch-epoker, learning rate 0,05, L2 0,01 och nollstart.
Minst 20 labels och fem av varje klass krävs. Högst 10 000 labels accepteras.
Detta är tekniska spärrar och säger inget om statistisk tillräcklighet.

### Valideringsval och fryst test

Trösklarna 0,0 / 0,4 / 0,5 / 0,6 / 0,7 är fasta innan fitting. Varje tröskel får
en egen fullständig validation-replay; gamla baslinjetrades filtreras inte ihop
till ett falskt resultat. Minst fem avslut, inga öppna positioner, inga gap och
ingen riskhalt krävs för teknisk kandidatur. Störst ending net equity väljs;
lika utfall väljer högre tröskel. Detta är ett forskningsval, inte acceptans för
handel. Ett explicit reject-all-filter finns i modellen som kontroll vid tröskel
1, men deltar inte i den förregistrerade tröskelrankingen.

Modellvikter lärs endast på development. `development_model.json` behålls
oförändrad. `selected_model.json` innehåller samma vikter och extra metadata som
binder tröskelvalet till `selection.json`. Den sparas före testresultaten beräknas.
Framtida bytes ingår i originalfilens audithash; om de ändras kan modellens
audithash därför ändras även när development-labels och lärda vikter är identiska.
Extern insyn i testperioden upptäcks inte automatiskt. Upprepad testanvändning
måste därför redovisas separat.

## Lokal BI5-konvertering

```bash
python -m scalper_research convert-bi5 private/ticks.bi5 \
  --spec private/bi5-spec.json --out ../converted
```

Specen kräver schema_version 1, format `dukascopy_bi5_20byte_be`,
`time_base` (`utc_hour` eller `utc_day`), periodjusterad `base_time_msc`,
`price_divisor` som tiopotens, `price_scale_evidence` och komplett
`source_metadata`. Varje 20-byte-record är big-endian offset/ask/bid/ask-volume/
bid-volume. Filnamn bestämmer inte tidsbas eller skala. Volymen bevaras som
källbevis, och används inte som verifierad tillgänglig likviditet.

Äldre Dukascopy-filer var timbaserade; den aktuella officiella
[exportdokumentationen](https://www.dukascopy.com/wiki/en/development/data-export/)
beskriver dagsbaserade filer, AWS-autentisering och requester-pays. Villkor och
träningstillstånd måste prövas för den valda åtkomstvägen. Adaptern hämtar inga
filer och dess `training_rights=not_verified` ger inte något nytt tillstånd.
Separata dokumenterade källpåståenden kan finnas i metadata men är fortfarande
inte oberoende verifierade.

Input är begränsad till 32 MiB, dekomprimerat BI5 till 10 MiB/500 000 records och
LZMA-minne till 64 MiB. CSV/replay accepterar högst 500 000 quotes. Detta är en
begränsad prototyp; den är inte lagring eller streaming för alla fleråriga ticks.

## Beständig filsimulering

```bash
python -m scalper_research paper-start private/appended-quotes.csv \
  --metadata private/market.json --config private/config.json \
  --model ../research/learning-runs/RUN/selected_model.json --threshold 0.4 \
  --out ../paper
python -m scalper_research paper-step --out ../paper
python -m scalper_research paper-stop --out ../paper
python -m scalper_research paper-status --out ../paper
```

Modell/tröskel är valfria; utan dem används baslinjen. Den faktiska valda
tröskeln hämtas ur learning-kvittot, inte från exemplet ovan. Modellen får inte
användas på quotes före sin fit-gräns; en validation-vald tröskel kräver quotes
efter validation-gränsen. Modell, config, metadata och eventuell selection-fil
binds till ursprungliga bytes och hash. Ändrade vikter får inte återanvända en
annan modells valideringsreceipt.

SQLite schema 2 sparar accepterat komplett CSV-prefix, cursor, rapport och
kontroller i en transaktion. Endast rader med avslutande newline accepteras;
en ännu inte accepterad ofullständig tail kan ändras. Redan accepterat prefix
får aldrig skrivas om eller kortas. Varje steg återskapar hela prefixet genom
samma frysta strategi, väntande beslut och samma sessionsriskbudget.
Det prioriterar omstartskorrekthet och är inte en lågfördröjd brokerloop.

Stopp sparas omedelbart och är beständigt. Det kan avbryta en väntande entry
före fill. En redan öppen position kräver en senare quote som observerar stoppet
och ytterligare en quote efter konfigurerad latency för hypotetisk exit. Ett
stopp utan nya quotes innebär inte att positionen är stängd. Rapporten visar
detta uttryckligen. `model_used` och `model_fit_previously` betyder att en fryst
modell användes; `training_performed_in_session=false` betyder ingen omträning.

## Rätt strategi behöver rätt historik

`strategy-audit` redovisar datakrav och regelgap för de två traderna. Fabios
publicerade metod använder futures, balans, volymprofil/LVN och orderflow.
Sivakumars olika undervisningsversioner använder bland annat optioner, OI och
volym/candles. En EURUSD-bid/ask-hypotes återskapar inte dessa. Marknadsrecaps,
kursmaterial, tävlingsresultat och kompletta personliga fills är separata
evidenstyper. En strategi kan först prövas som korrekt implementerad när dess
regelversion, instrument, beslutsinformation och förväntade handlingar går att
jämföra; lönsamhet behöver dessutom oberoende utvärdering.

En öppen kandidat är [WSELOB-2017](https://data.mendeley.com/datasets/3g4mhdp899/1),
Adam Marszałek, DOI 10.17632/3g4mhdp899.1, CC BY 4.0. Den omfattar 2017 års
orderböcker/trades för fem Warszawaaktier i HDF5. Originalfilerna är större än
nuvarande inputgräns och ligger inte i denna leverans. De kräver separat adapter,
verifierad tids-/eventsemantik och attribution; de är inte tradernas personliga
historik eller samma marknad som futures-/optionsstrategierna ovan.

Nästa faktiska evidenssteg är tillåten originalhistorik med verifierbara klockor,
instrument och kostnader. Därefter körs fryst marknadstest och kostnadsstress,
följt av brokerdemo med avstämda orderbekräftelser och observation över tid.
