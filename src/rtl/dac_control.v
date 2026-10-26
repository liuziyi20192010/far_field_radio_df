`timescale 1ns/1ps
// Dual synchronous ROM DDS interface derived from reference/hs_dual_da.v and da_wave_send.v.
// Exact 10-point phase sampling and Q6 coefficients are generated mathematically
// by scripts/prepare_sources.py; the converter output is rounded only once.
// GPIO bundle: [9:0] phase, [18:10] gain (0..256), [19] enable, [20] request toggle.
// Software holds the entire bundle until ack; apply atomically at a 10-sample boundary.
module dac_control(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK",
       X_INTERFACE_PARAMETER = "ASSOCIATED_RESET resetn" *) input wire clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST",
       X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) input wire resetn,
    input wire [20:0] config_async,
    output reg ack,
    (* IOB="TRUE" *) output reg [9:0] da_data_1, da_data_2,
    output wire da_clk_1, da_clk_2
);
    (* ASYNC_REG="TRUE" *) reg [20:0] config_meta, config_sync;
    reg request_delayed;
    reg [9:0] offset;
    reg [8:0] gain;
    reg enabled;
    reg [3:0] index;
    // lcm(10,1024)=5120 phase positions: index/10 + offset/1024.
    // Unlike rounded 1024-point addresses, this represents every requested
    // sample phase exactly before coefficient/amplitude quantization.
    wire [12:0] addr1 = {index,9'b0};
    // Compute 5*offset only when a configuration is committed. Registering
    // this constant removes a carry chain from every ROM sample address.
    reg [12:0] phase_base;
    wire [13:0] phase_sum = {1'b0,addr1} + {1'b0,phase_base};
    wire [12:0] addr2 = phase_sum>=14'd5120 ? phase_sum-14'd5120 : phase_sum[12:0];
    reg [3:0] reference_index_q;
    reg [12:0] addr2_q;
    // A power-of-two physical depth prevents a partial ROM tail becoming
    // a large LUT mux. Addresses still use the exact 5120-position period;
    // the unused words are zero-padded by prepare_sources.py.
    (* rom_style="block" *) reg signed [15:0] rom [0:8191];
    (* KEEP="TRUE" *) reg signed [15:0] wave1, wave2;
    // Carry gain/enable beside the ROM data.  Without these pipeline tags, the
    // last sample of the old phase was multiplied by the new gain when a
    // request was committed at the period boundary.
    reg [8:0] gain_addr,gain_s1;
    reg enable_addr,enable_s1,enable_s2;
    reg signed [25:0] scaled1, scaled2;
    // CH1 is the fixed-phase reference and needs only ten coefficients.
    // Keep its table independent of the variable-phase ROM: in the previous
    // Vivado 2020.2 implementation the shared dual-read ROM reduced port A
    // to address zero despite correct RTL simulation, leaving CH1 at 512.
    // Values equal sine_5120_q6.mem[512*n], with the same registered latency.
    function signed [15:0] reference_coefficient(input [3:0] sample_index);
        begin
            case (sample_index)
                1,4: reference_coefficient = 16'sd19223;
                2,3: reference_coefficient = 16'sd31103;
                6,9: reference_coefficient = -16'sd19223;
                7,8: reference_coefficient = -16'sd31103;
                default: reference_coefficient = 16'sd0;
            endcase
        end
    endfunction
    function [9:0] quantize_dac;
        input signed [25:0] product;
        reg signed [25:0] biased;
        reg signed [11:0] centered;
        reg signed [12:0] value;
        begin
            // Q6 ROM * gain/256 -> divide by 2^14. Nearest rounding,
            // with exact half steps away from zero on both polarities.
            // The bounded coefficient/gain product has ample 26-bit headroom.
            biased = product + (product[25] ? 26'sd8191 : 26'sd8192);
            centered = biased >>> 14;
            value = centered + 13'sd512;
            if (value < 0) quantize_dac = 10'd0;
            else if (value > 1023) quantize_dac = 10'd1023;
            else quantize_dac = value[9:0];
        end
    endfunction
    initial $readmemh("sine_5120_q6.mem", rom);
    // Falling-edge clock forwarding matches the original DAC interface.
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) fwd1(.C(clk),.CE(1'b1),.D1(1'b0),.D2(1'b1),.Q(da_clk_1),.R(1'b0),.S(1'b0));
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) fwd2(.C(clk),.CE(1'b1),.D1(1'b0),.D2(1'b1),.Q(da_clk_2),.R(1'b0),.S(1'b0));
    // Read-only synchronous ROM: no reset on the memory output registers.
    // Validity comes from the parallel enable pipeline. This form keeps
    // the ROM on a separate clock stage instead of folding its mux into DSP.
    always @(posedge clk) begin
        wave1 <= reference_coefficient(reference_index_q);
        wave2 <= rom[addr2_q];
    end
    always @(posedge clk) begin
        reference_index_q <= index; addr2_q <= addr2;
        gain_addr <= gain;
        enable_addr <= enabled;
        gain_s1 <= gain_addr;
        enable_s1 <= enable_addr;
        scaled1 <= wave1 * $signed({1'b0,gain_s1});
        scaled2 <= wave2 * $signed({1'b0,gain_s1});
        enable_s2 <= enable_s1;
        if (!resetn) begin
            config_meta<=0; config_sync<=0; request_delayed<=0; ack<=0;
            offset<=256; phase_base<=1280; gain<=0; enabled<=0; index<=0;
            reference_index_q<=0;addr2_q<=0;gain_addr<=0;enable_addr<=0;gain_s1<=0;
            enable_s1<=0; enable_s2<=0; scaled1<=0; scaled2<=0;
            da_data_1<=512; da_data_2<=512;
        end else begin
            config_meta<=config_async; config_sync<=config_meta;
            request_delayed<=config_sync[20];
            index <= index==9 ? 0 : index+1'b1;
            if (index==9 && request_delayed!=ack) begin
                offset<=config_sync[9:0];
                phase_base<={3'b0,config_sync[9:0]} + {1'b0,config_sync[9:0],2'b00};
                gain<=config_sync[18:10]>256 ? 9'd256 : config_sync[18:10];
                enabled<=config_sync[19]; ack<=request_delayed;
            end
            da_data_1 <= enable_s2 ? quantize_dac(scaled1) : 10'd512;
            da_data_2 <= enable_s2 ? quantize_dac(scaled2) : 10'd512;
        end
    end
endmodule
