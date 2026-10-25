# Trading Intelligence masterplan för aktier ETF fonder och futures

Version 1.4 · 25 oktober 2026 · För Hekmat Hourani

Version 1.4 preciserar mänskliga förhandsbedömningar, portföljhedging och dess livscykel samt flyttar enkel numerisk baslinje och LEAN-replay före det större AI- och grafbygget. Detta är dokumenterade krav; implementationen är fortfarande tidig fas 1 enligt [REBUILD_STATUS.md](REBUILD_STATUS.md). Dokumentuppdateringen ändrar inga handelsmandat eller verifieringsstatusar.

## 1 Beslut och mål

Trading Intelligence byggs om från en Collective2-importör till en plattform för bolagsanalys, kvantitativ forskning, portföljförvaltning och kontrollerad handel. Kärnan är en tidskorrekt dataplattform som försörjer flera strategier. AI läser och tolkar dokument. Beräkningskod räknar signaler och risk. En separat handelsmotor hanterar order och avstämning.

Målet är att hitta robusta samband efter kostnader och kunna förklara varje beslut. Systemet ska kunna avstå när underlaget är otillräckligt. Varken en känd traders historik, fler AI-roller eller en komplicerad modell visar i sig att en strategi är lönsam.

Första produkten är ett privat forsknings- och beslutsstöd för egen användning. Den förbereds för flera konton, dataleverantörer och mäklare genom tydliga kontrakt. Kundhandel, förvaltning åt andra och publik försäljning av signaler ingår inte i den första leveransen; en sådan produkt kräver en separat produkt- och regelgenomgång.

Prioriterade beslut:

- Aktier och vanliga ETF:er blir första instrumenten för simulerad börshandel. Hävstångsprodukter, inversa ETF:er och enaktie-ETF:er utesluts i piloten.
- Vanliga öppna fonder får analysstöd tidigt men ett separat orderflöde för NAV, bryttider och likviddagar.
- Futures ingår genom ett eget kontraktsregister, tidsversionerade villkor och en separat forsknings-/simuleringsbok. Första futurespiloten avgränsas till linjära, kontantavräknade kontrakt med fast tickstorlek; detta ändrar inte aktiepilotens riskmandat.
- Intradag, händelsestyrd swing och långsiktig allokering får separata strategiböcker, modeller och resultatmått.
- LEAN utvärderas som första börshandelsmotor. Qlib är ett senare forskningsverktyg. NautilusTrader är ett alternativ, inte en extra motor som installeras samtidigt.
- En fryst numerisk prisregel och avstämd LEAN-replay kommer före AI:s och bolagsgrafens påverkan på portföljbeslut. Varje senare lager ska visa sitt bidrag på jämförbara möjligheter, risk och kostnader.
- Human edge får en egen förhandsjournal för mänskliga hypoteser och ingrepp. Modellens ursprungliga förslag bevaras och det mänskliga bidraget utvärderas separat.
- Hedging får en versionsstyrd policy kopplad till verifierad exponering, målrisk och avslutsregel. Futureshedge, fristående futuresstrategi och minskad aktieexponering utvärderas separat.
- Traderhistorik blir en kompletterande datakälla. Egen marknads- och händelsehistorik gör att projektet kan fortsätta även när privata orderloggar saknas.
- Självlärande byggs som en återkopplingsloop med låsta prognoser, verifierade utfall, felklassning, förbättringsförslag och kontrollerade versionsbyten.
- Automatisk anpassning får ske inom en fastställd policy. Minne, modellträning, riskanpassning och kodändringar har olika behörigheter och tester.
- Ingen tränings- eller liveberedskap antas. Varje dataset och strategi måste få egna verifierade statusar.

## 2 Ombyggnad och rensning av projektet

Den tidigare läsande Collective2-importören finns vid commit 8c5056112721345540ea1cfbbca1f4c41fa816e8 och i arkivgrenen archive/collective2-v0.1-before-equities-2026-10-20. Ombyggnadsgrunden infördes redan i main genom PR #10. Den rensningen är genomförd och ska inte upprepas som ett nytt utvecklingssteg.

Git-historik, externa dataarkiv och eventuella privata originalexporter ska bevaras. Fortsatt arbete sker i avgränsade arbetsgrenar från aktuell main och förs in genom vanlig granskad merge. Ingen force push eller ny totalrensning ingår.

Den nya offlinegrunden har återinfört explicita identiteter, oföränderliga källversioner, karantän, exakta decimaler och idempotenta importer, följt av futures- och brokerkontrakt. De konkreta begränsningarna och verifieringsbevisen finns i REBUILD_STATUS.md. Detta innebär ännu inte en färdig analys- eller handelsprodukt.

Collective2 blir fortsatt en valfri adapter. Forex-, CFD- och MT5-antaganden ska inte styra det nya instrumentregistret. Version 1.4 bygger vidare på den befintliga grunden och bevarar dess statusgränser.

Överför inte gamla testantal, syntetiska exempel eller resultat till den nya plattformens verifieringsstatus. Arkivets tester verifierar den gamla importören. De visar inte att den nya produkten fungerar eller att någon verklig traderhistorik har hämtats.

## 3 Instrument och tidshorisonter

| Instrument | Analys | Ordermodell | Första omfattning |
| --- | --- | --- | --- |
| Noterade aktier | Bolag, rapporter, pris, volym och händelser | Börsorder med aktuella kvoteringar | Första börspiloten |
| ETF | Exponering, innehav, kostnad, överlapp och likviditet | Börsorder som separat värdepapper | Behöriga instrument utan hävstång, invers eller enaktieexponering |
| Vanlig öppen fond | NAV, andelsklass, avgifter, benchmark och förvaltning | Teckning eller inlösen till relevant framtida fondkurs | Analys först, orderadapter senare |
| Index | Marknadsläge och jämförelse | Ingen direkt order | Referensdata |
| Valuta | Omräkning, kassabok och ekonomisk exponering | Eventuell kontoväxling via mäklaradapter | Ingen egen valutastrategi |
| Futures/terminer | Underliggande marknad, kontraktskurva, volym och open interest | Explicit förfallande kontrakt, marginal och separat avräkning | Datakontrakt nu; linjär kontantavräknad simulering före eventuell live |
| Optioner, perpetuals, CFD och andra komplexa produkter | Separat senare forskningsområde | Egna kontrakt och riskmodeller | Ingår inte automatiskt genom futuresstödet |

ETF:er handlas under börsdagen till marknadspris. En vanlig fond får normalt en fondkurs som ännu inte är känd när ordern lämnas. Fond och distributör kan ha olika bryttider, kursdagar och bokföringsdagar. En NAV som publiceras senare får inte användas som indata före orderbeslutet. Den kan däremot vara korrekt avslutskurs i efterhand för en accepterad order, enligt fondens och distributörens faktiska regler. [S1, S2]

För en svensk användare skiljer vi analysuniversum från det aktuella kontots handelsuniversum. Ett instrument kan analyseras även om det inte kan köpas. Instrumentbehörighet, produktdokument, konto, mäklare och bosättningsland måste kontrolleras. Ingen automatisk ersättning med CFD, derivat eller en till synes likadan ETF tillåts. [S3]

Första forskningsurvalet är ungefär 30–50 likvida amerikanska aktier i ett sammanhängande bolagsnätverk. En separat historisk urvalsregel används i backtest, inklusive bolag som senare försvunnit. ETF-piloten använder ett litet dokumenterat urval; vilka som faktiskt kan handlas avgörs efter kontoverifiering. Vanliga fonder börjar som bevaknings- och allokeringsunderlag. Det begränsade bolagsnätverket är ett tekniskt och analytiskt piloturval. Resultat därifrån ska inte generaliseras till hela marknaden utan ett separat förregistrerat urval och bredare senare prov.

### 3 1 Futures med egna identiteter och kontroller

Version 1.2 utökar omfattningen enligt Hekmats instruktion. Det här är en konstruktionsplan; implementerad status finns i REBUILD_STATUS.md. Den första kodleveransen är en offlinegrund och ett beräknat öppningsunderlag, inte en fungerande terminsmäklare.

**Identitet och pris.** Skilj underliggande index/tillgång, börsprodukt, faktiskt förfallande kontrakt och mäklarens kontrakts-ID. Ett namn som Nasdaq kan betyda index, fond, CFD eller flera futuresstorlekar och förfall; textlikhet får inte välja åt kontot. Kontinuerliga serier är härledda analysdata. Order och avslut knyts till rått kontraktspris och explicit förfall. LEAN dokumenterar kontraktskedjor och byte av mappat kontrakt, vilket ska verifieras i vårt senare motorprov. [S39]

**Villkor.** Varje villkorsversion behöver prisvaluta, prisenhet, multiplikator, tickstorlek/tickvärde, tickregel, handelssession, sista handelstid, avräkningssätt och leveransrelaterade gränser. CME:s MNQ-beskrivning visar exempelvis att produktstorlek och prissteg är explicita egenskaper. Våra testdata är uppdiktade och ersätter inte aktuella börsvillkor. Variabel ticktabell, invers payoff och andra icke-linjära produkter kräver nya modeller och spärras av den första pilotens antagningsregler. [S35]

**Förfall och leverans.** Vi sparar både ekonomisk giltighet och när villkoren blev kända. Sista handelstid, first notice där relevant och mäklarens tidigare stängningsgräns får inte härledas från en generell tredje-fredagsregel. En explicit entry_cutoff stoppar nya öppningsförslag i god tid. Fysisk leverans är blockerad i första öppningspiloten. Senare stöd kräver verifierad leveranshantering och exitpolicy, inte bara ett datumfält. CME beskriver både rullning och att kvarstående kontrakt går till kontant eller fysisk avräkning. [S36, S38]

**Marginal och risk.** Marginal är säkerhet, inte nominell exponering eller ett förlusttak. Historiska och aktuella börs- och mäklarkrav hålls isär och sparas med konto, kontrakt, valuta, känd tid och utgångstid. Rabatterad intradagsmarginal ersätter inte kraven vid sessionens slut. Okänd/gammal marginal, fel kontovaluta eller ofullständig mäklarkapacitet blockerar nya riskökningar. Pilotens jämförelse använder fulla initial-/underhållskrav med en separat konfigurerad buffert; detta är inte en SPAN-motor. CME anger att marginalkrav varierar med produkt och volatilitet. Produktionsmotorn måste även kontrollera samlad exponering, öppna order, reserverad marginal, likviditet och stress. [S37]

