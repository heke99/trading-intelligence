# Trading Intelligence masterplan för aktier ETF och fonder

Version 1.0 · 20 oktober 2026 · För Hekmat Hourani

## 1 Beslut och mål

Trading Intelligence byggs om från en Collective2-importör till en plattform för bolagsanalys, kvantitativ forskning, portföljförvaltning och kontrollerad handel. Kärnan är en tidskorrekt dataplattform som försörjer flera strategier. AI läser och tolkar dokument. Beräkningskod räknar signaler och risk. En separat handelsmotor hanterar order och avstämning.

Målet är att hitta robusta samband efter kostnader och kunna förklara varje beslut. Systemet ska kunna avstå när underlaget är otillräckligt. Varken en känd traders historik, fler AI-roller eller en komplicerad modell visar i sig att en strategi är lönsam.

Första produkten är ett privat forsknings- och beslutsstöd för egen användning. Den förbereds för flera konton, dataleverantörer och mäklare genom tydliga kontrakt. Kundhandel, förvaltning åt andra och publik försäljning av signaler ingår inte i den första leveransen; en sådan produkt kräver en separat produkt- och regelgenomgång.

Prioriterade beslut:

- Aktier och vanliga ETF:er blir första instrumenten för simulerad börshandel. Hävstångsprodukter, inversa ETF:er och enaktie-ETF:er utesluts i piloten.
- Vanliga öppna fonder får analysstöd tidigt men ett separat orderflöde för NAV, bryttider och likviddagar.
- Intradag, händelsestyrd swing och långsiktig allokering får separata strategiböcker, modeller och resultatmått.
- LEAN utvärderas som första börshandelsmotor. Qlib är ett senare forskningsverktyg. NautilusTrader är ett alternativ, inte en extra motor som installeras samtidigt.
- Traderhistorik blir en kompletterande datakälla. Egen marknads- och händelsehistorik gör att projektet kan fortsätta även när privata orderloggar saknas.
- Ingen tränings- eller liveberedskap antas. Varje dataset och strategi måste få egna verifierade statusar.

## 2 Ombyggnad och rensning av projektet

Utgångspunkten är heke99/trading-intelligence vid commit 8c5056112721345540ea1cfbbca1f4c41fa816e8. Den befintliga koden är en läsande Collective2-importör. Dess README anger att modellen, marknadsdatakoppling och handelsmotor ännu saknas. Denna masterplan ersätter projektets tidigare produktinriktning.

Rensningen görs som en granskningsbar förändring på en separat gren. Den gamla versionen bevaras i arkivgrenen archive/collective2-v0.1-before-equities-2026-10-20. Git-historik, externa dataarkiv och eventuella privata originalexporter ska inte raderas. Ingen force push behövs.

På den nya grenen ersätts den gamla appkoden, dess tester, demonstrationer och Collective2-specifika produktdokument av en ren planeringsgrund. Det innebär inte att en ny fungerande app redan finns. Efter granskning kan samma gren utvecklas enligt byggordningen nedan. Huvudgrenen ändras först genom en vanlig merge.

Det som bör återinföras efter separat kodgranskning är idéerna om oföränderliga rådata, källklassning, versionshistorik, karantän för tvetydiga rader, exakta decimaler, idempotenta importer och tydliga tidszoner. Collective2 blir en valfri adapter. Forex-, CFD- och MT5-antaganden ska inte styra det nya instrumentregistret.

Överför inte gamla testantal, syntetiska exempel eller resultat till den nya plattformens verifieringsstatus. Arkivets tester verifierar den gamla importören. De visar inte att den nya produkten fungerar eller att någon verklig traderhistorik har hämtats.

## 3 Instrument och tidshorisonter

| Instrument | Analys | Ordermodell | Första omfattning |
| --- | --- | --- | --- |
| Noterade aktier | Bolag, rapporter, pris, volym och händelser | Börsorder med aktuella kvoteringar | Första börspiloten |
| ETF | Exponering, innehav, kostnad, överlapp och likviditet | Börsorder som separat värdepapper | Obelånade instrument som kontot får handla |
| Vanlig öppen fond | NAV, andelsklass, avgifter, benchmark och förvaltning | Teckning eller inlösen till relevant framtida fondkurs | Analys först, orderadapter senare |
| Index | Marknadsläge och jämförelse | Ingen direkt order | Referensdata |
| Valuta | Omräkning, kassabok och ekonomisk exponering | Eventuell kontoväxling via mäklaradapter | Ingen egen valutastrategi |
| Optioner, terminer och komplexa produkter | Senare separat forskningsområde | Egna kontrakt och riskmodeller | Utanför första versionen |

ETF:er handlas under börsdagen till marknadspris. En vanlig fond får normalt en fondkurs som ännu inte är känd när ordern lämnas. Fond och distributör kan ha olika bryttider, kursdagar och bokföringsdagar. En NAV som publiceras senare får inte användas som indata före orderbeslutet. Den kan däremot vara korrekt avslutskurs i efterhand för en accepterad order, enligt fondens och distributörens faktiska regler. [S1, S2]

För en svensk användare skiljer vi analysuniversum från det aktuella kontots handelsuniversum. Ett instrument kan analyseras även om det inte kan köpas. Instrumentbehörighet, produktdokument, konto, mäklare och bosättningsland måste kontrolleras. Ingen automatisk ersättning med CFD, derivat eller en till synes likadan ETF tillåts. [S3]

Första forskningsurvalet är ungefär 30–50 likvida amerikanska aktier i ett sammanhängande bolagsnätverk. En separat historisk urvalsregel används i backtest, inklusive bolag som senare försvunnit. ETF-piloten använder ett litet dokumenterat urval; vilka som faktiskt kan handlas avgörs efter kontoverifiering. Vanliga fonder börjar som bevaknings- och allokeringsunderlag.

## 4 Arkitektur och ansvar

Vi börjar med ett sammanhållet repo, tydliga moduler och ett litet antal driftsatta tjänster. Det är enklare att felsöka och avstämma än ett stort nät av mikrotjänster.

