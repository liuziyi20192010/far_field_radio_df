`timescale 1ns/1ps
module tb_cordic_phase;
    reg clk=0; always #10 clk=~clk;
    reg resetn=0,start=0;
    reg signed [47:0] re_in=0,im_in=0;
    wire busy,done; wire signed [31:0] angle;
    cordic_phase dut(.clk(clk),.resetn(resetn),.start(start),.re_in(re_in),.im_in(im_in),
        .busy(busy),.done(done),.angle(angle));
    integer degree,scale;
    real measured,error,radians;
    task check(input integer requested,input integer magnitude);
        begin
            radians=requested*3.141592653589793/180.0;
            re_in=$rtoi(magnitude*$cos(radians));
            im_in=$rtoi(magnitude*$sin(radians));
            @(negedge clk);start=1;@(negedge clk);start=0;
            wait(done); measured=$itor(angle)*180.0/2147483648.0;
            // Compare against the actual quantized input vector, not the real-valued request.
            error=measured-($atan2($itor(im_in),$itor(re_in))*180.0/3.141592653589793);
            if(error>180.0)error=error-360.0;
            if(error< -180.0)error=error+360.0;
            if(error>0.002 || error< -0.002)
                $fatal(1,"CORDIC mismatch requested=%0d measured=%f magnitude=%0d",requested,measured,magnitude);
        end
    endtask
    initial begin
        repeat(4)@(negedge clk);resetn=1;
        // Real cross products are much larger than 1000; test the operating range.
        for(scale=1000000;scale<=1000000000;scale=scale*1000)
            for(degree=-180;degree<180;degree=degree+1) check(degree,scale);
        $display("CORDIC_EXHAUSTIVE_PASS");$finish;
    end
    initial begin #100000000;$fatal(1,"CORDIC watchdog");end
endmodule
