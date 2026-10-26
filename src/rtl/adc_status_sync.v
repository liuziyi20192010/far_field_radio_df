`timescale 1ns / 1ps
// Status bits are independently meaningful; software must poll DMA completion
// before treating a frame as available in DDR.
module adc_status_sync (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK",
       X_INTERFACE_PARAMETER = "ASSOCIATED_RESET resetn" *)
    input wire clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST",
       X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input wire resetn,
    input wire [2:0] status_async,
    output wire [2:0] status_sync
);
    (* ASYNC_REG = "TRUE" *) reg [2:0] status_meta, status_ff;
    always @(posedge clk) begin
        if (!resetn) begin
            status_meta <= 0;
            status_ff <= 0;
        end else begin
            status_meta <= status_async;
            status_ff <= status_meta;
        end
    end
    assign status_sync = status_ff;
endmodule
