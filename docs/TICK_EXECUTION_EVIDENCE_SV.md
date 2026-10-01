# Underlag för verkliga ticks och fills

Granskat 2026-10-01. Detta dokument beskriver underlaget för EURUSD, Nasdaq, XAUUSD, GBPJPY och EURJPY. Ingen broker har identifierats och inga verkliga tick-/fillfiler har hämtats i denna deluppgift. Modellträning och livehandel är avstängda. Den maskinläsbara versionen finns i [tick_evidence_checklist.contract.json](../examples/tick_evidence_checklist.contract.json).

| Marknad | Identitet att bekräfta | Enheter att bekräfta |
|---|---|---|
| EURUSD | Exakt brokersymbol och FX-/CFD-produkt | EUR/USD är namnkonvention; faktisk kontraktsstorlek, lots/basenheter, tick och kontovaluta saknas. |
| Nasdaq | NDX-index, NQ, MNQ eller exakt CFD med cash-/terminsbasis | Aktuellt verifierat NQ: USD20/punkt, 0,25-punktstick = USD5. MNQ: USD2/punkt, 0,25-punktstick = USD0,50. Detta fastställer inga CFD- eller äldre brokervillkor. |
| XAUUSD | Exakt brokerprodukt: metall/spot/CFD | Guldenhet och vikt per lot kräver specifikation; ingen100oz-standard antas. |
| GBPJPY | Exakt brokersymbol och FX-/CFD-produkt | GBP/JPY enligt namnkonvention; kontrakt, profit-/kontovaluta och konvertering saknas. |
| EURJPY | Exakt brokersymbol och FX-/CFD-produkt | EUR/JPY enligt namnkonvention; samma krav på kontrakt och konvertering. |

NDX är ett indexvärde. NQ/MNQ är kontrakt med specifik expiry och egen marknadsdata. Ett Nasdaq-CFD använder brokerns egna kontrakts- och exekveringsvillkor. Dessa prisserier och mängdenheter är inte utbytbara.

## Filer och uppgifter att skicka

1. **Symboler och period:** befintlig broker/datakälla, exakt symbol för varje marknad, Nasdaq-produkt, start-/slutdatum och live/demo/tester-ursprung. Behåll brokersuffix och kontraktsmånad.
2. **Verkliga ticks:** original CSV/TSV/Parquet eller MT5-export med native tid/time_msc, bid, ask och ursprunglig radordning. Behåll flags,last,volume,volume_real när de faktiskt finns. Lägg med exportmetod/version, UTC-/tidszonsbasis, faktisk täckning och luckor.
3. **Historiska specifikationer:** kontraktsstorlek och enhet; lots/kontrakt/basenheter; tick size/value och valuta; digits/point; volymsteg; beräknings-/exekveringsläge; stop/freeze; avgifter per sida eller round-turn; swap och rollover; quote-/handelssessioner, tidszon/DST, daterade helgdagar/early closes och ändringsdatum. För futures: expiry, rullningskarta och ursprungliga ojusterade kontraktspriser.
4. **Fills för benchmark/imitation:** komplett anonymiserad brokerexport av deals/orders för hela perioden. Behåll ID-kopplingar, traderattribution, live/demo-status, exakt symbol, native millisekundstid, sida, entry/out/reversal, mängd/enhet, fillpris och alla kostnader. Ta med partial fills, avvisningar, stop/target-ändringar, beslut/submit/ack-tider och tidsstämplad plan/motivering där de finns, samt öppna positioner vid båda periodgränserna.
5. **Befintliga datavillkor:** licens/villkor eller ägarunderlag med dokumentversion och tillåten analys, automatisk bearbetning, träning och eventuell delning. Här har inget behov av nyinköp fastställts.

Ta bort namn, adress, inloggningsnummer och bankuppgifter. Ersätt konto- och kopplings-ID konsekvent så poster kan matchas. Skicka inga lösenord, API-nycklar, tokens, cookies eller identitetshandlingar.

## Vad underlaget kan bevisa

