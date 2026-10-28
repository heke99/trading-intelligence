# Händelseintelligens: från världsnyhet till granskningsbart handelsbeslut

Datum: 28 oktober 2026. Status: konstruktion med en första körbar del för händelseinsamling och dokumenterad anläggningskontext; se [implementation och gränser](EVENT_PIPELINE.md). Prediktiv analys och nyhetsstyrd orderläggning är ännu inte implementerade.

Detta tillägg konkretiserar [masterplanens](MASTERPLAN_SV.md) avsnitt 6–10, 13–15 och fas 1c/4. Målet är att automatiskt upptäcka verkliga förändringar, härleda möjliga ekonomiska konsekvenser och pröva om en handelsmöjlighet återstår efter kostnader och risk. Roboten ska också kunna upptäcka att en tidigare hypotes är fel och avstå eller ompröva enligt godkänd policy.

De senare modell-, order- och lärandeflödena nedan är fortsatt konstruktionsförslag. Den första implementationen har läsande USGS/GDACS-adaptrar och ändrar inga handelsmandat. [Rebuild status](REBUILD_STATUS.md) är fortsatt statuskälla. Det rapporterade syntetiska LEAN-kassaboksprovet är ingen verifiering av nyhetsstrategin. Den frysta forward-piloten ändras inte.

## 1 Beslutskedja och ansvar

| Steg | Fråga | Leverans |
| --- | --- | --- |
| Upptäckt | Vad uppges ha hänt, var och när? | Originalobservation med källversion, geometri, tid och status |
| Verifiering | Vad stöds av oberoende ursprungskällor? | Belagda fakta, motsägelser, korrigeringar och kvarvarande osäkerhet |
| Exponering | Vilken anläggning, verksamhet och ekonomisk relation berörs? | Tidsversionerade exponeringspåståenden med källstöd |
| Konsekvens | Hur kan produktion, kostnad, efterfrågan och kassaflöde förändras? | Alternativa scenarier, horisonter och motbevisningsvillkor |
| Marknad | Vilken möjlighet återstår från ett genomförbart pris? | Kvarvarande prognos, kostnader, likviditet och osäkerhet |
| Portfölj | Vilken åtgärd förbättrar portföljen inom mandatet? | Avstående, minskning eller typat positionsförslag |
| Exekvering | Är förslaget fortfarande giltigt och tillåtet för kontot? | Deterministisk riskkontroll, LEAN, brokeravstämning |
| Uppföljning | Har fakta, pris eller exponering ändrats? | Ny version av bedömningen; bevarad ursprunglig prognos och utfall |

AI-läsaren får tolka källor och föreslå hypoteser. Den får inte tillgång till brokerhemligheter, ge sig själv handelsbehörighet eller skicka order. Beräkningskod skattar resultat och risk. En auktoritativ portfölj-/orderägare per konto tillämpar mandat och hanterar exekvering. Nyhetsinnehåll är data och kan aldrig ändra systemets instruktioner.

## 2 Källor med skilda roller

Ingen källa täcker allt. Ett versionsstyrt källregister ska ange geografisk och ämnesmässig täckning, datatyp, originalursprung, uppmätt fördröjning, kvoter, driftstatus och tillåtna användningar. Lagring, analys, träning, extern modellbehandling och automatisk handel behöver verifieras mot rätt avtal och avsedd användning.

| Kandidat | Roll | Begränsning som konstruktionen måste hantera |
| --- | --- | --- |
| Bloomberg Event-Driven Feeds | Maskinläsbara nyheter och metadata, nyhetsanalys och nyhetsvärde | Produktbeskrivning visar inte att vårt konto har åtkomst eller rättigheter; Terminal, webb, marknadsdata och nyhetsfeed får inte likställas |
| USGS GeoJSON | Jordbävningsobservationer, plats, magnitud och uppdateringar | Flödesuppdatering varje minut är ingen garanti för tid från händelse till rapport; magnitud bevisar inte skada på en fabrik |
| GDACS | Global upptäckt och indikativa katastrofbedömningar | Automatiska notifieringar kan ha fel och kräver validering mot originalkällor; GDACS kan återanvända samma källa som andra flöden |
| NASA FIRMS | Satellitobserverade bränder och värmeavvikelser | Global NRT-data normalt inom tre timmar efter satellitobservation, inte brandstart; en värmepunkt bevisar inte industriskada |
| NOAA/NTWC/PTWC | Officiella tsunamimeddelanden via Atom/CAP | Varning, observation, uppdatering och avblåsning är skilda tillstånd; täckningen måste uttryckas regionalt |
| Bolagets IR och regulatoriska originaldokument | Driftbesked, tillgångar, produktsegment och ekonomisk betydelse | Dokumentdatum, publicering och vår faktiska tillgänglighet är olika; tystnad betyder inte normal drift |
| Bolags-/anläggnings-/leverantörsdata | Plats till operatör, ägare, leverantör och kund | Relationer kan vara uppskattade, ofullständiga eller gamla; historiska kopplingar måste ha då kända versioner |
| Marknads- och brokerdata | Genomförbara priser, session, kapacitet, lånevillkor och marginal | Nyhetsrättigheter ersätter inte marknadsdata- eller kontobehörighet |

