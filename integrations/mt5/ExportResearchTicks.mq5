// Read-only research export. No account, order, position or subscription APIs.
// Not compiled or executed in the project build environment; see MT5_EXPORT_SV.md.
#property strict
#property script_show_inputs
#property version "1.00"
#property description "Export an explicit UTC-ms interval of native bid/ask ticks for research."

input string InpSymbol = "";          // Empty: current chart symbol, including broker suffix
input ulong InpFromUtcMsc = 0;        // Inclusive UTC epoch milliseconds; mandatory
input ulong InpToUtcMsc = 0;          // Inclusive UTC epoch milliseconds; mandatory

#define RESEARCH_MAX_TICKS 500000
const ulong RESEARCH_CHUNK_MSC = 900000;
const ulong RESEARCH_MAX_INTERVAL_MSC = 604800000;
const ulong RESEARCH_MAX_TIME_MSC = 253402300799999;

// Fixed storage bounds each terminal response. A small-buffer error is fatal.
MqlTick g_ticks[RESEARCH_MAX_TICKS];
string g_symbol, g_currency = "", g_run_id, g_dir, g_failure = "";
long g_digits = -1, g_rows = 0, g_returned = 0, g_duplicates = 0;
long g_first_msc = 0, g_last_msc = 0, g_calls = 0, g_chunks_completed = 0;
double g_contract_size = 0;
bool g_facts_observed = false, g_csv_verified = false;
int g_csv = INVALID_HANDLE, g_lock = INVALID_HANDLE;
int g_failure_error = 0, g_copy_error = 0;
ulong g_csv_expected_bytes = 0, g_csv_observed_bytes = 0;

string ULongText(const ulong value)
{
   return StringFormat("%I64u", value);
}

void Fail(const string reason, const int error = 0)
{
   // Preserve the first cause; CopyTicksRange's captured error is also separate.
   if(g_failure == "")
   {
      g_failure = reason;
      g_failure_error = error;
   }
}

string JsonString(const string value)
{
   string result = "\"";
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort ch = StringGetCharacter(value, i);
      if(ch == 34) result += "\\\"";
      else if(ch == 92) result += "\\\\";
      else if(ch < 32 || ch > 126) result += StringFormat("\\u%04x", (uint)ch);
      else result += ShortToString(ch);
   }
   return result + "\"";
}

bool IsMetadataToken(const string value)
{
   if(StringLen(value) < 1 || StringLen(value) > 64) return false;
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort ch = StringGetCharacter(value, i);
      if(ch <= 32 || ch == 127 || ch == 133 || ch == 160 || ch == 0x1680 ||
         (ch >= 0x2000 && ch <= 0x200A) || ch == 0x2028 || ch == 0x2029 ||
         ch == 0x202F || ch == 0x205F || ch == 0x3000) return false;
   }
   return true;
}

