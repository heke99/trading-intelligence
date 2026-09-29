# Så tar du fram underlaget — Collective2-importören

## Vad som är byggt

Första kodpaketet kan läsa Collective2 API4: historiska stängda trades och historiska
order. Det kan också läsa sparade API-svar eller CSV-filer med en uttryckligen
kontrollerad kolumnmappning. Rådata, versionshistorik och kvalitetsrapporter sparas lokalt.

Detta är **datainsamlingen**, inte en färdig robot. Marknadsdataimport, tidsriktig
modellträning, utvärdering och handel återstår. Inga riktiga order kan skickas av paketet.

## 1. Börja med en eller två originalexporter

Första kandidaterna är:

- FOREX VIX-3, strategi-ID `134962085`: https://collective2.com/details/134962085
- Calicut Commodities, strategi-ID `146455121`: https://collective2.com/details/146455121

Det är provkällor för integrationen, inte ett beslut om vilka strategier roboten ska
kopiera eller vilka investeringar du ska göra. Historiska placeringar är inte bevis
för framtida resultat. Valutahistoriken ska inte automatiskt tolkas som M1-handel.

Logga in på Collective2 och öppna strategins **Trade Record / Trading Record**.
Vid granskningen fanns en länk **Download CSV**. Välj **Both** för både riktning och
vinst/förlust så att du inte av misstag bara exporterar vinnare. Välj hela perioden om
gränssnittet erbjuder ett periodval. Kontrollera vilka filter exporten faktiskt använder.

Spara filen i original. Ändra inte datumen, byt inte kolumnnamn och öppna/spara inte
om filen i Excel innan vi granskat den. En skärmbild av sammanställningen kan hjälpa
oss stämma av antal och period, men ersätter inte själva datafilen.

Skriv i en separat textfil:

```text
Plattform: Collective2
Strategi-ID:
Strateginamn:
Exportdatum och tid:
Vald period:
Valda filter:
Antal affärer enligt gränssnittet:
Äldsta och senaste datum enligt gränssnittet:
Tidszon enligt plattformens besked: okänd om ej verifierad
Typ av resultat: plattformens hypotetiska strategiresultat / annan verifierad källa
Rätt att hämta och lagra: vad som har bekräftats
Rätt till forskning/modellträning: okänd om ej bekräftad
Rätt till kommersiell användning: okänd om ej bekräftad
Eventuella kända dataluckor:
```

Behörighet och fullständighet är ännu inte provade med ett autentiserat konto.
En synlig Download CSV-länk bevisar inte att alla konton får hela historiken.
Om du möter inloggnings- eller abonnemangskrav: be supporten bekräfta rätt åtkomst
innan du betalar. Aktivera inte AutoTrade för att försöka få en dataexport att fungera.

Det första vi behöver få är originalfilen och textinformationen. Kontonummer kan
avidentifieras i en separat kopia om de förekommer, men bevara order-/positions-ID:n
eller pseudonymisera dem konsekvent så att kopplingarna inte förstörs. Behåll originalet
privat. Lägg inte kontofiler i det offentliga repot.

## 2. Automatisk import med API4

Collective2s aktuella API4-sida pekar på https://collective2.com/apikey där du
loggar in, skapar en nyckel och väljer dess roll. En äldre supportartikel pekar
också på https://collective2.com/account-info och **Configure APIv4 keys**.
Det är utvecklarnyckeln för API4 vi behöver, inte
API3/PlatformTransmit. Be om minsta möjliga läsbehörighet för de två datafunktionerna.
Det är inte verifierat att ditt standardkonto har rätt till just dessa strategier.

Kör från kodpaketets rot på din Mac med Python 3.11 eller senare:

```bash
python3 -m trading_intelligence fetch \
  --strategy-id 134962085 \
  --out data/forex-vix-3 \
  --acknowledge-authorized-access
```

Terminalen frågar efter nyckeln utan att visa den. **Nyckeln ska stanna på din dator.**
Skicka den inte till chatten, lägg den inte i källkoden och skriv den inte som ett
argument efter kommandot. Bekräftelseflaggan betyder att du har rätt att hämta och
lagra uppgifterna; den betyder inte att en modellträningslicens har kontrollerats.

Kör en separat import för nästa strategi:

```bash
python3 -m trading_intelligence fetch \
  --strategy-id 146455121 \
  --out data/calicut \
  --acknowledge-authorized-access
```

Vid 401/403 eller `API_RESPONSE_ERROR`: skicka felkoden och funktionsnamnet till
supporten, inte hela API-nyckeln. En bredare nyckel med handelsrättigheter är inte
vår standardlösning på nekad historikåtkomst.

Körningen skapar en manifestfil och normaliserade data. Dela vid behov manifestet
och tillåtna originalexporter för granskning. Manifestet ska fortfarande säga
`training_ready: false` — det är korrekt i denna första version.

## 3. Mail till Collective2

Till: **help@collective2.com**

Ämne: **Historical data access and ML research permission — API4**

```text
Hello Collective2 team,

We are building a read-only research system that links historical strategy
orders and closed trades to contemporaneous market data. We are not seeking
to activate AutoTrade, place orders or redistribute a live signal feed.

For an initial pilot, we would like access to strategies 134962085 (FOREX
VIX-3) and 146455121 (Calicut Commodities), including their full available
history through GetStrategyHistoricalClosedTrades and GetStrategyHistoricalOrders.

Could you confirm the necessary account/API4 permissions and costs, and whether
you can supply a small sample export plus the total available row counts and
inception/end dates? We also need to know whether canceled/expired orders,
archived periods and any historical revisions are included.

Please clarify the timezone of OpenDate and CloseDate when no UTC offset is
present, the timezone of the website CSV export, the meaning and units of each
quantity/contract, the P&L currency, and whether ProfitLoss already includes
Commission and other fees. Please distinguish simulated strategy fills from
any separately available real brokerage executions. Are actual fill timestamps,
open positions, historical equity and cash flows available?

Finally, please confirm in writing whether our permitted use includes storing
the data, training/evaluating machine-learning models, and commercial use of the
resulting models. Please specify any required consent from the strategy managers,
restrictions on derived data or retention after access ends, and whether a
separate agreement is needed. We are not assuming these rights follow from a
standard subscription.

Thank you,
Hekmat
```

Mailet är ett utkast; det har inte skickats. Det är en konkret begäran om åtkomst och
villkor, inte ett påstående om att standardvillkoren redan ger alla rättigheter.

## 4. Underlaget som behövs för korrekt inlärning

### Historiska beslut och genomföranden

Fullständiga öppnings-/stängningsrader med stabila ID:n, strategi-ID, symbol,
kontraktstyp, riktning, volym, pris, tidsstämplar och tillgängliga kostnader.
Råorder behövs utöver sammanfattade trades när vi ska förstå flera entries,
ändringar och delstängningar. Ursprunglig besluts-/publiceringstid är inte samma
sak som fill-tid. Historiska orderrader kan vara slutliga ögonblicksbilder snarare
än en händelselogg över alla förändringar.

### Kontot och riskbilden

Öppna positioner, eventuell historisk kontovärdering, insättningar/uttag, avgifter,
finansiering och kontraktsstorlekar. Annars kan stängda vinster dölja flytande
förluster eller felaktigt beräknad risk. Dessa kompletteringar importeras inte
automatiskt av den här första versionen — be om originalfilerna separat.

### Marknadsdata

Priser från tiden före och under varje affär, på rätt instrument/kontrakt och med
känd tidszon. För kortsiktig valutahandel efterfrågar vi bid/ask och spread, inte
bara ett mittpris. För aktier behövs även korrekt hantering av bolagshändelser,
noteringshistorik, handelskalender och eventuell blankningskostnad.

Köp inte stora dataabonnemang innan vi sett instrumentlistan, tidshorisonterna
och faktisk historiktäckning. Då kan vi specificera rätt källa och period.
Denna version innehåller ingen marknadsdataklient; den delen byggs efter första
verifierade traderexporten.

### Traderns motiv — när de faktiskt finns

Journaltext, strategibeskrivning, taggar och dokumenterade avstådda beslut.
Bevara skapandetid och ändringstid. Anteckningar skrivna efter affären får inte
förvandlas till information som roboten antas ha känt före affären.

Motiv kan saknas; det hindrar inte beteendeanalys. Då säger vi "mönster som modellen
hittar", inte "bevisad förklaring till traderns beslut". Avsaknad av en order betyder
inte säkert att en aktiv trader beslutade att avstå. Be gärna om aktiva tider och
vilka instrument som faktiskt bevakades.

### Historikens urval

Hela den tillåtna perioden, även förluster och svaga marknadsfaser. Senare behöver
vi också jämförelsestrategier och nedlagda strategier, inte bara dagens vinnare.
Topplacering, stor avkastning och många kopierande konton bevisar inte oberoende,
framtida användbar information. Vilka lärare vi väljer måste också utvärderas.

## 5. Vad nästa kodsteg blir efter filerna

Först avstämmer vi källan och kör importen med verkliga data. Vi granskar radantal,
första/sista datum, ID-kopplingar, tidszoner, instrumentenheter och kostnadsdefinitioner.
Därefter byggs marknadsmatchningen: ingen uppgift från efter beslutet får finnas i
modellens indata. Handelsfrekvensen väljs efter källans faktiska beteende, inte
utifrån att vi på förhand vill kalla allt M1.

Sedan jämförs en modell utan traderhistorik mot en modell med traderhistorik på
senare, osedda perioder under samma risk- och kostnadsantaganden. Textmotiveringar
blir en separat jämförelse om de finns. Därefter följer skuggkörning och demo.
En modell som bara kopierar historiken övertygande är inte färdig för riktiga pengar.

## 6. Var koden finns

Koden finns på `main` i https://github.com/heke99/trading-intelligence .
Välj **Code → Download ZIP** på GitHub eller klona repot. Kör kommandona i
`README.md` från projektets rot. Kontrollera den senaste körningen på
https://github.com/heke99/trading-intelligence/actions och den daterade
verifieringen i `docs/VERIFICATION.md` om koden ändras efter denna leverans.

Behåll traderfiler och nycklar utanför repot även om det görs privat. Dela endast
kontofiler här om du har tillstånd för den behandlingen; annars kan vi börja med
kolumnlistan och ett tillåtet avidentifierat prov medan hela importen körs lokalt.