**Sessioner.** Importera daterade sessionsegment, underhållspauser, helgdagar, tidiga stängningar och IANA-tidszoner från verifierad källa. Över-natt-session och handelsdatum är olika fält. En syntetisk kalender med korrekt UTC-jämförelse bevisar inte att vi har laddat börsens riktiga kalender. Kalenderändringar måste kunna rättas utan att skriva om tidigare kunskap.

**Rullning och avräkning.** Förregistrera urvalsregel, tillgänglig volym/open interest, tidpunkt och kostnader. Rullning skapar explicita stängnings- och öppningsben; namnbyte i en dataserie flyttar inte en verklig position. Gamla och nya ben, eventuell samtidig exponering, delavslut, avslag och avgifter avstäms separat. Justerade analyspriser får inte skapa fiktiv PnL. Daglig variation margin, realiserad/orealiserad PnL och slutavräkning behöver en gemensam kassabok så att samma rörelse inte bokas två gånger. Negativa priser stöds endast när både kontrakts- och mäklarvillkor uttryckligen medger det.

**Verifiering före handel.** Bygg i ordningen kontrakt och offlinekontroller, kontraktsvisa data, deterministisk replay, rullning/avräkning, paper-adapter och först därefter separat liveprövning enligt fas 8. En godkänd lokal preview är aldrig orderbehörighet. Optioner, perpetuals och CFD:er ingår inte genom detta tillägg.

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
| Portfölj och hedging | Deterministisk portföljpolicy framför ordermotorn | Samlad exponering, kapitalfördelning, hedgemål och kontospecifika riskkontroller |
| Jobb | En Postgres-baserad jobbkatalog och worker i starten | Schemaläggning, låsning, försök, hjärtslag och återhämtning |
| Lärande | Avgränsade Python-jobb och modellregister | Mogna utfall, kvalitetskontroll, kandidater och versionsbeslut |
| Felkorrigering | Incidentregister och separat reparationsmiljö | Orsakshypotes, regressionstest, åtgärd och verifiering |

eve är ett förslag för den nya AI-tjänsten, inte för själva orderloopen. Verktygen får läsa godkända datasnapshots och kalla beräkningsfunktioner. De får inte skicka mäklarorder. Projektets installerade versionsdokumentation ska styra implementationen. [S4]

Webben kan ligga på Vercel. Kontinuerliga marknadsflöden, forskningsjobb och mäklaranslutningar ska köras i lämpliga långlivade containrar, exempelvis Railway eller en separat worker-värd efter tekniskt prov. Handelsmotorn ska inte vara beroende av att en webbsida är öppen. Plats för drift, data och backup väljs utifrån leverantörernas villkor och uppmätt behov.

Postgres är kontrollplan och bokföring, inte standarddestination för varje börstick. Relationer kan börja som vanliga tidsversionerade tabeller. Separat grafdatabas, Kafka, ClickHouse och vektordatabas införs först när en uppmätt begränsning motiverar dem. En sökbar dokumentkatalog räcker för första beviskedjan.

Föreslagna moduler är web, research_api, ingestion, research_agent, execution_worker, fund_worker, contracts, strategies, evaluations, infra och docs. API-kontrakt definieras med OpenAPI och JSON Schema; TypeScript-typer genereras och testas mot Python-modeller. Tomma moduler presenteras inte som implementerade funktioner.

Modulerna learning och monitoring ansvarar för återkoppling och övervakning. Träningsjobb får läsa godkända dataset och skriva kandidatversioner men kan inte ändra den aktiva handelsversionen direkt. En separat versionskontroll tillämpar publicerad bytespolicy. Handelsutskick passerar en enda auktoritativ orderägare per konto; forskningskörningar saknar produktionsanslutning.

### 4 1 Flera brokers utan brokerlogik i strategin

Version 1.3 gör brokeroberoende till ett uttryckligt leveranskrav. Strategin lämnar ett kanoniskt orderunderlag med internt instrument, strategi, kvantitet, riktning, rått pris, beslutstid och giltighet. Mottagande broker väljs genom explicit kontoanknytning, inte textlikhet eller automatisk billigaste-route. Samma analys kan användas för flera konton, men varje konto har eget beslut, eget riskmandat, kapacitet, referensdata och avstämning.

**Kontonyckel.** Identiteten omfattar broker, anslutning, externt konto och miljö (paper/live). Lika kontonummer eller order-ID hos två brokers innebär inte samma konto eller affär. Flera anslutningar till samma externa konto kräver en gemensam auktoritativ orderägare och avstämning före framtida utskick; anslutningsnyckeln ger inte rätt att dubbelrouta kontot.

**Adapterkontrakt.** En adapter normaliserar instrumentuppslag, kontokapacitet, marknadsdata, orderförfrågningar, status, avbeställningar, delavslut, positioner, kassa och fel. Strategin ska inte känna till native symbol, TWS order-ID eller en viss leverantörs JSON. Första implementationen är avsiktligt bara beständiga offlineunderlag och två syntetiska kodare, utan submit-/cancel-metod eller externa anslutningar. BrokerStore sparar exakt adapter/version och källsnapshot. Den är inte en ordermotor.

**Instrument och förmågor.** Mappning görs från explicit aktie-/ETF-notering eller förfallande future till det aktuella kontots native instrument-ID, symbol, valuta, handelsplats, prissteg och kvantitetssteg. Ingen automatisk substitution med CFD, annat förfall eller annan produktstorlek tillåts. Tidsbegränsade kapacitetssnapshots anger giltiga kombinationer av instrumenttyp, ordertyp, time-in-force och sessionsläge. En kombination får inte uppfinnas genom att blanda oberoende stödda flaggor. Okänd/gammal kapacitet eller tvetydig mappning blockerar det nya underlaget.

**Återförsök och återhämtning.** Klientens stabila intent-ID nycklas per kontoroute. Ändrade parametrar med samma nyckel är en konflikt. Ett återförsök ska läsa exakt det sparade underlaget och klient-ID:t, även efter omstart eller en senare referenskorrigering. Det är historisk återläsning, inte ny orderbehörighet. Före framtida utskick måste aktuell risk, källa, quote, session, behörighet och orderägarskap kontrolleras igen. En timeout efter utskick blir okänd status tills den ursprungliga brokern har avstämts. Byt inte broker för att försöka igen: det kan skapa två positioner. Alpaca dokumenterar klient-ID och statusuppslag, medan IBKR har ett eget socketbaserat protokoll. Dessa skillnader motiverar adaptergränsen men bevisar inte färdig integration hos oss. [S40, S41]

**Risk och aktivering.** Konto- och sammanlagd ekonomisk risk bedöms före utskick; saldo får inte antas flyttbart mellan brokers. Valuta, avgifter, lån/locate, margin, öppna order och sena fills måste ingå i respektive verifierade kontomodell. Vanliga fonder använder fortsatt eget tecknings-/inlösenflöde. Ett godkänt offlineformat verifierar inte tillgänglig marknad, kontoeligibilitet, positiv avkastning eller handelsförmåga. Riktiga brokeradaptrar börjar med läsande metadata/kontoprov och paper-avstämning, därefter separat liveaktivering enligt fas 8.

## 5 Open source som återanvänds och utvärderas

| Projekt | Roll | Licens eller villkor att kontrollera | Beslut |
| --- | --- | --- | --- |
| QuantConnect LEAN | Motorprov för aktier, ETF och förfallande futures | Apache 2.0 för motorn; CLI, moln och data har separata villkor | Förstahandsval för motorprovet |
| Microsoft Qlib | Forskning, egenskaper och modellutvärdering | MIT | Senare om det sparar forskningsarbete |
| NautilusTrader | Tickdata, orderbok och händelsestyrd exekvering | LGPL 3.0; verifiera vald version och adapter | Alternativ om intradagskraven motiverar motorbyte |
| Finance Skills | Rutiner för värdering, rapporter, estimat och likviditet | MIT; källdata har egna villkor | Läs och anpassa utvalda arbetsflöden |
| Octagon Skills | Rapporter, SEC och rapportsamtal | MIT; beroende av Octagon MCP och dataåtkomst | Referens och valfri integration |
| TradingAgents | Analysroller och motargument | Apache 2.0 | Referens för forskningsflödet |
| scikit-learn och LightGBM | Baslinjer, klassificering, regression och rangordning | Verifiera paketens aktuella licenser | Numeriska modeller före djupinlärning |
| DuckDB och Polars | Analys av Parquet och tabeller | Verifiera vald release och beroenden | Databearbetning |
| MLflow | Registrering av experiment, modellversioner och artefakter | Verifiera vald release | Inför när modellförsöken börjar |
| River | Inkrementella modeller och fördröjd löpande utvärdering | BSD 3 Clause för projektet; verifiera vald release | Valfritt senare efter jämförelse mot batchomträning |
| eve | Versionerade AI-verktyg och analysflöden | Verifiera vald release och runtimevillkor | Avgränsad analystjänst |

LEAN-motorns öppna licens betyder inte att hela standardflödet är gratis. Den nuvarande officiella CLI-dokumentationen kräver medlemskap i en QuantConnect-organisation på betald nivå. Vi väljer mellan direkt drift av motorn och ett abonnemang efter motorprovet och kostnadsjämförelsen. [S5, S6]

NautilusTrader dokumenterar en versionsövergång. Adapterstöd och stabil release måste kontrolleras innan det väljs. Qlib ska inte bli en andra auktoritativ ordermotor. TradingAgents är inte belägg för en lönsam strategi. [S7, S8, S9]

Alla importerade delar får källadress, commit eller release, licens, NOTICE där det krävs, ändringshistorik och ansvarig modul. Skills granskas som kod och instruktioner före användning. Vi installerar inte breda sociala läsare eller godtyckliga tradingverktyg för att en analysrutin behöver ett rapportfält. Open source-instruktioner ger inte automatiskt rätt att lagra, återdistribuera eller träna på en extern tjänsts data. [S10, S11]