| Del | Förslag | Ansvar |
| --- | --- | --- |
| Webb | Next.js, React och TypeScript | Bevakning, analyskort, experiment och portföljöversikt |
| Identitet och transaktionsdata | Supabase Auth och Postgres | Användare, åtkomst, instrument, jobb, beslut och orderbokföring |
| API och forskning | Python med FastAPI | Import, datavalidering, egenskaper, etiketter och modellkörningar |
| Rådata och stora serier | Objektlagring och Parquet | Versionerade dokument, priser, kvoteringar och dataset |
| Lokal analys | DuckDB och Polars | Effektiva frågor och reproducerbara datasetbyggen |
| AI för dokument | Avgränsad eve-tjänst i TypeScript | Läsning, källutvinning, motargument och strukturerade analyskort |
| Börssimulering och order | LEAN-worker | Samma strategikontrakt i historisk simulering och kontrollerad exekvering |
| Jobb | En Postgres-baserad jobbkatalog och worker i starten | Schemaläggning, låsning, försök, hjärtslag och återhämtning |

eve är ett förslag för den nya AI-tjänsten, inte för själva orderloopen. Verktygen får läsa godkända datasnapshots och kalla beräkningsfunktioner. De får inte skicka mäklarorder. Projektets installerade versionsdokumentation ska styra implementationen. [S4]

Webben kan ligga på Vercel. Kontinuerliga marknadsflöden, forskningsjobb och mäklaranslutningar ska köras i lämpliga långlivade containrar, exempelvis Railway eller en separat worker-värd efter tekniskt prov. Handelsmotorn ska inte vara beroende av att en webbsida är öppen. Plats för drift, data och backup väljs utifrån leverantörernas villkor och uppmätt behov.

Postgres är kontrollplan och bokföring, inte standarddestination för varje börstick. Relationer kan börja som vanliga tidsversionerade tabeller. Separat grafdatabas, Kafka, ClickHouse och vektordatabas införs först när en uppmätt begränsning motiverar dem. En sökbar dokumentkatalog räcker för första beviskedjan.

Föreslagna moduler är web, research_api, ingestion, research_agent, execution_worker, fund_worker, contracts, strategies, evaluations, infra och docs. API-kontrakt definieras med OpenAPI och JSON Schema; TypeScript-typer genereras och testas mot Python-modeller. Tomma moduler presenteras inte som implementerade funktioner.

## 5 Open source som återanvänds och utvärderas

| Projekt | Roll | Licens eller villkor att kontrollera | Beslut |
| --- | --- | --- | --- |
| QuantConnect LEAN | Historisk simulering och handel för aktier och ETF | Apache 2.0 för motorn; CLI, moln och data har separata villkor | Förstahandsval för motorprovet |
| Microsoft Qlib | Forskning, egenskaper och modellutvärdering | MIT | Senare om det sparar forskningsarbete |
| NautilusTrader | Tickdata, orderbok och händelsestyrd exekvering | LGPL 3.0; verifiera vald version och adapter | Alternativ om intradagskraven motiverar motorbyte |
| Finance Skills | Rutiner för värdering, rapporter, estimat och likviditet | MIT; källdata har egna villkor | Läs och anpassa utvalda arbetsflöden |
| Octagon Skills | Rapporter, SEC och rapportsamtal | MIT; beroende av Octagon MCP och dataåtkomst | Referens och valfri integration |
| TradingAgents | Analysroller och motargument | Apache 2.0 | Referens för forskningsflödet |
| scikit-learn och LightGBM | Baslinjer, klassificering, regression och rangordning | Verifiera paketens aktuella licenser | Numeriska modeller före djupinlärning |
| DuckDB och Polars | Analys av Parquet och tabeller | Verifiera vald release och beroenden | Databearbetning |
| MLflow | Registrering av experiment och modeller | Verifiera vald release | Inför när modellförsöken börjar |
| eve | Versionerade AI-verktyg och analysflöden | Verifiera vald release och runtimevillkor | Avgränsad analystjänst |

LEAN-motorns öppna licens betyder inte att hela standardflödet är gratis. Den nuvarande officiella CLI-dokumentationen kräver medlemskap i en QuantConnect-organisation på betald nivå. Vi väljer mellan direkt drift av motorn och ett abonnemang efter motorprovet och kostnadsjämförelsen. [S5, S6]

NautilusTrader dokumenterar en versionsövergång. Adapterstöd och stabil release måste kontrolleras innan det väljs. Qlib ska inte bli en andra auktoritativ ordermotor. TradingAgents är inte belägg för en lönsam strategi. [S7, S8, S9]

Alla importerade delar får källadress, commit eller release, licens, NOTICE där det krävs, ändringshistorik och ansvarig modul. Skills granskas som kod och instruktioner före användning. Vi installerar inte breda sociala läsare eller godtyckliga tradingverktyg för att en analysrutin behöver ett rapportfält. Open source-instruktioner ger inte automatiskt rätt att lagra, återdistribuera eller träna på en extern tjänsts data. [S10, S11]

## 6 Datakällor och anskaffning

| Datatyp | Första väg | Vad som måste verifieras |
| --- | --- | --- |
| Amerikanska rapporter | SEC EDGAR och bolagets investerarsida | Inlämning, publicering, dokumentversion och rätt enhet |
| Nyheter | Ett strukturerat flöde, exempelvis Alpaca med Benzinga | Licens, historisk täckning, revisionshistorik och faktisk fördröjning |
| Priser och kvoteringar | En leverantör vald efter jämförelseprov | Marknadsplatstäckning, bolagshändelser, avnoterade instrument och lagringsrätt |
| Djup orderbok | Separat börs- eller leverantörsavtal om strategin behöver det | MBO eller MBP, feed, tidsstämplar, paketluckor och replay |
| Identiteter | Internt register med OpenFIGI som mappningshjälp | Andelsklass, notering, MIC, valuta och historik |
| Koncernrelationer | Bolagsrapporter och GLEIF | Typ av kontroll, giltighet och källstöd |
| Kund och leverantör | Originalrapporter; kommersiell källa om täckningen kräver det | Relationens ekonomiska betydelse och historik |
| Estimat | Leverantör med historik över då kända prognoser | Vintage, publiceringstid och senare revideringar |
| Makro | Officiella källor och ALFRED där tillämpligt | Den då tillgängliga dataversionen, inte senaste revideringen |
| Fonder | Fondbolag, distributör eller licensierad datakälla | ISIN, andelsklass, NAV-datum, publicering, avgifter och bryttid |

