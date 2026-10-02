# Brokeroberoende instrument och originalunderlag

Kravet är en gemensam strategi- och riskkärna för EURUSD, Nasdaq, XAUUSD, GBPJPY och EURJPY. Broker- och plattformsspecifika symboler, mängdenheter och exekveringsregler ska hanteras av adaptrar. Utvecklingen kräver inget permanent brokerval. Detta dokument anger arkitekturkravet och hur underlagen kan hämtas; automatisk symbolidentifiering och en exekverande robot är ännu inte byggda.

## Bindning till rätt instrument

Den redan skrivna MT5-ensymbolexporten använder `_Symbol` från aktuellt diagram när `InpSymbol` lämnas tomt. Det fungerar på källkodsnivå oavsett brokerns suffix. Skriptet måste fortfarande kompileras och provköras i en faktisk terminal. Basketexporten kräver däremot exakta namn och översätter inga alias.

Den fortsatta robotadaptern ska erbjuda diagrammets symbol, metadataidentifiering och ett uttryckligt symbolval. Identifiering ska kontrollera beskrivning/underliggande, produkttyp, valuta, kontraktsstorlek, tickstorlek, volymsteg, sessioner och eventuell löptid. Symbolnamn är kandidater, inte ensamma bevis. Om flera produkter passar ska användaren kunna välja rätt diagram eller uttryckligt kontrakt. Bindningen får inte bli en handelsorder.

Nasdaq behöver först definieras som önskad index-/produktfamilj: exempelvis Nasdaq-100. Ett indexpris, en broker-CFD och ett bestämt NQ-/MNQ-kontrakt får inte behandlas som samma exekverbara instrument. Samma princip gäller XAUUSD jämfört med andra guldprodukter. Inga universella lotstorlekar, tickvärden eller prisvalutor antas. Specifikationer ska kontrolleras igen vid ny anslutning och relevanta kontraktsändringar innan framtida exekvering.

Data från flera brokers får användas som separata, dokumenterade källor. Det exakta källsymbolnamnet bevaras även när strategin använder en gemensam instrumentfamilj. En flyttbar kärna bevisar inte att samma modell fungerar på alla feeds; senare utvärdering måste täcka skillnader i kvotering, spread, sessioner och utförande.

## Hämta tickoriginal i MT5

**Manuell native export:** öppna Market Watch, högerklicka och välj **Symbols**. Välj instrument, öppna fliken **Ticks**, ange period och välj **Request**, sedan **Export**. Spara CSV oförändrad med symbol, begärd period, exportdatum och uppgift om server/datakälla i separat dokumentation. Servern bestämmer vilken historik som finns. Den vanliga Market Watch-flikens lilla tickdiagram är inte en full historikexport.

Den manuella tickfilen kan innehålla bid, ask, last, volym och flaggor. Faktiska fält, klockprecision och tidsbasis ska granskas innan konvertering till forskningsformat. Filen ska först arkiveras med bytehash; den får inte öppnas och sparas om i ett kalkylblad som ändrar tider eller priser. Den nuvarande kanoniska importen är inte en automatiskt verifierad läsare för varje variant av MT5:s manuella CSV.

**Projektets exportskript:** följ [MT5-guiden](MT5_EXPORT_SV.md). Kör på rätt diagram med tomt `InpSymbol`, börja med ett litet intervall, och kopiera hela avslutade körningsmappen från `MQL5/Files/ResearchTicks/`. Den innehåller `quotes.csv` och `metadata.json`. Gränserna är högst sju dygn och 500 000 råa rader per symbol; använd mindre perioder om gränsen nås. Endast `source_export_status: completed` kan importeras. Skriptets fil är uttryckligen bid/ask, inte en full native export av last/volym/flaggor och inte egna eller namngivna traders fills.

Källans användningsvillkor gäller även vid export från en befintlig terminal. Inloggning eller att data kan visas innebär inte automatiskt rätt att träna eller återpublicera den. Originaldata ska förvaras utanför Git. En begärd period eller avslutad export bevisar inte komplett historisk täckning.

