# Granskning av tickkällor, 2026-10-01

EURUSD, GBPJPY, EURJPY, XAUUSD och Nasdaq har undersökts i leverantörernas egna källor. HistData annonserar alla fem som gratis webbarkiv. Ingen källa har ännu både verifierad aktuell anonym filåtkomst, klarlagda användningsvillkor för den avsedda träningen och provlästa råfiler för alla fem.

**Förvärvad historik: 0 tickarkiv och 0 verifierade tickrader.** Källgranskningen är dokumentläsning. Huvudagentens enda katalogbegäran slutade med NETWORK_BLOCKED_OR_UNAVAILABLE och 0 mottagna byte. Inga binärarkiv begärdes eller införskaffades. Den läsbara dokumentationen är källfakta, inte marknadsdata. Modellen har inte tränats på dessa kandidatdata.

## HistData: starkaste annonserade kandidaten för alla fem

| Behov | Leverantörens beteckning | Vad som är belagt |
|---|---|---|
| EURUSD | EUR/USD | Annonserad valutahistorik |
| GBPJPY | GBP/JPY | Annonserad valutahistorik |
| EURJPY | EUR/JPY | Annonserad valutahistorik |
| XAUUSD | XAU/USD | Annonserade guldkvoter i USD |
| Nasdaq | NSX/USD | Nasdaq 100 i USD; kontraktstyp inte verifierad |

[HistDatas startsida](https://www.histdata.com/) listar instrumenten och kostnadsfri webbnedladdning. Nasdaq-beteckningen bevisar inte CME NQ-futures eller Nasdaq Composite. Exakta aktuella år/månader, filadresser, storlekar och kontrollsummor har inte verifierats.

Välj **Generic ASCII → Tick Data**, eftersom MetaTrader-alternativet är minutdata och NinjaTrader Tick bygger sekundstaplar. [Detaljspecifikationen](https://www.histdata.com/f-a-q/data-files-detailed-specification/) visar CSV i ZIP, exempelvis `DAT_ASCII_EURUSD_T_201202.csv`, med fyra kommaavskilda fält utan visad rubrik: `YYYYMMDD HHMMSSmmm,Bid,Ask,Volume`. Tre slutsiffror anger millisekunder. Decimalpriserna ska bevaras; ingen prisfaktor behöver gissas.

[FAQ](https://www.histdata.com/f-a-q/) anger **fast EST utan sommartid**, alltså UTC−05:00 hela året. Konvertering är alltid +5 timmar, även i juli. Tidszonen `America/New_York` med DST vore fel. Volymuppgifter har tagits bort; det fjärde råfältet är ingen verifierad handelsvolym eller exekvering.

Leverantören bjuder in till eget bruk och backtesting, men någon uttrycklig öppen licens för rådata, generell bulkautomation eller kommersiell ML/vidaredistribution har inte kunnat fastställas. Det är en oklar rättighetsfråga, inte bevis för att vanlig nedladdning är förbjuden. [Webbflödet](https://www.histdata.com/download-free-forex-historical-data/) är gratis; snabbare FTP/SFTP är en separat betaltjänst.

Den lokala konverteraren i `scalper_research/histdata.py` kan granska en redan lagligt införskaffad, uppackad CSV. Den gör inga nätanrop och ger inget automatiskt tillstånd att hämta eller träna. Replay och modellträning har separata, uttryckliga användningsassertioner. Filkonvertering verifierar varken rättigheter, full historik eller träningsberedskap.

## FXCM: tre relevanta FX-par, motstridigt aktuellt åtkomstbesked

Det officiella [TickData-README](https://github.com/fxcm/MarketData/blob/master/TickData/README.md), ändrat 2023-01-03, listar EURUSD, GBPJPY och EURJPY samt 2019–2023. Det listar inte XAUUSD eller Nasdaq. Dokumenterad filmall är `https://tickdata.fxcorporate.com/{instrument}/{year}/{week}.csv.gz`, med EURUSD/2022/1 som uttryckligt exempel. Tiden är UTC; data anges som indikativa och för personligt bruk under EULA. Leverantören publicerar nedladdningsskript för detta äldre flöde.

Den aktuella [huvud-README:n](https://github.com/fxcm/MarketData) hänvisar samtidigt tickförfrågningar till FXCM. [EULA-sidan](https://www.fxcm.com/uk/forms/eula/) leder till en signeringsblankett. Nuvarande anonym arkivåtkomst och ML-rättigheter är därför inte fastställda. CSV-rubrik, fältordning, faktisk klockprecision och senaste period måste provläsas från en legitim fil; skriptets filmall bevisar inte dessa egenskaper. En eventuell programvarulicens ger inte automatiskt rådata-rättigheter.

## Exness: bred annonserad täckning, anonym åtkomst inte verifierad

Den offentliga [ticksidan](https://www.exness.com/tick-history/) annonserar ZIP-arkiv med bid/ask. [Hjälptexten](https://get.exness.help/hc/en-us/articles/360021547851-Tick-history), uppdaterad 2026-09-30, beskriver alla handelsinstrument men leder via inloggad Personal Area. Aktuell månad kan väljas per dag, äldre material per månad eller år. Exakta offentliga filadresser och de fem aktuella instrumentvalen har inte verifierats.

[USTEC](https://www.exness.com/indices/us-tech-100/) är uttryckligen en CFD på Nasdaq 100. [Leverantörens CSV-exempel](https://insights.exness.com/trading-basics/forex-data/) använder UTC-Z och millisekunder. Hjälpen beskriver fem fält inklusive `Exness`, medan exempelartikeln visar fyra; en verklig fil måste därför granskas före import. Kontosuffix och serverpriser kan skilja sig. Den publika sidan kallar priserna indikativa; de visar inte egna fills eller experttrades. Öppen licens för rådata och generell träningsrätt har inte fastställts.

## Dukascopy och nästa steg

[Dukascopys villkor](https://www.dukascopy.com/swiss/english/legal-pages/terms-of-use/), avsnitt 3, kräver föregående skriftligt tillstånd för automatiserad åtkomst. Villkoren innehåller även begränsningar kring kommersiellt bruk och databaser. Något skriftligt tillstånd har inte visats i uppdraget, och ingen automatiserad Dukascopy-hämtning har startats.

Nästa konkreta steg är en tillåten fil per instrument med fastställd kontraktstyp, ursprunglig ZIP/CSV och SHA-256. Kontrollera faktisk rubrik, datumformat, bid/ask, dubblettider, luckor och periodtäckning innan större införsel. Bevara källans radordning och samma tidsstämplar; påhittade millisekunder, volym eller fillhistorik ska inte läggas till. Test och träning kan börja först efter dessa kontroller och en uttalad plan för vilka användningsrättigheter som gäller.