SEC:s publika API:er ger inlämningshistorik och XBRL utan API-nyckel. Originaldokument behövs fortfarande för relationer och redovisningssammanhang. Vi följer SEC:s aktuella åtkomstregler och begränsar anrop. [S12]

Alpacas nyhetsdokumentation anger Benzinga-innehåll och historik från 2015. Det är en kandidat, inte en garanti för att alla nyheter, historiska versioner eller önskade träningsrättigheter finns. Alpacas kostnadsfria liveflöde för aktier omfattar IEX; konsoliderade amerikanska affärer och kvoteringar är en annan datanivå. SIP är inte en fullständig djup orderbok. [S13, S14]

GLEIF beskriver direkt och yttersta redovisningsmässigt konsoliderande moderbolag. Det ska inte etiketteras som ett komplett register över verkliga huvudmän eller alla aktieägare. [S15]

För varje leverantör görs ett begränsat prov med normala dagar, rapportdagar, en split, ett namnbyte, en avnotering och en korrigerad datapunkt. Köpbeslut kräver uppmätt täckning och offert. Inga obekräftade månadspriser läggs in som fakta i budgeten.

## 7 Datakontrakt och tid som systemet kan lita på

Varje källobjekt får source_id, provider_record_id, rådatahash, source_url, publicerad tid, mottagen tid, uppdaterad tid, originaltidszon, tolkningsregel och versionsnummer. Tidszoner uttrycks med IANA-namn. UTC används internt, men ursprungstiden bevaras. Sommartid, börshelgdagar och tidiga stängningar testas.

Vi skiljer mellan händelsens ekonomiska tid och tidpunkten när informationen var känd. För livebeslut måste informationen vara mottagen och färdigbehandlad före beslutet. I historisk replay krävs belagd historisk tillgänglighet och modellerad leverans- och beräkningsfördröjning. Att hämta en artikel idag med ett gammalt datum bevisar inte vilken text som fanns då.

Restaterade rapporttal, uppdaterade artiklar och reviderad makrodata blir nya versioner. De ersätter inte tidigare kunskap. För marknadsdata hanteras korrigerade affärer och efterhandsjusteringar med samma princip. Avkastningsserier och råa exekveringspriser hålls separata; utdelning och split får inte räknas två gånger.

| Datagrupp | Centrala objekt | Viktiga krav |
| --- | --- | --- |
| Källor | data_sources, source_rights, ingestion_runs, raw_objects | Åtkomst, tillåten användning, täckning och oföränderliga original |
| Identitet | entities, instruments, listings, identifier_history | Bolag är inte samma sak som aktieklass eller notering |
| Historik | corporate_actions, universe_memberships, calendars | Giltighetsperiod och när uppgiften blev känd |
| Information | documents, document_versions, facts, events, relationships | Källstycke, siffror, enheter, känd tid och ekonomisk exponering |
| Traderdata | trader_accounts, order_events, fills, fees, cashflows | Verifierad mäklarhistorik, modellhistorik och papper hålls isär |
| Forskning | opportunities, feature_snapshots, labels, experiments | Beslutstid, egenskapsversion, utfallshorisont och datasnapshot |
| Modeller | model_versions, calibrations, evaluation_runs | Träningsperiod, försökshistorik och godkänd användning |
| Handel | decisions, risk_checks, orders, executions, reconciliations | Spårbara orderstatusar, kassaflöden och avstämning |
| Fonder | fund_terms, fund_navs, subscriptions, redemptions | Bryttid, kursdag, publicering, accepterad order och likviddag |

Värdepapper får intern instrumentidentitet med separata mappningar till ISIN, FIGI, börsnotering och mäklarens kontrakts-ID. En ticker räcker inte. Automatisk textlikhet får föreslå en matchning men inte godkänna en tvetydig order. OpenFIGI är en hjälp för identifierare, inte ett fullständigt historiskt värdepappersregister. [S16]

Ett datasets status delas upp i åtkomst, rättigheter, tidskvalitet, fullständighet och tillåtet forskningsändamål. full_history_verified och training_ready förblir false tills just det materialet uppfyller dokumenterade krav. En lyckad import räcker inte. Uttalat okända värden ska förbli okända.

## 8 Bolagsgraf och ekonomiska samband

Grafen innehåller juridiska enheter, personer med offentligt dokumenterade roller, produkter, verksamhetssegment och relevanta tillgångar. Relationer har typ, riktning, giltighet, känd tid, källa och omfattning. Skilj ägande från styrelseuppdrag, samarbete och operativ kontroll.

En leverantörsrelation behöver produktområde, berörd geografi och när möjligt andel av omsättning eller inköp. Om storleken saknas anges relation verifierad och exponering okänd. Låg källsäkerhet får inte kompenseras av en övertygande berättelse.

Första hypotesen följer en direkt relation: en kund ändrar investeringar eller efterfrågan och en identifierad leverantör kan påverkas. AI ska beskriva mekanismen, omständigheter som kan motverka den och vad priset redan gjort. Gemensam ägare är främst struktur- och riskinformation tills prognosvärde har testats.

Högst två relationsled analyseras i den första versionen, med tydligt stöd i varje led och utan cirkulär förstärkning. Fem artiklar som återger samma pressmeddelande blir en händelse med flera återpubliceringar, inte fem oberoende bevis. Korrelation är inte bevis för en orsakskedja.

Grafen används också för genomlysning av portföljen. Direktägda aktier och samma innehav genom ETF:er eller fonder ska kunna visas som samlad exponering. Innehavslistans faktiska datum, publiceringsdatum och täckning måste synas; inaktuella eller ofullständiga innehav får inte presenteras som exakt dagsrisk.

