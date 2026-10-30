"""Verify Phase-0 artifacts against the export on disk (deterministic)."""
from pathlib import Path

E = Path("frontend/design/stitch_export_final/reelworld_not_found_404_error_states/code.html").read_text()
V = Path("frontend/views/404.html").read_text()
S = Path("frontend/index.html").read_text()

print("== 404 view: export strings present in my view?")
for s in ["PLATE-ROUTE-NULL", "System Exceptions", "Honest Recovery",
          "Diagnostic Ledger", "Unmapped Index", "LOAD-FAILURE",
          "Our Error Handling Philosophy", "Honest Failure",
          "Zero Telemetry Leaks", "Preserved Sandboxes",
          "Kenyan Architectural Cadastre Protocol v4", "Active Vault Seal",
          "Archival Waypoints", "Back to Reel", "Browse the Collection"]:
    print(f"  export-has={s in E} mine-has={s in V} :: {s}")

print("== shell header/footer vs export header/footer?")
for s in ["ReelWorld", "Built with Muse Spark Open", "Private Vault",
          "Archival Photographic Repository", "never indexed without explicit"]:
    print(f"  export-has={s in E} shell-has={s in S} :: {s}")

print("== my intentional removals (must be absent from my files)?")
for s in ["NBO-EDGE", "99.98%", "Inspect Pipe", "32ms round-trip"]:
    print(f"  in-my-404={s in V} in-shell={s in S} :: {s}")
