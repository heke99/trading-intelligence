# Verifiering av tickbygget, 2026-10-01

Python-kandidaten `429788dfeef5cf1830a948ca78fe18208f5ef36e` klarade **434 offline syntetiska tester** på Python 3.11, 3.12 och 3.13. [CI-körning 36936156548](https://github.com/heke99/trading-intelligence/actions/runs/36936156548) har success för samtliga jobb, inklusive tidigare importer, all-demo, native-demo och installerade kommandon utanför repot. MQL-tillägget granskas separat som källkod; ingen kompilering eller terminalexport har verifierats.

## Fiktiva resultat

Alla fem produkter nedan är konstruerade fixtures. De verifierar datapipeline och modellfitting, inte historisk täckning, förväntad avkastning eller experters strategier.

| Fixture | Resultatvaluta | Native rader | Samma-ms-rader | Härledda observationer | Utvecklingslabels | Senare testobservationer | Kostnadsscenarier |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EURJPY | JPY | 5427 | 1809 | 1806 | 108 | 601 | 5 |
| EURUSD | USD | 5427 | 1809 | 1806 | 108 | 601 | 5 |
| GBPJPY | JPY | 5427 | 1809 | 1806 | 108 | 601 | 5 |
| NAS100_SYNTHETIC | USD | 5427 | 1809 | 1806 | 108 | 601 | 5 |
| XAUUSD | USD | 5427 | 1809 | 1806 | 108 | 601 | 5 |

För varje fixture: 57 positiva och 51 negativa hypotetiska utvecklingslabels, tröskel 0,4 vald på validering, fem fördeklarerade kostnadsscenarier utan ny fitting. Dessa små fixtureantal är teknisk testtäckning och styrker ingen statistisk trading-edge. Installerad tick-demo gav samma modellinnehållshashar som modulkommandot för varje produkt. USD- och JPY-resultat hölls separata.

Det maskinläsbara kvittot [tick_synthetic_proof_2026-10-01.json](tick_synthetic_proof_2026-10-01.json) innehåller exakt verifierad commit, jobb/körning, scenarioantal och modellhashar. CI för senare commits visas i PR:s aktuella checks; beviset här avser uttryckligen den ovanstående Python-kandidaten.

## Rättningar med föregående reproduktion

[Första regressionskörningen](https://github.com/heke99/trading-intelligence/actions/runs/36934985740), commit `4117ac855763eadd2ada4db1015d71cf05f79a26`, reproducerade tre assertionfel och en decimal-overflow före rättning. Explicit träningsrätt/källattribution bevaras nu, avbrott ger färdig failed-receipt och fixtures isolerar sin Decimal-kontext.

[Andra regressionskörningen](https://github.com/heke99/trading-intelligence/actions/runs/36935718709), commit `efdad71f4889651a0af09a84c4e70c3dc96d3c61`, bekräftade att de tidigare felen var rättade och reproducerade ogiltiga Unicode-/kontrolltecken. Dessa lämnar nu stabilt valideringsfel med färdig kvittofil. Den efterföljande körningen passerade samtliga 434 tester.

## MT5 och verklig data

Nio ursprungliga fil-/låsnings-/JSON-hjälpfunktioner är byteidentiska efter uttag till gemensam MQL-header. Tickkopieringsloopen bevarar inkluderande fönster, native ordning, 17 signifikanta prisdigits, 500 000-radsgräns och avslag för delresultat med fel. Basketen kräver högst fem exakta unika symboler, nollställer symboltillstånd och låter oberoende symbolfel fortsätta. Oberoende statisk granskning fann inga nya blockerande fel eller order-/konto-/prenumerationsanrop. Detta är inte kompilering eller runtimeverifiering.

**Verklig tillförsel: 0 originaltickarkiv, 0 originalmarknadsbyte och 0 nya kompletta traderhistoriker.** HistData-katalogförsöket gav NETWORK_BLOCKED_OR_UNAVAILABLE. Annonserad instrumenttäckning är inte provlästa filer. Nasdaq-produkt, historiska kontrakt/kostnader, rättigheter, komplett täckning och brokerforwardevidens återstår. Fabio/Sivas fullständiga fills och samtida beslutsplaner har inte tillkommit.

`training_ready`, `full_history_verified`, `trading_enabled`, `broker_connected` och `model_trained_on_real_market` förblir false. [Tickguiden](TICK_WORKFLOW_SV.md) och [underlagslistan](TICK_EXECUTION_EVIDENCE_SV.md) anger nästa datasteg och begränsningarna för stora flerårsarkiv.