## 9 AI analyser och granskningsbart resonemang

AI-tjänsten ska lämna korta, strukturerade beslutsunderlag med kontrollerbart källstöd. Vi behöver inte en lång intern tankekedja. Vi behöver belagda fakta, redovisade antaganden, motargument och en tydlig anledning att gå vidare eller avstå.

| Analys | Fråga | Leverans |
| --- | --- | --- |
| Händelse | Vad har faktiskt förändrats och när? | Händelsetyp, bolag, siffror, perioder och källstycken |
| Rapport | Vad överraskade jämfört med då kända förväntningar? | Utfall, vintage för prognos, guidning och segment |
| Fundamental | Hur utvecklas affär och finansiering? | Tillväxt, marginaler, kassaflöde, skulder och utspädning |
| Värdering | Vilka förväntningar förutsätter priset? | Dokumenterade scenarier och känslighetsanalys |
| Bolagsrelation | Vilka andra bolag är ekonomiskt exponerade? | Belagd relation, mekanism och okänd omfattning |
| Marknad och sektor | Vilka omständigheter ändrar signalens relevans? | Kodberäknade tillstånd och möjlig förklaring |
| Fond | Vad äger vi och vad kostar exponeringen? | Andelsklass, risk, överlapp, benchmark och avgifter |
| Motargument | Vad gör hypotesen fel? | Alternativa förklaringar och villkor som måste följas |

Varje analystjänst får tillåtna verktyg, typade in- och utdata, tidsgräns, kostnadsbudget, testfall och avstå-svar. Externa artiklar, webbsidor och traderkommentarer behandlas som data och kan inte ändra instruktioner, hämta hemligheter eller ge orderbehörighet.

Analyskortet innehåller event_id, snapshot_id, beslutstid, instrument, horisont, bekräftade fakta, relationer, hypotes, motargument, osäkerheter och nästa kontroll. Språkmodellens egen säkerhet är inte en kalibrerad sannolikhet för vinst. Om en numerisk prognos används kommer den från en utvärderad modell med dokumenterad kalibrering.

Modellnamn, promptversion, verktygsresultat, datahash och beräkningsversion sparas. Modeller ska kunna bytas genom ett leverantörsoberoende kontrakt. Små modeller kan användas för sortering; svårare eller motsägelsefulla fall kan få mer analys inom budgeten. Fler roller eller modeller införs bara om mätningen visar bättre kvalitet per kostnad och fördröjning.

Ett första granskningsmaterial bör innehålla 100–200 händelser med positiva, negativa, tvetydiga och irrelevanta exempel. Mät rätt identifiering, korrekta siffror och enheter, giltiga källhänvisningar, förväxlingar, dubbletter och välmotiverat avstående. Föreslaget första krav är full spårbarhet för fakta som används i en handelskandidat och inga olösta kritiska identitets- eller tidsfel.

## 10 Strategier och algoritmer

Varje strategi definieras innan slututvärderingen: syfte, universum, tillgänglig information, beslutstid, in- och utträde, positionering, kostnader, avstående, benchmark, primärt mått och stoppvillkor. Parametervarianter räknas som forskningsförsök och registreras även när de går dåligt.

| Strategi | Första testbara hypotes | Horisont | Baslinje |
| --- | --- | --- | --- |
| Intradag | Fortsättning efter ett definierat öppningsintervall, villkorad på likviditet och volatilitet | Minuter till stängning | Samma regel utan AI och traderdata |
| Rapport och guidning | Ny information relativt förhandsförväntningar tillför prognosvärde | 1–20 handelsdagar | Pris och volym före händelsen |
| Kund och leverantör | Kundens efterfrågehändelse förbättrar prognosen för dokumenterat exponerad leverantör | 1–20 handelsdagar | Direkta bolagsnyheter utan graf |
| Långsiktiga aktier | Kombination av kvalitet, värdering och momentum ger bättre riskjusterad utveckling än enkel baslinje | Månatlig ombalansering, innehav i månader eller år | Riskjämförbart brett totalavkastningsindex |
| ETF och fondallokering | Kontrollerad ombalansering förbättrar vald riskprofil efter omsättning och kostnad | Vecka eller månad | Fast dokumenterad allokering |
| Ägarhändelser | Publicerade köp eller uttalade ägarplaner ger ytterligare information | Dagar till månader | Samma modell utan ägardata |

Detta är forskningshypoteser, inte färdiga köpstrategier. Till exempel ska intervallets längd, likviditetsfilter och exit i intradagstestet frysas före sluttestet. Val av aktier får inte baseras på vilka som senare blev vinnare. Intradag är inte automatiskt högfrekvenshandel; den första versionen ska tåla uppmätt normal feed-, modell- och orderfördröjning.

Stapelns stängningspris och intervallets högsta eller lägsta pris blir tillgängliga först när respektive period är avslutad. Simulerat avslut sker först efter beslutstid och modellerad fördröjning vid ett möjligt exekveringspris. Om både stop och mål berörs i samma stapel krävs tickreplay eller dokumenterad konservativ hantering. En berörd limitkurs är inte i sig bevis för ett möjligt avslut.

Första algoritmlagret är deterministiska regler och enkla statistiska modeller. Därefter jämförs regulariserad regression och LightGBM för riktning, rangordning, förväntad nettoöveravkastning eller kvantiler. Djupinlärning, reinforcement learning och avancerade regimmodeller införs först om enklare alternativ lämnar ett tydligt problem olöst.

Egenskaper kan omfatta relativ styrka, volym, volatilitet, spread, rapportöverraskning, nyhetsnyhet, försäljningsberoende och värderingsmått. Normalisering, imputering, urval och kalibrering lärs endast på träningsperioden. Inga framtida exitpriser, efterhandsberäknade trade-VWAP eller senare artikelformuleringar får användas som ingångsegenskaper.

Modellens förslag jämförs med förväntade handelskostnader, osäkerhet och riskbudget. Vi väljer inte en godtycklig summa av AI-betyg som köpknapp. Avstå blir ett uttryckligt alternativ. Samtidiga signaler vägs i en portföljpolicy som hanterar nettoexponering, likviditet, sektor och gemensamma beroenden.

