# Exportera marknadsticks från en befintlig MT5-terminal

`integrations/mt5/ExportResearchTicks.mq5` exporterar en symbol och `integrations/mt5/ExportResearchBasket.mq5` exporterar högst fem uttryckligen angivna symboler. Båda använder `integrations/mt5/ResearchTickExport.mqh` för att läsa ett uttryckligt tidsintervall med bid/ask-ticks och skriva forskningsunderlag. Det anropar inga order-, positions-, kontohistorik- eller prenumerationsfunktioner och sparar inga kontonummer eller inloggningsuppgifter. Terminalen kan själv synkronisera saknad tickhistorik från sin befintliga serveranslutning när `CopyTicksRange` anropas ([MetaQuotes: CopyTicks](https://www.mql5.com/en/docs/series/copyticks)).

**Koden är inte kompilerad eller körd i MT5 här.** MetaEditor och en MT5-terminal saknas i byggmiljön. Python-tester verifierar inte MQL5-syntax, terminalens historik, filkodning eller körbeteende. Kodens API-användning och spärrar har granskats mot de officiella källorna nedan; nästa faktiska kontroll är kompilering och en liten export i din terminal.

För brokeroberoende användning: kör ensymbolexporten på rätt diagram med tomt `InpSymbol`. Den läser då diagrammets exakta `_Symbol` även när brokern har egna suffix. Det är befintlig exportbindning, inte en färdig symbolidentifierare eller handelsrobot. [Guiden för brokeroberoende data](BROKER_INDEPENDENT_DATA_SV.md) beskriver den planerade metadataidentifieringen, terminalens manuella originalexport och hur daterade avgifts-/kontraktsvillkor hämtas.

## Kör exporten

1. Öppna terminalens **File → Open Data Folder**. Lägg `ExportResearchTicks.mq5`, `ExportResearchBasket.mq5` och `ResearchTickExport.mqh` tillsammans i `MQL5/Scripts/`. Öppna det skript du ska köra i MetaEditor. Kompilera och åtgärda eventuella fel innan körning; hjälpfunktionen behöver finnas bredvid skriptet.
2. Kontrollera att dataleverantörens villkor tillåter den avsedda exporten, lokala analysen och eventuell modellträning. Skriptet gör inga rättighetsanspråk.
3. Kör skriptet på ett diagram. Lämna `InpSymbol` tomt för diagrammets symbol eller ange terminalens exakta symbol, inklusive eventuellt suffix. Skriptet väljer eller prenumererar inte automatiskt på andra symboler.
4. Ange `InpFromUtcMsc` och `InpToUtcMsc` som heltal i **UTC-millisekunder sedan 1970-01-01**. Båda gränserna är inkluderande. Nollvärden och intervall längre än sju dygn avvisas. Använd inte en avläst mäklartid som om den vore UTC.

Det här fristående Python-exemplet räknar endast om två uttryckliga UTC-tider till millisekunder. Det ansluter inte till MT5:

```python
from datetime import datetime, timezone

epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
start = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)
end_exclusive = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)

def utc_ms(value):
    delta = value - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000

print("InpFromUtcMsc =", utc_ms(start))
print("InpToUtcMsc =", utc_ms(end_exclusive) - 1)
```

Välj ett intervall där den aktuella terminalen faktiskt har tillgänglig historik. Exemplens datum är inte ett påstående om att data finns.

## Resultat och fel

Varje körning reserverar en egen undermapp i `MQL5/Files/ResearchTicks/`. Tid i mappnamnet är endast en namnkomponent; marknadens klocka kommer från `MqlTick.time_msc`. Tidigare körningar skrivs inte över.

| Fil | Betydelse |
| --- | --- |
| `quotes.csv` | UTF-8, exakt rubrik `time_msc,bid,ask`, mottagna giltiga ticks i originalordning. |
| `metadata.started.json` | Startkvitto med `source_export_status: "in_progress"`. Ska inte importeras. |
| `metadata.json` | Slutrapport med `completed` eller `failed`. Använd endast `completed` tillsammans med terminalens motsvarande slutmeddelande. |
| `metadata.failed.json` | Reservrapport om slutrapporten inte kunde publiceras. Exporten har misslyckats. |
| `*.pending` | Ofullständigt eller opublicerat underlag; ska inte importeras. |
| `run.lock` | Bestående markering som hindrar att skriptet återanvänder körningens sökväg. |

Anropen gäller högst 15 minuter åt gången. En fast mottagningsbuffert rymmer högst 500 000 ticks per anrop, och högst 500 000 råa tickrader skrivs totalt. Gränsen eller en för liten buffert ger en misslyckad export med bevarat giltigt prefix; skriptet försöker inte igen med en annan begäran. Om gränsen nås innan det sista tidsfönstret har kontrollerats blir resultatet också `failed`.

`CopyTicksRange` har inkluderande gränser; nästa fönster börjar på föregående slut + 1 ms. Alla rader med samma millisekund bevaras. Ett negativt resultat eller ett positivt resultat med någon felkod, inklusive timeout och delvis synkroniserad historik, stoppar körningen. Ogiltiga/crossade priser, minskande klocka, tider utanför fönstret och skriv-, flush-, storleks- eller stängningsfel ger också `failed`. Vid tvångsavslut kan endast startkvittot finnas kvar. Saknas en giltig slutrapport är exporten inte komplett.

Priserna serialiseras från terminalens `double` med 17 signifikanta siffror. Skriptet avrundar inte efter `SYMBOL_DIGITS` och uppfinner inte fler klocksiffror. CSV innehåller bid/ask-marknadsobservationer; den beskriver inte traders beslut, affärer, fills eller exekverbar likviditet.

## Import och nästa steg

Kopiera hela körningsmappen till en arbetsplats utanför Git. Importera bara en avslutad export:

```bash
python -m scalper_research import-quotes /path/to/run/quotes.csv \
  --metadata /path/to/run/metadata.json \
  --out /path/to/research-import
```

Importören avvisar annan `source_export_status` än `completed`. En lyckad export bevisar inte att leverantören har levererat hela marknadshistoriken eller att rätten till modellträning är klar. Metadata lämnar `data_origin: "user_supplied_unverified"`, `usage_rights: "not_verified"`, `training_usage_rights: "not_verified"`, `training_ready: false` och `full_history_verified: false`.

`SYMBOL_CURRENCY_PROFIT` sparas som observerad vinstvaluta och som uttryckligen **overifierad kandidat** för `price_currency`; egenskapen garanterar inte prisets denominering för alla instrument. `SYMBOL_TRADE_CONTRACT_SIZE` och antalet decimalsiffror är terminalfakta. Kontrollera instrumentet och prisvalutan innan du skapar en separat analyskonfiguration med granskad `quantity`, `contract_multiplier`, `price_currency` och kostnadsantaganden. Dessa värden ska inte automatiskt bli exekveringsinstruktioner. Behåll originalfilerna och dokumentera eventuella rättighetspåståenden i separat granskad metadata.

Rader med identiska millisekunder kan importeras och arkiveras. De får kvalitetsflaggan `EQUAL_TIMESTAMP_ORDER_UNVERIFIED` och blockerar direkt replay och träning. Det befintliga kommandot `project-ticks` erbjuder en uttrycklig projektion till avslutade tidsgrupper; originalraderna och deras identiska native klockor bevaras i granskningsunderlaget. Projektionen förutsätter en virtuell händelseklocka, använder ingen senare grupps pris i en tidigare grupp och bevisar inte verklig feedtillgänglighet eller exekverbar likviditet. Följ [tickarbetsflödet](TICK_WORKFLOW_SV.md) för granskade parametrar och gapspärrar. Flytta inte native ticks till påhittade millisekunder. Exporten tränar ingen modell och lämnar verklig handel avstängd.

## Kör en explicit basket

Kör `ExportResearchBasket.mq5` med `InpSymbols` satt till 1–5 av terminalens exakta symbolnamn, separerade med kommatecken **utan mellanslag**. Tom lista, tomma element, dubbletter, fler än fem symboler eller symbolnamn längre än 64 tecken ger en misslyckad basket. Ett ofyllt `InpSymbols` använder ingen diagramsymbol. Skriptet översätter inga alias och väljer eller prenumererar inte på symboler.

Kontrollera därför terminalens exakta namn för EURUSD, XAUUSD, GBPJPY och EURJPY, inklusive suffix. För Nasdaq behöver du först identifiera själva produkten: Nasdaq-100-indexet, en specifik NQ/MNQ-future eller en mäklar-CFD är olika underlag. Basketen väljer inte produkt, expiry eller kontraktsstorlek åt dig.

`InpFromUtcMsc` och `InpToUtcMsc` har samma obligatoriska, inkluderande UTC-gränser som i ensymbolexporten. Gränserna är högst sju dygn och 500 000 råa ticks **per symbol**; basketen kan således skriva högst 2 500 000 råa rader. Den fasta mottagningsbufferten återanvänds mellan symbolerna. Radräknare, fel, klockor, filhandtag och terminalfakta nollställs inför varje symbol.

Ett vanligt symbolfel avslutar den symbolens export och låter nästa uttryckligen angivna symbol fortsätta. Ett uttryckligt användarstopp avbryter återstående exporter. Slutstatus för basketen är `completed` endast när alla begärda symboler har avslutats utan fel och basketens slutrapport har publicerats korrekt.

Basketen skriver en separat körningsmapp under `MQL5/Files/ResearchTickBaskets/`:

| Fil | Betydelse |
| --- | --- |
| `basket.started.json` | Startkvitto; basketen är inte avslutad. |
| `basket.asset_N.json` | Separat checkpoint efter ett symbolförsök; ingen slutrapport. |
| `basket.json` | Slutstatus och status, radantal, fel och sökväg för varje symbol. |
| `basket.failed.json` | Reservrapport om slutrapportens publicering misslyckades. |
| `*.pending`, `run.lock` | Ofärdiga filer respektive bestående körningsreservation. |

Varje symbols CSV och metadata ligger fortfarande i en egen mapp under `MQL5/Files/ResearchTicks/`. `asset_output_directory` och `asset_metadata` i basketrapporten anger dessa sökvägar relativt `MQL5/Files`. Kopiera basketrapporten och samtliga refererade symbolmappar för att behålla underlaget. Importera varje symbols CSV med dess egen avslutade metadata. En symbol med `completed` kan granskas separat även om en annan symbol gjorde att basketens sammanlagda status blev `failed`.

## Aktuella terminalfakta

Efter lyckad läsning av grundfakta innehåller slutmetadata för båda skripten dessutom ett aktuellt symbol-snapshot under `terminal_facts`:

| Fält | Native egenskap |
| --- | --- |
| `trade_tick_size` | `SYMBOL_TRADE_TICK_SIZE` |
| `trade_tick_value_profit`, `trade_tick_value_loss` | Motsvarande native tick-värden |
| `trade_calc_mode` | `SYMBOL_TRADE_CALC_MODE`, sparat som enum-heltal |
| `volume_min`, `volume_max`, `volume_step` | Terminalens aktuella volymgränser och steg |
| `base_currency`, `profit_currency`, `margin_currency` | Respektive symbolvaluta |
| `digits`, `trade_contract_size` | Samma obligatoriska fakta som tidigare |

De nya extraegenskaperna är valfria: misslyckad läsning, ogiltiga tal eller otillgängliga värden blir `null`. Noll för en positiv storleks-/värdeegenskap räknas som otillgängligt, inte som en granskad nollkostnad. Det ändrar inte ensymbolexportens befintliga krav på giltiga decimalsiffror, vinstvaluta och kontraktsstorlek.

Snapshotet bevisar inte vilka villkor som gällde under det exporterade historiska intervallet. Tick-värdenas valuta, mängdens enhet, kostnader, sessionskalender och historiska kontraktsändringar behöver fortfarande dokumenteras separat. Skriptet läser inte kontots valuta, räknar inte om PnL och antar ingen lotstorlek. `quantity_unit_verified` och `tick_value_currency_verified` förblir `false`.

Exporten är uttryckligen **quote-only**. `last`, `volume`, `volume_real`, `flags` och native `time` skrivs inte till någon sidecar; `native_sidecar_exported` är `false`. `COPY_TICKS_ALL` väljer native rader, men det innebär inte att dessa utelämnade fält finns i forskningsfilen. Underlaget räcker inte för att verifiera orderflow, aggressorsida, egna fills eller Fabio/Sivas affärshistorik.

## Primärkällor

- [CopyTicksRange](https://www.mql5.com/en/docs/series/copyticksrange): ursprunglig ordning, inkluderande epoch-ms, buffertgräns och delresultat med fel.
- [MetaQuotes om MT5-ticks i UTC](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py): klockbevis; Python-exemplet på källsidan används inte för någon terminalanslutning här.
- [MqlTick](https://www.mql5.com/en/docs/constants/structures/mqltick): native `time_msc`, bid och ask.
- [StringSplit](https://www.mql5.com/en/docs/strings/stringsplit): explicit kommaseparerad symbolista och returvärden.
- [Symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants): vinstvaluta, kontraktsstorlek och decimalsiffror.
- [FileOpen](https://www.mql5.com/en/docs/files/fileopen), [filflaggor](https://www.mql5.com/en/docs/constants/io_constants/fileflags), [FileWrite](https://www.mql5.com/en/docs/files/filewrite), [FileWriteString](https://www.mql5.com/en/docs/files/filewritestring), [FileMove](https://www.mql5.com/en/docs/files/filemove): lokal filsandbox, uttrycklig UTF-8, CSV-radslut, bytekontroll och publicering utan överskrivningsflagga.
- [PrintFormat](https://www.mql5.com/en/docs/common/printformat): `g`-formatets signifikanta siffror och heltalsformat.
