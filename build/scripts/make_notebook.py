"""Generate the concise demonstration notebook; maintenance stays in board/README.md."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def md(text):
    return dict(cell_type='markdown', metadata={}, source=text.splitlines(True))


def code(text):
    return dict(cell_type='code', metadata={}, source=text.splitlines(True),
                outputs=[], execution_count=None)


def main():
    cells = [md("""# 远场模拟无线电实时测向系统

双路信号相位测量 · 远场方向模拟

运行下方单元，选择输入模式，完成 **0° 校准** 后开始测量。
板载模式连接 DAC1 → ADC1、DAC2 → ADC2；外部模式接入同频的双路 **12.5 MHz** 信号。
切换输入模式后分别校准；改变板载输出幅度后重新校准。
"""), code("""from phase_measure import PhaseMeasure
from dashboard import Dashboard

if 'ui' in globals():
    ui.close()
if 'pm' in globals():
    pm.close()
pm = PhaseMeasure(encoding='offset_binary')
if not pm.test_link():
    pm.close()
    raise RuntimeError('采集连接检查未通过，请检查板卡配置后重试。')
ui = Dashboard(pm)
ui.show()
"""), md("""相位按 **CH2 − CH1** 显示。场景根据双通道相位和等效阵列模型换算方向；6 m 为模型间距。
外部信号的幅度、偏置及接线须符合 ADC 输入规格。结束演示后运行下方单元关闭输出。
"""), code("""# 结束使用时，取消下面两行注释后运行。
# ui.close()
# pm.close()
""")]
    notebook = dict(cells=cells, metadata=dict(
        kernelspec=dict(display_name='Python 3', language='python', name='python3'),
        language_info=dict(name='python', version='3.8')),
        nbformat=4, nbformat_minor=4)
    target = ROOT / 'board/app/far_field_radio_df.ipynb'
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('NOTEBOOK_PASS: demonstration notebook generated')


if __name__ == '__main__':
    main()