Utöka senare taxonomin till exempelvis krig, sanktioner, tullar, strejker, cyberincidenter, elavbrott, hamnstängningar, räntor, inflation, regleringsbesked och företagsrapporter. Varje typ behöver egna auktoritativa källor, scenarier och testning. Sociala medier kan vara upptäcktssignaler; de är inte automatiskt tillräckligt underlag för riskökning.

Behandla olika fördröjningar som olika användningsfall. Långsammare källor kan vara värdefulla för verifiering, senare följdeffekter och riskhantering. De får inte i efterhand simuleras som ett snabbt nyhetsflöde. Varken fler källor eller fler AI-roller bevisar bättre handelsresultat.

## 3 Händelse- och beviskontrakt

Följande är föreslagna kontrakt, inte nya implementerade tabeller eller API:er.

| Objekt | Minsta innehåll |
| --- | --- |
| EventObservation | Intern observationsnyckel, provider/event-ID, revisions-ID, typ, plats/geometri med koordinatsystem, geografi, allvarlighetsmått och enhet, källans händelsestatus, originalbytes/hash och källhänvisning |
| Källtider | Händelsetid eller intervall, publicering om känd, mottagning, bearbetningsklar tid, observations-/mättid där relevant samt tidszon och tidsosäkerhet |
| EventCluster | Intern incidentidentitet, ursprungskällor, återpubliceringsgrupp, relaterade delhändelser och senare rättelse/återkallelse |
| EvidenceAssessment | Påstående, stödjande/motsägande observationer, originalursprung, faktastatus, verifieringsmetod och bedömningens egen tillgänglighet |
| ExposureAssertion | Anläggning/tillgång, polygon/koordinatosäkerhet, operatör kontra ägare, produkt/kapacitet, ekonomisk relation, giltighet, då känd tid, källa och omfattning eller uttryckligt okänd omfattning |
| ImpactHypothesis | Händelseversion och datasnapshot, faktastöd, mekanism, alternativ, berörda enheter/instrument, horisont, osäkerhet, giltighet och villkor som motbevisar hypotesen |
| TradabilityAssessment | Aktuell och daterad pris-/kvoteringssnapshot, genomförbar startpunkt, fördröjning, observerad reaktion, kostnader, marknadsstatus, instrument/kontobehörighet och riskkontrollresultat |
| DecisionRecord | Hypotesversion, strategi/bok, beslutstid, route/konto/miljö, åtgärd, storlek eller avstående, utgångstid, policyversioner och orsaker |
| OutcomeRecord | Förregistrerad utfallsdefinition, horisont, mognad, validering, revisionslinje och uppdelning mellan faktakvalitet, prognos och exekvering |

Okända tider förblir okända. Varken publicering eller när en äldre relation kunde vara känd får hittas på från hämtningstid. Endast faktiskt tillgängliga och för ändamålet tillåtna data får ingå vid ett beslut. Nuvarande rättighets-/incidentspärrar får inte kringgås med ett gammalt historiskt datum. En adapter till äldre kontrakt med obligatorisk publicering behöver en explicit kompatibilitetslösning; den får inte fylla fältet med en påhittad tid.

Korrigeringar är nya oföränderliga observationer. Tidigare beslut och deras då tillgängliga underlag bevaras. En ursprunglig tsunami-varning som senare dras tillbaka måste kunna återspelas som två olika kunskapslägen.

