# Konkurrenskraftig quant och källbelagt beslutsfattande

27 oktober 2026 · Fördjupning till masterplan 1.5 · Specifikation, inte genomförd tradingfunktion

## 1 Målet som vi faktiskt kan pröva

Bygg en plattform som upptäcker, utvärderar och genomför ekonomiskt relevanta möjligheter inom valda marknader och risktak. Professionell nivå kräver mätbar kvalitet i data, prognoser, risk, exekvering och drift. Ingen känd metod garanterar att vi blir bäst eller överträffar hedgefonder. Jämförelser ska avse förregistrerade strategier, samma period, verklig genomförbarhet, kostnader, kapital och risk; en jämförelse mot ett valt fondindex bevisar inte överlägsenhet mot alla fonder.

Första konkurrenshypotesen är **källbelagd händelseanalys och direkt ekonomisk exponering med horisont på dagar**, efter datagrund och avstämd numerisk baslinje. Ett begränsat kapital kan göra små möjligheter relevanta för oss, men illikviditet, spread och marknadspåverkan kan samtidigt eliminera vinsten. Detta måste mätas. Vi antar ingen fördel från millisekundhandel eller exklusiva data som vi inte har.

Den frysta forward-piloten ändras inte. Nya hypoteser får egna protokoll. Arkitekturen ska kunna breddas till intradag, andra sektorer och marknader först när deras data och genomförbarhet har verifierats. Dokumentation av en senare förmåga ändrar inte fasernas beroendeordning.

## 2 Granskningen av vad vi har

| Del | Verifierad lokal grund | Viktigaste återstående gräns |
| --- | --- | --- |
| Identitet och evidens | Historiska identiteter, oföränderliga källversioner och användningskontroller | Ett faktiskt godkänt helt pris-/kalender-/bolagshändelseurval återstår |
| Matematisk forskning | Faktiska LedoitWolf- och SPA-anrop med syntetiska prov | Ingen registrerad strategi vars realiserbara nettoresultat verifierats |
| Försöksregister | Låsta regler, tidsperioder och skydd mot återanvänt sluttest | SPA accepterar fria arrayer; fullständig försöksfamilj är ännu inte verifierad |
| Exekveringsaudit | Beständiga tillförda syntetiska delavslut och deduplicering | Osignerade kvantiteter räcker inte som positioner; instrument, sida, korrigeringar och kontokassa behövs |
| LEAN | Pinnad observergrund och export/reader | Full order/fill/fee → kassabok → avstämning saknas |
| Brokers | Exakta broker/anslutning/konto/miljö-routes och syntetiska format | Ingen verifierad riktig ordertransport; första och andra paperbroker samt kontoalias/ensam avsändare återstår |
| AI och bolagsgraf | Tydliga kontraktskrav i masterplanen | Källbelagd extraktion, graf, prognosmodell och adaptivt lärande är inte implementerade |

542 lokala tester i föregående leverans visar lokala kontrakt på uppfunna data. De är inte ett lönsamhetsmått. Denna fördjupning är dokumentation och lägger inte till körbara handelsfunktioner.

## 3 Förmågor som gör resonemanget användbart

| Förmåga | Körbart ansvar | Bevis som krävs |
| --- | --- | --- |
| Förstå ny information | Extrahera händelse, aktörer, belopp, enhet, period och negation med exakt källposition | Mänskligt granskat test med rätt/fel entitet, måttenhet, negation och frånvaro av fakta |
| Knyta ihop bolag | Sök endast tids- och källbelagda relationer: ägande, kund, leverantör, konkurrent, råvara, region | En senare ägar-/leverantörsändring får inte påverka ett äldre beslut |
| Bedöma ekonomisk mekanism | Separera känt faktum, hypotes, motsägelse, alternativ förklaring och okänd exponering | Varje materiellt påstående har källa eller är uttryckligen en hypotes |
| Bedöma marknadens förväntningar | Jämför ny information med tidigare känd guidning, tillgänglig konsensus och observerad prisreaktion | Saknad eller otillåten konsensus förblir okänd; positiv nyhet blir inte automatiskt köp |
| Hantera osäkerhet | Lär och utvärdera prognosfördelning/kalibrering från mogna utfall | Språkmodellens egen säkerhet får inte bli en kalibrerad sannolikhet |
| Söka mer information | Välj en ytterligare källa när den kan ändra ett konkret beslut | Logga sökskäl, kostnad och om informationen faktiskt ändrade beslutet; hård budget |
| Byta uppfattning | Registrera ny evidens som ny analys-/prognosversion | Ursprungligt beslut och senare korrigering bevaras; öppna positioner har fortsatt exitpolicy |
| Lära av erfarenhet | Poängsätt före uppdatering och skilj prognosförlust från faktiskt systemfel | Fryst modell jämförs med hela uppdateringsprocessen på samma möjligheter |