## 11 Traderhistorik som kompletterande läromaterial

Vi skiljer tre uppgifter: förstå traderns beteende, förutsäga marknadens framtida utfall och bestämma vår egen risk och orderläggning. En skicklig traders avslut är demonstrationer av handlingar. De är inte automatiskt etiketter för den optimala handlingen.

| Källa | Möjligt underlag | Användningsgräns |
| --- | --- | --- |
| Deltagande traders | Originalexporter, hela kontoperioder och journaler | Kräver avstämd historik och rätt till avtalad användning |
| Collective2 | Strategiorder och avslutade affärer via dokumenterade API:er | Modellhistorik hålls separat från verifierade mäklaravslut |
| Kinfo eller liknande | Mäklarverifierade profiler och resultat | Profilen bevisar inte komplett export eller träningsrätt |
| Offentliga intradagsgenomgångar | Exempel på setups och förklaringar | Urval, ofullständig tidsinformation och efterhandsförklaring märks |
| SEC 13F | Rapporterade kvartalsinnehav | Inga exakta köpdatum eller fullständiga orderloggar |
| SEC Form 4 och 13D | Rapporterade transaktioner och vissa uttalade planer | Publiceringsfördröjning, transaktionstyp och fotnoter behövs |
| ARK | Dagliga innehav och meddelanden efter stängning | Officiellt historiskt handelsarkiv erbjuds inte |

Collective2 dokumenterar historiska order och avslutade trades, men åtkomst, täckning och användningsrätt måste verifieras för vårt konto och varje strategi. Tjänstens hypotetiska resultat blandas inte med kontoavslut. IBKR:s Flex Queries är en konkret exportväg när en kontoinnehavare deltar. [S17, S18, S19]

13F är kvartalsinnehav och lämnas normalt inom 45 dagar. Form 4 lämnas i de flesta fall inom två arbetsdagar och kan avse annat än ett vanligt börsköp. 13D:s planer och transaktionsuppgifter är användbara händelser men ingen fullständig investerarlogg. Alla signaler börjar när informationen faktiskt blev offentlig, med relevant fördröjning. ARK anger uttryckligen att historiska handelsarkiv inte tillhandahålls. [S20, S21, S22, S23]

För varje trader behövs tidsstämplade delavslut, orderkedja, ändringar, avgifter, cash flows, kontovaluta och kapitalhistorik. Vi tar med förlustperioder, misslyckade strategier och nedlagda konton när de finns. Traders viktas inte efter social räckvidd eller en utvald avkastningsbild.

Utan bevakningslista eller aktivitet vet vi inte vad tradern valde bort. En minut utan avslut etiketteras därför som oobserverad, inte avstått köp. Vårt eget system ska från första dagen logga alla kvalificerade kandidater och skälen till köp, sälj, minskning eller avstående.

Historiken kompletteras med marknadsdata som fanns före handlingen. Beteendemodeller får föreslå regler att testa. Om tradern saknar dokumenterad ursprunglig stop eller motivering fyller AI inte i den som fakta. Video eller journal kan ge en hypotes med separat källklassning.

## 12 Fonder och genomlysning av exponering

För varje fond skiljer vi fond, andelsklass och eventuell börsnotering. Avgifter, minsta köp, utdelande eller ackumulerande klass, valuta, valutasäkring, distributionsvillkor och benchmark sparas separat. Handelsvaluta beskriver inte hela den ekonomiska valutarisk som fonden bär.

Fondanalysen omfattar totalavkastning, risk, jämförelse mot benchmark, koncentration, innehavsöverlapp, förvaltarbyte och ändrat mandat. ETF-analysen lägger till spread, likviditet, replikering och premie eller rabatt mot relevant NAV. Publiceringstid och datans ålder ska synas.

ETF-pris och NAV måste jämföras vid förenliga tidpunkter och med hänsyn till underliggande marknaders öppettider. Gårdagens NAV eller en stängd utländsk marknad får inte ge sken av en aktuell riskfri prisskillnad.

Löpande fondavgifter som redan påverkat NAV ska inte dras en gång till i simuleringen. Direkta transaktionsavgifter, spread, FX och eventuella prestationsavgifter hanteras utifrån källans exakta definition. Samma princip gäller totalavkastningsserier där utdelning redan återinvesterats.

Fondordern har egna steg: mottagen, behörighetskontrollerad, lämnad till distributör, accepterad, väntar på kurs, prissatt, bokförd, likviderad eller avvisad. Bryttid och kalender är fond- och distributörsspecifika. Tillgängligt kontantsaldo ska ta hänsyn till att en försäljning inte alltid kan finansiera ett samtidigt köp omedelbart.

Automatiska fondorder aktiveras först när en vald mäklare faktiskt stöder teckning och inlösen genom ett verifierat gränssnitt. Tills dess finns analys, manuella orderunderlag och separat simulering. Ett anpassat datafält i LEAN bevisar inte fungerande fondorder.

## 13 Risk portfölj och orderhantering

Varje strategi har egen bok och riskbudget. Det hindrar att en förlorande intradagsaffär byter etikett till långsiktigt innehav. En gemensam portföljmotor räknar samlad ekonomisk exponering och mäklarordrar. Om två strategier vill samma instrument ska tilldelning och intern nettning vara förklarlig.

Riskpolicyn omfattar position, total och nettoexponering, sektor, beroenden, volatilitet, omsättning, kassareserv och maximal tillåten förlust enligt valda mått. Gränser konfigureras före körning. Det finns inga löften om att en stop begränsar förlusten vid gap, avbrott eller avsaknad av likviditet.

Den första börspiloten använder köp och kontanter. Blankning kräver senare verifierade lån, locate, avgifter och mäklarvillkor. Riskgränser i procent eller kronor bestäms när kapital, kontotyp och kostnadsmodell är kända; de ska inte härledas från en språkmodells säkerhetsbetyg.

