# Separata quant- och exekveringskontroller

2026-10-27. Detta tillägg ändrar inte den frysta forward-piloten.

## Implementerat

`quant_checks.py` innehåller tre fristående offlineberäkningar:

- Positionsstorlek: q = floor(B / ((d × M + c) × s)) × s. B är förlustbudget, d stopavstånd, M kontraktsmultiplikator, c deklarerad tur/retur-kostnad per enhet och s kvantitetssteg. Alla belopp måste ha samma valuta. Gap, marginal, valutaomräkning, likviditet och aggregerad risk ingår inte.
- Historisk minsta-varians-hedge: h = cov(portfölj, hedge) / var(hedge). Kräver synkroniserade avkastningar från en separat träningsperiod. Detta är en koefficient, inte ett orderantal eller ett hedgegodkännande. Koefficienten kan vara negativ eller instabil.
- Träningsurval för en tidsfold: både beslut, etikettens slut och etikettens tillgänglighet måste ligga strikt före teststart minus gap. Överlappande och ännu okända etiketter utesluts. Funktionen verifierar inte datasetets rättigheter och ersätter inte experimentregistret.

`execution_checks.py` arkiverar uttryckligen tillförda syntetiska delavslut i SQLite med befintlig broker/anslutning/konto/miljö-nyckel. Identiska återleveranser påverkar inte kvantiteten igen; samma exekverings-ID med ändrat innehåll avvisas. Återstart, separat broker med samma konto-ID, sena avslut och överfyllnad testas. Rapporten ger aldrig tillstånd till omsändning. Detta är en audit av tillförda händelser, inte en simulator som genererar avslut eller en brokertransport. Statusmaskin, avbrottsdetektion och extern positions-/kassaavstämning återstår.

## Brokerarkitektur och nästa prov

Befintlig `AdapterRegistry` stödjer flera exakta paperroutes och kanoniska instrument. Dess två kodare är uppfunna format. Alpaca har en läsande referensadapter; IBKR har ingen verklig adapter här. Vi kan därför förbereda flera brokers, men kan inte ännu hävda fungerande orderkoppling.

1. Behåll LEAN som första motor. Verifiera dess fills mot kassaboken och dessa separata kontroller.
2. Första uttryckligt konfigurerade paperkonto: instrumentbindningar, behörigheter, order-/execution-ID, öppna order, positioner, avgifter och kassa måste stämmas av.
3. Andra broker: upprepa samma kontraktsprov. Mappa verkligt instrument, valuta, börs, förfall, tick och lot; anta aldrig att samma symbol avser samma produkt.
4. Vid okänd orderstatus: stoppa ny risk och sök originalordern/exekveringar. Timeout är inte bevis för avvisning. Ingen automatisk omsändning eller flytt till annan broker.
5. Deduplicera exekveringar med verklig vendorsemantik. Hantera korrigeringar/busts separat; denna audit stödjer dem inte.

IBKR beskriver dubbla orderStatus-callbacks och separata execDetails. Statusmeddelanden får därför inte användas som unika delavslut. LEAN har broker-, fee-, fill- och slippage-modeller; motorns stöd är inte bevis för vårt kontos behörighet.

## Matematisk utvecklingsordning

| Ordning | Metod | Vad den ska pröva | Krav före användning |
| --- | --- | --- | --- |
| 1 | Fryst momentum/medelvärdesbaslinje och kontantalternativ | Om en enkel regel tillför något efter kostnader | Godkända data och avstämd LEAN-replay |
| 2 | Volatilitetsskalning, koncentrationsgränser, kovarians med shrinkage | Stabilare riskfördelning än lika kapital | Träningsfönster, valutasamband, portfölj-/marginalkontroll |
| 3 | Walk-forward med etikettpurging och gap | Om resultat håller på senare perioder | Registrera alla försök; separat sluttest |
| 4 | Blockbootstrap, drawdown, expected shortfall och kostnadsstress | Osäkerhet, svansrisk och känslighet | Bevara tidsberoende; förregistrera blocklängd och beslutsgränser |
| 5 | Ridge/logistisk regression före större ML | Om enkla prediktorer förbättrar den frysta baslinjen | Mogna etiketter, train-only preprocessing, kalibrering |
| 6 | Dynamisk beta/hedge, senare Kalmanfilter | Om varierande exponering förbättrar totalrisk efter kostnad | Futuresavräkning, basisrisk, marginal och hedgepolicy |

Framtida bibliotek: scikit-learn för tidsdelning, Ridge och Ledoit–Wolf; SciPy för optimering och statistiska kontroller. Inga nya beroenden är installerade. Qlib kan senare användas för forskning, inte som andra auktoritativa ordermotor. Automatiskt lärande eller strategipromotion byggs först efter jämförbar kandidatprövning. Inget matematiskt verktyg bevisar lönsamhet.

## Realistisk avslutsmodell som återstår

Använd explicit bid/ask, orderankomst efter beslut och latens, tickavrundning, kvantitetsgräns per marknadshändelse och uteblivna/delvisa avslut. En limit får aldrig fyllas sämre än sin gräns. Dela likviditetsbudgeten mellan samtidiga order. Stressa spread, marknadspåverkan, avgifter, avvisning och avbrott. För kalibrering krävs tillåtna verkliga offerter/exekveringar; OHLC ensamt visar inte köposition eller intrabar ordning. Vanliga fonder kräver separat NAV-flöde. Detta leveranssteg implementerar inte denna fullständiga modell.

## Officiella källor kontrollerade 2026-10-27

- IBKR status: https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status/introduction
- IBKR exekveringar: https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details/receive-execution-details
- LEAN brokers: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/brokerages/supported-models
- LEAN slippage: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/supported-models
- scikit-learn tidsdelning: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

Metodvalen och införandeordningen är projektets förslag. Tester är syntetiska och visar lokala kontrakt, inte lönsamhet eller extern anslutning.
