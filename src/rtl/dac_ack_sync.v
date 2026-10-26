module dac_ack_sync(
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 clk CLK", X_INTERFACE_PARAMETER="ASSOCIATED_RESET resetn" *) input wire clk,
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 resetn RST", X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire resetn,
    input wire ack_async, output wire ack_sync);
    (* ASYNC_REG="TRUE" *) reg ack_meta,ack_ff;
    always @(posedge clk) if(!resetn) begin ack_meta<=0;ack_ff<=0;end
        else begin ack_meta<=ack_async;ack_ff<=ack_meta;end
    assign ack_sync=ack_ff;
endmodule