Första lärandeloopen använder schemalagda Python-jobb, befintliga datakontrakt och MLflow när modeller finns. MLflow dokumenterar versioner, aliases och tags; det tillhandahåller inte vår statistiska godkännandepolicy. River är ett möjligt senare verktyg för inkrementellt lärande och fördröjd utvärdering, inte ett krav för att systemet ska kunna förbättras. Vi bygger inte flera överlappande övervakningsramverk från start. [S31, S32, S33]

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
| Futures | Börsens kontraktsvillkor och licensierad kontraktsvis marknadsfeed | Tickstorlek, multiplikator, pris-/valutaenhet, sessioner, förfall, leveransrisk och då gällande mäklarmarginal |

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
| Mänskliga bedömningar | human_assessments, human_interventions | Aktör, ursprungligt modellförslag, förhandsmotivering, giltighet och versionshistorik |
| Modeller | model_versions, calibrations, evaluation_runs | Träningsperiod, försökshistorik och godkänd användning |
| Återkoppling | predictions, label_definitions, outcome_events | Låst prognos, utfallshorisont, tillgänglig tid och etikettversion |
| Korrigering | incidents, correction_events, artifact_dependencies | Belagd orsak, ursprungsversion och berörda följdartefakter |
| Lärande | learning_runs, model_candidates, promotion_events | Tillåtna data, jämförelser, kandidatstatus och bytesbeslut |
| Driftpolicy | promotion_policies, deployment_manifests, monitor_snapshots | Oföränderliga versioner, mandat, larm och återgång |
| Handel | decisions, risk_checks, orders, executions, reconciliations | Spårbara orderstatusar, kassaflöden och avstämning |
| Hedging | hedge_policies, hedge_intents, hedge_links, hedge_events | Skyddad exponering, målrisk, kontoroute, storlek, livscykel och hänvisningar till verkliga order/avslut |
| Fonder | fund_terms, fund_navs, subscriptions, redemptions | Bryttid, kursdag, publicering, accepterad order och likviddag |
| Futures | future_products, future_contracts, contract_terms, margin_snapshots, roll_events | Produkt, förfall, mäklaridentitet, giltighet, känd tid och avräkningsflöden hålls isär |

Värdepapper får intern instrumentidentitet med separata mappningar till ISIN, FIGI, börsnotering och mäklarens kontrakts-ID. En ticker räcker inte. Automatisk textlikhet får föreslå en matchning men inte godkänna en tvetydig order. OpenFIGI är en hjälp för identifierare, inte ett fullständigt historiskt värdepappersregister. [S16]

Ett datasets status delas upp i åtkomst, rättigheter, tidskvalitet, fullständighet och tillåtet forskningsändamål. full_history_verified och training_ready förblir false tills just det materialet uppfyller dokumenterade krav. En lyckad import räcker inte. Uttalat okända värden ska förbli okända.

Prognoser lagras före utfallet med prediction_id, decision_at, target_definition_id, horizon, model_version, feature_snapshot_id, memory_snapshot_id och policy_version. Utfallet kopplas senare med label_end, outcome_available_at, origin och version. En faktisk affär, ett modellerat marknadsutfall och en traders uppgift om sin avsikt är olika källtyper.

Alla härledda artefakter får explicita beroenden till källor, beräkningar och etikettversioner. En korrigering skapar en ny version och markerar berörda dataset, experiment och modeller som påverkade. Ursprungliga beslut bevaras. Den korrigerade analysen redovisas separat från det realiserade historiska resultatet.

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

Analyskortet innehåller event_id, snapshot_id, beslutstid, instrument, horisont, bekräftade fakta, relationer, hypotes, motargument, osäkerheter och nästa kontroll. Det har även giltighetstid, villkor för att hypotesen inte längre gäller och status för eventuell uppföljning. En uppdaterad analys ersätter inte den prognos som redan utvärderas. Språkmodellens egen säkerhet är inte en kalibrerad sannolikhet för vinst. Om en numerisk prognos används kommer den från en utvärderad modell med dokumenterad kalibrering.

Modellnamn, promptversion, verktygsresultat, datahash och beräkningsversion sparas. Modeller ska kunna bytas genom ett leverantörsoberoende kontrakt. Små modeller kan användas för sortering; svårare eller motsägelsefulla fall kan få mer analys inom budgeten. Fler roller eller modeller införs bara om mätningen visar bättre kvalitet per kostnad och fördröjning.

Ett första granskningsmaterial bör innehålla 100–200 händelser med positiva, negativa, tvetydiga och irrelevanta exempel. Mät rätt identifiering, korrekta siffror och enheter, giltiga källhänvisningar, förväxlingar, dubbletter och välmotiverat avstående. Föreslaget första krav är full spårbarhet för fakta som används i en handelskandidat och inga olösta kritiska identitets- eller tidsfel. AI-genererade efterhandsförklaringar är granskningshypoteser. De blir inte korrekta träningsetiketter genom att samma modell upprepar dem. Bekräftade faktakorrigeringar behöver regler, källstöd eller separat granskning.

### 9 1 Human edge och mänsklig förhandsjournal

Human edge betyder här en mänsklig hypotes eller ändring av ett konkret beslutsförslag. Det kan gälla en ekonomisk mekanism, ett källproblem, ett marknadsläge eller ett avstående. Traderhistorik i avsnitt 11 är en separat datakälla. En människas bedömning blir inte ett verifierat faktum eller en träningsetikett enbart genom att den registreras.

Varje human_assessment får assessment_id, actor_id, recorded_at, decision_at, snapshot_id, berörda instrument/böcker, horisont, källor, hypotes, motargument, giltighetstid och villkor för omprövning. Ett ingrepp länkar dessutom till det oförändrade ursprungliga modell- eller regelförslaget med dess version, föreslagen ändring, förhandsmotivering och versionssatt beslutsmandat. Ett avstående är ett möjligt ingrepp. Saknad ursprunglig rekommendation anges uttryckligt för fristående mänskliga förslag.

Journalen låses före det beslut som bedömningen ska påverka. Ändringar skapar nya versioner med egen registreringstid; senare utfall eller efterhandsmotiveringar får inte bakdateras. En utgången bedömning kan inte tyst återanvändas. Kontots auktoritativa portfölj- och riskkontroller gäller även mänskliga förslag. Bedömaren får inte kringgå hårda stopp eller höja riskmandat genom en kommentar.

Utvärderingen bevarar modellens ursprungliga förslag och utförda portföljbeslut separat. Jämför modell/regler ensamma, mänskliga beslut där ett fullständigt förhandsprotokoll finns och kombinationen på samma dokumenterade möjlighetsurval, period, kapital, risk och kostnadsmodell. Registrera även avståenden och uteblivna ingrepp. Urval av enbart lyckade ingrepp eller av efterhandskända vinnare får inte ligga till grund för slutsatsen att människan tillför värde.

Den alternativa modellvägen är en märkt hypotetisk simulering och använder samma regler för tillgänglig information och möjliga avslut. Den får inte bokföras som verklig handel. Visa realiserat resultat, simulerad skillnad, riskförändring och osäkerhet separat; skillnaden mellan två vägar är inte i sig ett säkert kausalt mått. Klart-kriteriet är att ett förhandsregistrerat ingrepp, ett avstående, en utgången bedömning och en senare rättelse kan återskapas utan att skriva om ursprungliga beslut. Datakontraktet kan förberedas i fas 1; ekonomisk utvärdering införs i fas 4.

## 10 Strategier och algoritmer

Varje strategi definieras innan slututvärderingen: syfte, universum, tillgänglig information, beslutstid, in- och utträde, positionering, kostnader, avstående, benchmark, primärt mått och stoppvillkor. Signalens giltighet, utfallshorisont och positionens exitpolicy definieras var för sig. Parametervarianter räknas som forskningsförsök och registreras även när de går dåligt.

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

Egenskaper kan omfatta relativ styrka, volym, volatilitet, spread, rapportöverraskning, nyhetsnyhet, försäljningsberoende och värderingsmått. Normalisering, imputering och egenskapsurval anpassas inom respektive träningsfönster. Modellval använder separat kronologisk validering. Kalibrering får ett särskilt avsett material skilt från det som tränar den underliggande prognosmodellen. Inga framtida exitpriser, efterhandsberäknade trade-VWAP eller senare artikelformuleringar får användas som ingångsegenskaper.

Modellens förslag jämförs med förväntade handelskostnader, osäkerhet och riskbudget. Vi väljer inte en godtycklig summa av AI-betyg som köpknapp. Avstå blir ett uttryckligt alternativ. Samtidiga signaler vägs i en portföljpolicy som hanterar nettoexponering, likviditet, sektor och gemensamma beroenden.

Första lärandealgoritmen är schemalagd batchomträning med ett förregistrerat fönster, tillåtna egenskaper och ett begränsat antal försök. Inkrementellt lärande eller ändrade strategivikter jämförs mot en oförändrad modell och samma batchrutin innan de kan väljas. Portföljens riskmandat är en separat gräns och kan inte utökas av träningsoptimeringen.

## 11 Traderhistorik som kompletterande läromaterial

Vi skiljer tre uppgifter: förstå traderns beteende, förutsäga marknadens framtida utfall och bestämma vår egen risk och orderläggning. En skicklig traders avslut är demonstrationer av handlingar. De är inte automatiskt etiketter för den optimala handlingen.

| Källa | Möjligt underlag | Användningsgräns |
| --- | --- | --- |
| Deltagande traders | Originalexporter, hela kontoperioder och journaler | Kräver avstämd historik och rätt till avtalad användning |
| Collective2 | Strategiorder och avslutade affärer via dokumenterade API:er | Modellhistorik hålls separat från verifierade mäklaravslut |
| Kinfo eller liknande | Mäklarverifierade profiler och resultat | Profilen bevisar inte komplett export eller träningsrätt |
| Öppna genomgångar | Exempel på setups och förklaringar | Urval, ofullständig tidsinformation och efterhandsförklaring märks |
| SEC 13F | Rapporterade kvartalsinnehav | Inga exakta köpdatum eller fullständiga orderloggar |
| SEC Form 4 och 13D | Rapporterade transaktioner och vissa uttalade planer | Publiceringsfördröjning, transaktionstyp och fotnoter behövs |
| ARK | Dagliga innehav och meddelanden efter stängning | Officiellt historiskt handelsarkiv erbjuds inte |

Collective2 dokumenterar historiska order och avslutade trades, men åtkomst, täckning och användningsrätt måste verifieras för vårt konto och varje strategi. Tjänstens hypotetiska resultat blandas inte med kontoavslut. IBKR:s Flex Queries är en konkret exportväg när en kontoinnehavare deltar. [S17, S18, S19]

13F är kvartalsinnehav och lämnas normalt inom 45 dagar. Form 4 lämnas i de flesta fall inom två arbetsdagar och kan avse annat än ett vanligt börsköp. 13D:s planer och transaktionsuppgifter är användbara händelser men ingen fullständig investerarlogg. Alla signaler börjar när informationen faktiskt blev offentlig, med relevant fördröjning. ARK anger uttryckligen att historiska handelsarkiv inte tillhandahålls. [S20, S21, S22, S23]

För varje trader behövs tidsstämplade delavslut, orderkedja, ändringar, avgifter, cash flows, kontovaluta och kapitalhistorik. Vi tar med förlustperioder, misslyckade strategier och nedlagda konton när de finns. Traders viktas inte efter social räckvidd eller en utvald avkastningsbild.