Ordermotorn hanterar förslag, riskkontroll, skickad order, kvittens, delavslut, avslut, avbeställning, avvisning och okänd status. Varje order får idempotensnyckel och beständig koppling till beslutet. Vid timeout får motorn inte anta att ingen order finns och skicka en ny utan kontroll.

Mäklaren är auktoritet för externa avslut. Det interna systemet avstämmer order, innehav, avgifter och kassa vid start, återanslutning och löpande. Olöst kritisk differens blockerar nya order. Avgifter, likviddag, öppettider, prissteg, valutahantering och stödda ordertyper ligger i tidsversionerade mäklarkapaciteter.

Varje konto har exakt en aktiv orderägare. Ett ledarlås med utgångstid och ett stigande ägarskapstoken kontrolleras vid orderutskick, så att en gammal worker inte fortsätter handla efter failover. Idempotensnycklar ersätter inte detta skydd. Förlorad ägarskapssignal blockerar nya order och kräver avstämning före återstart.

Nödstoppet ska ha definierad innebörd: stoppa nya order, försöka avbeställa öppna order och rapportera kvarvarande exponering. Automatisk försäljning av alla innehav är en separat policy. För vanliga fonder kan en redan accepterad order sakna möjlighet att återkallas.

## 14 Tester som skiljer resultat från efterhandsanpassning

Tester delas mellan dataintegritet, analyskvalitet, prognosvärde, portföljresultat och operationell funktion. Ett grönt tekniskt test visar inte positiv nettoavkastning.

1. Frys hypotes, urvalsregel, horisont, label, kostnadsmodell och primärt mått före sluttestet.
2. Dela kronologiskt med rullande träning och senare validering. Ta bort träningsobservationer vars utfallsperiod överlappar validering eller test. Gruppera samma nyhet och relaterade bolagshändelser så att de inte läcker mellan delar.
3. Lär endast förbehandling och modellval på träningsmaterialet. Oregelbundna händelser kräver en egen tids- och gruppdelning; en standardfunktion är inte automatiskt korrekt. [S24]
4. Jämför kontanter, riskjämförbar benchmark, enkla prisregler, direkta nyheter, graf och traderinformation. Ta bort ett lager i taget för att mäta dess bidrag.
5. Registrera alla försök. Håll en sista period orörd. Skatta osäkerhet med hänsyn till att affärer samma dag eller kring samma händelse är beroende. Många trades är inte lika med många oberoende observationer. [S25]
6. Stressa spread, latens, avgifter, marknadspåverkan, delavslut, uteblivna avslut, gap, stopp och sämre feed. Visa resultat per period, sektor, instrument och marknadsläge.
7. Kör framåtriktad skugganalys och därefter simulerad orderhantering. Jämför vad systemet förutsåg med vad som faktiskt fanns tillgängligt.

Historiska tester med en modern språkmodell kan innehålla kunskap om senare utfall från modellens förträning. Att dölja framtida dokument i vår egen databas löser inte hela det problemet. Framåtriktade resultat och enklare textmodeller är viktiga jämförelser.

Rapporten visar avkastning efter modellerade kostnader, drawdown, nedsiderisk, kapitalbindning, turnover, kapacitet, benchmarkexponering och osäkerhet. Win rate är inte ett huvudbevis. Valda trösklar måste förregistreras per strategi när datatäckning och realistiska kostnader är kända.

Innan live måste varje strategi klara den förregistrerade bedömningen av nettoresultat, risk, osäkerhet och bidrag jämfört med baslinjen på orört testmaterial och framåtriktade observationer. Operationell stabilitet räcker inte. Om underlaget är negativt eller för svagt stannar strategin i forskning eller simulerad handel.

## 15 Lärande minne och modelluppdateringar

Minne består av tidsstämplade analysfall, källor, prognoser, avståenden och senare utfall. Det hämtar liknande tidigare situationer som var avslutade och kända före det nya beslutet. En senare förklaring får inte ändra den ursprungliga beslutsloggen.

Vi skiljer mellan faktisk observation, analys som gjordes då och efterhandsutvärdering. Minnet får stödja hypoteser och felsökning. Det är inte bevis för att en ny situation får samma utfall. Utvärdera om minneshämtning förbättrar resultatet jämfört med samma modell utan minne.

Modelluppdateringar sker som challenger mot en befintlig version. De får ett fryst dataset, hela experimenthistoriken, oberoende utvärdering och ett spårbart beslut om eventuell ersättning. En uppdatering marknadsförs inte automatiskt för att ett kort backtest förbättras.

Drift i data, modell eller exekveringskostnad kan minska risk eller stoppa nya order. Den ska inte utlösa fri självändring av produktionens strategi. Felsökning, omträning och återaktivering är separata steg med rollback.

## 16 Webb och användarflöden

Gränssnittet byggs för att användaren ska kunna följa bevis och resultat. Det ska inte visa en dekorativ AI-poäng utan förklaring.

- Översikt visar kontantandel, samlad exponering, datastatus och aktiva strategier.
- Bevakning visar bolag och instrument, aktuella händelser och källornas ålder.
- Analyskort visar bekräftade uppgifter, relationer, antaganden, motargument och beslut.
- Bolagsvyn samlar rapporter, nyheter, värdering och en filtrerbar relationskarta.
- Fondvyn visar andelsklass, avgifter, innehav, överlapp och ordervillkor.
- Forskningsvyn jämför baslinjer och modeller på samma tidsperiod och kostnadsantaganden.
- Traderdata visar verifieringsnivå, täckning och avstämning före eventuell forskningsanvändning.
- Order och portfölj visar livscykel, delavslut, avgifter och avvikelser mot mäklaren.
- Driftvyn visar fördröjning, jobb, dataluckor, kostnader och nödstopp.

Inläst artikel får en direkt källänk och synlig versionstid. Statusarna analys, skuggläge, simulerad handel och live ska alltid kunna skiljas åt. Mobilvyn prioriterar bevakning, läsning, avvikelser och stoppfunktioner.

## 17 Säkerhet och drift