string Metadata(const string status)
{
   string facts = g_facts_observed ? "true" : "false";
   string verified = g_csv_verified ? "true" : "false";
   string first = g_rows > 0 ? IntegerToString(g_first_msc) : "null";
   string last = g_rows > 0 ? IntegerToString(g_last_msc) : "null";
   string result = "{\r\n";
   result += "  \"schema_version\":1,\r\n";
   result += "  \"source_id\":" + JsonString(g_run_id) + ",\r\n";
   result += "  \"source_export_status\":" + JsonString(status) + ",\r\n";
   result += "  \"symbol\":" + JsonString(g_symbol) + ",\r\n";
   result += "  \"price_currency\":" + JsonString(g_currency) + ",\r\n";
   result += "  \"price_currency_verified\":false,\r\n";
   result += "  \"price_currency_basis\":\"Observed SYMBOL_CURRENCY_PROFIT is a candidate; quote denomination requires independent review.\",\r\n";
   result += "  \"contract_multiplier\":" + JsonString(StringFormat("%.17g", g_contract_size)) + ",\r\n";
   result += "  \"contract_multiplier_verified\":false,\r\n";
   result += "  \"timestamp_basis\":\"utc_epoch_milliseconds\",\r\n";
   result += "  \"timezone_evidence\":\"CopyTicksRange uses inclusive milliseconds since 1970: https://www.mql5.com/en/docs/series/copyticksrange ; MetaQuotes states MT5 stored ticks use UTC: https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py . Native MqlTick.time_msc retained without a display-time shift.\",\r\n";
   result += "  \"clock_scope\":\"Terminal API market tick clock; not a broker fill or trader decision clock.\",\r\n";
   result += "  \"data_origin\":\"user_supplied_unverified\",\r\n";
   result += "  \"usage_rights\":\"not_verified\",\r\n";
   result += "  \"training_usage_rights\":\"not_verified\",\r\n";
   result += "  \"training_rights\":\"not_verified\",\r\n";
   result += "  \"broker_verified\":false,\r\n";
   result += "  \"training_ready\":false,\r\n";
   result += "  \"full_history_verified\":false,\r\n";
   result += "  \"trading_enabled\":false,\r\n";
   result += "  \"model_trained\":false,\r\n";
   result += "  \"record_type\":\"market_bid_ask_tick\",\r\n";
   result += "  \"copy_ticks_flags\":\"COPY_TICKS_ALL\",\r\n";
   result += "  \"source_order_preserved\":true,\r\n";
   result += "  \"equal_millisecond_rows_preserved\":true,\r\n";
   result += "  \"timestamp_projection\":\"none\",\r\n";
   result += "  \"price_serialization\":\"Native MqlTick double formatted with 17 significant digits; no SYMBOL_DIGITS rounding.\",\r\n";
   result += "  \"liquidity_evidence\":\"Bid/ask quotes only; no executable depth, fills or volume claim.\",\r\n";
   result += "  \"csv_file\":\"quotes.csv\",\r\n";
   result += "  \"csv_encoding\":\"UTF-8\",\r\n";
   result += "  \"csv_io_verified\":" + verified + ",\r\n";
   result += "  \"csv_expected_bytes\":" + ULongText(g_csv_expected_bytes) + ",\r\n";
   result += "  \"csv_observed_bytes\":" + ULongText(g_csv_observed_bytes) + ",\r\n";
   result += "  \"requested_from_utc_msc\":" + ULongText(InpFromUtcMsc) + ",\r\n";
   result += "  \"requested_to_utc_msc\":" + ULongText(InpToUtcMsc) + ",\r\n";
   result += "  \"chunk_milliseconds\":" + ULongText(RESEARCH_CHUNK_MSC) + ",\r\n";
   result += "  \"maximum_exported_raw_ticks\":500000,\r\n";
   result += "  \"raw_rows_written\":" + IntegerToString(g_rows) + ",\r\n";
   result += "  \"ticks_returned_by_terminal\":" + IntegerToString(g_returned) + ",\r\n";
   result += "  \"equal_timestamp_row_count\":" + IntegerToString(g_duplicates) + ",\r\n";
   result += "  \"first_time_msc\":" + first + ",\r\n";
   result += "  \"last_time_msc\":" + last + ",\r\n";
   result += "  \"copy_ticks_calls\":" + IntegerToString(g_calls) + ",\r\n";
   result += "  \"chunks_completed\":" + IntegerToString(g_chunks_completed) + ",\r\n";
   result += "  \"last_copy_ticks_error\":" + IntegerToString(g_copy_error) + ",\r\n";
   result += "  \"failure_reason\":" + JsonString(g_failure) + ",\r\n";
   result += "  \"failure_error_code\":" + IntegerToString(g_failure_error) + ",\r\n";
   result += "  \"terminal_facts\":{\"observed\":" + facts;
   result += ",\"symbol\":" + JsonString(g_symbol);
   result += ",\"digits\":" + IntegerToString(g_digits);
   result += ",\"profit_currency\":" + JsonString(g_currency);
   result += ",\"trade_contract_size\":" + JsonString(StringFormat("%.17g", g_contract_size)) + "},\r\n";
   result += "  \"contract_multiplier_basis\":\"Observed SYMBOL_TRADE_CONTRACT_SIZE; PnL convention and quantity units require review.\",\r\n";
   result += "  \"publication_rule\":\"Only metadata.json plus a completed terminal report is final; ignore .pending and metadata.started.json.\"\r\n";
   return result + "}\r\n";
}