Detta operationaliserar delar av en analytikers arbete; det etablerar inte allmän mänsklig intelligens. Språkmodellen läser och föreslår. Verifierade beräkningsfunktioner räknar. Deterministisk risk och exekvering beslutar om order får gå vidare. Ett kritikeranrop kan hitta brister, men två modeller som håller med utgör inte två oberoende källor.

Ett analysbeslut ska minst lagra: beslutstid, käll-/snapshot-ID, berörda kanoniska instrument, nya fakta, förväntansreferens, mekanism, motargument, relationsväg, explicit okända värden, prognoshorisont och måldefinition, kalibreringsversion, möjliga åtgärder inklusive avstå, risk-/kostnadsunderlag, invalideringsvillkor och giltighet. Versionsreferenser omfattar modell, prompt, verktyg och kod. Spara kontrollerbara skäl och verktygsresultat; en lång fri resonemangstext är inget bevis för rätt beslut.

## 4 Grafen ska beskriva ekonomiska mekanismer

En relation behöver minst käll- och målentitet, relationstyp, riktning, ekonomisk period/giltighet när den är känd, första kännedom, bearbetningstid, dokumenthash, källposition, eventuell uppgiven exponeringsandel och rättelsehänvisning. En period är inte samma sak som dagen då vi fick veta den. En okänd siffra ersätts inte med en uppskattning som om den vore ett faktum.

Första provet använder en direkt relation. Två led kräver särskilt prov enligt masterplanens grafgräns. Vi multiplicerar inte godtyckliga vikter genom ett nät och kallar resultatet vinstprognos. Samma slutexponering via flera vägar behöver dedupliceras och överlappande koncernintäkter får inte summeras dubbelt.

GLEIF Level 2 beskriver direkta och yttersta **redovisningskonsoliderande moderbolag**, med undantagsrapportering. Det är varken komplett aktieägarregister eller ett leverantörsnät. Gemensam ägare, styrelseledamot eller branschetikett ger sökuppslag; sambandets ekonomiska effekt måste beläggas separat. SEC Companyfacts ersätter inte läsning av företagsspecifika kontrakt och fotnoter. [K1, K2]

Sambandstäckningen byggs efter ekonomisk mekanism, med separata kontrakt för varje ny typ:

| Samband | Vad som behöver beläggas | Felslut som ska testas |
| --- | --- | --- |
| Kund/leverantör/konkurrent | Produkt, riktning, beroende, ersättningsmöjlighet och tidsperiod | En störning gynnar inte automatiskt varje konkurrent |
| Koncern/ägande | Ägar- eller konsolideringsrelation och eventuell ekonomisk kontroll | Gemensam investerare innebär inte gemensamt kassaflöde |
| Ränta/valuta/råvara | Skuldvillkor, intäkts-/kostnadsvaluta, insatsvara och befintliga säkringar | Högre råvarupris betyder inte samma effekt på producent och kund |
| Region/reglering | Faktisk försäljning, produktion och tillämplig verksamhet | Hemvist eller branschetikett räcker inte som kvantifierad exponering |
| Portfölj/faktor/likviditet | Direkta och genomlysta innehav, faktor-/valutaöverlapp, omsättningsbarhet | Flera tickers innebär inte flera oberoende risker |

Vi söker brett efter kandidater men inför inte obegränsade relationskedjor i ett handelsbeslut. Varje ny typ behöver egen källdefinition, tidsregler, negativa exempel och prövning av inkrementellt värde.

