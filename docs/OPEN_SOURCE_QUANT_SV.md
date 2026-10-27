# Återanvändning av open source och kvantitativ forskningsarkitektur

Kontrollerat 27 oktober 2026. Kompletterar masterplan 1.4, ändrar inte den frysta piloten eller införandeordningen för verkliga data. Ambitionen är en konkurrenskraftig forskningsplattform. Banbrytande resultat måste visas i nya data; antalet bibliotek eller modellernas komplexitet är inget resultatmått.

## Kod som faktiskt används i detta steg

`quant_research.risk_snapshot` anropar **scikit-learn 1.8.0 `LedoitWolf.fit`**. Detta är upstreams implementation, inte en egen approximation. Den stabiliserar kovariansen genom shrinkage mot en skalad identitetsmatris. Risk beräknas som σ = sqrt(wᵀΣw), och komponentbidrag som wᵢ(Σw)ᵢ/σ. Bidragen summerar till portföljens volatilitet; negativa bidrag kan förekomma vid negativ samvariation. Framtida rader utesluts före fit och indata identifieras med hash. Avkastningar, tidssteg och basvaluta måste vara synkroniserade av anroparen. Ingen årlig skalning antas.

`quant_research.superior_predictive_ability` anropar **arch 8.0.0 `SPA`**, med stationary bootstrap och studentisering. Lägre förlust är bättre. Testet prövar den deklarerade modellfamiljen mot en benchmark och ger tre p-värden enligt upstreams metod. Konstant förlustdifferens avvisas här som degenererad. Vi hävdar inte att ett p-värde är sannolikheten för framtida vinst.

Detta gör faktisk återanvändning av upstreams matematiska kod genom versionslåsta beroenden. Ingen modifierad upstreamkod är inklistrad i vår källkod. Paketens medföljande licenser följer distributionerna. scikit-learn använder BSD-3-Clause och arch använder NCSA-licens; kontrollera medföljande distributionslicenser vid paketering av produkt.

Den egna integrationskoden innehåller ett parat cirkulärt blockbootstrap-intervall, explicit kostnadsstress, geometrisk avkastning och drawdown. Bootstrapen drar samma tidsblock för kandidat och benchmark via deras differens. Det är ett deskriptivt percentile-intervall, inte SPA eller en multipeltestkorrigering. Blocklängd och konfidens ska förregistreras och känslighetsprövas.

Kör i separat forskningsmiljö:

```sh
python3 -m venv .venv-quant
.venv-quant/bin/python -m pip install -r requirements-quant.txt
PYTHONPATH=src .venv-quant/bin/python -m unittest discover -s tests -p test_quant_research.py -v
PYTHONPATH=src .venv-quant/bin/python -m trading_intelligence.quant_research_demo
```

Demot använder bara uppfunna serier. Kovarians fitas på de första 60 observationerna, jämförelsen använder de följande 20. Kostnadsscenarier på 0, 5, 20 och 50 baspunkter är hypotetiska. Rapporten tillåter ingen promotion. Slumpfröna är fasta; numeriska resultat förutsätter också samma beroenden och plattform. Separat CI-jobb installerar de valda forskningsberoendena, medan kärnans standardbiblioteksflöde kan köras utan dem.

## Projektval och licenser

| Projekt/källa | Beslut | Konkret användning |
| --- | --- | --- |
| QuantConnect LEAN, Apache-2.0 | Behåll första exekveringsmotorn | Återanvänd fill/fee/slippage/brokerage-gränssnitt. Befintlig pinnad observer är inte en färdig strategi-replay. |
| scikit-learn, BSD-3-Clause | Integrerat i detta steg | Upstreams LedoitWolf; Ridge och kalibrering kan senare prövas när datakraven är uppfyllda. |
| arch, NCSA | Integrerat i detta steg | Upstreams SPA över deklarerade kandidater med tidsberoende bootstrap. |
| PyPortfolioOpt, MIT | Granskad kandidat, inte integrerad | Jämför senare shrinkage, HRP och constrained-allokering mot enklare riskregler. |
| Microsoft Qlib, MIT | Senare forskningsintegration | Dataset/feature/workflow och modelljämförelse, bakom våra as-of- och rättighetsgränser. Ingen extra ordermotor. |
| MLFinLab, all rights reserved | Ingen kod återanvänd | Nuvarande repo beskriver kommersiell licens. Publik GitHub innebär inte fri användning. |
| Bailey/López de Prado: Deflated Sharpe Ratio | Forskningskälla, inte implementerad | Lägg senare till när försöksfamilj, beroenden mellan försök och momentantaganden kan redovisas korrekt. |