Tio webbadresser kan återge samma telegram. Spara därför ursprungskedjan och räkna oberoende bevis efter faktisk källa. GDACS plus ett telegram som båda använder samma USGS-observation är inte tre oberoende jordbävningsmätningar. Motsägelser ska synas och kan blockera riskökning.

## 4 Geografi och ekonomisk exponering

Lokalisera verksamheten, inte bara huvudkontoret eller bolagets hemland. Skadeområde, lokal skakningsintensitet, översvämningsyta, elförsörjning och transportstopp kan vara mer relevanta än avståndet till ett epicentrum. Varje antagande om skadeområde behöver underlag och osäkerhet.

Första analyserna följer högst två källbelagda ekonomiska relationsled enligt masterplanen. Skilj den geografiska kopplingen händelse till anläggning från leverantörs-/kundleden. Cirklar och dubbla vägar får inte förstärka samma exponering flera gånger.

Bedöm exempelvis berörd produktionsandel, lager, alternativa leverantörer, reservkraft, anläggningens tålighet, försäkring, avtal, prissättningsmakt och möjlig återstart. Saknad uppgift ger osäkerhet, inte noll exponering eller en uppfunnen vikt. En konkurrent kan dela samma elnät, hamn eller leverantör och därför också förlora.

En verifierad relation bevisar inte hela den ekonomiska orsakskedjan. Direkta fakta, uppskattad omfattning och följdhypoteser ska visas separat. Om möjligt redovisas intervall och känslighet i stället för punktvärden med falsk precision.

## 5 Scenarier och kvarvarande handelsmöjlighet

För en hypotetisk jordbävning nära en produktionsanläggning kan scenarierna vara ingen betydande störning, kort produktionspaus eller längre produktions-/logistikbortfall. Separera sannolikheten för att händelsen inträffat, för faktisk driftstörning och för en framtida kursrörelse. De är olika prognoser.

Föreslagen beräkningsgrund:

E[netto-PnL(q)] = summan över scenarier s av P(s | då tillgängliga bevis och marknad) × PnL_s(q), minus förväntade handels- och finansieringskostnader.

Scenariots resultat räknas från ett pris som kan nås efter data-, analys- och orderfördröjning. Spread, slippage, avgifter, lånekostnad, finansiering och relevanta rullningskostnader räknas konsekvent utan dubbelräkning. Använd inte priset före nyheten som om roboten kunde handla där. Dra inte dessutom av en godtycklig inprisningsfaktor om prisreaktionen redan ingår i prognosen från dagens genomförbara pris.

En riskökande spekulativ kandidat behöver positiv konservativ nettofördel och klara portföljens förregistrerade gränser för stressförlust, likviditet, koncentration och marginal. Hedge och riskminskning utvärderas mot sitt deklarerade mål för portföljrisk och kostnader; en hedge kan ha negativ förväntad egen PnL men ändå förbättra portföljens riskutfall inom sitt separata mandat. Ingen universell sannolikhetsgräns eller riskprocent fastställs här. Modellens kalibrering och osäkerhet måste mätas, särskilt när antalet oberoende katastrofer är litet. En språkmodells självangivna säkerhet är inte en validerad sannolikhet. Otillräckligt underlag ger avstående.

Pröva neutral marknad, fortsatt prisreaktion, överreaktion, normalisering och förändrad marknadsregim. En korrekt berättelse om gårdagens prisfall räcker inte. Forskning om LLM och nyheter skiljer den första icke genomförbara reaktionen från senare drift [S7]; den visar inte att vår katastrofstrategi är lönsam.

## 6 Åtgärder, instrument och gemensam risk

Föreslagna analysutfall är observera, utred, avstå, föreslå minskning, föreslå long, föreslå short eller föreslå hedge. Ett förslag är inte ett ordermandat. Flera uttryck för samma hypotes jämförs under samma kostnads- och riskantaganden.

- Första aktiepiloten behåller long plus kontanter. Blankning kräver ett separat godkänt flöde med aktuell lånetillgång/locate där relevant, avgifter, återkallelser, bolagshändelser och kontokapacitet.
- Futures kräver ett explicit förfallande kontrakt, riktning, multiplikator, tick, valuta, session, avräkning och kontospecifik marginal. En kontinuerlig analysserie är inget orderinstrument.
- Första futuresflödet är fortsatt linjärt, kontantavräknat och med fast tick; första hedgeprovet följer masterplanens indexhedge. Råvaru- eller fysiskt levererade katastroftrades ingår inte automatiskt.
- En ny hedge kräver egen policy och mandat samt spårad skyddad exponering. Den kan öka bruttoexponering och kontantbehov. Marginal är säkerhet, inte maximal förlust.
- Befintlig portfölj, väntande order och nya förslag räknas ihop per konto och totalt. Fem bolag beroende av samma hamn eller chipproducent kan vara en gemensam risk. Sätt även budget per incident och exponeringskedja.
- Saldon och säkerheter får inte antas flyttbara mellan brokers. Okänd orderstatus hos en broker får inte utlösa ett försök hos en annan.