Den oföränderliga evidenslagringen är auktoritet. Graf-/vektorindex kan återskapas och måste filtrera på tid, rättigheter och incidentstatus. Nuvarande graf får aldrig användas som historisk sanning. En relevant textposition visar var ett påstående finns, men bevisar inte att källan har rätt eller att relationen är aktuell.

## 5 Första konkreta händelseprovet

Hypotetiskt exempel, inga riktiga bolag eller marknadsprognoser:

1. Bolag A meddelar att en fabrik stängs. Systemet bevarar originaldokument, mottagningstid och vad A faktiskt har sagt.
2. Ett tidigare känt dokument visar att B köper en viss komponent från A. Uppgiven exponering och period sparas; saknas andel är den okänd.
3. Analysen prövar flera förklaringar: tillfälligt lager kan skydda B; alternativa leverantörer kan finnas; störningen kan minska B:s produktion; andra producenter kan gynnas. Hypoteser blir inte nya graffakta.
4. Prövningen frågar vad som är nytt jämfört med tidigare känd information och vilken prisrörelse som redan observerats. En tidigare prisreaktion kan vara en feature, men bevisar inte att allt är inprisat.
5. Numeriska modeller ger en prövbar prognos för en definierad senare horisont. Om underlaget inte räcker avstår systemet eller begär en specificerad källa inom budget.
6. Portföljlagret jämför handlingsalternativ mot aktuellt innehav, samlad risk och kostnad. En ny hedge räknas som egen handel med eget marginalbehov.
7. Ett tillåtet simulerat beslut följs till moget utfall. Pris, direkt händelse, graf och mänskligt tillägg jämförs var för sig på samma möjligheter, med kontroll för marknads-/sektorrörelser och samtidiga direkta nyheter om B.

Första forskningsurvalet ska vara tidslåst med uttryckliga inklusionsregler och en händelsetyp. Bolagen får inte väljas efter senare vinnare. Börja med ett litet kod-/extraktionsprov; välj därefter antal utvärderingsobservationer genom styrke- och osäkerhetsanalys. Ett bekvämt antal dokument är ingen statistisk acceptansgräns.

## 6 Matematiken byggs runt beslutet

Prognoslagret skattar utfall och osäkerhet för en bestämd horisont. Portföljlagret väljer storlek utifrån prognosen, kostnaderna och riskmandatet. Vi kan använda följande forskningsformulering som utgångspunkt:

`max_w [ mu(t)^T w - lambda * w^T Sigma(t) w - C(w - w_current) - H(w) - U(w) ]`

Alla termer måste ha deklarerad tidshorisont och förenliga enheter. `mu` är skattad avkastning, `Sigma` kovarians, `C` omsättnings-/impactkostnad, `H` innehavskostnad och `U` en explicit osäkerhetspåföljd. Riskaversion och osäkerhetsstraff förregistreras; de väljs inte efter sluttestet. En separat CVaR/expected-shortfall-formulering kan jämföras senare. Denna formel är ett konstruktionsförslag, inte implementerad optimering eller ett alpharesultat. Boyd med flera skiljer uttryckligen optimeringen från den svåra prognosuppgiften. [K3]

Krav omfattar cash, omsättning, koncentration, faktorexponering, gross/net, likviditet och faktiska kontogränser. Ett teoretiskt optimalt w blir inte en genomförbar order förrän pris, tick, lot, valuta, börs, blankningsmöjlighet och marginal verifierats. Futures kräver heltalskontrakt och råa förfallande kontrakt; en kontinuerlig serie är ett forskningsunderlag. Avrundning och uppdelning mellan konton kan försämra lösningen och behöver ny riskkontroll.

Modellordning: fast prisregel → Ridge/logistisk modell med train-only pipeline → trädbaserad modell → utvalda text-/grafinteraktioner. Jämför volatilitetsskalning och lika vikt mot shrinkagebaserad allokering. Senare ensemblevikter ska bygga på kronologiskt observerad kvalitet och risk; tre korrelerade modeller blir inte tre oberoende signaler. Online-/regimmodeller kommer först efter att deras uppdateringsregel utvärderats.

