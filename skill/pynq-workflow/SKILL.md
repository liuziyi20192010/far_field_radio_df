---
name: pynq-workflow
description: Build and diagnose PYNQ overlays using an explicit hardware contract, matched BIT/HWH artifacts, bounded simple AXI DMA transfers, buffer ownership, and golden-reference evidence. Use for PYNQ data acquisition or accelerator projects; adapt board pins and packet formats to the actual hardware.
---

# PYNQ workflow

Make the interface contract explicit before generating host code: board/part and image version; IP instance names and VLNV; register offsets/bitfields; stream width, byte length and TLAST; cache policy; start/done/rearm; reset/quiescence. Never infer these from another project's constants or from an IP name alone.

Read [interface_contract.md](references/interface_contract.md) when creating or changing an overlay interface. BIT, same-stem HWH and host decoder must come from one build. Use `scripts/overlay_audit.py --bit <file> --contract <json> --manifest <json>` before loading. The audit is read-only and proves configured metadata/hashes, not electrical compatibility or bitstream correctness. Check `overlay.ip_dict` and the actual IP `register_map` on the target image before changing registers.

For finite simple AXI DMA S2MM, use [dma_and_cdc.md](references/dma_and_cdc.md) and `scripts/dma_session.py`. Compute bytes from count and dtype; compare against the configured BTT width, DRE/alignment and allocation. Receive must be armed before a producer starts. Keep the PYNQ buffer alive until completion and driver cache invalidation; copy results before freeing. Timeout, transfer errors and KeyboardInterrupt require retention until a successful hardware reset ends every old write. A stopped notebook/UI is insufficient. One physical DMA needs one shared owner. The helper assumes the AXI DMA simple S2MM register layout; do not apply it to SG, cyclic DMA or MCDMA.

Separate transport correctness from signal/algorithm correctness: use a counter or known vector for the first, then independent same-frame reference results for the second. Compare stages from raw samples to intermediate accumulators, products and final output when diagnosing divergence. Use `scripts/golden_compare.py <npz> --tolerance <limit>` (add `--circular` only for degrees), and `scripts/report_metrics.py <report_dir>`. Reject unknown report formats instead of inventing numbers. Preserve invalid/overrange frames in evidence.

Before changing an estimator or adding compensation for a stable measurement bias, check source outputs, cable seating, common reference, input range and calibration conditions. Keep physical observations separate from digital same-frame agreement. For notebook presentation changes, read [presentation_and_evidence.md](references/presentation_and_evidence.md): simplify the normal view while retaining invalid states, raw diagnostics and reproducible evidence outside it.

Read [pitfalls.md](references/pitfalls.md) for a matching symptom, and [prompts.md](references/prompts.md) to organize model/tool correction loops. Verify a claimed improvement with the same input and defined baseline; label simulation, offline mock behavior, calculated bounds and board measurements separately. Templates and prompts are aids, not independently proven universal workflows.

The scripts contain no ADC format, carrier frequency, phase protocol, package pins or fixed DMA instance name. A new board still needs its own PS/DDR/MIO, constraints and image compatibility checks. Cross-board physical validation has not been performed; see the parent [README](../README.md) for demonstrated scope and failure conditions.