Utan bevakningslista eller aktivitet vet vi inte vad tradern valde bort. En minut utan avslut etiketteras därför som oobserverad, inte avstått köp. För utvärdering av beteendemodeller hålls även senare tidsperioder och, när urvalet tillåter, hela traders utanför utvecklingsmaterialet. Det hjälper oss att skilja ett överförbart mönster från en viss persons enskilda historik. Vårt eget system ska från första dagen logga alla kvalificerade kandidater och skälen till köp, sälj, minskning eller avstående.

Historiken kompletteras med marknadsdata som fanns före handlingen. Beteendemodeller får föreslå regler att testa. Om tradern saknar dokumenterad ursprunglig stop eller motivering fyller AI inte i den som fakta. Video eller journal kan ge en hypotes med separat källklassning.

## 12 Fonder och genomlysning av exponering

För varje fond skiljer vi fond, andelsklass och eventuell börsnotering. Avgifter, minsta köp, utdelande eller ackumulerande klass, valuta, valutasäkring, distributionsvillkor och benchmark sparas separat. Handelsvaluta beskriver inte hela den ekonomiska valutarisk som fonden bär.

Fondanalysen omfattar totalavkastning, risk, jämförelse mot benchmark, koncentration, innehavsöverlapp, förvaltarbyte och ändrat mandat. ETF-analysen lägger till spread, likviditet, replikering och premie eller rabatt mot relevant NAV. Publiceringstid och datans ålder ska synas.

ETF-pris och NAV måste jämföras vid förenliga tidpunkter och med hänsyn till underliggande marknaders öppettider. Gårdagens NAV eller en stängd utländsk marknad får inte ge sken av en aktuell riskfri prisskillnad.

Löpande fondavgifter som redan påverkat NAV ska inte dras en gång till i simuleringen. Direkta transaktionsavgifter, spread, FX och eventuella prestationsavgifter hanteras utifrån källans exakta definition. Samma princip gäller totalavkastningsserier där utdelning redan återinvesterats.

Fondordern har egna steg: mottagen, behörighetskontrollerad, lämnad till distributör, accepterad, väntar på kurs, prissatt, bokförd, likviderad eller avvisad. Bryttid och kalender är fond- och distributörsspecifika. Tillgängligt kontantsaldo ska ta hänsyn till att en försäljning inte alltid kan finansiera ett samtidigt köp omedelbart.

Automatiska fondorder aktiveras först när en vald mäklare faktiskt stöder teckning och inlösen genom ett verifierat gränssnitt. Tills dess finns analys, manuella orderunderlag och separat simulering. Ett anpassat datafält i LEAN bevisar inte fungerande fondorder.

Fondlärande väntar tills relevant kurs har publicerats och vald utfallshorisont passerat. Faktiskt affärsresultat kräver dessutom avstämda order och kostnader. NAV-datum, publicering, affärsdag och likviddag är skilda tidpunkter. En korrigerad NAV får en ny etikettversion; den ger inte roboten historisk tillgång till den korrigerade kursen.

## 13 Risk portfölj och orderhantering

Varje strategi har egen bok och riskbudget. Det hindrar att en förlorande intradagsaffär byter etikett till långsiktigt innehav. En gemensam portföljmotor räknar samlad ekonomisk exponering och mäklarordrar. Om två strategier vill samma instrument ska tilldelning och intern nettning vara förklarlig.

Riskpolicyn omfattar position, total och nettoexponering, sektor, beroenden, volatilitet, omsättning, kassareserv och maximal tillåten förlust enligt valda mått. Gränser konfigureras före körning. En förtestad regulator får minska risk vid sämre likviditet, dataproblem eller konstaterad försämring. Återgång kräver uttryckliga observationskrav, väntetid och skilda trösklar för stopp och återstart. Den får aldrig höja mandatets tak eller öka risk för att vinna tillbaka förluster. Det finns inga löften om att en stop begränsar förlusten vid gap, avbrott eller avsaknad av likviditet.

Den första aktie-/ETF-piloten använder köp och kontanter. Aktieblankning kräver senare verifierade lån, locate, avgifter och mäklarvillkor. Futures har egen bok: en kort terminsposition är inte ett aktielån, men kräver uttryckligt mandat, marginalkontroll och verifierad mäklarkapacitet. Riskgränser i procent eller kronor bestäms när kapital, kontotyp och kostnadsmodell är kända; de ska inte härledas från en språkmodells säkerhetsbetyg.

Ordermotorn hanterar förslag, riskkontroll, skickad order, kvittens, delavslut, avslut, avbeställning, avvisning och okänd status. Varje order får idempotensnyckel och beständig koppling till beslutet. Vid timeout får motorn inte anta att ingen order finns och skicka en ny utan kontroll.

Mäklaren är auktoritet för externa avslut. Det interna systemet avstämmer order, innehav, avgifter och kassa vid start, återanslutning och löpande. Olöst kritisk differens blockerar riskökande order. Avgifter, likviddag, öppettider, prissteg, valutahantering och stödda ordertyper ligger i tidsversionerade mäklarkapaciteter. Avstämningen omfattar även manuella mäklaraffärer, korrigerade avslut, bolagshändelser och valutaposter. Okända externa innehav registreras som sådana och tillskrivs inte automatiskt en strategi.

Varje konto har exakt en aktiv orderägare. Ett ledarlås med utgångstid och ett stigande ägarskapstoken kontrolleras vid orderutskick, så att en gammal worker inte fortsätter handla efter failover. Idempotensnycklar ersätter inte detta skydd. Förlorad ägarskapssignal blockerar nya order och kräver avstämning före återstart.

Nödstoppet har högre prioritet än strategins driftläge. Ett hårt orderstopp blockerar alla nya orderutskick, även exits, men fortsätter ta emot status och avslut. Verifierade avbeställningar kan hanteras av en separat tillåten rutin. Automatisk försäljning av alla innehav är en separat policy. För vanliga fonder kan en redan accepterad order sakna möjlighet att återkallas.

Strategins driftläge är beständigt och har definierade övergångar: active, degraded, reduce_only, paused och recovery. I paus fortsätter status, avstämning och uppföljning av kvarvarande exponering. Skyddande exits kan tillåtas enligt nedan när inget hårt stopp gäller. Återstart kräver datakontroll, avstämning och giltigt kontoägarskap. En timeout eller ett avbeställningsförsök bevisar inte att en order är borta.

| Läge | Riskökande order | Reducerande order | Status och sena avslut |
| --- | --- | --- | --- |
| Active | Enligt mandat | Enligt exitpolicy | Alltid |
| Degraded | Bara inom begränsad policy | Med verifierad kvantitet | Alltid |
| Reduce only eller paused | Nej | Bara om uttryckligen tillåtet och verifierat | Alltid |
| Recovery | Nej före godkänd återstart | Bara verifierad skyddsåtgärd | Alltid |
| Hårt orderstopp | Nej | Nej | Alltid |

En reducerande order kräver verifierad tillgänglig position, hänsyn till öppna order och möjliga sena avslut samt kontroll att den inte skapar motsatt exponering. Okänd kvantitet eller osäkra orderstatusar gör även denna order otillåten tills läget är avstämt.

En versionsåtergång återställer kod och modellpaket men aldrig kassa eller externa avslut till en äldre snapshot. Varje position behåller strategy_id, model_version och den körbara exitregelns kodversion tills en explicit överföring genomförts. En kompatibel exithanterare måste finnas kvar så länge den behövs. Väntande fondorder följs färdigt även om en strategi eller kandidat stoppas.

### 13 1 Hedgepolicy och mål för kvarvarande exponering

Varje hedge_intent ska länka till en versionssatt hedge_policy och ett verifierat snapshot av det innehav eller den bok som ska skyddas. Policyn anger kontoroute, skyddad riskfaktor, mål för kvarvarande exponering, tillåtna kontrakt, högsta hedge, beräkningsversion, besluts- och giltighetstid, ombalanseringsband, minsta väntetid och avslutsregel. En fristående futuresstrategi har eget syfte och egen riskbudget; den klassificeras inte automatiskt som hedge för att den är kort.

Första hedgesimuleringen avgränsas till marknadsexponering i en behörig aktie-/ETF-bok mot ett verifierat linjärt, kontantavräknat indexfutureskontrakt. Bolagsspecifik risk och skillnaden i rörelse mellan portföljen och hedgeinstrumentet finns kvar. Automatisk valuta-, ränte- eller fondhedging ingår inte i denna pilot. En senare utvidgning behöver eget exponeringsmått, mandat och prov.

Storleken baseras på nominell exponering, samband med relevant index och önskad kvarvarande risk. Antal kontrakt beräknas med verifierat rått futurespris, multiplikator och förenlig valuta. Portföljbeta eller annan tillåten skattning använder en förregistrerad historik som fanns tillgänglig vid beslutet. Storleken får inte härledas från säkerhetskravet eller från en språkmodells säkerhetsbetyg. Avrundning till hela kontrakt redovisar uppnådd exponering och kvarvarande rest; den får inte överskrida policyns gränser. [S42]

Priser, växelkurser och positionssnapshot behöver förenliga värderingstidpunkter och dokumenterade åldersgränser. En stängd aktiemarknads senaste kurs får inte behandlas som en samtidig livevärdering av ett öppet futuresben. Okänt eller inaktuellt samband, för låg likviditet eller otillräcklig kontantbuffert blockerar nya hedgeben och utlöser den definierade omprövningsrutinen.

Den gemensamma riskkontrollen mäter exponering före och efter föreslagen hedge samt bruttoexponering, öppna order, reserverad marginal och stressat kontantbehov per konto. Daglig variation margin och förändrade säkerhetskrav ska kunna finansieras på det konto där futurespositionen finns. Kontanter hos en annan broker får inte antas omedelbart tillgängliga. Marginal- och avräkningsbetalningar behandlas som verkliga kassaflöden i simulatorn. [S37, S43]

### 13 2 Hedgens livscykel och orderbehörighet

En hedge har beständig identitet och tillstånd för föreslagen, godkänd, under utförande, aktiv, delvis genomförd, omprövning, under avveckling och avslutad; olöst extern status hålls uttryckligt okänd. Varje övergång sparar snapshot, beslut, policyversion, allokering till skyddad bok och hänvisningar till faktiska order och avslut. Första provet använder en explicit skyddad bok per hedge; senare delade hedgar kräver en allokeringsregel som hindrar dubbelräkning.