## Nästa vetenskapliga och tekniska lager

1. **Korrekt observation:** ett faktiskt godkänt dataurval med bolagshändelser, historiskt universum och tydlig informationsfördröjning. Förhindra survivorship bias och look-ahead innan modellstorlek ökas.
2. **Kontrollerad simulator:** koppla LEAN:s verkliga orderhändelser till kassaboken. Spread, delavslut, latens, samtidiga order och likviditet måste ge avstämda händelser. Ingen parallell auktoritativ ordermotor.
3. **Robust risk:** jämför lika vikt, volatilitetsskalning och shrinkagebaserad risk. Inför sektor-/koncentrationsgränser, likviditetsbudget, basvaluta och konservativ kovariansstress. Vikter blir inte order förrän instrument, tick, lot, marginal och mandat är kontrollerade.
4. **Forskningsdisciplin:** bind varje försök till befintligt experimentregister och datasetmanifest. Alla prövade modeller ska följa med till familjeutvärderingen. SPA-funktionen verifierar ännu inte denna bindning; utelämnade misslyckade försök kan göra analysen missvisande. Förbrukat sluttest förblir förbrukat.
5. **Kandidater med prövbar hypotes:** trend, cross-sectional momentum, mean reversion och händelsesignaler får separata horisonter, universum, exitregler och kostnadsantaganden. Pröva om varje extra informationskälla tillför något på samma möjligheter.
6. **Regim och osäkerhet:** jämför rullande volatilitet, shrinkage, strukturbrott och senare tillståndsmodeller. Regimetiketter får bara byggas av då tillgänglig information. Avstå när osäkerheten eller kapacitetskostnaden är för stor.
7. **Hedge och futures:** villkorad beta, basisrisk och heltalskontrakt kopplas till separata hedgepolicys. Dagsavräkning och marginalstress byggs före dynamiska hedgeorder.
8. **Adaptivt lärande:** kalibrera och utvärdera fördröjda utfall före uppdatering. Challenger, champion och rollback använder förregistrerade regler. Läraren får inte själv öka riskmandat eller ändra sina utvärderingsgränser.

Målet är att kombinera dessa komponenter på ett tidskorrekt, spårbart och brokeroberoende sätt. Teknisk kvalitet och ekonomiskt mervärde bedöms separat. Ingen verklig modellträning, strategioptimering, automatisk promotion eller lönsamhet har verifierats i denna leverans.

## Primärkällor

- LEAN kod/licens: https://github.com/QuantConnect/Lean
- LEAN reality models: https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/trading-and-orders
- scikit-learn 1.8 LedoitWolf: https://scikit-learn.org/1.8/modules/generated/sklearn.covariance.LedoitWolf.html
- arch SPA och metodreferenser: https://bashtage.github.io/arch/devel/multiple-comparison/generated/arch.bootstrap.SPA.html
- arch projekt: https://github.com/bashtage/arch
- PyPortfolioOpt licens: https://github.com/PyPortfolio/PyPortfolioOpt/blob/main/LICENSE
- Qlib licens: https://github.com/microsoft/qlib/blob/main/LICENSE
- MLFinLab licensstatus: https://github.com/hudson-and-thames/mlfinlab
- Deflated Sharpe Ratio, originalartikel: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
