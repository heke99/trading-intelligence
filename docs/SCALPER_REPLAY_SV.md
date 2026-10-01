# Körbar scalpingprototyp för offlineforskning

`scalper_research` är ett separat paket för bid/ask-import och regelbaserad replay.
Historikimportören behåller sina egna tabeller och kommandon. Ingen modell tränas,
ingen traderhistorik används automatiskt som signaldata och inga order skickas.

## Kör direkt på Mac

Python 3.11 eller senare; runtime kräver inga extra paket. Kör från projektroten:

```bash
python3 -m scalper_research demo --out ../scalper-demo
python3 -m scalper_research status --out ../scalper-demo
```

Detta genererar 72 **fiktiva** EURUSD-quotes, importerar dem och kör tre separata
perioder. EURUSD, storlek, sessionsfönster och kostnader är demonstrationen av
programmet, inte rekommenderade eller verifierade marknadsinställningar.
Resultatet visar att mekaniken fungerar; det visar inte att en strategi har edge.

`../scalper-demo/synthetic-inputs/` innehåller CSV, metadata och den kompletta
konfigurationen. Dessa filer kan användas som formatmallar. Skapa nya filer för
verkliga data; behåll dem och all output utanför Git.

## Första regelhypotesen

Strategin heter `rolling_quote_breakout_v1`. Vid varje quote jämför den aktuellt
mittpris `(bid+ask)/2` med högsta/lägsta mittpris i de **föregående N** quotesen:

- Long-signal när mittpriset är högre än intervallets högsta plus angiven buffer.
- Short-signal när mittpriset är lägre än intervallets lägsta minus buffer.
- En position åt gången, fast explicit storlek, fast stop- och targetavstånd.
- Exit även vid maximal hålltid, stängd session, förlustgräns eller datagap.
- Signalcooldown räknas från signaltid; en signal kan sedan nekas av exekveringsregler.

Denna regel är vår egen explicita forskningshypotes. Den är inte en kopia av
Fabio Valentinis, Sivakumar Jayachandrans eller någon annan traders policy.
Urvalet av N quotes är beroende av quote-frekvens och är inte en tidsbaserad candle.

## Exekvering och kostnader

En signal på tiden `t` kan tidigast simuleras på första **senare** quote vid eller
efter `t+latency_ms`. Latens måste vara minst 1 ms. Long köps på ask plus slippage
och säljs på bid minus slippage; short använder motsatta sidor. Priset på den
faktiskt använda quoten sparas. Ett stop eller target är en exittrigger, inte ett
löfte om ett avslut exakt på stop-/targetpriset.

Spread ingår i sidornas priser och subtraheras inte en gång till. Commission
debiteras på båda sidor:

```text
gross_pnl = (exit_price - entry_price) × direction × quantity × contract_multiplier
commission = 2 × quantity × commission_per_unit_per_side
net_pnl = gross_pnl - commission
```

`direction` är +1 för long och -1 för short. Commission måste anges i samma
uttryckliga prisvaluta som P&L. Storleken är den unit som användarens multiplier
och commission per unit beskriver; programmet antar inga lots, tickvärden eller
automatisk valutaväxling. Ingen initial kontobalans antas. Equity/drawdown är
P&L i prisvalutan, inte kontoavkastning eller procenttal.

Om priset rör sig under väntetiden används det senare priset. Förlustgränsen
stoppar nya entries och begär exit; latens och luckor kan göra den slutliga
förlusten större än gränsen. Det är ingen garanti för maximal realiserad förlust.

Det finns ingen orderbok, köplats, likviditets-, partiell fill-, marginal- eller
brokerregelmodell. Session är ett explicit UTC-fönster `[start,end)` inom samma
UTC-dygn; det motsvarar inte automatiskt London/NY:s lokala tider eller DST.

## Tidsordning och luckor

CSV-importen bevarar alla rader, även flera på samma millisekund. Den sorterar
eller raderar inte historik. Replay kräver strikt ökande tid: oklara samtidiga
quotes stoppar körningen. Källordning görs inte om till en verifierad marknadssekvens.

Ett datagap över `max_quote_gap_ms` markerar den okända prisbanan, avbryter en
väntande entry och tömmer signalhistoriken. En öppen position får en exitbegäran
med samma latens. Redan begärd exit behåller sin tidigare tidsgräns. Gapets
verkliga risk kan inte räknas ut ur första quoten efter luckan.

Vid dataslut avbryts en väntande entry. En öppen position eller väntande exit
förblir **öppen och orealiserad**, med separat bid/ask-markering och uppskattad
exitkostnad. Programmet skapar inget påhittat avslut för att göra rapporten komplett.

## Verkliga marknadsdata