Det är avstämda avslut, inte den beställda kvantiteten, som bestämmer aktuell exponering. Ändrat huvudinnehav, delavslut, avvisat hedgeben, förfall eller försenad status utlöser omberäkning enligt policyn. Om huvudinnehavet försvinner markeras en kvarvarande futuresposition som saknande skyddad exponering. Motorn ska då följa en förregistrerad avvecklings- eller återhämtningsregel med nya riskkontroller och verifierade kvantiteter. Ett hårt orderstopp behåller företräde; om åtgärden är blockerad synliggörs kvarvarande risk och larm tills tillåten återhämtning kan ske. Positionen får inte tyst byta etikett till en lönsam fristående strategi.

En instrumentbaserad reduce_only-order minskar en befintlig position i just det instrumentet. Att öppna en kort future kan minska portföljbeta men ökar kontrakts- och finansieringsåtaganden. Ett nytt eller utökat hedgeben behöver därför uttryckligt fördefinierat mandat, godkänd kontokapacitet och full kontroll av brutto-/nettorisk, likviditet och marginal. Ordet hedge ger inget undantag från paus, reduce_only eller hårt orderstopp. Första piloten öppnar och utökar hedgar endast i active enligt mandatet; en senare särskild skyddspolicy kräver separat verifiering av tillåtna övergångar.

Underliggande innehav och hedge är inte atomiska över flera instrument eller brokers. Delvis genomförd öppning, stängning och rullning måste ha tidsgräns, högsta tillåtna kvarvarande exponering och en förregistrerad åtgärdsordning. Ingen automatisk broker-failover tillåts vid okänd status. Rullningens gamla och nya ben behåller länken till samma hedgesyfte och följer avsnitt 3 1 utan att skapa ett andra ekonomiskt skydd i rapporteringen.

Acceptansprovet omfattar minst delavslutat huvudinnehav, avvisat hedgeben, stängt huvudinnehav med kvarvarande hedge, okänd orderstatus med sent avslut, ett avvisat rullningsben, förfallsgräns, ändrat samband och ett hårt stopp mitt i avvecklingen. Varje scenario ska visa kvarvarande risk, korrekt kassabok, spårbart åtgärdsbeslut och att inga okända positioner ignoreras.

## 14 Tester som skiljer resultat från efterhandsanpassning

Tester delas mellan dataintegritet, analyskvalitet, prognosvärde, portföljresultat och operationell funktion. Ett grönt tekniskt test visar inte positiv nettoavkastning.

1. Frys hypotes, urvalsregel, horisont, label, kostnadsmodell och primärt mått före sluttestet.
2. Dela kronologiskt med rullande träning och senare validering. Ta bort träningsobservationer vars utfallsperiod överlappar validering eller test. Gruppera samma nyhet och relaterade bolagshändelser så att de inte läcker mellan delar.
3. Anpassa förbehandling på träningsfönstret och använd separat kronologisk validering för modellval. Kalibrering får avsett separat material. Sluttestet används inte för dessa val. Oregelbundna händelser kräver en egen tids- och gruppdelning; en standardfunktion är inte automatiskt korrekt. [S24, S34]
4. Jämför kontanter, riskjämförbar benchmark, enkla prisregler, direkta nyheter, graf och traderinformation. Ta bort ett lager i taget för att mäta dess bidrag.
5. Registrera alla försök. Håll en sista period orörd fram till dess definierade slututvärdering. Skatta osäkerhet med hänsyn till att affärer samma dag eller kring samma händelse är beroende. Många trades är inte lika med många oberoende observationer. [S25]
6. Stressa spread, latens, avgifter, marknadspåverkan, delavslut, uteblivna avslut, gap, stopp och sämre feed. Visa resultat per period, sektor, instrument och marknadsläge.
7. Kör framåtriktad skugganalys och därefter simulerad orderhantering. Jämför vad systemet förutsåg med vad som faktiskt fanns tillgängligt.

När ett sluttest har påverkat modellval, prompt, minnesrutin eller korrigering är det förbrukat som oberoende sluttest för de efterföljande valen. Det kan bli utvecklingsmaterial. Nya kandidater behöver ny framtida evidens eller en i förväg definierad sekventiell jämförelsepolicy med begränsade försök. Upprepad testning tills en kandidat ser bra ut är inte oberoende verifiering.

Själva anpassningsregeln testas kronologiskt: starta från dokumenterad modell och minne, lås prognosen, invänta tillgängligt utfall, poängsätt och uppdatera först därefter. Även normalisering, kalibrering och minneshämtning följer denna ordning. Jämför oförändrad modell, batchomträning och eventuell inkrementell modell på samma möjligheter och kostnader. En modell som redan sett hela perioden får inte användas som startpunkt. River dokumenterar denna princip som fördröjd löpande utvärdering. [S32]

Historiska tester med en modern språkmodell kan innehålla kunskap om senare utfall från modellens förträning. Att dölja framtida dokument i vår egen databas löser inte hela det problemet. Framåtriktade resultat och enklare textmodeller är viktiga jämförelser.

Rapporten visar avkastning efter modellerade kostnader, drawdown, nedsiderisk, kapitalbindning, turnover, kapacitet, benchmarkexponering och osäkerhet. Resultat räknas i jämförbar valuta med dokumenterad hantering av kapitalflöden och utdelningar. Extraktionskvalitet och sannolikhetskalibrering rapporteras separat från ekonomiskt resultat. Win rate är inte ett huvudbevis. Valda trösklar måste förregistreras per strategi när datatäckning och realistiska kostnader är kända.

Innan live måste varje strategi klara den förregistrerade bedömningen av nettoresultat, risk, osäkerhet och bidrag jämfört med baslinjen på orört testmaterial och framåtriktade observationer. Operationell stabilitet räcker inte. Om underlaget är negativt eller för svagt stannar strategin i forskning eller simulerad handel.

### 14 1 Separat utvärdering av hedging och mänskliga ingrepp

Frys hedgepolicy, mål, skattningsfönster, ombalanseringsregel och primärt riskmått före slututvärdering. Kör samma skyddade portfölj med och utan denna policy. Visa den osäkrade portföljen, futuresbenet och kombinationen separat med resultat, avgifter, spread, slippage, rullning, finansieringskostnader och högsta kontant-/säkerhetsbehov. Variation margin ska stämma mot kassaboken och inte dubbelräknas som både ny kostnad och samma prisförlust.

Mät faktisk förändring av målrisken, kvarvarande exponering, drawdown, nedsida, avstådd uppgång och osäkerhet. En hedge bedöms mot sitt deklarerade riskmål; enbart positiv hedge-PnL eller hög win rate räcker inte. Jämför också med en förregistrerad lägre aktieexponering och större kontantandel, med tydliga skillnader i kapital och risk. En dynamisk hedge får inte vinna jämförelsen genom att få känna till senare marknadsrörelser eller genom tät efterhandsoptimering.

Stressfallen inkluderar samtidig förlust i innehav och hedge, försämrad korrelation, inaktuella eller osamtidiga priser, prisgap, delavslut, stängd underliggande marknad, höjda marginalkrav och otillgängliga kontanter på annat konto. Kostnaden för likviditet och kvarvarande risk vid ett blockerat hedgeben redovisas även när portföljens slutliga nettoresultat ser bra ut.

Human-journalen enligt avsnitt 9 1 får motsvarande jämförelse på förhandsregistrerade möjligheter. Redovisa ingrepp, avståenden, kostnader, resultat och riskförändringar även för misslyckade fall. Det hypotetiska modellresultatet, det faktiska kombinerade resultatet och ett eventuellt komplett mänskligt jämförelseflöde hålls isär. Ingen version av mänsklig bedömning, hedge eller modell får ändras med hjälp av slutperioden och sedan redovisas som ett nytt orört test.

## 15 Självlärande felkorrigering och kontrollerade uppdateringar

Självlärandet ska vara ett eget systemflöde som samlar erfarenheter, mäter kvalitet, föreslår förbättringar och kontrollerar om de hjälper. Det innebär inte att modellen förbättras efter varje affär. En korrekt förlust registreras som ett utfall. Ett faktiskt fel behöver belägg och en verifierad åtgärd. Även en vinst kan innehålla datafel eller ett brutet riskvillkor.

### 15 1 Fyra skilda former av förbättring

Minne lagrar och hämtar tidigare källbelagda fall. Modellträning ändrar numeriska parametrar. Kalibrering justerar hur en prognos förhåller sig till observerad frekvens. Kod- och policyändringar påverkar systemets logik. Dessa har olika tester och behörigheter. Att lägga ett fall i minnet tränar inte språkmodellens vikter.

Språkmodellen kan föreslå en förbättrad tolkning, ny regel eller kodpatch. Förslaget är en kandidat tills det verifierats. Modellens egen efterhandsberättelse får inte fungera som facit. Finjustering av språkmodellen är ett separat senare beslut som kräver kontrollerade exempel och mätbart bättre analyskvalitet.

### 15 2 Återkoppling från beslut till moget utfall

Flödet är beslut, låst prognos, väntan på utfall, utvärdering, felklassning, förbättringskandidat, oberoende prov och eventuell versionsväxling. Alla steg länkas till samma prognos, snapshot och strategiversion. Beslut, avståenden och ej genomförda order följs utan att blanda faktisk handel med hypotetiska utfall.

Utfallsjobbet hanterar pending, matured, unavailable och quarantined. En senare korrigering skapar en ny version med hänvisning till föregående etikett och en egen available_at. Historisk träning vid tid T använder versionen som var känd vid T; rättelsen ärver inte originalets tillgänglighetstid. target_definition anger vad som ska mätas, referenstid, utfallshorisont, benchmark och pris- och kostnadskonvention. För realiserat handelsresultat används verkliga avslut; för marknadsprognoser används en förregistrerad hypotetisk genomförbar regel.

En femdagarsprognos får inte lära sig ett slutligt utfall efter en dag. Orealiserad avkastning kan övervakas men blir inte automatiskt rätt träningsetikett. Endast mogna, validerade utfall som var tillgängliga före träningskörningens stoppdatum får användas. Saknad data blir aldrig nollavkastning. Försenade utfall, handelsstopp och avnoteringar hanteras uttryckligt och rapporteras, så att svåra eller förlustbringande fall inte försvinner ur utvärderingen.

### 15 3 Felklassning och orsaksanalys