För intradag ska den deterministiska handelsloopen använda förberedd information med strikt latensbudget. Kostsamma språkmodellfrågor i varje tick är inte grunddesignen. Orderflow kräver korrekt handels-/quote-/orderboksdata och börsens relevanta semantik; dagliga OHLC-staplar får inte märkas som orderflow.

## 7 Två utvärderingar och en gemensam beviskedja

**Prognos:** mät relevant prognosfel, kalibrering och ranking när det passar uppgiften. Brier/log loss hör till verkliga sannolikhetsprognoser; träffprocent ensam visar inte ekonomiskt värde.

**Ekonomi:** mät nettoresultat, osäkerhet, drawdown, svansrisk, beta/faktorexponering, omsättning, kapitalbehov, likviditet och koncentration. Jämför vid samma risk och möjligheter. Redovisa forsknings-/datakostnader separat och vid bedömning av total ekonomisk bärkraft. Avgifter, spread, slippage, impact, lånekostnad och FX får inte dubbelräknas eller glömmas. [K3, K4]

Ett nytt `research_campaign`-kontrakt ska binda hypotes, hela kandidatfamiljen inklusive avbrutna försök, dataset-/universumversion, modellcheckpoint, features, horisonter, tidsfoldar, mognade etiketter, förhandsvalda kostnader, försöksbudget och förbrukade slutperioder. SPA ska läsa verifierade kampanjresultat i stället för att lita på valfria arrayer. Avbrutet försök utan användbart resultat behåller status och skäl; saknad förlustserie blir inte nollförlust och kan blockera ett bekräftande familjeresultat. [K5]

Negativa kontroller: grupp-/tidsanpassade permuterade etiketter, placebohändelser, felvänd/utgången relation, framtida dokument, korrigerad etikett efter cutoff och helt oförändrad signal. Naiv oberoende permutation av korrelerade rader är ingen generell finansiell nollmodell; sådana enkla prov används enbart som läckagediagnostik. En gemensam händelse får inte ge närmast identiska exempel i både träning och test. Grupp- och tidssplit ska även hantera överlappande horisonter. Förregistrera primärt ekonomiskt mått, riskgränser och minsta relevant förbättring; välj databehov utifrån osäkerhet och beroende, inte ett magiskt Sharpe- eller win-rate-tal.

Lägg till information ett lager i taget: pris → direkt händelse → relation → minne → mänskligt ingrepp. Varje lager betalar för sin extra data-, beräknings- och handelskostnad. SPA/DSR/PBO ger kompletterande urvalsdiagnostik; ingen ersätter nya framåtriktade observationer.

### Språkmodellens inlärda framtidskunskap

Historiskt korrekta dokument och en instruktion att bortse från framtiden räcker inte om modellens träning redan innehåller det senare utfallet. Forskningskällor dokumenterar denna typ av look-ahead-bias. [K6]

Registrera exakt modell/checkpoint, offentliggjord träningsgräns när den är känd, release-/användningstid och kontaminationsstatus. Är träningens tidsgräns okänd, är den okänd. Historiska LLM-resultat på potentiellt redan sedda händelser redovisas som explorativa. Anonymisering, framtidsfrågor och ändrade namn/datum är diagnostik, inte garantier. Bekräftande LLM-jämförelse kräver prospektivt låsta beslut på nya händelser eller ett särskilt verifierat point-in-time-modellprotokoll. Modellversion får inte bytas obemärkt mitt i en sådan prövning.

## 8 Exekvering och brokers på professionell nivå

LEAN förblir första order-/simuleringsmotorn. Verifiera dess faktiska händelser mot kassaboken, inte två oberoende uppfunna sammanställningar. Varje beslut följs genom orderankomst, kvittens, delavslut, avgift, position och kassa. Logga implementation shortfall både mot beslutspris och ankomstpris samt utebliven exekvering. Likviditetsbudgeten delas mellan samtidiga order. Paperfyllningar är inte bevis för verklig köposition eller kapacitet. [K4]

Inför en kanonisk extern kontoidentitet med alias för anslutningar och ett avsändarlås/fencing. Två anslutningar till samma verkliga konto får inte ge två riskbudgetar eller två oberoende avsändare. Separata brokerkonton kan ha olika marginal och tillgänglig kassa; globala riskberäkningar innebär inte att pengar är flyttbara i realtid.

