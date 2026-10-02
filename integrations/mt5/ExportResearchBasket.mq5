// Read-only research basket export. No account/order/position/subscription APIs.
// Not compiled or executed here. Exact symbol inputs are mandatory; see docs.
#property strict
#property script_show_inputs
#property version "1.00"
#property description "Export explicit UTC-ms native bid/ask quotes for one to five exact symbols."

input string InpSymbols = "";       // Mandatory comma-separated exact symbols; no spaces or aliases
input ulong InpFromUtcMsc = 0;      // Inclusive UTC epoch milliseconds; mandatory
input ulong InpToUtcMsc = 0;        // Inclusive UTC epoch milliseconds; mandatory

#include "ResearchTickExport.mqh"

#define RESEARCH_BASKET_MAX_SYMBOLS 5
#define RESEARCH_BASKET_MAX_INPUT_LENGTH 324
string b_symbols[];
string b_entries[RESEARCH_BASKET_MAX_SYMBOLS];
string b_run_id = "", b_dir = "", b_failure = "", b_request = "";
int b_count = 0, b_attempted = 0, b_completed = 0, b_failed = 0;
int b_failure_error = 0, b_lock = INVALID_HANDLE;
bool b_inputs_valid = false, b_user_stop_observed = false;

void BasketFail(const string reason, const int error = 0)
{
   if(b_failure == "") { b_failure = reason; b_failure_error = error; }
}

bool ValidateBasketInputs()
{
   int length = StringLen(InpSymbols);
   b_request = length <= RESEARCH_BASKET_MAX_INPUT_LENGTH ? InpSymbols : "<REJECTED_OVERSIZE_SYMBOL_LIST>";
   if(length < 1 || length > RESEARCH_BASKET_MAX_INPUT_LENGTH)
   { BasketFail("EXPLICIT_SYMBOL_LIST_REQUIRED_OR_TOO_LONG"); return false; }
   if(StringGetCharacter(InpSymbols, 0) == 44 ||
      StringGetCharacter(InpSymbols, length - 1) == 44 || StringFind(InpSymbols, ",,") >= 0)
   { BasketFail("EMPTY_SYMBOL_TOKEN"); return false; }
   ResetLastError();
   int count = StringSplit(InpSymbols, StringGetCharacter(",", 0), b_symbols);
   int error = GetLastError();
   if(count < 1 || count > RESEARCH_BASKET_MAX_SYMBOLS || error != 0)
   { BasketFail("SYMBOL_COUNT_OR_SPLIT_INVALID", error); return false; }
   for(int i = 0; i < count; i++)
   {
      if(!IsMetadataToken(b_symbols[i]))
      { BasketFail("UNSUPPORTED_SYMBOL_TOKEN"); return false; }
      for(int j = 0; j < i; j++)
         if(b_symbols[i] == b_symbols[j])
         { BasketFail("DUPLICATE_EXACT_SYMBOL_TOKEN"); return false; }
   }
   if(InpFromUtcMsc == 0 || InpToUtcMsc == 0 || InpToUtcMsc < InpFromUtcMsc ||
      InpToUtcMsc > RESEARCH_MAX_TIME_MSC ||
      InpToUtcMsc - InpFromUtcMsc >= RESEARCH_MAX_INTERVAL_MSC)
   { BasketFail("INVALID_EXPLICIT_UTC_INTERVAL"); return false; }
   b_count = count;
   for(int i = 0; i < b_count; i++)
      b_entries[i] = "{\"symbol\":" + JsonString(b_symbols[i]) +
         ",\"status\":\"not_started\",\"asset_metadata\":null,\"raw_rows_written\":0,\"failure_reason\":\"\"}";
   b_inputs_valid = true;
   return true;
}