| Felklass eller utfall | Exempel | Tillåten första åtgärd |
| --- | --- | --- |
| Källfel eller identitet | Fel valuta, bolag, tidszon eller gammal kurs | Karantän och blockering av berörda beräkningar |
| Dokumenttolkning | Negation missas eller miljoner blir miljarder | Källbelagd korrigering och regressionsexempel |
| Beräkningsfel | Framtida värde i feature eller felaktig etikett | Spärra påverkat material och bygg om härledningar |
| Exekveringsfel | Dubbelorder, fel kvantitet eller okänt avslut | Stoppa riskökning och avstäm innan åtgärd |
| Policybrott | Exponeringsgräns kringgås | Blockera och utred incidenten |
| Prognosavvikelse | Korrekt sannolikhetsprognos får negativt utfall | Poängsätt prognosen utan omedelbart regelbyte |
| Möjlig försämring | Sämre prognos eller ekonomi på tillräckligt material | Undersök orsak och skapa kandidat inom policyn |

En incident får identitet, upptäcktstid, kategori, allvar, berörda beslut och data, orsakshypotes och verifieringsstatus. Orsaken får förbli okänd. Slippage över antagandet kan vara marknadsförhållanden, en dålig kostnadsmodell eller ett tekniskt fel och ska inte automatiskt klassas som kodbugg.

Korrigeringar bevarar gammalt och nytt värde, källstöd, orsak, åtgärd och berörda följdartefakter. Läckande dataset och experiment markeras som ogiltiga för tidigare prestandapåståenden. Historiskt realiserat resultat och resultat efter en korrigerad replay visas var för sig. Korrigerad historik skriver inte om den information roboten faktiskt hade.

### 15 4 Minne och granskad återanvändning

Minnet består av fakta, analysen som gjordes då, låst prognos, utfall och separat senare utvärdering. Hämtning vid ett beslut får bara använda information som redan var känd; utfallsdelen kräver ett färdigt och tillgängligt utfall. Ursprunglig analys ersätts aldrig av den efterföljande förklaringen.

Liknande fall kan ge kandidathypoteser och motargument. Vi mäter förbättring mot samma modell utan minne. Minskad kvalitet eller höjd kostnad utan tydligt värde kan motivera att minnesfunktionen stängs av. Ingen förlorad affär blir direkt en ny systeminstruktion.

### 15 5 Träningsjobb och takt per strategi

Första versionen använder batchomträning. En policy anger schema eller utlösande villkor, minsta nya mogna underlag, tillåtna modellfamiljer och egenskaper, historikfönster, antal försök och resursbudget. Ett driftlarm kan skapa ett träningsförslag men ger inte rätt att ersätta modellen.

Intradag kan utvärderas efter avslutade sessioner och avstämda kostnader. Swing behöver färdiga utfall för sin horisont. Långsiktiga strategier och fonder kräver längre uppföljning, med hänsyn till rapport- och NAV-publicering. Ett kort tidsfönster med många korrelerade observationer räknas inte som samma mängd oberoende evidens.

Varje learning_run låser dataurval, etikettversioner, stoppdatum, uppdateringsregel, kod, startmodell och kostnader. Poängsättning och träningsurval har en observationsjournal som unikt identifierar prediction_id, target_definition_id och label_version. En rättelse ersätter eller återtar den gamla observationen i nya resultat; båda räknas inte som två oberoende utfall. Återförsök på samma jobb skapar inte fler försök eller en extra modellpromotion. Endast en utsedd kandidat kan publiceras per dokumenterad jämförelse; inga ändlösa loopar som söker tills något ser bättre ut.

### 15 6 Kandidater och versionsbyten

Kandidatstatus är draft, trained, validated, shadow, eligible, promoted och retired eller rolled_back. Varje övergång får kriterier, mätvärden och skäl. Jämförelsen mot den aktiva modellen använder samma förutsättningar, möjligheter, risk och kostnader. Ingen förändring är ett giltigt beslut om ingen kandidat uppfyller kraven.

Ett driftsättningsmanifest innehåller modell, featureschema, förbehandling, kalibrering, prompt och skill-versioner, riskpolicy, exekveringskonfiguration samt data- och kodreferenser. Det införs atomiskt med oföränderliga versions-ID:n. En alias som pekar på en ny modell räcker inte för att visa vilken kombination som faktiskt användes. MLflow kan bära modellversionerna medan vår kontrolltjänst ansvarar för övergångar och statistiska krav. [S31]

Promotion kräver datakvalitet, mogen oberoende evidens, förregistrerade krav på nettoresultat och risk, relevant kalibrering, godkänd driftsfunktion och oförändrat mandat. En förbättring som beror på större risk får inte döljas som bättre modell. Driftsättning börjar med skuggläge; begränsad aktiv utrullning följer först när tillåten policy och evidens finns.

### 15 7 Vad som får ske automatiskt

| Åtgärd | Automatisk hantering | Begränsning |
| --- | --- | --- |
| Samla utfall och övervaka | Ja enligt definierade jobb | Tids- och kvalitetskontroller gäller |
| Bekräftad datakorrigering | Ny version och ombyggnad | Ursprungliga beslut och påverkan bevaras |
| Träna och jämföra kandidater | Ja inom resurs- och dataram | Ingen egen livebehörighet |
| Minska eller pausa risk | Ja enligt testade regler | Ingen höjning av riskmandat |
| Återställa normal drift | Bara enligt återstartspolicy | Avstämning och observationskrav krävs |
| Byta aktiv modell | Möjligt inom beslutad bytespolicy | Alla kvalitets- och versionskrav måste uppfyllas |
| Ändra kod eller mandat | Isolerat förslag och verifiering | Separat releasepolicy för ändringens kritikalitet |

Startläget för modellpromotion är paper_only. Automatisk modellpromotion i en redan aktiverad livemiljö kan senare tillåtas genom en explicit konfigurerad policy. Policyn anger omfattning, tak och stoppvillkor så att rutinuppdateringar inte kräver ett nytt beslut varje gång. Nya instrumenttyper, höjda risktak, nya datarättigheter och fri ändring av ordersemantik ingår inte i detta mandat.

### 15 8 Teknisk självreparation och återgång

Reparationsflödet är incident, reproducerande test, isolerad kodgren, minsta patch, relevanta tester och replay, skuggläge och versionssatt release enligt ändringspolicy. Agenten får felsöka, föreslå och testa rättningar utan produktions- eller mäklarhemligheter. Den får inte ändra sina egna testkrav eller riskspärrar för att få igenom en patch.

Kritiska ändringar av instrumentmappning, orderlogik, risk eller databokföring kräver särskild verifiering och releasepolicy. Vanliga dataåterförsök och redan testade återstartsprocedurer kan automatiseras separat. Systemet ska minska påverkan när det inte kan reparera ett fel och rapportera vad som återstår.

Senast fungerande versionspaket bevaras. Rollback byter körbar version men behåller verkliga order, innehav, avgifter och kassabok enligt avsnitt 13. Återgång kräver kompatibilitetskontroll för datakontrakt och kvarvarande positioner. Övervaknings- och stoppfunktionen kan inte avaktiveras av den modell som utvärderas.

### 15 9 Mätning som visar om lärandet hjälper

Följ separat datakvalitet, analysfel, prognosfel och kalibrering på mogna utfall, nettoresultat, risk och verkliga exekveringskostnader. Ändrad indatafördelning bevisar inte förlorat prognosvärde. Larmtrösklar tar hänsyn till tid på dagen, period och beroende mellan observationer.

Jämför den oförändrade modellen med hela den adaptiva processen. Mät även avståenden, kandidater som nekats, tid till upptäckt och verifierad rättning, omträningens kostnad, felaktiga återstarter och misslyckade återgångar. Bättre textprecision eller kalibrering är värdefullt men inte samma sak som bättre nettoavkastning.

Lärandets acceptansprov omfattar försenat utfall, korrigerad etikett, framtida minnesinformation, dubblerat träningsjobb, förbrukat sluttest, kandidat med högre risk, ofullständigt versionspaket, överskriden budget och rollback med öppna positioner. Dessa prov måste visa att spärrarna fungerar även när kandidaten ser attraktiv ut.

## 16 Webb och användarflöden

Gränssnittet byggs för att användaren ska kunna följa bevis och resultat. Det ska inte visa en dekorativ AI-poäng utan förklaring.

- Översikt visar kontantandel, samlad exponering, datastatus och aktiva strategier.
- Bevakning visar bolag och instrument, aktuella händelser och källornas ålder.
- Analyskort visar bekräftade uppgifter, relationer, antaganden, motargument och beslut.
- Human-journalen visar ursprungligt modellförslag, mänskligt ingrepp/avstående, aktör, förhandsmotivering, giltighet, versioner och separat utvärdering av bidraget.
- Bolagsvyn samlar rapporter, nyheter, värdering och en filtrerbar relationskarta.
- Fondvyn visar andelsklass, avgifter, innehav, överlapp och ordervillkor.
- Futuresvyn visar underliggande produkt, faktiskt kontrakt och mäklar-ID, förfall, session, tickvärde, nominell exponering, daterad marginal och kommande rullningsgräns.
- Forskningsvyn jämför baslinjer och modeller på samma tidsperiod och kostnadsantaganden.
- Traderdata visar verifieringsnivå, täckning och avstämning före eventuell forskningsanvändning.
- Order och portfölj visar livscykel, delavslut, avgifter och avvikelser mot mäklaren.
- Hedgevyn visar skyddad bok, policy/målrisk, exponering före och efter, faktiskt kontrakt, kvarvarande rest, marginal/kontantbehov, livscykel och larm för hedge utan huvudinnehav. Resultat med och utan hedge hålls åtskilda.
- Lärandevyn visar väntande och mogna utfall, aktiv modell, kandidater, jämförelser och versionshistorik.
- Incidentvyn visar felklass, underlag, berörda beslut, rättningar och verifieringsstatus.
- Driftvyn visar fördröjning, jobb, dataluckor, kostnader, beständigt driftläge och nödstopp.

Inläst artikel får en direkt källänk och synlig versionstid. Statusarna analys, skuggläge, simulerad handel och live ska alltid kunna skiljas åt. Mobilvyn prioriterar bevakning, läsning, avvikelser och stoppfunktioner.

## 17 Säkerhet och drift

Forsknings-, simulerings- och livekonton får separata miljöer och behörigheter. AI-tjänsten saknar handelshemligheter. Webbläsaren får inte mäklarnycklar eller Supabase service_role. RLS och lagringspolicyer testas för det faktiska ägarskapet; en inloggning räcker inte som behörighetskontroll.

Originalexporter och licensierade dokument förvaras privat med åtkomstlogg och fastställd retention. Bara syntetiska eller uttryckligen tillåtna fixtures får ligga i det publika repot. Publikt tillgänglig information och rätt att träna på den är separata frågor.

Backuper ska återläsas i prov. Rådata, konfiguration, databas och modellversioner behöver tillsammans kunna återskapa en körning. Jobb har lås, timeout, återförsök med backoff och en tydlig fellista. Samma jobb får inte producera dubbla dataset eller order.