Forsknings-, simulerings- och livekonton får separata miljöer och behörigheter. AI-tjänsten saknar handelshemligheter. Webbläsaren får inte mäklarnycklar eller Supabase service_role. RLS och lagringspolicyer testas för det faktiska ägarskapet; en inloggning räcker inte som behörighetskontroll.

Originalexporter och licensierade dokument förvaras privat med åtkomstlogg och fastställd retention. Bara syntetiska eller uttryckligen tillåtna fixtures får ligga i det publika repot. Publikt tillgänglig information och rätt att träna på den är separata frågor.

Backuper ska återläsas i prov. Rådata, konfiguration, databas och modellversioner behöver tillsammans kunna återskapa en körning. Jobb har lås, timeout, återförsök med backoff och en tydlig fellista. Samma jobb får inte producera dubbla dataset eller order.

Övervakning följer feedfördröjning, saknade data, antal karantänrader, analysfel, modellkostnad, avvisade riskkontroller, mäklarkontakt och avstämningsdifferenser. Produktionsberoenden och containrar versionslåses. Underhållsregler och API-förändringar kontrolleras före uppgradering.

För Supabase följs aktuell dokumentation, RLS och nyckelhantering. Databasen ska inte göras publikt läsbar för att förenkla utveckling. Den aviserade avvecklingen av äldre TLS-cipherkombinationer i november 2026 ska beaktas vid val av klienter och runtime. [S26]

## 18 Byggordning och leveranskriterier

Varje fas har en leverans som går att demonstrera. Nästa fas ska lösa ett konstaterat behov. Kalenderuppskattningar för utveckling är inte bevis för strategins kvalitet.

### Fas 0 Rensning och arkitekturbeslut

Arkivera den gamla grenen, gör en ren ombyggnadsgren och publicera masterplan, ny README och nya projektinstruktioner. Dokumentera motorval, instrumentgränser och dataklassning. Klart när förändringen är granskad, den gamla versionen går att återfinna och inga hemligheter eller originaldata finns i ändringen.

### Fas 1 Instrument och datagrund

Bygg instrumentregister, kalendrar, källregister, råarkiv och första importer för SEC, prisdata och en nyhetskälla. Lägg till NAV-import som separat datakontrakt. Klart när omkörning är idempotent, tvetydigheter hamnar i karantän och split, namnbyte, artikelrevision och tidszon kan återspelas korrekt.

### Fas 2 Första analyskedjan

Bygg en händelsetyp, en verifierad direkt bolagsrelation och ett källbelagt analyskort. Kör samma händelse från rådata till strukturerat resultat. Klart när kvalitetsutvärderingen, källstöd och explicit avstående fungerar även för motsägelsefulla eller irrelevant dokument.

### Fas 3 Börsmotor och enkel strategi

Gör LEAN-provet med egna normaliserade data och en enkel deterministisk regel. Modellera avgifter, spread, fördröjning och handelstider. Klart när avslut, position och kassa kan avstämmas och samma regel ger förklarlig replay. Besluta därefter direktdrift eller betald CLI-väg.

### Fas 4 Forskning och jämförelser

Bygg kronologisk utvärdering, experimentregister och baslinjer. Testa pris, direkta händelser och graf separat. Lägg till första ML-modellen när datakontraktet är stabilt. Klart när slutperioden är orörd, alla försök är registrerade och rapporten visar kostnadskänslighet samt osäkerhet. Ett negativt resultat är ett giltigt utfall.

### Fas 5 Traderhistorik

Lägg till mäklarexport och valfri Collective2-adapter. Verifiera tidszon, kostnader, kontoavstämning, källa och rättigheter. Klart när ett verkligt tillåtet material har full dokumenterad täckning för avsett bruk. Saknas underlag fortsätter egen forskning utan att kalla materialet träningsklart.

### Fas 6 Framåtriktad simulering

Kör skugganalys och därefter simulerade order med separata strategiböcker. Testa återstart, dubbel kvittens, nätverksavbrott, avvisad order, delavslut och nödstopp. Klart när alla kritiska avstämningsfel är lösta och framåtriktade beslut går att rekonstruera. En bestämd månadslängd bevisar inte alpha.

### Fas 7 Fondallokering och mäklarkapacitet

Bygg exponering genom fondinnehav, avgiftskontroll och långsam ombalansering. Genomför fondorderprovet för vald distributör om gränssnitt finns. Klart när bryttider, kursdag, väntande order, kassa och likvid är korrekt representerade. Analys får levereras även om automatisk fondhandel ännu inte stöds.

### Fas 8 Begränsad live och kontrollerad utveckling

Verifiera aktuellt konto, tillgängliga instrument, feedavtal, riskbudget och mäklaradapter. Kräv också godkänd förregistrerad strategiutvärdering enligt avsnitt 14; bristande eller otillräckliga resultat blockerar live. Live aktiveras som ett separat beslut med vald kapitalgräns och godkända strategiversioner. Följ verkliga avslut och kostnader mot simuleringen. Vid driftfel minskas eller stoppas risken enligt policy. Det finns ingen automatisk upptrappning baserad på några få vinster.

## 19 Första konkreta utvecklingsuppgifter

| Prioritet | Uppgift | Bevis för klar leverans |
| --- | --- | --- |
| P0 | Arkivgren och ren projektgrund | Granskningsbar diff och återställningspunkt |
| P0 | Kontrakt för enhet, instrument och notering | Två listningar och ett namnbyte hanteras utan sammanblandning |
| P0 | Källobjekt och tidsversionering | Ursprunglig och korrigerad artikel kan återspelas separat |
| P0 | Datakatalog och användningsstatus | Ej verifierat material blockeras för otillåtet användningsfall |
| P1 | SEC- och marknadsdataadapter | Täckt period, luckrapport och normaliserade enheter |
| P1 | Nyhetsadapter och händelsegruppering | Återpubliceringar räknas som samma händelse |
| P1 | AI-extraktion med källstycken | Testmaterial med siffror, negation och tvetydighet |
| P1 | Direkt bolagsrelation | Tidssatt källa och explicit okänd exponering |
| P1 | LEAN-replay och kassabok | Avgifter, utdelning, split och delavslut avstämda |
| P2 | Kronologiska baslinjer | Ingen framtida datapunkt i något ingångssnapshot |
| P2 | Egen opportunity-logg | Kandidater och avståenden sparas vid beslutet |
| P2 | Traderexportadapter | Original, delavslut och kapitalhistorik avstämda |
| P2 | NAV-simulator | Order före och efter bryttid får rätt kursdag |
| P3 | Paper-mäklaradapter | Återanslutning skapar inga dubbla order |
| P3 | Drift och återställningsprov | Backup återläst och oberoende stopp demonstrerat |

