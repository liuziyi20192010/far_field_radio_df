`timescale 1ns/1ps
// Exercise the exported primitive netlist, with no RTL module as its reference.
// A ten-point DFT checks both output amplitudes, phase, mean and harmonics.
module tb_dac_implemented;
    reg clk=0; always #4 clk=~clk;
    reg resetn=0;
    reg [20:0] config_bus=0;
    wire ack,clock1,clock2;
    wire [9:0] data1,data2;
    implemented_dac dut(.clk(clk),.resetn(resetn),.config_async(config_bus),.ack(ack),
        .da_data_1(data1),.da_data_2(data2),.da_clk_1(clock1),.da_clk_2(clock2));
    integer request=0,j,k,count_checks=0;
    integer first1[0:9],first2[0:9];
    real i1,q1,i2,q2,mean1,mean2,amp1,amp2,phase,error_deg,expected_amp;
    real hi1,hq1,hi2,hq2,harm1,harm2,angle,limit;
    localparam real TWO_PI=6.283185307179586;

    // Both falling-edge forwarded clocks must actually toggle. Start after
    // global initialization/reset, so primitive GSR cannot cause a false fail.
    always @(posedge clk) begin
        #1;
        if(resetn && (clock1!==1'b0 || clock2!==1'b0))
            $fatal(1,"DAC implemented rising-edge clock forwarding failure");
    end
    always @(negedge clk) begin
        #1;
        if(resetn && (clock1!==1'b1 || clock2!==1'b1))
            $fatal(1,"DAC implemented falling-edge clock forwarding failure");
        if(resetn && ((^data1)===1'bx || (^data2)===1'bx))
            $fatal(1,"DAC implemented output contains X/Z");
    end

    task check_setting(input integer phase_code,input integer gain_code,input integer enabled);
        begin
            @(negedge clk); #2;
            request=1-request;
            config_bus=(request<<20)|(enabled<<19)|(gain_code<<10)|phase_code;
            // A missing configuration acknowledgement is bounded independently
            // of the global timeout. No internal hierarchy/index is consulted.
            j=0;
            while(ack!==request[0] && j<100) begin @(negedge clk);j=j+1;end
            if(ack!==request[0])$fatal(1,"DAC implemented configuration acknowledgement timeout");
            repeat(10)@(negedge clk);
            i1=0;q1=0;i2=0;q2=0;mean1=0;mean2=0;
            for(j=0;j<20;j=j+1)begin
                @(negedge clk);#2;
                if(j<10)begin first1[j]=data1;first2[j]=data2;end
                else if(data1!==first1[j-10] || data2!==first2[j-10])
                    $fatal(1,"DAC implemented ten-sample periodicity failure");
                if(!enabled || gain_code==0)begin
                    if(data1!=512 || data2!=512)$fatal(1,"DAC implemented disable/midscale failure");
                end else if(j<10)begin
                    angle=TWO_PI*j/10.0;
                    i1=i1+($itor(data1)-512)*$cos(angle);
                    q1=q1-($itor(data1)-512)*$sin(angle);
                    i2=i2+($itor(data2)-512)*$cos(angle);
                    q2=q2-($itor(data2)-512)*$sin(angle);
                    mean1=mean1+$itor(data1);mean2=mean2+$itor(data2);
                end
            end
            if(enabled && gain_code>0)begin
                amp1=$sqrt(i1*i1+q1*q1)/5.0;amp2=$sqrt(i2*i2+q2*q2)/5.0;
                expected_amp=511.0*gain_code/256.0;
                if(amp1<expected_amp-2.0 || amp1>expected_amp+2.0 ||
                   amp2<expected_amp-2.0 || amp2>expected_amp+2.0)
                    $fatal(1,"DAC implemented amplitude failure phase=%0d gain=%0d CH1=%f CH2=%f expected=%f",phase_code,gain_code,amp1,amp2,expected_amp);
                if(mean1/10.0<511.5 || mean1/10.0>512.5 || mean2/10.0<511.5 || mean2/10.0>512.5)
                    $fatal(1,"DAC implemented offset-binary midpoint failure");
                phase=$atan2(q2*i1-i2*q1,i2*i1+q2*q1)*360.0/TWO_PI;
                error_deg=phase-phase_code*360.0/1024.0;
                if(error_deg>180.0)error_deg=error_deg-360.0;
                if(error_deg< -180.0)error_deg=error_deg+360.0;
                limit=gain_code>=128 ? 0.13 : 0.50;
                if(error_deg>limit || error_deg< -limit)
                    $fatal(1,"DAC implemented phase failure target=%f actual=%f",phase_code*360.0/1024.0,phase);
                harm1=0;harm2=0;
                for(k=2;k<=5;k=k+1)begin
                    hi1=0;hq1=0;hi2=0;hq2=0;
                    for(j=0;j<10;j=j+1)begin
                        angle=TWO_PI*k*j/10.0;
                        hi1=hi1+(first1[j]-512)*$cos(angle);hq1=hq1-(first1[j]-512)*$sin(angle);
                        hi2=hi2+(first2[j]-512)*$cos(angle);hq2=hq2-(first2[j]-512)*$sin(angle);
                    end
                    harm1=harm1+hi1*hi1+hq1*hq1;harm2=harm2+hi2*hi2+hq2*hq2;
                end
                if($sqrt(harm1)/(amp1*5.0)>0.01 || $sqrt(harm2)/(amp2*5.0)>0.01)
                    $fatal(1,"DAC implemented waveform harmonic failure");
                $display("DAC_IMPLEMENTED_CASE phase_code=%0d gain=%0d CH1_amp=%f CH2_amp=%f phase_error=%f",phase_code,gain_code,amp1,amp2,error_deg);
            end else $display("DAC_IMPLEMENTED_CASE phase_code=%0d gain=%0d enabled=%0d midscale_ok",phase_code,gain_code,enabled);
            count_checks=count_checks+1;
        end
    endtask
    initial begin
        #203;resetn=1;repeat(30)@(negedge clk);
        check_setting(0,128,1);check_setting(128,128,1);
        check_setting(896,128,1);check_setting(256,128,1);
        // Change phase, gain and enable in both directions between captures.
        check_setting(17,64,1);check_setting(735,192,1);
        check_setting(128,128,0);check_setting(896,128,1);
        check_setting(0,0,1);check_setting(0,128,1);
        $display("DAC_IMPLEMENTED_PASS: %0d routed-netlist waveform/configuration cases, both data paths and forwarded clocks",count_checks);
        $finish;
    end
    initial begin #100000;$fatal(1,"DAC implemented simulation timeout");end
endmodule