Övervakning följer feedfördröjning, saknade data, antal karantänrader, analysfel, modellkostnad, avvisade riskkontroller, mäklarkontakt och avstämningsdifferenser. Träningsjobb och reparationsagent har separata behörigheter från ordermotorn. Kandidatartefakter kontrolleras mot tillåten typ, innehåll, hash och versionsmanifest innan de kan laddas. Resurs- och anropsbudgeter begränsar träning, analys och återförsök. Produktionsberoenden och containrar versionslåses. Underhållsregler och API-förändringar kontrolleras före uppgradering.

För Supabase följs aktuell dokumentation, RLS och nyckelhantering. Databasen ska inte göras publikt läsbar för att förenkla utveckling. Den aviserade avvecklingen av äldre TLS-cipherkombinationer i november 2026 ska beaktas vid val av klienter och runtime. [S26]

## 18 Byggordning och leveranskriterier

Varje fas har en leverans som går att demonstrera. Nästa fas ska lösa ett konstaterat behov. Kalenderuppskattningar för utveckling är inte bevis för strategins kvalitet. Återkopplingsloggen byggs före modellträning; det ska gå att lära senare från de första riktiga besluten. Traderdata är en parallell valfri källa och blockerar inte framåtriktad simulering. En separat algoritm, ny modellfamilj eller ny fondtyp införs en i taget när föregående flöde är verifierat.

Version 1.4 ändrar ordningen för fas 2–4: enkel numerisk baslinje och LEAN-replay först, därefter futuresavräkning och hedgesimulering, sedan AI/human edge/graf och utökad forskning. Datakontrakt och en liten dokumentimport kan förberedas parallellt. AI eller ännu obeställd traderhistorik ska inte vara ett beroende för den första prisbaslinjen. Samma krav på tidskorrekt data och oberoende utvärdering gäller i alla spår.

### Fas 0 Rensning och arkitekturbeslut

Genomförd genom PR #10 enligt REBUILD_STATUS.md. Arkivgren, historik och återställningspunkt bevaras. Fortsatt utveckling utgår från aktuell main i avgränsade arbetsgrenar. Dokumentera ändrade arkitekturbeslut och deras bevis utan att upprepa rensningen. Denna planuppdatering inför inga tjänster eller strategier.

### Fas 1 Instrument och datagrund

Leverera datagrunden i avgränsade delar och märk status per del:

- **1a Identitet och offlinekontrakt:** vidareutveckla befintligt instrumentregister, råarkiv, rättighetsdeklarationer och broker-/futureskontrakt. De redan dokumenterade offlineproven räknas inte som autentiserad API- eller marknadsdataverifiering.
- **1b Första pris- och replaypaketet:** importera verifierade daterade kalendrar, priser och bolagshändelser för ett litet deklarerat aktie-/ETF-urval. Leveransen behöver rådata, mottagnings-/bearbetningstider, käll- och användningsstatus, luckrapport och historiska urvalsregler. Klart när omkörning är idempotent, tvetydigheter hamnar i karantän och split, utdelning, namnbyte och tidszon kan återspelas utan framtida information eller dubbelräkning. Detta är datakravet före aktieprovet i fas 2; fullständigt fond- och nyhetsstöd behöver inte vara klart samtidigt.
- **1c Dokument och separata instrumentdata:** bygg en auditerbar SEC-adapter, en nyhetsimport med artikelrevisioner och händelsegruppering, samt NAV som separat datakontrakt. Futures kräver egna produkt-/förfallsidentiteter, kontraktsvisa råpriser, källbelagda villkor, exakta prissteg, sessionsimport, avgifter och tidsbegränsade kontomarginaler före sitt motorprov. En justerad kontinuerlig serie får inte bli orderpris. Varje spår godkänns för sitt avsedda bruk; avsaknad eller tvetydighet blockerar berörda underlag.

Bygg artefaktberoenden, utfallsdefinitioner, utfallskö och separat incidentlogg före första modellträningen. Förbered datakontrakt för human-journal och hedgepolicy; de deklareras som planerade tills körbara flöden verifierats. Hela fas 1 markeras inte klar genom att enbart 1b godkänns.

### Fas 2 Enkel numerisk baslinje och LEAN-replay

Frys en enkel deterministisk prisregel, dess universum, beslutstid, exitpolicy, kostnadsmodell och jämförelse mot kontanter och relevant riskjämförbar benchmark. Gör LEAN-provet med normaliserade data från godkänd fas 1b, utan AI-påverkan på portföljbeslut. Registrera kandidater och avståenden när de uppstår. Modellera avgifter, spread, fördröjning, handelstider, delavslut och möjliga uteblivna avslut; biblioteksstandarder får inte ersätta verifierade antaganden för vårt urval. [S44]

Klart när samma datamanifest, kod och konfiguration ger reproducerbar replay med avstämda avslut, positioner, utdelningar, split och kassa. Visa att ett avslut inte kan inträffa före möjlig orderankomst, att kandidatens giltighet skiljs från positionens exitpolicy och att driftlägen och kostnadsattribution fungerar. Tidsdelning och försöksjournal ska fungera från första regelvarianten, även utan ML. Teknisk acceptans visar korrekt simulering; lönsamhet prövas separat enligt avsnitt 14.

Dokumentera motorprovets resultat, pinnad version och beslut om direktdrift eller betald CLI-väg. LEAN är första provet; byte till NautilusTrader kräver ett dokumenterat problem och jämförbart prov. Qlib blir inte en extra ordermotor.

### Fas 3 Futuresavräkning och hedgesimulering

Efter avstämd kassabok i fas 2 och godkända futuresdata i fas 1c byggs ett avgränsat futuresprov. Använd råa förfallande kontrakt, fulla initial-/underhållskrav, kontospecifik marginalreservation, daglig variation margin, slutavräkning, avgifter och rullningskostnader. Samma prisrörelse får inte bokföras dubbelt. Avstäm en rullning med delavslut och avvisat andra ben; båda benens samtidiga exponering måste rymmas inom kontots risk.

Koppla därefter en deklarerad aktie-/ETF-bok till en fryst indexhedgepolicy enligt avsnitt 13 1–13 2. Klart när exponering före/efter, avrundningsrest, budget och kontantbehov är spårbara och alla livscykelprov i avsnitt 13 2 fungerar. Jämför osäkrad portfölj, hedge, kombination och enklare kontantalternativ enligt avsnitt 14 1, inklusive samtidig förlust och höjda marginalkrav. Ett motorbiblioteks stöd eller gröna fixtures är inte bevis för extern mäklarintegration, ekonomisk fördel eller livebehörighet.

### Fas 4 AI human edge bolagsgraf och utökad forskning

Bygg en händelsetyp, en verifierad direkt bolagsrelation och ett källbelagt analyskort med dokumentdata som godkänts i fas 1c. Kör samma händelse från rådata till strukturerat resultat. Klart för analysdelen när kvalitetsutvärderingen i avsnitt 9, källstöd och explicit avstående fungerar även för motsägelsefulla eller irrelevanta dokument. Demonstrera att ett ännu inte tillgängligt utfall inte kan bli minne eller träningsdata.

Inför human-journalen enligt avsnitt 9 1. Visa att en bedömning registreras före beslutet, att rättelse/utgång inte skriver om historiken och att originalförslag och faktiskt beslut kan jämföras. Håll hypotetiska alternativ skilda från verkliga avslut. AI, direkta händelser, graf och mänskliga ingrepp läggs till ett lager i taget och jämförs mot den frysta prisbaslinjen från fas 2. Långsiktiga strategier behåller egna horisonter och krav på mogna utfall.

Utöka kronologisk utvärdering och experimentregister. Lägg till första ML-modellen först när datakontrakt, artefaktberoenden, utfallskö och incidentlogg är stabila. Klart när slutperioden är orörd, alla försök är registrerade och rapporten visar kostnadskänslighet samt osäkerhet. Inför modellregister, begränsade kandidatkörningar och deklarerad promotionpolicy i paper_only. Testa hela läranderegeln med fördröjda etiketter och jämför mot en fryst modell. Sluttestet får inte återanvändas som orört efter modellval. Ett negativt resultat är ett giltigt utfall.

### Fas 5 Traderhistorik

Lägg till mäklarexport och valfri Collective2-adapter. Verifiera tidszon, kostnader, kontoavstämning, källa och rättigheter. Klart när ett verkligt tillåtet material har full dokumenterad täckning för avsett bruk. Saknas underlag fortsätter egen forskning utan att kalla materialet träningsklart.

### Fas 6 Framåtriktad simulering

Kör skugganalys och därefter simulerade order med separata strategiböcker. Testa återstart, dubbel kvittens, nätverksavbrott, avvisad order, delavslut och nödstopp. Klart när alla kritiska avstämningsfel är lösta och framåtriktade beslut går att rekonstruera. Kör även modellbyte och rollback med öppna positioner och försenade avslut. Fondorder används här som syntetiska kontraktsprov inför nästa fas. Visa att en misslyckad kandidat stannar i simulering och att avstämningen överlever versionsbytet. En bestämd månadslängd bevisar inte alpha.

Första verkliga brokertransporten verifieras i en uttryckligt konfigurerad papermiljö med order-, positions-, fill- och kassaavstämning; den befintliga läsande referensadaptern ersätter inte detta prov. Verifiera därefter en andra mäklaradapter inom dess faktiska kapacitet och håll samma kanoniska strategikontrakt. Upprepa okänd status, sena avslut och konto-isolering utan automatisk failover. Human- och hedgeflöden får påverka paperkonton först efter sina respektive kontrakts-, risk- och livscykelprov; stöd för en tillgång hos första brokern antas inte finnas hos den andra.

### Fas 7 Fondallokering och mäklarkapacitet

Bygg exponering genom fondinnehav, avgiftskontroll och långsam ombalansering. Genomför fondorderprovet för vald distributör om gränssnitt finns. Klart när bryttider, kursdag, väntande order, kassa och likvid är korrekt representerade. Visa även försenad NAV och korrigerad fondetikett i lärandeloopen. Upprepa versionsbytes- och rollbackproven genom det färdiga fondflödet med väntande order; kontraktsproven i fas 6 ersätter inte detta. Analys får levereras även om automatisk fondhandel ännu inte stöds.

### Fas 8 Begränsad live och kontrollerad utveckling