Varje position behöver en versionsstyrd exitpolicy med högsta innehavstid, riskutträde, omprövning och villkor för att hypotesen upphör. Ett utgånget analysförslag stänger inte automatiskt en befintlig position. Avblåst varning, återstartbesked och återkallat lån måste bedömas enligt positionens gällande policy. Hårda orderstopp gäller alltid; sena avslut måste fortfarande tas emot och avstämmas.

## 7 Självständig drift inom fast policy

Kontinuerlig insamling och händelsehantering körs i en långlivad worker enligt masterplanen. Mät hela kedjan: händelse/observation, publicering, mottagning, bearbetning, förslag, orderankomst och fill. En flödes uppdateringsintervall är inte en garanti för total fördröjning.

Arbetskön ska hantera återstart, omläsning, dubbletter, out-of-order-meddelanden, kvoter, saknade sidor, klockfel och feedavbrott. Spara vattenmärken och luckor. En ny artikel om samma oförändrade fakta ska inte skapa en ny position. Idempotens och portföljmål ska förhindra att upprepade eller reviderade förslag staplar oavsiktlig risk.

Skilj händelsens källstatus från analysens arbetsstatus och orderns livscykel. Vid korrigering länkas berörda hypoteser, kandidater, öppna order och positioner. Omprövning får inte skriva över den gamla prognosen, tappa en sen fill eller förutsätta att en cancel redan är bekräftad.

Bortfall eller gammalt underlag blockerar berörd ny risk enligt käll- och strategipolicy. Öppna positioner hanteras av en förberedd exitpolicy med verifierad kontostatus; ett generellt sälja allt vid nätverksfel är inget antagande. Återställning av modellkod återställer inte en brokerposition.

Roboten får automatiskt samla, kontrollera, analysera och senare handla inom ett godkänt mandat. Den får inte själv höja riskbudget, köpa datatjänster, välja livekonto eller skriva om acceptanskraven. Lärande använder mogna validerade utfall och kandidatversioner enligt masterplanen. Nya kandidater börjar i paper_only och konkurrerar med en fryst version.

## 8 Utvärdering som kan motbevisa idén

Registrera möjlighetsurval, hypoteser och avståenden före utfall. Jämför successivt prisbaslinje, direkt händelse, verifierad exponering och AI-tolkning på samma möjligheter, kapital, risk och kostnader. En meningsfull framgång är bättre verifierat nettoutfall eller riskhantering; fler affärer är inget mål.

Använd kronologiska perioder med gruppering per sammanhängande incident och överlappande prognoshorisont. Alla artiklar och bolag från samma katastrof ska hållas ihop vid delning. Anpassa förbehandling endast inom respektive träningsfönster. Kalibrera på separat kronologiskt kalibreringsmaterial som inte användes för att träna grundmodellen; använd aldrig sluttestet för anpassning eller kalibrering. Registrera alla modell-/prompt-/strategiförsök och återanvänd inte en förbrukad slutperiod som orörd.

Historiska företagsrelationer och nyheter måste ha då tillgängliga snapshots. En modern språkmodell kan redan känna till gamla katastrofers utfall. Modellens kunskapsgräns och kontamineringsrisk ska anges; maskerade namn kan vara ett diagnostiskt prov men bevisar inte frånvaro av läckage. Prospektiv skugganalys efter att modellen och protokollet frysts behövs som komplettering.

Mät separata nivåer:

| Nivå | Exempel på mätning |
| --- | --- |
| Fakta | Identitet/plats, enheter, verkliga källhänvisningar, dubbletter, rättelser och falska alarm |
| Störning | Förregistrerad driftstatus/varaktighet, källtäckning och felaktiga exponeringskopplingar |
| Prognos | Kalibrering, Brier/log loss för definierade utfall, osäkerhet och avståendets täckning |
| Handel | Netto-PnL, drawdown, stress, spread/slippage, kapacitet och verklig latens |
| Portfölj | Gemensam incidentrisk samt osäkrad bok, hedge och kombination separat |
| Drift | Förlorade/duplicerade beslut, återstart, okänd orderstatus, sena fills och avstämning |