## 20 Kostnader och beslut som behöver mätas

Budgeten delas mellan historiska data, livefeed, nyheter och estimat, fonddata, mäklaravgifter, lagring, beräkning och modellanalys. Handel för egen räkning och professionell vidareanvändning kan ha olika datavillkor. Budgeten ska därför bygga på faktisk användningsklass och offert.

Första mätningen omfattar kostnad per analyserad händelse, per godkänt analyskort och per simulerad strategidag. Spara tokenåtgång, modellval, cacheträffar, datauttag, lagring och worker-tid. Återanvänd analys för samma dokumentversion; en senare uppdatering får en ny körning.

De praktiska valen är första mäklarkonto, dataleverantör, månatlig databudget, första fondurval och eventuell rätt att använda traderexporter. De hindrar inte att datakontrakt och offlinekedja byggs. De måste däremot vara avgjorda innan kontospecifik livehandel eller ett betalt dataköp genomförs.

## 21 Instruktion till nästa byggagent

Arbeta i ombyggnadsgrenen och läs AGENTS.md och denna plan först. Börja med fas 1 efter att planeringsgrunden granskats. Implementera instrumentregister och oföränderlig källimport före strategier. Håll datahämtning, analys, simulering och orderläggning i separata kontrakt.

Använd aktuella officiella dokument för valda versioner. Bevara licenser när kod återanvänds. Lägg inte in alla föreslagna ramverk. Installera endast vad den aktuella fasen använder och lås versionerna. Genomför inga betalda köp eller liveorder som ett led i ett tekniskt test.

För varje leverans redovisas ändrade filer, vad som faktiskt körts, testresultat och begränsningar. Visa hela flödet med källor och dataset-ID. Märk syntetiska exempel tydligt. Påstå inte att API-åtkomst, full traderhistorik, träning, lönsamhet eller livehandel verifierats om det inte finns konkret bevis.

## 22 Källor och verifieringsgrund

Officiella dokument och projektkällor kontrollerades den 20 oktober 2026. Rekommenderad arkitektur, hypoteser och införandeordning är våra konstruktionsbeslut. Projektens beskrivningar visar funktioner och licenser, inte oberoende bevis för handelsresultat.

- S1 Investor.gov om mutual funds och ETF: https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/characteristics-mutual-funds-exchange-traded-funds
- S2 SEB om fondhandel och bryttider: https://seb.se/privat/spara-och-investera/villkor-och-avgifter/handel-med-fonder-i-sebs-fondlista
- S3 EU om PRIIPs och produktinformation: https://finance.ec.europa.eu/consumer-finance-and-payments/retail-financial-services/key-information-documents-packaged-retail-and-insurance-based-investment-products-priips_en
- S4 eve dokumentation: https://eve.dev/docs
- S5 LEAN kod och licens: https://github.com/QuantConnect/Lean
- S6 LEAN CLI autentisering och betald organisationsnivå: https://www.quantconnect.com/docs/v2/lean-cli/initialization/authentication
- S7 NautilusTrader kod och licens: https://github.com/nautechsystems/nautilus_trader
- S8 Qlib kod och dokumentation: https://github.com/microsoft/qlib
- S9 TradingAgents kod och projektbeskrivning: https://github.com/TauricResearch/TradingAgents
- S10 Finance Skills: https://github.com/himself65/finance-skills
- S11 Octagon Skills: https://github.com/OctagonAI/skills
- S12 SEC EDGAR API: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- S13 Alpaca nyhetshistorik: https://docs.alpaca.markets/us/docs/historical-news-data
- S14 Alpaca marknadsdatatäckning: https://docs.alpaca.markets/us/docs/market-data-faq
- S15 GLEIF koncernrelationer: https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-2-data-who-owns-whom
- S16 OpenFIGI identifierarmappning: https://www.openfigi.com/api/documentation
- S17 Collective2 API och paginering: https://api-docs.collective2.com/guides/pagination
- S18 Collective2 hypotetiska resultat: https://collective2.com/leader-board
- S19 IBKR Trade Confirmation Flex Query: https://www.interactivebrokers.com/campus/glossary-terms/trade-confirmation-flex-query/
- S20 Investor.gov om 13F: https://www.investor.gov/introduction-investing/investing-basics/glossary/form-13f-reports-filed-institutional-investment
- S21 SEC om Form 3 4 5: https://www.sec.gov/files/forms-3-4-5.pdf
- S22 Schedule 13D formulär och fält: https://www.ecfr.gov/current/title-17/chapter-II/part-240/section-240.13d-101
- S23 ARK om avsaknad av historiskt handelsarkiv: https://helpcenter.ark-funds.com/do-you-share-historical-trades
- S24 scikit-learn om dataläckage: https://scikit-learn.org/stable/common_pitfalls.html
- S25 Bailey med flera om backtestöveranpassning: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- S26 Supabase om TLS-förändring: https://supabase.com/changelog/cbc-tls-ciphers-deprecated
- S27 ALFRED historiska dataversioner: https://alfred.stlouisfed.org/
- S28 LightGBM: https://github.com/lightgbm-org/LightGBM
- S29 DuckDB Parquet: https://duckdb.org/docs/stable/data/parquet/overview
- S30 Befintlig projektgrund: https://github.com/heke99/trading-intelligence/tree/8c5056112721345540ea1cfbbca1f4c41fa816e8

De första leveransernas verifieringsjournal ska ange faktiska API-prov, datatäckning, kostnader, körningar och resultat. Denna plan är kravbilden som de leveranserna bedöms mot.