Verifiera varje brokers aktuella konto, anslutningsmiljö, tillgängliga instrument, feedavtal, riskbudget och mäklaradapter. Gemensamma strategier måste klara kontospecifik risk och samlad exponering; ingen automatisk broker-failover sker efter okänd orderstatus. Kräv också godkänd förregistrerad strategiutvärdering enligt avsnitt 14; bristande eller otillräckliga resultat blockerar live. Live aktiveras som ett separat beslut med vald kapitalgräns och godkända strategiversioner. Följ verkliga avslut och kostnader mot simuleringen. Vid driftfel minskas eller stoppas risken enligt policy. Ett eventuellt automatiskt modellbyte får bara ske inom publicerad policy enligt avsnitt 15 och måste kunna återgå utan att tappa öppna order. Det finns ingen automatisk upptrappning baserad på några få vinster.

## 19 Första konkreta utvecklingsuppgifter

Följande grund finns redan enligt REBUILD_STATUS.md. Den ska bevaras och byggas vidare på; uppgifterna ska inte utföras som en ny rensning eller få högre verifieringsstatus genom denna dokumentändring.

| Befintlig grund | Dokumenterat läge och gräns |
| --- | --- |
| Arkivgren och ombyggnadsgrund | Genomförd genom PR #10; återställningspunkt och historik bevarade |
| Enhet, instrument, notering och tidsversionerade källor | Implementerade offline; historiska identifierarfrågor och korrigeringsprov finns, full bolagshändelseimport saknas |
| Datakatalog och användningsdeklarationer | Standardmässig spärr och metadata finns; verkliga användningsrättigheter och träningsberedskap är inte verifierade |
| Futuresprodukt, förfall, villkor och öppningsunderlag | Offlineberäkningar med syntetiska sessioner/marginaler; ingen rullning, avräkning eller samlad riskmotor |
| Kontoavgränsade brokerformat och beständiga underlag | Två syntetiska kodare och idempotenta utkast finns; ingen riktig ordertransport |
| Alpaca paper referensläsare | GET-läsare för konto/tillgångar finns; autentiserad åtkomst och handelsförmåga är inte verifierade |

Öppna uppgifter följer beroendeordningen i avsnitt 18. P1 för numerisk baslinje är nu tidigare än P2 för större AI-/grafbygge. Datakontrakt för senare flöden kan förberedas parallellt utan att funktionen räknas som implementerad.

| Prioritet | Fas | Uppgift | Bevis för klar leverans |
| --- | --- | --- | --- |
| P1 | 1b | Auktoritativa kalendrar, prisimport och bolagshändelser | Täckt period, luckrapport, historiskt urval och replay av split, utdelning, namnbyte och tidszon |
| P1 | 1c | SEC-adapter, nyhetsimport och separat NAV-kontrakt | Källversioner, enheter, publicerings-/bearbetningstid och artikelrevisioner bevaras; berört bruk prövas separat |
| P1 | 1 | Artefaktberoenden och incidentlogg | En rättelse markerar rätt följdartefakter utan att skriva om beslut |
| P1 | 1–2 | Låsta beslut/prognoser, utfallskö och opportunity-logg | Kandidater och avståenden sparas före utfallet; en femdagarsetikett är spärrad tills den är tillgänglig |
| P1 | 1/4 | Datakontrakt för human-journal | Aktör, förhandsmotivering, originalförslag och giltighet bevaras; körbar jämförelse verifieras i fas 4 |
| P1 | 1/3 | Datakontrakt för hedgepolicy och kopplingar | Skyddad exponering, målrisk, kontoroute och budget är explicita; simulering verifieras i fas 3 |
| P1 | 2 | Fryst numerisk baslinje och kronologiskt försöksregister | Urval, regel, exit och kostnader låsta före sluttest; inga framtida ingångsvärden |
| P1 | 2 | LEAN-replay och kassabok | Avgifter, utdelning, split, delavslut och kassa avstämda; samma manifest ger samma resultat |
| P1 | 3 | Futuresavräkning och rullningsreplay | Variation/slutavräkning dubbelräknas inte; delavslut och avvisat andra ben avstäms |
| P1 | 3 | Hedgesimulering och livscykel | Sålt huvudinnehav, sena avslut, förfall och stopp lämnar spårbar kvarvarande risk och tillåten åtgärd |
| P1 | 3 | Hedgens risk- och resultatattribution | Osäkrad portfölj, hedge, kombination och kontantalternativ jämförs med kontantbehov och samtidiga förlustfall |
| P2 | 4 | AI-extraktion och händelsegruppering | Källstycken, siffror, negation, avstående och dubbletter klarar avsnitt 9:s prov |
| P2 | 4 | Direkt bolagsrelation | Tidssatt källa och explicit okänd exponering; extra prognosvärde jämförs mot pris/direkt nyhet |
| P2 | 4 | Human-journal och jämförelse | Förhandsregistrerat ingrepp/avstående, utgång och rättelse kan rekonstrueras; faktisk och hypotetisk väg skiljs åt |
| P2 | 4 | Modellregister och kandidatjämförelse | Samma möjligheter och kostnader samt oförändrat riskmandat |
| P2 | 4 | Policy för automatisk promotion | Nekad kandidat förblir inaktiv; start i paper_only och spårbart versionsbeslut |
| P2 | 4 | Test av hela läranderegeln | Fördröjt utfall poängsätts före uppdatering och ett förbrukat sluttest återanvänds inte som orört |
| P2 | 5 | Traderexportadapter | Original, delavslut, avgifter och kapitalhistorik avstämda för tillåtet material |
| P3 | 6 | Första papertransport och andra brokeradapter | Avstämning, konto-isolering, återanslutning och okänd status ger inga dubbla order |
| P3 | 6 | Isolerad reparationskedja och versionsåtergång | Fel reproduceras utan handelshemligheter; öppna positioner och sena avslut behålls efter rollback |
| P2 | 7 | NAV-simulator och fondflöde | Order före/efter bryttid får rätt kursdag; försenad och korrigerad NAV samt väntande order hanteras |
| P3 | 6–8 | Drift och återställningsprov | Backup återläst, oberoende stopp demonstrerat och realiserat kontotillstånd bevarat |

## 20 Kostnader och beslut som behöver mätas

Budgeten delas mellan historiska data, livefeed, nyheter och estimat, fonddata, mäklaravgifter, lagring, beräkning och modellanalys. Handel för egen räkning och professionell vidareanvändning kan ha olika datavillkor. Budgeten ska därför bygga på faktisk användningsklass och offert.

Futuresbudgeten särredovisar börs-/databehörighet, kontraktsvis historik, orderboksnivå, clearing-/mäklaravgifter och säkerhetslikviditet. Ingen aktuell marginalnivå hårdkodas som ett allmängiltigt belopp.

Första mätningen omfattar kostnad per analyserad händelse, per godkänt analyskort och per simulerad strategidag. Spara tokenåtgång, modellval, cacheträffar, datauttag, lagring och worker-tid. Återanvänd analys för samma dokumentversion; en senare uppdatering får en ny körning. Träningsförsök och felsökningsloopar har tak för tid, antal kandidater och kostnad; ett larm får inte starta obegränsad omträning.

De praktiska valen är första mäklarkonto, dataleverantör, månatlig databudget, första fondurval och eventuell rätt att använda traderexporter. De hindrar inte att datakontrakt och offlinekedja byggs. De måste däremot vara avgjorda innan kontospecifik livehandel eller ett betalt dataköp genomförs.

## 21 Instruktion till nästa byggagent

Läs AGENTS.md, denna plan och REBUILD_STATUS.md först. Arbeta i en avgränsad arbetsgren från aktuell main. Fas 0 är redan genomförd och offlinegrunden ska bevaras. Fortsätt fas 1 med ett avgränsat pris-/kalender-/bolagshändelsepaket och reproducerbar replay. Följ därefter fas 2 med fryst numerisk baslinje och LEAN-provet, före större AI-/grafbygge. SEC-/nyhets- och separata instrumentkontrakt kan utvecklas parallellt enligt fas 1c och blockeras per användningsfall.

Håll datahämtning, analys, simulering, återkoppling och orderläggning i separata kontrakt. Bygg artefaktberoenden, utfallskö och incidentlogg innan den första modellen tränas. Förbered human- och hedgekontrakt utan att märka funktionerna som färdiga. Verifiera human-journalen enligt avsnitt 9 1 och hedgeflödena enligt avsnitt 13–14 innan de påverkar paperhandel. Implementera avsnitt 15 som en del av varje relevant fas, inte som en senare självlärande-funktion utan indata.

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
- S31 MLflow modellregister och versionshantering: https://mlflow.org/docs/latest/ml/model-registry/workflow/
- S32 River fördröjd löpande utvärdering: https://riverml.xyz/dev/api/evaluate/progressive-val-score/
- S33 River projekt och licens: https://github.com/online-ml/river
- S34 scikit-learn om kalibrering: https://scikit-learn.org/stable/modules/calibration.html

De första leveransernas verifieringsjournal ska ange faktiska API-prov, datatäckning, kostnader, körningar och resultat. Denna plan är kravbilden som de leveranserna bedöms mot.

Futureskällor tillagda i version 1.2, kontrollerade 20 oktober 2026:

- S35 CME MNQ kontraktsegenskaper: https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html
- S36 CME förfall och kontraktsrullning: https://www.cmegroup.com/education/courses/introduction-to-futures/understanding-futures-expiration-contract-roll
- S37 CME marginaler och föränderliga krav: https://www.cmegroup.com/solutions/risk-management/performance-bonds-margins.html
- S38 CME fysisk leverans: https://www.cmegroup.com/articles/brochures-and-handbooks/101-overview-delivery.html
- S39 QuantConnect/LEAN kontraktskedjor och mappningsbyten: https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/futures/handling-data

Brokerkällor tillagda i version 1.3, kontrollerade 20 oktober 2026:

- S40 Alpaca order-ID, status och buying power: https://docs.alpaca.markets/us/docs/orders-at-alpaca
- S41 IBKR TWS socketprotokoll och anslutningsmodell: https://www.interactivebrokers.com/docs/tws-api/doc/introduction

Källor till preciseringarna i version 1.4, kontrollerade 25 oktober 2026. Våra policy-, journal- och acceptanskrav ovan är konstruktionsbeslut, inte färdiga funktioner hos en leverantör:

- S42 CME om aktieindexhedging, beta, kontraktsstorlek och kvarvarande risk: https://www.cmegroup.com/education/whitepapers/hedging-with-e-mini-sp-500-future
- S43 CME om daglig mark-to-market och kontantbehov: https://www.cmegroup.com/education/courses/introduction-to-futures/mark-to-market
- S44 QuantConnect om avslutsmodeller, kvantiteter, spread och slippage: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts
