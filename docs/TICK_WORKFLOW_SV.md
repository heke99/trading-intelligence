# Tickflöde för fem marknader

Detta byggsteg förbereder EURUSD, Nasdaq, XAUUSD, GBPJPY och EURJPY. "GPBJPY" i beställningen tolkas som GBPJPY. Exakta mäklarsymboler och Nasdaq-produkt är fortfarande okända. Ingen ny verklig tickhistorik har införskaffats: den enda HistData-katalogbegäran gav 0 byte. Källgranskning, kod och fiktiva testdata räknas separat.

## Plan och original

Kör `scalper-research tick-plan --out data/tick-plan` för en plan med fem separata underlag. Den föreslagna perioden är 2024-01-01 till 2026-10-01 exklusivt, en måltäckning som inte har bekräftats av användaren eller leverantören. Inga filer hämtas av kommandot.

Första kontrollen behöver en liten originalfil per exakt instrument samt leverantörens klockbeskrivning och användningsvillkor. Se [källgranskningen](TICK_SOURCE_AUDIT_SV.md), [underlagslistan](TICK_EXECUTION_EVIDENCE_SV.md) och [MT5-exporten](MT5_EXPORT_SV.md). NSXUSD är HistDatas Nasdaq 100-serie; den är inte verifierad som CME NQ/MNQ eller användarens CFD.

Original, licensunderlag och runtimefiler hålls utanför Git. Tidstämpelmin/max visar observerad räckvidd; det bevisar inte obruten historik eller saknade ticks. Täckning måste jämföras med daterade sessioner, helgdagar och en källinventering.

## Lokal HistData-konvertering

Välj leverantörens Generic ASCII Tick, inte minutstaplar. Konverteraren tar en redan legitimt införskaffad, uppackad CSV med fyra fält per rad och utan rubrik: datum/tid, bid, ask, råvolym. Den laddar inte ned eller packar upp ZIP.

Importspecifikationen är ett eget JSON-underlag:

```json
{
  "schema_version": 1,
  "format": "histdata_generic_ascii_tick_v1",
  "source_file_sha256": "<64 lowercase hex from the original CSV>",
  "symbol": "EURUSD",
  "native_timestamp_basis": "fixed_est_milliseconds",
  "native_timezone_utc_offset_minutes": -300,
  "source_clock_evidence": "https://www.histdata.com/f-a-q/",
  "source": {
    "schema_version": 1,
    "source_id": "histdata_eurusd_original_sample",
    "symbol": "EURUSD",
    "price_currency": "USD",
    "timestamp_basis": "utc_epoch_milliseconds",
    "timezone_evidence": "Converted from documented fixed EST without DST",
    "data_origin": "user_supplied_unverified",
    "usage_rights": "not_verified",
    "training_usage_rights": "not_verified"
  }
}
```

Byt symbol till GBPJPY/EURJPY och price_currency till JPY för de två korsen. XAUUSD/NSXUSD har USD. Beräkna SHA-256 från originalets bytes; ersätt platshållaren. En hash styrker byteidentitet, inte äkthet eller rättigheter.

```bash
scalper-research import-histdata private/original.csv \
  --spec private/import.spec.json --out data/histdata-sample
```

En slutförd manifest anger `quotes_csv_path`, `quotes_metadata_path` och `native_ticks_path`. OriginalCSV och specifikation arkiveras med hash före validering. Native datumtext, decimaltexter, råvolym och fysisk källrad bevaras. Fast EST blir alltid UTC +5 timmar, även på sommaren. Volymfältet används inte som verifierad handelsvolym, orderflöde eller fill.

`usage_rights=user_asserted_permitted` kräver konkret `rights_evidence`. Verklig modellfitting kräver dessutom ett separat explicit `training_usage_rights=user_asserted_permitted` och `training_rights_evidence`. Skriv bara detta om det stöds av befintligt underlag. Ingen assertion höjer training_ready eller full_history_verified.

## Samma millisekund och luckor

Råimporten bevarar distinkta ticks med samma millisekund och fysisk radordning. Den skapar inga nya tider, sorterar inte och tappar inte dubbletter. Den befintliga replay-/lärandemotorn kräver strikt stigande observationsklocka; native dubbletter behandlas därför i ett separat deklarerat projektionssteg.

