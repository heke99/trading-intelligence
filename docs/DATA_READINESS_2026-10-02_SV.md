# Verklig databeredskap – 2026-10-02

Det nya byggsteget är lokal införsel av större tickfiler. **Inga nya originalarkiv med marknadsticks och inga nya kompletta Fabio-/Siva-fillutdrag har införskaffats.** Kod och fiktiva testsiffror är inte evidens för att roboten lärt sig scalpa verkliga marknader.

**Arkitekturkrav: brokeroberoende kärna.** Ingen fast broker behöver väljas för att fortsätta utvecklingen. Instrumentet ska bindas via aktuellt diagram eller granskade symboluppgifter; exakta symboler och kontraktsvillkor hör till respektive adapter och datakälla. Ensymbolexporten i MT5 använder redan diagrammets `_Symbol` när `InpSymbol` är tomt. Automatisk symbolidentifiering och en exekverande robot är ännu inte implementerade. Se [brokeroberoende bindning och hur underlagen hämtas](BROKER_INDEPENDENT_DATA_SV.md).

## Fem efterfrågade marknader

| Marknad | Vad som fortfarande saknas för första verkliga körning |
|---|---|
| EURUSD | Tillåten originalfil, käll-/brokeridentitet, tidsbasis och kostnads-/kontraktsunderlag |
| Nasdaq | Exakt produkt: broker-CFD, NQ/MNQ-kontrakt eller index; därefter matchande original och historiska specifikationer |
| XAUUSD | Tillåten originalfil och brokerproduktens kvotering, storleksenhet och historiska kontrakts-/avgiftsvillkor |
| GBPJPY | Tillåten originalfil, historiska kontrakts-/avgiftsvillkor och korrekt JPY-basis |
| EURJPY | Tillåten originalfil, historiska kontrakts-/avgiftsvillkor och korrekt JPY-basis |

En första provfil per marknad räcker för formatsäkring. För träning krävs därefter en **fördeklarerad period** med dokumenterad kvalitet och ett senare orört testintervall. Antal år eller många tickrader är inte i sig ett tillräcklighetskriterium. JPY- och USD-resultat ska hållas isär utan dokumenterad valutakonvertering.

[Tidigare källgranskning](TICK_SOURCE_AUDIT_SV.md) och [exekveringschecklista](TICK_EXECUTION_EVIDENCE_SV.md) gäller fortsatt. HistData, FXCM, Exness och Dukascopy är dokumenterade kandidater, inte godkända dataset. Exness aktuella hjälptext leder till inloggad Personal Area; Dukascopys villkor kräver skriftligt tillstånd för automatiserad åtkomst. Kontoinloggning, köp, begäran om nya behörigheter eller användning av privata credentials har inte genomförts. Tidigare nekade/blockerade rådataflöden har inte återförsökts eller kringgåtts. Läsbar webb-/sökdokumentation är inte mottagna råarkiv.

Primärkällor återkontrollerade i detta steg:

- https://get.exness.help/hc/en-us/articles/360021547851-Tick-history
- https://www.dukascopy.com/swiss/english/legal-pages/terms-of-use/
- https://www.histdata.com/f-a-q/

## Traders: planer är inte deras utförda affärer

Den tidigare sparade strategigranskningen innehåller 12 separata dokumentversioner och 65 regelatomer, inte 12 körbara strategier. Originalhistorik som redan importerats från andra publicerare blir inte Fabio-/Siva-fills. Tidigare sparade rapporter har kontrollerats; det nya steget ersätter inte deras observationer och gör inget nytt fullständighetsanspråk.

Fabios nuvarande publicerarsida beskriver futures-scalping med trend- och återgångsmodeller, profilnivåer och orderflödesbekräftelse. Den anger New York respektive London som olika modellkontexter. Det finns kvalitativa villkor som inte är objektiva algoritmtrösklar. Två schematiska exempel är inte en daterad, fullständig brokerjournal. Dessa undervisningsuppgifter får inte generaliseras till en påstådd edge på alla fem marknader.

Källa: https://www.tradezella.com/strategies/auction-market-strategy

Sivakumar Jayachandrans undervisningsdeck anger 26 juli 2022 och 3-/5-minutersmodeller för indiska indexfutures/-optioner. Föreläsningsdatum och klockslag är inte tidpunkter för hans affärer. Det läsbara PDF-textindexet har en olöst konflikt: sidan med shortrubrik upprepar long-villkor. Ingen invers shortregel har gissats. Originalets visuella verifiering är fortfarande inte färdig, och någon låst källa eller alternativ rååtkomstväg har inte använts.

Källa: https://www.moneycontrol.com/premarket/pdf/webinars/optionOmega/Session07_Sivakumar.pdf

Användarens stavning ”Shukmar Jay Chandran” är inte ett verifierat alias. Det tidigare sammanhanget pekar på OI Pulse-tradern Sivakumar Jayachandran; det är en arbetsidentifiering, inte bevis för namnekvivalens.

För expertimitation behövs attribution, kompletta order-/fill-/partialutdrag, kontrakt och alla kostnader, verifierad tidszon, versionsbundna beslut och de historiska marknadsfält som fanns vid respektive beslut. Fabios orderflödesvillkor behöver riktiga affärs-/volymfält; Sivas villkor behöver bland annat historisk OI och specifika optioner. Enbart bid/ask ersätter inte dessa. Privata loggar eller proprietära indikatorformler kan inte rekonstrueras till fakta ur intervjuer.

## Kvarvarande bygg- och evidensgrindar

1. Bind varje önskad instrumentfamilj till diagrammet eller granskad produktmetadata från valfri datakälla. Dokumentera den faktiska produkten, särskilt för Nasdaq, utan att låsa kärnan till en broker. Dagens produktlista bevisar inte historiska villkor.
2. Ta emot tillåtna original och dokumentera hur de erhölls, tidsbasis, rättigheter samt käll-/bytehash. Ingen lösenords- eller nyckeluppladdning behövs.
3. Kör lokal formatkontroll, uppdelning och integritetsverifiering. Stäm av faktiska perioder, överlapp och luckor mot historisk sessionskalender och leverantörens täckning.
4. Lås produktspecifik kostnadsmodell, dataperioder, reset-/purge-/holdoutregler och kriterier innan modellval. Att flytta sluttestet efter resultat är inte ett nytt oberoende test.
5. Bygg och verifiera sammanhängande streamingträning över flera delar. Den här införseln implementerar inte det; separata shard-körningar får inte räknas som en sådan träning.
6. Jämför oberoende basmodell och eventuell expertmodell under samma fördeklarerade kostnader. Därefter fryst kostnadsstress, skuggkörning och separat demo-verifiering.

MT5-exporten är fortfarande källgranskad men inte kompilerad eller provkörd i en terminal. Inga verkliga brokerorders har skickats. Alla beredskapsgrindar för verklig träning/handel är kvar på falskt.

Första externa underlaget är **en tillåten originalexport per marknad med källmetadata**, samt tillgängliga daterade kostnads-/kontraktsvillkor. En MT5-export från rätt diagram kan fånga det exakta symbolnamnet; det behöver inte anges separat i förväg. Datakällans identitet behövs för spårbarhet och produktgranskning, inte som en permanent brokerlåsning. Om målet uttryckligen är att imitera Fabio/Siva behövs även ett legitimt fillutdrag från dem. Deras privata historik är inte ett krav för att undersöka en oberoende quote-strategi, men är ett krav för att kalla den tränad på deras utförda affärer.
