`timescale 1ns/1ps
module tb_dac_control;
    reg clk=0;always #4 clk=~clk;
    reg resetn=0;
    reg [20:0] config_bus=0;
    wire ack,dc1,dc2;
    wire [9:0] d1,d2;
    dac_control dut(.clk(clk),.resetn(resetn),.config_async(config_bus),.ack(ack),
        .da_data_1(d1),.da_data_2(d2),.da_clk_1(dc1),.da_clk_2(dc2));
    integer j,req=0,sweep;
    real i1,q1,i2,q2,phase,err,target,amp;
    real phase_limit;
    real h2i,h2q,h3i,h3q,h4i,h4q,h5i,h5q,fund,harm,thd;
    reg [9:0] previous1[0:9],previous2[0:9];
    // Independent sine-law scoreboard observes every cycle, including the
    // three pipeline clocks surrounding a phase/gain/enable update. It does
    // not copy ROM addresses or RTL fixed-point arithmetic. The <=1-code
    // allowance covers Q6 coefficient rounding near a DAC code boundary.
    integer expect1[0:2],expect2[0:2],now1,now2,delta1,delta2;
    reg [2:0] score_valid=0;
    real sample_angle,scaled;
    function integer ideal_code(input real value);
        integer rounded;
        begin
            if(value<0)rounded=-$rtoi(-value+0.5);else rounded=$rtoi(value+0.5);
            ideal_code=512+rounded;
            if(ideal_code<0)ideal_code=0;
            if(ideal_code>1023)ideal_code=1023;
        end
    endfunction
    always @(posedge clk) begin
        if(!resetn)score_valid=0;
        else begin
            sample_angle=6.283185307179586*$itor(dut.index)/10.0;
            scaled=511.0*$itor(dut.gain)/256.0;
            now1=dut.enabled ? ideal_code(scaled*$sin(sample_angle)) : 512;
            now2=dut.enabled ? ideal_code(scaled*$sin(sample_angle+6.283185307179586*$itor(dut.offset)/1024.0)) : 512;
            #1;
            if(score_valid[2]) begin
                delta1=$itor(d1)-expect1[2];delta2=$itor(d2)-expect2[2];
                if(delta1>1 || delta1< -1 || delta2>1 || delta2< -1)
                    $fatal(1,"DAC pipeline sample/config mismatch d1=%0d ref1=%0d d2=%0d ref2=%0d",d1,expect1[2],d2,expect2[2]);
            end
            expect1[2]=expect1[1];expect2[2]=expect2[1];
            expect1[1]=expect1[0];expect2[1]=expect2[0];
            expect1[0]=now1;expect2[0]=now2;
            score_valid={score_valid[1:0],1'b1};
        end
    end
    task check_wave(input integer offset,input integer gain,input integer enabled);
        begin
            #3;req=1-req;config_bus=(req<<20)|(enabled<<19)|(gain<<10)|offset;
            wait(ack==req);repeat(30) @(negedge clk);
            i1=0;q1=0;i2=0;q2=0;
            h2i=0;h2q=0;h3i=0;h3q=0;h4i=0;h4q=0;h5i=0;h5q=0;
            for(j=0;j<20;j=j+1) begin
                @(negedge clk);#1;
                if(j<10) begin previous1[j]=d1;previous2[j]=d2;end
                else begin
                    if(previous1[j-10]!==d1)$fatal(1,"DAC1 periodicity failure");
                    if(previous2[j-10]!==d2)$fatal(1,"DAC2 periodicity failure");
                end
                if(!enabled || gain==0) begin if(d1!=512 || d2!=512)$fatal(1,"disable/midscale failure");end
                else if(j<10) begin
                    i1=i1+($itor(d1)-512)*$cos(6.283185307179586*j/10);
                    q1=q1-($itor(d1)-512)*$sin(6.283185307179586*j/10);
                    i2=i2+($itor(d2)-512)*$cos(6.283185307179586*j/10);
                    q2=q2-($itor(d2)-512)*$sin(6.283185307179586*j/10);
                    h2i=h2i+($itor(d2)-512)*$cos(2*6.283185307179586*j/10);
                    h2q=h2q-($itor(d2)-512)*$sin(2*6.283185307179586*j/10);
                    h3i=h3i+($itor(d2)-512)*$cos(3*6.283185307179586*j/10);
                    h3q=h3q-($itor(d2)-512)*$sin(3*6.283185307179586*j/10);
                    h4i=h4i+($itor(d2)-512)*$cos(4*6.283185307179586*j/10);
                    h4q=h4q-($itor(d2)-512)*$sin(4*6.283185307179586*j/10);
                    h5i=h5i+($itor(d2)-512)*$cos(5*6.283185307179586*j/10);
                    h5q=h5q-($itor(d2)-512)*$sin(5*6.283185307179586*j/10);
                end
            end
            if(enabled && gain>0) begin
                phase=$atan2(q2*i1-i2*q1,i2*i1+q2*q1)*180/3.141592653589793;
                target=offset*360.0/1024;err=phase-target;
                if(err>180)err=err-360;if(err< -180)err=err+360;
                // Ten-bit physical output still sets a finite quantization
                // limit, especially at low amplitude; it is not a board claim.
                if(gain>=192)phase_limit=0.09;
                else if(gain>=128)phase_limit=0.13;
                else if(gain>=64)phase_limit=0.27;
                else phase_limit=0.50;
                if(err>phase_limit || err< -phase_limit)$fatal(1,"DAC offset mismatch: target=%f actual=%f",target,phase);
                amp=$sqrt(i1*i1+q1*q1)/5;
                if(amp<510*gain/256.0-2 || amp>513*gain/256.0+2)$fatal(1,"DAC gain mismatch %f",amp);
                fund=$sqrt(i2*i2+q2*q2);
                harm=$sqrt(h2i*h2i+h2q*h2q+h3i*h3i+h3q*h3q+
                           h4i*h4i+h4q*h4q+h5i*h5i+h5q*h5q);
                thd=harm/fund;
                if(thd>0.01)$fatal(1,"DAC2 shape/THD failure offset=%0d gain=%0d thd=%f",offset,gain,thd);
            end
            if(offset==128 || offset==896)$display("DAC_PRECISION target=%f actual=%f error=%f gain=%0d",target,phase,err,gain);
            if(gain!=128 || offset%128==0)$display("DAC_PASS offset=%0d gain=%0d enabled=%0d",offset,gain,enabled);
        end
    endtask
    initial begin
        #103;resetn=1;repeat(30)@(negedge clk);
        if(d1!=512 || d2!=512)$fatal(1,"DAC not disabled after reset");
        check_wave(256,128,1);check_wave(0,256,1);check_wave(85,256,1);
        check_wave(896,128,1);check_wave(512,64,1);check_wave(1023,256,1);
        // Exercise phase and amplitude changes in both directions; these are
        // the transitions that previously mixed an old sample with new gain.
        check_wave(17,64,1);check_wave(735,192,1);check_wave(341,96,1);
        check_wave(128,128,1);check_wave(896,128,1);check_wave(17,32,1);
        // Exhaust all advertised phase codes at the user's default gain.
        for(sweep=0;sweep<1024;sweep=sweep+1)check_wave(sweep,128,1);
        check_wave(256,0,1);check_wave(256,256,0);
        // A bundle change without a request must not update the active setting.
        config_bus[19:0]=(1<<19)|(256<<10)|512;repeat(50)@(negedge clk);
        if(d1!=512 || d2!=512)$fatal(1,"configuration applied without request");
        $display("DAC_RTL_PASS: 1024 phase codes at gain=0.5, configuration transitions and low-gain boundary");$finish;
    end
    initial begin #2000000;$fatal(1,"DAC watchdog");end
endmodule
