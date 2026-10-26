`timescale 1ns/1ps
module tb_phase_measure;
    localparam N=4096;
    reg clk=0; always #10 clk=~clk;
    reg resetn=0;
    reg [2:0] ctrl=0;
    reg [9:0] ad1=512,ad2=512;
    reg otr1=0,otr2=0,ready=0;
    wire [31:0] data; wire [3:0] keep;wire valid,last;wire [2:0] status;
    adc_capture dut(.adc_clk(clk),.adc_resetn(resetn),.ad_data_1(ad1),.ad_data_2(ad2),.ad_otr_1(otr1),.ad_otr_2(otr2),.ctrl_async(ctrl),.status(status),.m_axis_tdata(data),.m_axis_tkeep(keep),.m_axis_tvalid(valid),.m_axis_tready(ready),.m_axis_tlast(last));
    reg [31:0] received[0:N+15], expected[0:N-1];
    integer count=0,acq_count=0,tick=0,frame_id=0,stall_last=0;
    integer code1,code2,dc1=17,dc2=-13,amp1=280,amp2=220;
    integer sampled_code1,sampled_code2;
    integer si1,sq1,si2,sq2;
    reg twos=0,inject_otr=0,force_stall=0;
    real phase_deg=0.0, phi, measured,err;
    reg old_stall=0,old_last;
    reg [31:0] old_data;
    reg signed [63:0] cross_re,cross_im;
    always @(negedge clk) begin
        tick=tick+1;
        code1=$rtoi(dc1+amp1*$sin(6.283185307179586*tick/4.0+0.43));
        code2=$rtoi(dc2+amp2*$sin(6.283185307179586*tick/4.0+0.43+phase_deg*3.141592653589793/180.0));
        ad1=twos ? code1 : code1+512;
        ad2=twos ? code2 : code2+512;
        otr1=inject_otr && (tick%37==0);otr2=inject_otr && (tick%41==0);
        if(force_stall) ready=0;
        else if(last && stall_last<19) begin ready=0;stall_last=stall_last+1;end
        else ready=($urandom_range(0,3)!=0);
    end
    always @(posedge clk) begin
        if(resetn) begin
            if(old_stall && (!valid || data!==old_data || last!==old_last)) $fatal(1,"AXIS changed under backpressure");
            if(dut.state==1) begin
                sampled_code1 = twos ? $signed(dut.ad_data_1_q) : $signed({1'b0,dut.ad_data_1_q})-512;
                sampled_code2 = twos ? $signed(dut.ad_data_2_q) : $signed({1'b0,dut.ad_data_2_q})-512;
                expected[acq_count]={5'b0,dut.ad_otr_2_q,dut.ad_data_2_q,5'b0,dut.ad_otr_1_q,dut.ad_data_1_q};
                case(acq_count%4)
                    0:begin si1=si1+sampled_code1;si2=si2+sampled_code2;end
                    1:begin sq1=sq1-sampled_code1;sq2=sq2-sampled_code2;end
                    2:begin si1=si1-sampled_code1;si2=si2-sampled_code2;end
                    3:begin sq1=sq1+sampled_code1;sq2=sq2+sampled_code2;end
                endcase
                acq_count=acq_count+1;
            end
            if(valid && ready) begin
                if(count>=N+16) $fatal(1,"extra AXIS beat");
                if(keep!==4'hf || last!==(count==N+15)) $fatal(1,"TKEEP/TLAST error %0d",count);
                received[count]=data;count=count+1;
            end
            old_stall=valid&&!ready;old_data=data;old_last=last;
        end else old_stall=0;
    end
    task run_frame(input real phase,input integer mode,input integer overrange);
        integer j;
        begin
            @(negedge clk);ctrl=0;phase_deg=phase;twos=(mode==2);inject_otr=overrange;
            count=0;acq_count=0;si1=0;sq1=0;si2=0;sq2=0;stall_last=0;
            repeat(12) @(negedge clk);
            ctrl=(mode==1 ? 2 : mode==2 ? 4 : 0);
            repeat(12) @(negedge clk);ctrl=ctrl|1;
            wait(count==N+16);repeat(8) @(negedge clk);
            frame_id=frame_id+1;
            if(acq_count!=N || received[0]!==32'h50484d31 || received[1]!=frame_id || received[2]!=N) $fatal(1,"header/count mismatch");
            if($signed(received[5])!=si1 || $signed(received[6])!=sq1 || $signed(received[7])!=si2 || $signed(received[8])!=sq2) $fatal(1,"IQ mismatch, last sample missing or signed error");
            cross_re=64'(si2)*si1+64'(sq2)*sq1;cross_im=64'(sq2)*si1-64'(si2)*sq1;
            if({received[10],received[9]}!==cross_re || {received[12],received[11]}!==cross_im) $fatal(1,"cross product mismatch");
            for(j=0;j<N;j=j+1) if(received[j+16] !== (mode==1 ? j : expected[j])) $fatal(1,"sample pair mismatch %0d",j);
            measured=$itor($signed(received[4]))*180.0/2147483648.0;
            err=measured-phase; if(err>180)err=err-360;if(err< -180)err=err+360;
            if(amp1!=0 && amp2!=0 && (err>0.35 || err< -0.35)) $fatal(1,"phase sign/accuracy mismatch: expected %f measured %f",phase,measured);
            if(overrange && received[3][2:1]!=3) $fatal(1,"missing OTR flags");
            if(status[2] !== (overrange && mode!=1)) $fatal(1,"registered GPIO OTR status mismatch");
            if(amp1==0 && !received[3][4]) $fatal(1,"missing zero signal flag");
            repeat(50) @(negedge clk);
            if(count!=N+16 || status[0] || !status[1]) $fatal(1,"held start retrigger/status error");
            ctrl=0;repeat(10) @(negedge clk);
            $display("FRAME_PASS phase=%f measured=%f mode=%0d",phase,measured,mode);
        end
    endtask
    initial begin
        #91; resetn=1;
        run_frame(0,0,0);run_frame(30,0,0);run_frame(-45,0,0);
        run_frame(90,0,1);run_frame(-90,2,0);run_frame(179,0,0);
        run_frame(-179,2,0);run_frame(180,0,0);run_frame(45,1,0);
        amp1=0;run_frame(0,0,0);amp1=280;
        // Reset while an acquired frame is blocked: no stale valid afterwards.
        count=0;acq_count=0;force_stall=1;ctrl=1;
        wait(valid);@(negedge clk);resetn=0;ctrl=0;
        repeat(5) @(negedge clk);resetn=1;force_stall=0;frame_id=0;
        run_frame(-30,0,0);
        $display("PHASE_RTL_PASS");$finish;
    end
    initial begin #20000000;$fatal(1,"watchdog timeout");end
endmodule