string BasketManifest(const string status)
{
   string result = "{\r\n";
   result += "  \"schema_version\":1,\r\n";
   result += "  \"record_kind\":\"explicit_native_quote_basket_export\",\r\n";
   result += "  \"source_id\":" + JsonString(b_run_id) + ",\r\n";
   result += "  \"source_export_status\":" + JsonString(status) + ",\r\n";
   result += "  \"requested_symbol_list\":" + JsonString(b_request) + ",\r\n";
   result += "  \"symbol_inputs_valid\":" + (b_inputs_valid ? "true" : "false") + ",\r\n";
   result += "  \"requested_from_utc_msc\":" + ULongText(InpFromUtcMsc) + ",\r\n";
   result += "  \"requested_to_utc_msc\":" + ULongText(InpToUtcMsc) + ",\r\n";
   result += "  \"maximum_symbols\":5,\r\n";
   result += "  \"maximum_raw_ticks_per_asset\":500000,\r\n";
   result += "  \"maximum_raw_ticks_basket\":2500000,\r\n";
   result += "  \"symbol_count\":" + IntegerToString(b_count) + ",\r\n";
   result += "  \"assets_attempted\":" + IntegerToString(b_attempted) + ",\r\n";
   result += "  \"assets_completed\":" + IntegerToString(b_completed) + ",\r\n";
   result += "  \"assets_failed\":" + IntegerToString(b_failed) + ",\r\n";
   result += "  \"user_stop_observed\":" + (b_user_stop_observed ? "true" : "false") + ",\r\n";
   result += "  \"failure_reason\":" + JsonString(b_failure) + ",\r\n";
   result += "  \"failure_error_code\":" + IntegerToString(b_failure_error) + ",\r\n";
   result += "  \"symbol_resolution\":\"Exact supplied tokens only; no aliases, defaults, automatic symbol selection or subscriptions.\",\r\n";
   result += "  \"terminal_history_sync_possible\":true,\r\n";
   result += "  \"network_scope\":\"No network API is called by the script; CopyTicksRange may synchronize through the terminal's existing server connection.\",\r\n";
   result += "  \"market_record_scope\":\"Bid/ask only; no last/volume/flags sidecar, expert history or execution evidence.\",\r\n";
   result += "  \"cross_asset_sequence_verified\":false,\r\n";
   result += "  \"historical_contract_terms_verified\":false,\r\n";
   result += "  \"usage_rights\":\"not_verified\",\r\n";
   result += "  \"training_usage_rights\":\"not_verified\",\r\n";
   result += "  \"broker_verified\":false,\r\n";
   result += "  \"training_ready\":false,\r\n";
   result += "  \"full_history_verified\":false,\r\n";
   result += "  \"model_trained\":false,\r\n";
   result += "  \"trading_enabled\":false,\r\n";
   result += "  \"publication_rule\":\"Use each asset's completed metadata.json and terminal report; basket completion is not complete historical coverage or market approval.\",\r\n";
   result += "  \"assets\":[";
   for(int i = 0; i < b_count; i++)
   {
      if(i > 0) result += ",";
      result += b_entries[i];
   }
   return result + "]\r\n}\r\n";
}

