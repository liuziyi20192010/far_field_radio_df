# 测试数据与参考结果

`reference/rtl_phase_comparison.csv`与NPZ从本次XSim日志的11条FRAME_PASS提取，证据类型为RTL仿真。`rtl_comparison_result.json`按bench的0.35°圆周容差比对：最大误差0.236137°，RMSE0.123781°。其中含零信号/异常模式帧，聚合值只是打印测试向量的比对摘要，不能宣称模拟链路精度。

`measurement_columns.csv`定义上板采集字段，不含实测数值。真实数据由board/collect_measurements.py生成在board/results，按版本manifest、原始帧、黄金参考及仪器设定一同保存。仿真、计算、用户定性反馈和实测不得混写。