Verifiera första verkliga papertransporten och därefter en andra broker med samma kanoniska strategikontrakt. Konto-/produktspecifika förmågor måste upptäckas och verifieras; stöd för en tillgång eller ett ordervillkor antas inte gälla hos alla. IBKR skiljer orderstatus från exekveringar och har särskild korrigeringssemantik. [K7]

Obligatoriska felprov: avbrott precis efter send, okänd status, dubbel kvittens, cancel/fill-race, sena fills efter stopp, korrigerat/bustat avslut, kontoalias, samtidiga strategier, delvis fylld hedge/roll och återstart. Ingen automatisk omsändning eller broker-failover efter oklart utfall. Ett hårt stopp får aldrig hindra bokföring av ett faktiskt sent avslut. Skilj riskpaus från fullständigt orderstopp: cancel eller reducerande order kräver egen tillåtelse och verifierad exponering/pending-state och får inte kringgå ett hårt orderstopp. Futuresvariation, settlement, margin och FX måste avstämmas separat innan de används i portföljoptimering.

## 9 Återanvändningsbeslut för kod

| Kod/källa | Del att återanvända | Beslut och införandekrav |
| --- | --- | --- |
| LEAN, Apache-2.0 | Befintliga fill/fee/slippage/brokerage-gränssnitt | Vald första motor; nästa steg är avstämd replay |
| scikit-learn, BSD-3-Clause | LedoitWolf nu; Pipeline, Ridge, kalibrering senare | Faktisk numerisk integration finns; predictive fit kräver godkända data |
| arch, NCSA | Befintligt SPA-anrop | Bind till kampanj och fullständiga resultat innan bekräftande rapport |
| Google LangExtract, Apache-2.0 | Spanförankrad strukturerad extraktion | Nästa avgränsade AI-kandidat; avvisa char_interval=None eller mismatch mot råtext. Verifiera negation, entitet, belopp och period även vid matchad span |
| Microsoft Qlib, MIT | Utvalda features, data-/experiment-/modellkomponenter | Använd bakom våra tids-/admissionsgränser, ingen parallell ordermotor |
| Microsoft RD-Agent, MIT | Utvalda research→implementation→feedback-komponenter | Senare sandboxad kandidatgenerator med försöksbudget och låst evaluator; ingen självgodkänd promotion |
| CVXPY, Apache-2.0 | Optimeringsmodellering och validerade solveranrop | Föredragen kandidat för egen deklarerad portföljpolicy; lösare och toleranser ska låsas separat |
| Cvxportfolio, GPL-3.0 | Vetenskaplig referens och eventuellt separat utvärdering | Kopiera inte GPL-kod till vår produkt som om den hade permissiv licens; inget nuvarande integrationsbeslut |
| Graphiti, Apache-2.0 / GraphRAG, MIT | Eventuellt retrieval-/indexlager | Först egna bitemporala relationskontrakt; nytt verktyg kräver förbättrad retrieval/ekonomi och källriktighet |

Endast scikit-learn och arch i tabellens forskningslager har integrerats i föregående leverans. Övriga nya kandidater är granskade förslag, inte installerade komponenter. Vid återanvändning låses release/commit och beroenden; licens/NOTICE följer med och modellen/data granskas separat från kodlicensen. Projektens benchmarktabeller och marknadsföringspåståenden är inte våra resultat. [K8–K13]

## 10 Prioriterad leveransordning och stoppkriterier

