`timescale 1ns/1ps
// One coherent frame: 4096 sample pairs + 16-word PL measurement header.
// Capture is independent of AXIS backpressure; SEND holds all signals while stalled.
module adc_capture # (parameter integer SAMPLE_COUNT=4096)(
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 adc_clk CLK",
       X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF M_AXIS, ASSOCIATED_RESET adc_resetn" *) input wire adc_clk,
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 adc_resetn RST",
       X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire adc_resetn,
    input wire [9:0] ad_data_1, ad_data_2,
    input wire ad_otr_1, ad_otr_2,
    // start, counter test, two's-complement ADC (otherwise offset binary).
    input wire [2:0] ctrl_async,
    output wire [2:0] status,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *) output wire [3:0] m_axis_tkeep,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output reg m_axis_tvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_axis_tready,
    (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output reg m_axis_tlast
);
    localparam AW=$clog2(SAMPLE_COUNT);
    localparam IDLE=0,CAPTURE=1,MUL=2,CROSS=3,ANGLE=4,WAIT_ANGLE=5,HEADER=6,SEND=7,DRAIN=8,REARM=9;
    reg [3:0] state;
    (* ASYNC_REG="TRUE" *) reg [2:0] ctrl_meta,ctrl_sync;
    reg busy,done,test_mode,twos;
    reg [1:0] otr_seen;
    // Register the OR before crossing to PS; combinational reconvergence at
    // a synchronizer input can glitch even though each source flag is sticky.
    (* KEEP="TRUE" *) reg otr_any;
    reg [AW-1:0] wr_index,rd_index;
    reg [3:0] header_index;
    reg [31:0] sequence_id;
    // Capture each external ADC bit once before it fans out to BRAM and DDC.
    // This keeps the raw frame and PL measurement on the identical registered
    // sample pair even if board/input skew is marginal. IOB placement is a hint;
    // final input-delay constraints still require converter + PCB timing data.
    (* IOB="TRUE" *) reg [9:0] ad_data_1_q, ad_data_2_q;
    (* IOB="TRUE" *) reg ad_otr_1_q, ad_otr_2_q;
    (* ram_style="block" *) reg [21:0] sample_mem [0:SAMPLE_COUNT-1];
    reg [21:0] sample_q;
    reg [31:0] payload_q,header_q;
    reg output_header;
    reg signed [23:0] i1,q1,i2,q2;
    reg signed [47:0] p_ii,p_qq,p_qi,p_iq,re,im;
    reg angle_start;
    wire angle_done;
    wire signed [31:0] angle;
    wire signed [10:0] x1 = twos ? $signed({ad_data_1_q[9],ad_data_1_q}) : $signed({1'b0,ad_data_1_q})-11'sd512;
    wire signed [10:0] x2 = twos ? $signed({ad_data_2_q[9],ad_data_2_q}) : $signed({1'b0,ad_data_2_q})-11'sd512;
    assign status={otr_any,done,busy};
    assign m_axis_tkeep=4'hf;
    assign m_axis_tdata=output_header ? header_q : test_mode ? payload_q : {5'b0,sample_q[21:11],5'b0,sample_q[10:0]};
    cordic_phase calc(.clk(adc_clk),.resetn(adc_resetn),.start(angle_start),.re_in(re),.im_in(im),.busy(),.done(angle_done),.angle(angle));
    always @(posedge adc_clk) begin
        if (!adc_resetn) begin
            ctrl_meta<=0; ctrl_sync<=0;
            ad_data_1_q<=0; ad_data_2_q<=0; ad_otr_1_q<=0; ad_otr_2_q<=0;
        end else begin
            ctrl_meta<=ctrl_async; ctrl_sync<=ctrl_meta;
            ad_data_1_q<=ad_data_1; ad_data_2_q<=ad_data_2;
            ad_otr_1_q<=ad_otr_1; ad_otr_2_q<=ad_otr_2;
        end
        if (adc_resetn && state==CAPTURE) sample_mem[wr_index]<={ad_otr_2_q,ad_data_2_q,ad_otr_1_q,ad_data_1_q};
        if (adc_resetn && state==SEND && (!m_axis_tvalid || m_axis_tready)) sample_q<=sample_mem[rd_index];
    end
    always @(posedge adc_clk) begin
        if (!adc_resetn) begin
            state<=IDLE; busy<=0; done<=0; otr_seen<=0; otr_any<=0; wr_index<=0; rd_index<=0;
            test_mode<=0; twos<=0; sequence_id<=0; header_index<=0;
            i1<=0;q1<=0;i2<=0;q2<=0;p_ii<=0;p_qq<=0;p_qi<=0;p_iq<=0;re<=0;im<=0;
            angle_start<=0; m_axis_tvalid<=0;m_axis_tlast<=0;output_header<=1;header_q<=0;payload_q<=0;
        end else begin
            angle_start<=0;
            case(state)
                IDLE: if(ctrl_sync[0]) begin
                    busy<=1;done<=0;otr_seen<=0;otr_any<=0;test_mode<=ctrl_sync[1];twos<=ctrl_sync[2];
                    wr_index<=0;i1<=0;q1<=0;i2<=0;q2<=0;sequence_id<=sequence_id+1'b1;state<=CAPTURE;
                end
                CAPTURE: begin
                    if(!test_mode) begin
                        otr_seen<=otr_seen|{ad_otr_2_q,ad_otr_1_q};
                        otr_any<=otr_any|ad_otr_1_q|ad_otr_2_q;
                    end
                    // Fs/4 DDC: exp(-j*pi*n/2), shared LO guarantees channel pairing.
                    case(wr_index[1:0])
                        0:begin i1<=i1+x1;i2<=i2+x2;end
                        1:begin q1<=q1-x1;q2<=q2-x2;end
                        2:begin i1<=i1-x1;i2<=i2-x2;end
                        3:begin q1<=q1+x1;q2<=q2+x2;end
                    endcase
                    if(wr_index==SAMPLE_COUNT-1) state<=MUL;
                    else wr_index<=wr_index+1'b1;
                end
                MUL:begin p_ii<=i2*i1;p_qq<=q2*q1;p_qi<=q2*i1;p_iq<=i2*q1;state<=CROSS;end
                CROSS:begin re<=p_ii+p_qq;im<=p_qi-p_iq;state<=ANGLE;end
                ANGLE:begin angle_start<=1;state<=WAIT_ANGLE;end
                WAIT_ANGLE:if(angle_done) begin header_index<=0;state<=HEADER;end
                HEADER:if(!m_axis_tvalid || m_axis_tready) begin
                    output_header<=1;m_axis_tvalid<=1;m_axis_tlast<=0;
                    case(header_index)
                        0:header_q<=32'h50484d31;
                        1:header_q<=sequence_id;
                        2:header_q<=SAMPLE_COUNT;
                        3:header_q<={25'b0,twos,test_mode,(i1==0 && q1==0),(i2==0 && q2==0),otr_seen,1'b1};
                        4:header_q<=angle;
                        5:header_q<={{8{i1[23]}},i1}; 6:header_q<={{8{q1[23]}},q1};
                        7:header_q<={{8{i2[23]}},i2}; 8:header_q<={{8{q2[23]}},q2};
                        9:header_q<=re[31:0];10:header_q<={{16{re[47]}},re[47:32]};
                        11:header_q<=im[31:0];12:header_q<={{16{im[47]}},im[47:32]};
                        13:header_q<=50000000;14:header_q<=12500000;15:header_q<=32'h00010000;
                    endcase
                    if(header_index==15) begin rd_index<=0;state<=SEND;end
                    else header_index<=header_index+1'b1;
                end
                SEND:if(!m_axis_tvalid || m_axis_tready) begin
                    output_header<=0;payload_q<=rd_index;m_axis_tvalid<=1;m_axis_tlast<=(rd_index==SAMPLE_COUNT-1);
                    if(rd_index==SAMPLE_COUNT-1) state<=DRAIN; else rd_index<=rd_index+1'b1;
                end
                DRAIN:if(m_axis_tvalid && m_axis_tready) begin m_axis_tvalid<=0;m_axis_tlast<=0;busy<=0;done<=1;state<=REARM;end
                REARM:if(!ctrl_sync[0]) state<=IDLE;
                default:state<=IDLE;
            endcase
        end
    end
endmodule