// Exactly the original metadata writer's ASCII-escaped UTF-8 publication checks:
// write count, flush, size, close and non-replacing FileMove must all succeed.
bool WriteNewBasketManifest(const string name, const string status, int &error)
{
   string destination = b_dir + "\\" + name;
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
   string payload = BasketManifest(status);
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

bool ReserveBasketRun()
{
   // TimeLocal is a filename token only, never a tick clock or UTC evidence.
   string prefix = "mt5_basket_" + IntegerToString((long)TimeLocal()) + "_" + ULongText(GetTickCount64());
   for(int attempt = 0; attempt < 100; attempt++)
   {
      string candidate = prefix + "_" + IntegerToString(attempt);
      string directory = "ResearchTickBaskets\\" + candidate;
      ResetLastError();
      int handle = FileOpen(directory + "\\run.lock", FILE_READ|FILE_WRITE|FILE_BIN|FILE_ANSI, 0, CP_UTF8);
      int open_error = GetLastError();
      if(handle == INVALID_HANDLE || open_error != 0)
      { if(handle != INVALID_HANDLE) FileClose(handle); continue; }
      ResetLastError();
      ulong size = FileSize(handle);
      int size_error = GetLastError();
      bool occupied = size != 0 || size_error != 0 ||
         FileIsExist(directory + "\\basket.json") || FileIsExist(directory + "\\basket.started.json") ||
         FileIsExist(directory + "\\basket.json.pending") || FileIsExist(directory + "\\basket.started.json.pending");
      if(occupied) { FileClose(handle); continue; }
      ResetLastError();
      uint written = FileWriteString(handle, "reserved");
      int write_error = GetLastError();
      ResetLastError(); FileFlush(handle);
      int flush_error = GetLastError();
      ResetLastError(); ulong reserved_size = FileSize(handle);
      int reserved_size_error = GetLastError();
      if(written != 8 || write_error != 0 || flush_error != 0 ||
         reserved_size_error != 0 || reserved_size != 8)
      { FileClose(handle); continue; }
      b_lock = handle; b_run_id = candidate; b_dir = directory;
      return true;
   }
   return false;
}

void CloseBasketReservation()
{
   if(b_lock == INVALID_HANDLE) return;
   ResetLastError(); FileClose(b_lock);
   int error = GetLastError(); b_lock = INVALID_HANDLE;
   if(error != 0) BasketFail("BASKET_RESERVATION_CLOSE_FAILED", error);
}

void FinishBasket()
{
   CloseBasketReservation();
   int error = 0;
   string status = b_failure == "" && b_completed == b_count && b_inputs_valid ? "completed" : "failed";
   if(!WriteNewBasketManifest("basket.json", status, error))
   {
      BasketFail("BASKET_FINAL_PUBLICATION_FAILED", error);
      int report_error = 0;
      WriteNewBasketManifest("basket.failed.json", "failed", report_error);
      Print("Research basket export failed: BASKET_FINAL_PUBLICATION_FAILED; MQL5\\Files\\", b_dir);
      return;
   }
   Print("Research basket export ", status, "; completed=", b_completed, "; failed=", b_failed,
         "; reason=", b_failure, "; MQL5\\Files\\", b_dir, "\\basket.json");
}

void OnStart()
{
   ValidateBasketInputs();
   if(!ReserveBasketRun())
   { Print("Research basket export failed: CANNOT_RESERVE_UNIQUE_BASKET_OUTPUT"); return; }
   int error = 0;
   if(!WriteNewBasketManifest("basket.started.json", "in_progress", error))
   { BasketFail("BASKET_INITIAL_PUBLICATION_FAILED", error); FinishBasket(); return; }
   if(!b_inputs_valid) { FinishBasket(); return; }
   for(int i = 0; i < b_count; i++)
   {
      if(IsStopped()) { b_user_stop_observed = true; BasketFail("BASKET_USER_STOPPED"); break; }
      bool completed = ExportResearchSymbol(b_symbols[i], InpFromUtcMsc, InpToUtcMsc);
      b_attempted++;
      if(completed) b_completed++;
      else { b_failed++; BasketFail("ONE_OR_MORE_ASSET_EXPORTS_FAILED"); }
      string metadata_path = g_dir == "" || !FileIsExist(g_dir + "\\metadata.json") ?
         "null" : JsonString(g_dir + "\\metadata.json");
      b_entries[i] = "{\"symbol\":" + JsonString(b_symbols[i]) +
         ",\"status\":" + JsonString(completed ? "completed" : "failed") +
         ",\"asset_metadata\":" + metadata_path +
         ",\"asset_output_directory\":" + (g_dir == "" ? "null" : JsonString(g_dir)) +
         ",\"raw_rows_written\":" + IntegerToString(g_rows) +
         ",\"equal_timestamp_row_count\":" + IntegerToString(g_duplicates) +
         ",\"csv_io_verified\":" + (g_csv_verified ? "true" : "false") +
         ",\"failure_reason\":" + JsonString(g_failure) +
         ",\"failure_error_code\":" + IntegerToString(g_failure_error) +
         ",\"last_copy_ticks_error\":" + IntegerToString(g_copy_error) + "}";
      int checkpoint_error = 0;
      if(!WriteNewBasketManifest("basket.asset_" + IntegerToString(i + 1) + ".json", "in_progress", checkpoint_error))
         BasketFail("BASKET_CHECKPOINT_PUBLICATION_FAILED", checkpoint_error);
      // A failed symbol does not block independent symbols. An explicit user
      // stop does: unattempted entries remain not_started in the final receipt.
      if(IsStopped()) { b_user_stop_observed = true; BasketFail("BASKET_USER_STOPPED"); break; }
   }
   FinishBasket();
}
