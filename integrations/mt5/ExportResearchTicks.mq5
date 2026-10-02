// Read-only research export. No account, order, position or subscription APIs.
// Not compiled or executed in the project build environment; see MT5_EXPORT_SV.md.
#property strict
#property script_show_inputs
#property version "1.00"
#property description "Export an explicit UTC-ms interval of native bid/ask ticks for research."

input string InpSymbol = "";          // Empty: current chart symbol, including broker suffix
input ulong InpFromUtcMsc = 0;        // Inclusive UTC epoch milliseconds; mandatory
input ulong InpToUtcMsc = 0;          // Inclusive UTC epoch milliseconds; mandatory

#include "ResearchTickExport.mqh"

void OnStart()
{
   // Preserve the original single-symbol empty-input chart default.
   ExportResearchSymbol(InpSymbol == "" ? _Symbol : InpSymbol, InpFromUtcMsc, InpToUtcMsc);
}
