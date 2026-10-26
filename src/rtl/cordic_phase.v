`timescale 1ns/1ps
// atan2(y,x), signed binary angle: pi = 2^31. 24 vectoring iterations.
// Input cross-products are <= 2^41, 48-bit vector leaves gain/headroom.
module cordic_phase(input wire clk, resetn, start,
    input wire signed [47:0] re_in, im_in,
    output reg busy, done, output reg signed [31:0] angle);
    reg signed [49:0] x,y;
    reg signed [31:0] z;
    reg [4:0] iter;
    function [31:0] atan_lut(input [4:0] i);
        begin case(i)
            0:atan_lut=32'h20000000; 1:atan_lut=32'h12e4051e;
            2:atan_lut=32'h09fb385b; 3:atan_lut=32'h051111d4;
            4:atan_lut=32'h028b0d43; 5:atan_lut=32'h0145d7e1;
            6:atan_lut=32'h00a2f61e; 7:atan_lut=32'h00517c55;
            8:atan_lut=32'h0028be53; 9:atan_lut=32'h00145f2f;
            10:atan_lut=32'h000a2f98; 11:atan_lut=32'h000517cc;
            12:atan_lut=32'h00028be6; 13:atan_lut=32'h000145f3;
            14:atan_lut=32'h0000a2fa; 15:atan_lut=32'h0000517d;
            16:atan_lut=32'h000028be; 17:atan_lut=32'h0000145f;
            18:atan_lut=32'h00000a30; 19:atan_lut=32'h00000518;
            20:atan_lut=32'h0000028c; 21:atan_lut=32'h00000146;
            22:atan_lut=32'h000000a3; 23:atan_lut=32'h00000051;
            default:atan_lut=0;
        endcase end
    endfunction
    always @(posedge clk) begin
        if (!resetn) begin busy<=0; done<=0; angle<=0; x<=0; y<=0; z<=0; iter<=0; end
        else begin
            done<=0;
            if (start && !busy) begin
                busy<=1; iter<=0;
                if (re_in<0) begin x<=-$signed({{2{re_in[47]}},re_in}); y<=-$signed({{2{im_in[47]}},im_in}); z<=32'h80000000; end
                else begin x<=re_in; y<=im_in; z<=0; end
            end else if (busy) begin
                if (iter==24) begin angle<=z; done<=1; busy<=0; end
                else begin
                    if (y>0) begin x<=x+(y>>>iter); y<=y-(x>>>iter); z<=z+atan_lut(iter); end
                    else if (y<0) begin x<=x-(y>>>iter); y<=y+(x>>>iter); z<=z-atan_lut(iter); end
                    iter<=iter+1'b1;
                end
            end
        end
    end
endmodule