## Hämta kontrakt och avgifter

| Underlag | Var det hämtas | Vad det styrker |
| --- | --- | --- |
| Aktuell produktspecifikation | Market Watch → högerklicka symbolen → **Specification**. Spara uppgifterna med observationsdatum, symbol, server och relevant kontotyp. | Dagens storleks-, pris-, volym-, sessions- och tillgängliga avgiftsuppgifter. Exportskriptet sparar redan vissa aktuella symbolfakta, med overifierad historisk giltighet. |
| Faktiskt debiterade kostnader | Välj relevant period i **History**, högerklicka → **Report** och spara originalrapporten. Brokerportalen kan också ha daterade avräkningar. | Utförda affärer och redovisade kostnader för de affärer och det konto som rapporten täcker. Det bevisar inte avgiften för alla hypotetiska affärer. |
| Historisk tariff och kontraktsvillkor | Brokerns daterade prislistor, kontraktsblad, ändringsmeddelanden och skriftliga supportunderlag. | Vilka regler som gällde för en viss produkt och kontotyp under varje angiven period. |

MT5-specifikationen kan visa provisionsregler. Projektets MQL-exportör läser **inte** provisionstabellen, historiska tariffändringar eller kontohistorik. Ingen automatisk kontorapportimport finns i detta ticksteg. En tom avgiftsuppgift ska förbli okänd; den betyder inte noll.

Kontorapporter kan innehålla kontonummer och namn. Behåll originalet privat och använd en separat maskerad kopia vid delning. Tickklocka och rapportens affärsklocka ska granskas var för sig. Verkliga spreadar hämtas från matchande bid/ask-data; slippage kan inte fastställas ur en prislista och behöver senare separat utförandeunderlag.

En begäran som användaren kan skicka till varje aktuell broker:

> Jag behöver daterade historiska kontraktsspecifikationer och avgiftstabeller för [symboler], [kontotyp] och [datumperiod]. Ange giltig-från/giltig-till, kontraktsstorlek och volymenhet, tickstorlek, tickvärdets valuta/beräkningsgrund, volymgränser, sessioner och relevanta kontraktsändringar. För provision: belopp eller tariff, valuta, per lot eller affär, entry/exit eller round turn, eventuella nivåer/minimiavgifter och debiteringstidpunkt. Bifoga historiska swap-/finansieringsregler, övriga avgifter och ändringsmeddelanden som gäller perioden.

Detta är en text att skicka, inte ett meddelande som projektet har skickat. Om daterade villkor saknas kan kostnadsscenarier användas i tidig forskning, tydligt märkta som antaganden. De får inte redovisas som verifierade historiska nettovinster. Aktuella snapshots kan sparas framåt; de återskapar inte äldre villkor.

## Första användbara leverans

Börja med en tillåten liten tickexport från varje instruments rätta diagram samt tillhörande aktuell specifikation. Bifoga tillgängliga daterade historiska villkor för den period som sedan ska utvärderas. Källidentitet dokumenteras för spårbarhet och kostnadsgranskning; kärnan binds inte permanent till den brokern. Lösenord och API-nycklar behövs inte för filgranskningen.

Det lokala införsel-/kontrollflödet är byggt. Inga originaltickarkiv har tillförts i detta ändringssteg och ingen verklig marknadsmodell har tränats. MT5-skripten är fortfarande okompilerade och terminal-otestade här. Sammanhängande träning över hela tickkorpusen och automatisk runtime-bindning återstår. Verklig handel är avstängd.

## Officiella källor, kontrollerade 2026-10-02

- [MetaTrader 5: symbolhantering, historikexport och Specification](https://www.metatrader5.com/en/terminal/help/trading/market_watch)
- [MetaTrader 5: History-rapport, orders, deals och kostnader](https://www.metatrader5.com/en/terminal/help/trading_advanced/history_report)
- [MQL5: symboluppgifter](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants)
- [MQL5: CopyTicksRange](https://www.mql5.com/en/docs/series/copyticksrange)