| Mål | Nödvändigt underlag | Gräns för slutsatsen |
|---|---|---|
| Marknadsbaserad strategiforskning | Verkliga quotes, historiska villkor, kausala features och senare orörd holdout | Kan testa en separat hypotes; innebär inte att modellen imiterar en namngiven trader. |
| Orderflödesstrategi | Exekverad volym/aggressorsida, eventuell orderbok, profilregler och event-/mottagningstider | Quoteantal och saknad volym är inte verkligt orderflöde eller ett egenutvecklat vendorsignalvärde. |
| Exekveringsbenchmark | Matchande brokerfills/orders/quotes, kostnader och faktiska klockor | Latens/slippage mäts där verkliga tids- och orderuppgifter finns; inga okända värden hittas på. |
| Imitation av Fabio/Siva | Komplett attribuerad historik, versionsspecifik plan, beslutstidsfeatures och användningsrätt | De tidigare granskade undervisningskällorna ger ingen komplett fillhistorik. Traderns andra marknader märks inte om till dessa fem automatiskt. |

## Tid, mängd och kostnader

MetaQuotes dokumenterar Python-tickhistorik som UTC. Terminal-/serverklocka och andra native exporter måste ändå beskrivas separat. Distinkta verkliga ticks kan dela samma millisekund: behåll källordningen utan nya påhittade tider. Tickflags kan visa att bara ena quotesidan ändrats medan andra värden behållits.

Last/volume är marknadsdata och identifierar inte ett konto eller en traders fill. En observerad quote bevisar inte att önskad mängd hade kunnat fyllas. MT5-dealens stop/target-värde visar inte alla mellanliggande orderändringar; journal/orderhändelser behövs.

Mängdenhet och kontraktsmultiplikator används exakt en gång. Point, tickstorlek och tickvärde är skilda storheter. Tickvärde behöver valuta och as-of-basis. Spread beräknas som ask minus bid per tick; kommission och övriga avgifter tillkommer med korrekt mängd-/sidbasis. JPY- och USD-resultat summeras först efter dokumenterad konvertering vid rätt tid. Även en kort scalp kan korsa rollover; swap antas inte noll.

## Historisk giltighet och rättigheter

Dagens hämtade specifikation styrker inte äldre villkor. Dokumentera effective-from/to och dela perioden när kontrakt, avgifter, swap eller sessionsregler ändras. Veckosessioner ersätter inte daterade handelskalendrar, helgundantag eller DST. För futures används originalkontrakt och explicit rollmap; en bakåtjusterad kontinuerlig serie är inte ett faktiskt fillpris.

MetaQuotes dokumentation beskriver dataformatet och plattformen, inte en specifik brokers villkor eller dataanvändningslicens. CME:s publicerade2025-avtal visar olika användningsklasser; det fastställer inte användarens gällande2026-avtal, en generell träningsspärr eller ett köpbehov. Börja med befintliga legitima exporter och deras tillämpliga villkor.

## Officiella primärkällor

- NAS_NDX: [Nasdaq](https://indexes.nasdaqomx.com/Index/Overview/NDX) — official index description; Index Description.
- CME_NQ: [CME Group](https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html) — official current contract reference; About E-mini Nasdaq-100.
- CME_MNQ: [CME Group](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html) — official current contract reference; About Micro E-mini Nasdaq-100.
- CME_FAQ: [CME Group](https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html) — official FAQ, not a dated historical schedule; Questions5,6,8,10.
- CME_CAL: [CME Group](https://www.cmegroup.com/trading-hours.html) — official holiday/trading-hours hub; Holiday and Trading Hours.
- MQ_SPEC: [MetaQuotes](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants) — official symbol-property schema; Symbol Properties tables.
- MQ_POINT: [MetaQuotes](https://www.mql5.com/en/book/automation/symbols/symbols_point_tick) — official price-unit documentation; Price representation accuracy and change steps.
- MQ_COPY: [MetaQuotes](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py) — official tick-history API documentation; Note and example time_msc1578614411128.
- MQ_TICK: [MetaQuotes](https://www.mql5.com/en/docs/constants/structures/mqltick) — official native tick schema; MqlTick and tick flags.
- MQ_SESSION: [MetaQuotes](https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade) — official weekly-session API documentation; Parameters from/to.
- MQ_TIME: [MetaQuotes](https://www.mql5.com/en/docs/dateandtime/timecurrent) — official native-server clock documentation; Description and Note.
- MQ_DEAL: [MetaQuotes](https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties) — official executed-deal schema; Deal Properties tables.
- CME_RIGHTS: [CME Group](https://www.cmegroup.com/market-data/files/schedule-5-to-the-ila-february-2025.pdf) — official2025 licence-schedule context; Definitions page2; section11.