| Paket | Fas och konkret leverans | Acceptans och vad som blockerar nästa steg |
| --- | --- | --- |
| A | Fas 1: godkänt litet pris-/kalender-/bolagshändelseurval | Datamanifest, rättigheter, gap/avnoteringar och tidskorrekt replay; fel ger karantän |
| B | Fas 2: pinnad LEAN → eventnormalisering → kassabok | Inga förtida fills; avgifter, split, utdelning, positioner och kassa avstämda efter restart |
| C | Fas 2/4: kampanjregister kopplat till mogna resultat och SPA | Bortvald dålig kandidat, ändrad kostnad, saknat resultat eller återanvänt sluttest kan inte skapa giltig bekräftelse |
| D | Fas 1c/4: en dokumenttyp och en händelsefamilj med källpositioner | Kritiska fel på bolag, belopp, enhet, period och negation upptäcks; saknad källa ger avstående |
| E | Fas 4: en direkt ekonomisk relation och låst prospektiv jämförelse | Historisk graf läcker inte; händelse+graf visar inkrementellt värde mot händelse utan graf efter kostnad/osäkerhet |
| F | Fas 2/3/6: aggregerad risk, kontoreservation och futureskassa | Ingen dubbelspendering eller dubbelt konto; margin/hedge/roll klarar ofullständig exekvering |
| G | Fas 6: första och andra verkliga paperbroker | Alla avbrotts-/korrektionsprov och kontoavstämning passerar; ingen oklar order lämnas som säker avvisning |
| H | Fas 4/6: begränsad adaptiv uppdatering | Förutsäg → lås → invänta → poängsätt → uppdatera jämförs mot fryst modell; sämre kandidat stannar inaktiv |

Paketbokstäverna är arbets-ID, inte en strikt seriell fasordning. B kräver A; C kräver B; D kräver relevant fas 1c-data från A; E kräver B+C+D och låsta relationer. F kräver A+B och godkända futuresdata för futuresdelen; G kräver B och relevant F-acceptans. H kräver C och mogna etiketter; kontopåverkande D/E/H kräver även relevant F och G, och hedgepåverkan kräver futures-/hedgeacceptans i F. Dessa är beroenden, inte ett löfte om en kalenderdeadline. Kontrakt och källgranskning för senare delar kan förberedas samtidigt. Begränsad live ligger fortsatt i fas 8 och kräver separat aktivering samt både ekonomisk och operativ acceptans. Ingen månads väntan, hög träffprocent eller enstaka bra p-värde ersätter dessa kriterier.

## 11 Primärkällor och hur de används

Källorna styr metod-/licensval. Prioriteringarna och acceptanskraven är våra konstruktionsbeslut. Cohen/Frazzinis historiska studie av ekonomiska länkar motiverar en prövbar kund–leverantörshypotes, inte ett antagande om kvarvarande alpha 2026. [K14]

- K1 SEC API och begränsningar i standardiserade XBRL-fakta: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- K2 GLEIF Level 2, konsoliderande moderbolag och undantag: https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-2-data-who-owns-whom
- K3 Boyd med flera, Multi-Period Trading via Convex Optimization: https://web.stanford.edu/~boyd/papers/cvx_portfolio.html
- K4 LEAN fillmodellkontrakt: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts
- K5 arch SPA, jämför även installerad pinnad implementation: https://bashtage.github.io/arch/devel/multiple-comparison/generated/arch.bootstrap.SPA.html
- K6 Didisheim, Fraschini och Somoza, AI's predictable memory in financial analysis (2025), DOI 10.1016/j.econlet.2025.112602: https://orbilu.uni.lu/handle/10993/68692
- K7 IBKR execution object och korrigeringar: https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details/the-execution-object
- K8 LangExtract kod, grounding och licens: https://github.com/google/langextract
- K9 Qlib kod/licens: https://github.com/microsoft/qlib ; benchmarkens faktiska urval: https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md
- K10 RD-Agent kod/licens och researchflöden: https://github.com/microsoft/RD-Agent
- K11 CVXPY kod/licens: https://github.com/cvxpy/cvxpy ; Cvxportfolio kod/licens: https://github.com/cvxgrp/cvxportfolio
- K12 Graphiti kod/licens: https://github.com/getzep/graphiti ; GraphRAG kod/licens: https://github.com/microsoft/graphrag
- K13 scikit-learn train-only preprocessing: https://scikit-learn.org/stable/common_pitfalls.html ; kalibrering: https://scikit-learn.org/stable/modules/calibration.html

- K14 Cohen/Frazzini, Economic Links and Predictable Returns (2008): https://pages.stern.nyu.edu/~afrazzin/pdf/Economic%20Links%20and%20Predictable%20Returns%20-%20Cohen%20and%20Frazzini.pdf