Sällsynta händelser kräver redovisat antal oberoende incidenter och bred osäkerhet. Många prisrader från en enda katastrof är inte många oberoende prov. Syntetiska händelser provar kontrakt och motståndskraft; de etablerar ingen lönsamhet. Liknande historiska fall får inte väljas enbart för att de stödjer en önskad affär.

## 9 Byggordning och acceptans

1. Nu: specificera kontrakt och källkrav. Bevara nuvarande prisbaslinje och forward-pilot.
2. Fas 1c: en läsande händelseadapter, råarkiv, revisioner, geografi och gruppering med uttrycklig käll-/användningsstatus. Börja med en händelsetyp. Ingen handelsfunktion krävs för att verifiera insamlingen.
3. Efter tillämplig datagrund och LEAN-baslinje: en verifierad direkt exponeringskoppling och ett analyskort enligt fas 4. Jämför mot fryst baslinje innan större graf eller fler modeller.
4. Lägg till futures-/hedgeutvärdering först efter de separata avräknings-, marginal- och livscykelproven. Short kräver eget flöde.
5. Lås modell och utvärderingsprotokoll. Kör prospektiv skugganalys; sedan separat accepterad paper-ordertransport med full avstämning och en andra broker enligt masterplanen.
6. Live kräver ett separat uttryckligt beslut om konto, strategi, kapital och risk efter dokumenterad teknisk och ekonomisk acceptans. Detta dokument aktiverar inget.

Återanvänd EvidenceStore, källornas senare capturelager, ArtifactRegistryStore, OutcomeQueueStore samt broker-/futuresidentiteter. Inför inte en parallell ordermotor. Utfallsgrunden använder för närvarande förflutna UTC-sekunder; en horisont i handelssessioner behöver ett eget verifierat kalenderkontrakt.

Första acceptanspaketet ska täcka jordbävning nära respektive långt från en anläggning, värmepunkt utan bekräftad skada, tsunami-varning som avblåses, återpublicerade nyheter, verklig korrigering, två samtidiga incidenter, gammal exponeringskarta, redan flyttat pris och stängd handelsplats. Prova också promptinjektion i en artikel, feedavbrott, återstart och sena meddelanden. Innan framtida exekvering tillkommer behövs de befintliga order-/hedgeproven med delavslut och okänd status.

Klart för varje del betyder reproducerbar beviskedja, fungerande avstående och godkända specifika prov. Källåtkomst, faktakvalitet, statistisk fördel, paper-exekvering och livebehörighet är separata statusar.

## 10 Primärkällor

Kontrollerade 28 oktober 2026. Källorna styrker produkters och datas egenskaper, inte tillgång i vårt konto eller lönsamhet för den föreslagna strategin.

- S1: [Bloomberg Event-Driven Feeds](https://professional.bloomberg.com/products/data/enterprise-catalog/event-driven-feeds/) — maskinläsbara nyheter, metadata och nyhetsanalys.
- S2: [USGS GeoJSON Summary](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php) — format och flödesuppdateringar.
- S3: [GDACS Terms of Use](https://www.gdacs.org/About/termofuse.aspx) — automatiska bedömningar, osäkerhet, validering och driftbegränsningar.
- S4: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — satellitobservationer, värmeavvikelser och NRT-fördröjning.
- S5: [NOAA Tsunami Message Subscriptions](https://www.tsunami.gov/?page=productRetrieval) — Atom- och CAP-flöden samt regionala ansvarsområden.
- S6: [Bloomberg Supply Chain](https://professional.bloomberg.com/institutions/corporations/supply-chain/) — företagsrelationer, anläggningsdata och exponeringsanalys.
- S7: [Lopez-Lira och Tang, Can ChatGPT Forecast Stock Price Movements?, version 6](https://arxiv.org/abs/2304.07619v6) — skiljer första icke genomförbara prisreaktion från efterföljande drift och beskriver avtagande avkastning vid ökad användning.

Ekonomiska mekanismer, datakontrakt, beslutsregler och acceptansförslag ovan är projektets konstruktionsförslag.
