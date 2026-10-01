# Exportera marknadsticks från en befintlig MT5-terminal

`integrations/mt5/ExportResearchTicks.mq5` är ett skript för att läsa ett uttryckligt tidsintervall med bid/ask-ticks och skriva forskningsunderlag. Det anropar inga order-, positions-, kontohistorik- eller prenumerationsfunktioner och sparar inga kontonummer eller inloggningsuppgifter. Terminalen kan själv synkronisera saknad tickhistorik från sin befintliga serveranslutning när `CopyTicksRange` anropas ([MetaQuotes: CopyTicks](https://www.mql5.com/en/docs/series/copyticks)).

**Koden är inte kompilerad eller körd i MT5 här.** MetaEditor och en MT5-terminal saknas i byggmiljön. Python-tester verifierar inte MQL5-syntax, terminalens historik, filkodning eller körbeteende. Kodens API-användning och spärrar har granskats mot de officiella källorna nedan; nästa faktiska kontroll är kompilering och en liten export i din terminal.

## Kör exporten

1. Öppna terminalens **File → Open Data Folder**. Lägg skriptet i `MQL5/Scripts/ExportResearchTicks.mq5` och öppna det i MetaEditor. Kompilera och åtgärda eventuella fel innan körning.
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

Rader med identiska millisekunder kan importeras och arkiveras. De får kvalitetsflaggan `EQUAL_TIMESTAMP_ORDER_UNVERIFIED` och blockerar nuvarande replay/träningssteg tills en uttrycklig, granskad tidsprojektion finns. Flytta inte ticks till påhittade millisekunder för att få dem godkända. Exporten lämnar robotens träning och verkliga handel avstängda.

## Primärkällor

- [CopyTicksRange](https://www.mql5.com/en/docs/series/copyticksrange): ursprunglig ordning, inkluderande epoch-ms, buffertgräns och delresultat med fel.
- [MetaQuotes om MT5-ticks i UTC](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py): klockbevis; Python-exemplet på källsidan används inte för någon terminalanslutning här.
- [MqlTick](https://www.mql5.com/en/docs/constants/structures/mqltick): native `time_msc`, bid och ask.
- [Symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants): vinstvaluta, kontraktsstorlek och decimalsiffror.
- [FileOpen](https://www.mql5.com/en/docs/files/fileopen), [filflaggor](https://www.mql5.com/en/docs/constants/io_constants/fileflags), [FileWrite](https://www.mql5.com/en/docs/files/filewrite), [FileWriteString](https://www.mql5.com/en/docs/files/filewritestring), [FileMove](https://www.mql5.com/en/docs/files/filemove): lokal filsandbox, uttrycklig UTF-8, CSV-radslut, bytekontroll och publicering utan överskrivningsflagga.
- [PrintFormat](https://www.mql5.com/en/docs/common/printformat): `g`-formatets signifikanta siffror och heltalsformat.