// Write ASCII-escaped JSON through the explicit UTF-8 code page, then publish
// only after exact byte count, flush, size and close checks. Never FILE_REWRITE.
bool WriteNewMetadata(const string name, const string status, int &error)
{
   string destination = g_dir + "\\" + name;
   string pending = destination + ".pending";
   if(FileIsExist(destination) || FileIsExist(pending)) { error = 0; return false; }
   ResetLastError();
   int handle = FileOpen(pending, FILE_WRITE|FILE_TXT|FILE_ANSI, 0, CP_UTF8);
   error = GetLastError();
   if(handle == INVALID_HANDLE || error != 0)
   {
      if(handle != INVALID_HANDLE) FileClose(handle);
      return false;
   }
   string payload = Metadata(status);
   ResetLastError();
   uint written = FileWriteString(handle, payload);
   error = GetLastError();
   bool valid = error == 0 && written == (uint)StringLen(payload);
   ResetLastError();
   FileFlush(handle);
   int flush_error = GetLastError();
   if(flush_error != 0) { valid = false; if(error == 0) error = flush_error; }
   ResetLastError();
   ulong size = FileSize(handle);
   int size_error = GetLastError();
   if(size_error != 0 || size != (ulong)StringLen(payload))
   { valid = false; if(error == 0) error = size_error; }
   ResetLastError();
   FileClose(handle);
   int close_error = GetLastError();
   if(close_error != 0) { valid = false; if(error == 0) error = close_error; }
   if(!valid) return false;
   ResetLastError();
   bool moved = FileMove(pending, 0, destination, 0);
   error = GetLastError();
   return moved && error == 0;
}

bool ReserveRun()
{
   // TimeLocal is a filename token only: never a market clock or UTC assertion.
   string prefix = "mt5_" + IntegerToString((long)TimeLocal()) + "_" + ULongText(GetTickCount64());
   for(int attempt = 0; attempt < 100; attempt++)
   {
      string candidate = prefix + "_" + IntegerToString(attempt);
      string directory = "ResearchTicks\\" + candidate;
      ResetLastError();
      int handle = FileOpen(directory + "\\run.lock", FILE_READ|FILE_WRITE|FILE_BIN|FILE_ANSI, 0, CP_UTF8);
      int open_error = GetLastError();
      if(handle == INVALID_HANDLE || open_error != 0)
      { if(handle != INVALID_HANDLE) FileClose(handle); continue; }
      ResetLastError();
      ulong size = FileSize(handle);
      int size_error = GetLastError();
      bool occupied = size != 0 || size_error != 0 ||
         FileIsExist(directory + "\\quotes.csv") || FileIsExist(directory + "\\metadata.json") ||
         FileIsExist(directory + "\\metadata.started.json") ||
         FileIsExist(directory + "\\metadata.started.json.pending") || FileIsExist(directory + "\\metadata.json.pending");
      if(occupied) { FileClose(handle); continue; }
      ResetLastError();
      uint written = FileWriteString(handle, "reserved");
      int write_error = GetLastError();
      ResetLastError();
      FileFlush(handle);
      int flush_error = GetLastError();
      if(written != 8 || write_error != 0 || flush_error != 0)
      { FileClose(handle); continue; }
      // No SHARE flags: concurrent instances cannot hold this reservation.
      g_lock = handle; g_run_id = candidate; g_dir = directory;
      return true;
   }
   return false;
}