```bash
scalper-research project-ticks data/source.csv \
  --metadata data/source.metadata.json --sample-period-ms 1000 \
  --max-native-gap-ms 1000 --out data/projection
```

Intervallet [start, slut) väljer den sista fysiska källraden strikt före slutet. En senare native tid visar att intervallet är avslutat; dess pris får aldrig påverka det tidigare intervallet. Utdata är märkta med intervallets sluttid. Detta förutsätter en virtuell händelseklocka, inte observerad broker-/mottagningstid. Vittnets tid och fördröjning loggas separat. Den härledda observationen bevisar inte en faktisk tick eller exekverbar likviditet vid gränsen.

Tomma intervall fylls inte framåt. En för stor native lucka gör intervallet med den senare raden ogiltigt och startar ett nytt segment. Tidigare redan avslutat intervall påverkas inte retroaktivt. Sista oavslutade intervallet utelämnas. Alla råa accepterade rader finns kvar i arkiv och JSONL-bevis.

Perioden måste vara 1–1000 ms. Native luckgräns är explicit och får inte bredda ärvda WSE-/projektionsgränser. Replay, learning, stress och paper måste följa den minsta av alla kvarvarande observationsluckgränser. Tätare sampling kan lämna för få rena observationer; ingen pris-/volym-/fillinformation uppfinns för att få modellen att passa.

## Fryst lokal forskning

Varje instrument har sin egen fullständiga config med mängdenhet, kontraktsmultiplikator, prisvaluta, kommission, slippage, latens, riskgräns och utvecklings-/valideringsgräns. Utgå från befintliga configschemat i [replayguiden](SCALPER_REPLAY_SV.md). Använd daterade faktiska villkor eller tydligt deklarerade forskningsantaganden. USD och JPY summeras inte utan dokumenterad historisk valutakonvertering.

```bash
scalper-research tick-run data/source.csv \
  --metadata data/source.metadata.json --config private/frozen.config.json \
  --sample-period-ms 1000 --max-native-gap-ms 1000 --out data/tick-research
```

Kommandot arkiverar källCSV, metadata och config före vidare steg. Det projicerar, passar en separat regelhypotes på utvecklingsperioden, väljer tröskel på valideringen och utvärderar senare test samt fem fördeklarerade kostnadsscenarier med samma frysta modell. Det omtränar inte på validering/test. Okända träningsrättigheter, fel instrument/valuta, för bred luckpolicy eller ofullständiga steg lämnar en färdig felmanifest.

Hypotetiska labels kommer från den oberoende regelmodellen. De är inte Fabio Valentinis eller Sivas verkliga beslut. Imitation kräver komplett attribuerad fillhistorik och samtida beslutsunderlag. Återkörning gör inte en externt redan granskad testperiod orörd.

CSV-inläsning och härledda CSV är begränsade till 32 MiB och 500 000 rader per körning; native JSONL-bevis till 256 MiB. Stora månads-/årsarkiv kräver separat granskad uppdelning och periodinventering. Ingen automatisk sammanslagning av hela flerårshistoriken påstås vara implementerad. Detta byggsteg är avsett för ett verifierat originalprov och ett explicit forskningsfönster.

## Fiktiv verifiering

`scalper-research tick-demo --out data/tick-demo` kör fem separata helt fiktiva produkter genom tickbevarande, projektion, utvecklingsfitting, fryst valideringsval, test och kostnadsstress. Nasdaq-symbolen är NAS100_SYNTHETIC. Alla priser, storlekar och avgifter är fixtures; JPY-resultat hålls separata. Körningen är ett tekniskt funktionstest och räknas inte som marknadshistorik, brokerforwardtest eller avkastningsbevis.

MT5-filerna behöver dessutom kompileras och provexporteras i användarens terminal. Ingen MetaEditor eller broker finns i CI. Verklig data, historiska kontrakt/kostnader, användningsrätt och brokerdemofills återstår före bedömning för livehandel. Samtliga acceptance-flaggor förblir false.