Importören kräver UTF-8 CSV med exakt `time_msc,bid,ask`, och valfri `symbol`-kolumn:

```csv
time_msc,bid,ask
1704186000000,1.10000,1.10002
1704186000250,1.10001,1.10003
```

Ovanstående rader är fiktiva formatillustrationer. Alla priser måste vara positiva
ASCII Decimal-tal; ask får inte vara lägre än bid. Inga tomma, felaktiga eller
bakåt daterade rader släpps tyst igenom. Gränsen är 32 MiB och 500 000 quotes per fil.
Extrema eller alltför långa tal kan bevaras av importören men nekas av replayns
snävare räknedomän. Replay beräknar med ett separat, deterministiskt Decimal-context.

Metadata är JSON med åtminstone följande fält:

```json
{
  "schema_version": 1,
  "source_id": "my_reviewed_quote_export",
  "symbol": "EXACT_BROKER_SYMBOL",
  "timestamp_basis": "utc_epoch_milliseconds",
  "timezone_evidence": "ACTUAL_SOURCE_CLOCK_DOCUMENTATION",
  "data_origin": "user_supplied_unverified",
  "price_currency": "ACTUAL_PRICE_CURRENCY",
  "usage_rights": "not_verified"
}
```

Symbol, valuta och tidszonsbelägg måste ersättas med verkliga uppgifter. Import
tillåter okända användningsvillkor och visar dem; replay kräver för verkliga data
`usage_rights="user_asserted_permitted"` och `rights_evidence` med den verkliga
tillåtelsen. Användarens uppgift är fortfarande inte oberoende verifierad och
ger inga modellträningsrättigheter. Ingen brokerautenticitet intygas.

```bash
python3 -m scalper_research import-quotes ../private/ticks.csv \
  --metadata ../private/market.json --out ../scalper-data
python3 -m scalper_research replay ../private/ticks.csv \
  --metadata ../private/market.json --config ../private/replay-config.json \
  --out ../scalper-data
```

MetaQuotes dokumenterar `copy_ticks_range` med bid/ask och UTC-tider för sitt
Python-API: [officiell referens](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py).
Den kräver ett fungerande lokalt MT5/terminalupplägg; paketet här ansluter inte till
terminalen. MT5:s GUI-export kan ha andra rubriker, format och tidsuppgifter. En
godtycklig GUI-CSV antas därför inte följa UTC-ms-kontraktet; original och ett
granskat format-/tidszonskontrakt behövs före en särskild adapter.

MetaQuotes skiljer även verkliga broker-ticks från genererade ticks och beskriver
bid/ask som exekveringspriser: [officiell testerbeskrivning](https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation).
Ingen verklig marknadshistorik har hämtats eller testats i denna prototypleverans.

## Fryst konfiguration och perioder

Kopiera demo-konfigurationens schema och ersätt varje parameter med ett uttryckligt
forskningsval och faktiska instrument-/kostnadsuppgifter. Pris- och kostnadstal
skrivs som Decimal-strängar; latens, quoteantal och tidsgränser som heltal.
Okända fält eller ogiltiga värden stoppar körningen.

`development_end_msc` och `validation_end_msc` ger tre icke överlappande intervall:

1. Development: tid före första gränsen.
2. Validation: tid från första gränsen, före andra gränsen.
3. Test: tid från andra gränsen och framåt.

Varje period börjar flat med tom historik och egen förlust-/tradegräns. Ingen
position, signal eller väntande entry flyttas mellan perioderna. Samma konfiguration
och dess SHA-256 gäller alla tre. Ingen optimering, automatisk parameterselektion
eller maskininlärning sker. Tre delar av en fil bevisar inte att testperioden varit
orörd; det kräver ett separat låst forskningsprotokoll och får inte intygas här.

## Rapporter och nästa grind

`market-runs/` innehåller importmanifest och normaliserade quotes. `replay-runs/<id>/`
innehåller manifest, tre periodrapporter och `summary.json`. Original CSV/metadata/
konfiguration arkiveras oförändrade med SHA-256 i `raw/`. Misslyckade körningar
behåller indata och felstatus; status visar också den senaste misslyckade körningen.
Exitkod är 0 för slutförd operation, 2 för fel och 130 för avbrott.

Alla resultat är hypotetiska; `model_trained`, `training_ready`, `trading_enabled`
och `replay_accepted` är alltid false. Positivt P&L aktiverar inga grindar.

Nästa nödvändiga underlag är verkliga tillåtna tickdata för valt instrument och
dess kontraktsstorlek, prisvaluta, kostnader och session. Därefter låses strategi,
tidsperioder och acceptanskriterier innan den senare testperioden utvärderas.
Brokerdemo är en separat senare komponent efter godkänd forskning.