bool ReadTerminalFacts()
{
   if(!IsMetadataToken(g_symbol)) { Fail("UNSUPPORTED_SYMBOL_TOKEN"); return false; }
   ResetLastError();
   bool read = SymbolInfoInteger(g_symbol, SYMBOL_DIGITS, g_digits);
   int error = GetLastError();
   if(!read || error != 0 || g_digits < 0) { Fail("SYMBOL_DIGITS_READ_FAILED", error); return false; }
   ResetLastError();
   read = SymbolInfoString(g_symbol, SYMBOL_CURRENCY_PROFIT, g_currency);
   error = GetLastError();
   if(!read || error != 0 || !IsMetadataToken(g_currency)) { Fail("PROFIT_CURRENCY_READ_FAILED", error); return false; }
   ResetLastError();
   read = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_CONTRACT_SIZE, g_contract_size);
   error = GetLastError();
   if(!read || error != 0 || !MathIsValidNumber(g_contract_size) || g_contract_size <= 0)
   { Fail("CONTRACT_SIZE_READ_FAILED", error); return false; }
   g_facts_observed = true;
   return true;
}

bool WriteCsvRow(const string time, const string bid, const string ask)
{
   // Three ASCII strings, two commas, CRLF. No native FileWrite double rounding.
   uint expected = (uint)(StringLen(time) + StringLen(bid) + StringLen(ask) + 4);
   ResetLastError();
   uint written = FileWrite(g_csv, time, bid, ask);
   int error = GetLastError();
   if(error != 0 || written != expected) { Fail("CSV_WRITE_FAILED", error); return false; }
   g_csv_expected_bytes += expected;
   return true;
}

void CloseOutputs()
{
   if(g_csv != INVALID_HANDLE)
   {
      bool valid = true;
      ResetLastError(); FileFlush(g_csv);
      int error = GetLastError();
      if(error != 0) { valid = false; Fail("CSV_FLUSH_FAILED", error); }
      ResetLastError(); g_csv_observed_bytes = FileSize(g_csv);
      error = GetLastError();
      if(error != 0 || g_csv_observed_bytes != g_csv_expected_bytes)
      { valid = false; Fail("CSV_SIZE_MISMATCH", error); }
      ResetLastError(); FileClose(g_csv);
      error = GetLastError(); g_csv = INVALID_HANDLE;
      if(error != 0) { valid = false; Fail("CSV_CLOSE_FAILED", error); }
      g_csv_verified = valid;
   }
   if(g_lock != INVALID_HANDLE)
   {
      ResetLastError(); FileClose(g_lock);
      int error = GetLastError(); g_lock = INVALID_HANDLE;
      if(error != 0) Fail("RESERVATION_CLOSE_FAILED", error);
   }
}

void Finish()
{
   CloseOutputs();
   int error = 0;
   string status = g_failure == "" ? "completed" : "failed";
   if(!WriteNewMetadata("metadata.json", status, error))
   {
      Fail("FINAL_METADATA_PUBLICATION_FAILED", error);
      int report_error = 0;
      // If publication failed, leave all earlier evidence and attempt a separate
      // failed report. The pending file is explicitly never an admitted export.
      WriteNewMetadata("metadata.failed.json", "failed", report_error);
      Print("Research tick export failed: FINAL_METADATA_PUBLICATION_FAILED; MQL5\\Files\\", g_dir);
      return;
   }
   Print("Research tick export ", status, "; rows=", g_rows, "; reason=", g_failure,
         "; MQL5\\Files\\", g_dir, "\\metadata.json");
}

void OnStart()
{
   g_symbol = InpSymbol == "" ? _Symbol : InpSymbol;
   if(!ReserveRun()) { Print("Research tick export failed: CANNOT_RESERVE_UNIQUE_OUTPUT"); return; }
   int error = 0;
   if(!WriteNewMetadata("metadata.started.json", "in_progress", error))
   { Fail("INITIAL_METADATA_PUBLICATION_FAILED", error); Finish(); return; }
   if(InpFromUtcMsc == 0 || InpToUtcMsc == 0 || InpToUtcMsc < InpFromUtcMsc ||
      InpToUtcMsc > RESEARCH_MAX_TIME_MSC ||
      InpToUtcMsc - InpFromUtcMsc >= RESEARCH_MAX_INTERVAL_MSC)
   { Fail("INVALID_EXPLICIT_UTC_INTERVAL"); Finish(); return; }
   if(!ReadTerminalFacts()) { Finish(); return; }
   if(FileIsExist(g_dir + "\\quotes.csv")) { Fail("OUTPUT_ALREADY_EXISTS"); Finish(); return; }
   ResetLastError();
   g_csv = FileOpen(g_dir + "\\quotes.csv", FILE_WRITE|FILE_CSV|FILE_ANSI, ',', CP_UTF8);
   error = GetLastError();
   if(g_csv == INVALID_HANDLE || error != 0) { Fail("CSV_OPEN_FAILED", error); Finish(); return; }
   if(!WriteCsvRow("time_msc", "bid", "ask")) { Finish(); return; }

   ulong start = InpFromUtcMsc;
   while(start <= InpToUtcMsc && g_failure == "")
   {
      if(IsStopped()) { Fail("USER_STOPPED_EXPORT"); break; }
      if(g_rows >= RESEARCH_MAX_TICKS) { Fail("TICK_LIMIT_REACHED_BEFORE_INTERVAL_END"); break; }
      ulong end = InpToUtcMsc;
      if(end - start >= RESEARCH_CHUNK_MSC) end = start + RESEARCH_CHUNK_MSC - 1;
      ResetLastError();
      int copied = CopyTicksRange(g_symbol, g_ticks, COPY_TICKS_ALL, start, end);
      g_copy_error = GetLastError(); // Capture before any file or formatting API.
      g_calls++;
      if(copied < 0) { Fail("COPY_TICKS_FAILED", g_copy_error); break; }
      g_returned += copied;
      int remaining = RESEARCH_MAX_TICKS - (int)g_rows;
      int retain = copied < remaining ? copied : remaining;
      for(int i = 0; i < retain; i++)
      {
         if(IsStopped()) { Fail("USER_STOPPED_EXPORT"); break; }
         long clock = g_ticks[i].time_msc;
         double bid = g_ticks[i].bid, ask = g_ticks[i].ask;
         if(clock <= 0 || (ulong)clock < start || (ulong)clock > end ||
            (g_rows > 0 && clock < g_last_msc)) { Fail("INVALID_OR_DECREASING_TICK_CLOCK"); break; }
         if(!MathIsValidNumber(bid) || !MathIsValidNumber(ask) || bid <= 0 || ask <= 0 || ask < bid)
         { Fail("INVALID_BID_ASK_TICK"); break; }
         if(!WriteCsvRow(IntegerToString(clock), StringFormat("%.17g", bid), StringFormat("%.17g", ask))) break;
         if(g_rows == 0) g_first_msc = clock;
         else if(clock == g_last_msc) g_duplicates++;
         g_last_msc = clock; g_rows++;
      }
      if(g_failure != "") break;
      // A positive partial result with an error is NEVER completion or retry.
      if(g_copy_error != 0) { Fail("COPY_TICKS_PARTIAL_OR_ERROR", g_copy_error); break; }
      if(copied > remaining) { Fail("TICK_LIMIT_EXCEEDED"); break; }
      g_chunks_completed++;
      if(end == InpToUtcMsc) break;
      start = end + 1; // Inclusive windows never overlap or split equal-ms ticks.
   }
   if(g_failure == "" && g_rows == 0) Fail("NO_TICKS_IN_INTERVAL");
   if(g_failure == "" && IsStopped()) Fail("USER_STOPPED_EXPORT");
   Finish();
}
