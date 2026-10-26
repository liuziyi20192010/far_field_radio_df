"""PYNQ driver + offline decoder for the 12.5 MHz dual-channel phase overlay."""
from pathlib import Path
import math
import time
import threading
import numpy as np

SAMPLE_COUNT = 4096
SAMPLE_RATE_HZ = 50_000_000
CARRIER_HZ = 12_500_000
EQUIVALENT_ARRAY_SPACING_M = 6.0
PHASE_MODEL_LIMIT_DEG = 90.0
PHASE_ENDPOINT_TOLERANCE_DEG = 0.25
HEADER_WORDS = 16
FRAME_WORDS = SAMPLE_COUNT + HEADER_WORDS


def wrap_degrees(value):
    return (value + 180.0) % 360.0 - 180.0


def phase_to_direction_deg(phase_deg):
    """Map phase difference to bearing for the project's d=lambda/4 model."""
    if not math.isfinite(phase_deg) or abs(phase_deg) > PHASE_MODEL_LIMIT_DEG + PHASE_ENDPOINT_TOLERANCE_DEG:
        return float('nan')
    limited = max(-PHASE_MODEL_LIMIT_DEG, min(PHASE_MODEL_LIMIT_DEG, phase_deg))
    return math.degrees(math.asin(limited / PHASE_MODEL_LIMIT_DEG))


def phase_to_delay_ns(phase_deg, frequency_hz=CARRIER_HZ):
    """Convert CH2-CH1 phase into the equivalent signed time delay."""
    if not math.isfinite(phase_deg) or not math.isfinite(frequency_hz) or frequency_hz <= 0:
        return float('nan')
    return phase_deg / (360.0 * frequency_hz) * 1e9


def phase_measurement_error_deg(measured_deg, reference_deg):
    """Return the shortest signed circular error (measured-reference)."""
    if not math.isfinite(measured_deg) or not math.isfinite(reference_deg):
        return float('nan')
    return wrap_degrees(measured_deg - reference_deg)


def signed_word(value):
    value = int(value)
    return value - (1 << 32) if value & (1 << 31) else value


def decode_frame(words, min_amplitude=3.0):
    """Decode signed PL results and paired raw ADC codes; usable without PYNQ."""
    words = np.asarray(words, dtype=np.uint32)
    if words.shape != (FRAME_WORDS,) or int(words[0]) != 0x50484D31:
        raise ValueError('Incorrect packet size/magic; check matching BIT/HWH and driver')
    if int(words[2]) != SAMPLE_COUNT or tuple(map(int, words[13:16])) != (SAMPLE_RATE_HZ, 12_500_000, 0x10000):
        raise ValueError('Unsupported hardware packet version or sample clock')
    flags = int(words[3])
    if not flags & 1:
        raise ValueError('Incomplete hardware measurement')
    payload = words[HEADER_WORDS:]
    codes = np.column_stack((payload & 1023, (payload >> 16) & 1023)).astype(np.int32)
    samples = np.where(codes >= 512, codes - 1024, codes) if flags & 64 else codes - 512
    otr = np.column_stack(((payload >> 10) & 1, (payload >> 26) & 1)).astype(bool)
    iq = np.array([signed_word(x) for x in words[5:9]], dtype=np.int64)
    z1, z2 = complex(*iq[:2]), complex(*iq[2:])
    amplitude = 2 * np.array([abs(z1), abs(z2)]) / SAMPLE_COUNT
    phase = signed_word(words[4]) * 180.0 / (1 << 31)
    cross = complex(signed_word(words[10]) * (1 << 32) + int(words[9]),
                    signed_word(words[12]) * (1 << 32) + int(words[11]))
    test_mode = bool(flags & 32)
    overrange = bool(flags & 6)
    valid = not (flags & 0x3E) and bool(np.all(amplitude >= min_amplitude))
    reference = np.exp(-2j * np.pi * np.arange(SAMPLE_COUNT) / 4)
    sw_iq = samples.T @ reference
    sw_phase = wrap_degrees(float(np.angle(sw_iq[1] * np.conj(sw_iq[0]), deg=True)))
    # Three independent views of the PL pipeline make board-level faults localizable:
    # accumulated I/Q -> Python atan2, PL cross product -> Python atan2, and PL CORDIC.
    pl_iq_phase = wrap_degrees(float(np.angle(z2 * np.conj(z1), deg=True)))
    pl_cross_phase = wrap_degrees(float(np.angle(cross, deg=True)))
    iq_expected = np.rint(np.column_stack((sw_iq.real, sw_iq.imag))).astype(np.int64).ravel()
    iq_error = iq - iq_expected
    iq_phase_error = wrap_degrees(pl_iq_phase - sw_phase)
    cross_phase_error = wrap_degrees(pl_cross_phase - pl_iq_phase)
    cordic_phase_error = wrap_degrees(phase - pl_cross_phase)
    pipeline_consistent = (np.max(np.abs(iq_error)) <= 1 and
                           abs(iq_phase_error) < 0.02 and
                           abs(cross_phase_error) < 0.02 and
                           abs(cordic_phase_error) < 0.02)
    return dict(sequence=int(words[1]), flags=flags, words=words.copy(), samples=samples,
                codes=codes, otr=otr, iq=iq, cross=cross, amplitude=amplitude,
                phase_deg=phase if valid else float('nan'), raw_phase_deg=phase,
                software_phase_deg=sw_phase, pl_iq_phase_deg=pl_iq_phase,
                pl_cross_phase_deg=pl_cross_phase, iq_expected=iq_expected,
                iq_error=iq_error, iq_phase_error_deg=iq_phase_error,
                cross_phase_error_deg=cross_phase_error,
                cordic_phase_error_deg=cordic_phase_error,
                pipeline_consistent=pipeline_consistent,
                valid=valid, overrange=overrange,
                test_mode=test_mode, encoding='twos_complement' if flags & 64 else 'offset_binary')


def diagnose_frame(result):
    """Return a short diagnosis of the first PL stage that disagrees with the frame."""
    if result['test_mode']:
        return '计数自检帧不包含有效测相结果'
    if result['overrange']:
        return 'ADC 出现 OTR，先降低 DAC 幅度或检查模拟输入量程'
    if np.any(result['amplitude'] < 3.0):
        return '12.5 MHz 基波幅度过低，角度没有可靠意义'
    if np.max(np.abs(result['iq_error'])) > 1:
        return ('PL I/Q 累加与同帧原始样点不一致：优先检查 BIT/HWH/Python 是否配套，'
                '若配套则检查采集域 RTL 或板上时序')
    if abs(result['cross_phase_error_deg']) >= 0.02:
        return 'PL 复共轭乘法结果与 PL I/Q 不一致，问题在复乘或结果锁存级'
    if abs(result['cordic_phase_error_deg']) >= 0.02:
        return 'PL CORDIC 角度与其输入 Re/Im 不一致，问题在 CORDIC 或角度锁存级'
    if abs(result['iq_phase_error_deg']) >= 0.02:
        return 'PL I/Q 与同帧软件 DFT 的相位不一致，问题在 PL DDC/IQ 累加级'
    return 'PL 各级与同帧软件结果一致；若显示仍跳动，应检查是否混用了旧对象或并发刷新任务'


def spectrum(samples):
    """Hann-windowed one-sided amplitude spectrum, dBFS (peak full scale=512 codes)."""
    samples = np.asarray(samples, dtype=float)
    n = len(samples)
    window = np.hanning(n)
    centered = samples - samples.mean(axis=0)
    magnitude = np.abs(np.fft.rfft(centered * window[:, None], axis=0)) * 2 / window.sum()
    magnitude[0] *= 0.5
    if n % 2 == 0:
        magnitude[-1] *= 0.5
    dbfs = 20 * np.log10(np.maximum(magnitude / 512, 1e-8))
    return np.fft.rfftfreq(n, 1 / SAMPLE_RATE_HZ), dbfs


class PhaseMeasure:
    def __init__(self, bitfile='overlay/phase_measure.bit', encoding='offset_binary'):
        if encoding not in ('offset_binary', 'twos_complement'):
            raise ValueError('encoding must be offset_binary or twos_complement')
        self.encoding = encoding
        self.bitfile = str(Path(bitfile).resolve())
        self._failed_buffer = None
        self._config_fault = False
        self._lock = threading.RLock()
        self.phase_zero_deg = 0.0
        self._load_overlay()

    def _load_overlay(self):
        from pynq import Overlay, allocate
        self._allocate = allocate
        self.overlay = Overlay(self.bitfile)
        self.dma = self.overlay.axi_dma_0
        self.gpio = self.overlay.axi_gpio_0
        self.dac_gpio = self.overlay.dac_gpio
        self.gpio.write(0x04, 0)
        self.gpio.write(0x0C, 7)
        self.gpio.write(0x00, 0)
        self.dac_gpio.write(0x04, 0)
        self.dac_gpio.write(0x0C, 1)
        time.sleep(0.01)
        self._toggle = self.dac_gpio.read(0x08) & 1
        self._config_fault = False
        self.dac_setting = dict(phase_deg=90.0, gain=0.5, enabled=False)
        self.set_dac(**self.dac_setting)

    def recover(self):
        """Reload overlay (DAC off) before releasing any possibly active DMA buffer."""
        with self._lock:
            self._load_overlay()
            if self._failed_buffer is not None:
                self._failed_buffer.freebuffer()
                self._failed_buffer = None

    @property
    def status(self):
        bits = self.gpio.read(0x08)
        return dict(busy=bool(bits & 1), done=bool(bits & 2), overrange=bool(bits & 4))

    def set_dac(self, phase_deg=90.0, gain=0.5, enabled=True, timeout=1.0):
        """Atomically set CH2-CH1 phase, shared amplitude, and output enable.

        Off outputs midscale code 512; it does not disconnect the analog output.
        Frequency is fixed at 12.5 MHz. Gain is 0..1; phase step is 360/1024 deg.
        """
        if not all(math.isfinite(v) for v in (phase_deg, gain, timeout)) or not 0 <= gain <= 1 or timeout <= 0:
            raise ValueError('Use finite phase, gain 0..1, and positive timeout')
        with self._lock:
            if self._config_fault:
                raise RuntimeError('Previous DAC update timed out; call recover()')
            phase_code = int(round((phase_deg % 360) * 1024 / 360)) % 1024
            gain_code = int(round(gain * 256))
            self._toggle ^= 1
            word = phase_code | (gain_code << 10) | (bool(enabled) << 19) | (self._toggle << 20)
            self.dac_gpio.write(0x00, word)
            try:
                deadline = time.monotonic() + timeout
                while (self.dac_gpio.read(0x08) & 1) != self._toggle:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('DAC configuration acknowledgement missing; call recover()')
                    time.sleep(0.0001)
                time.sleep(0.001)  # pipeline + analog settling before the next frame
            except BaseException:
                self._config_fault = True
                raise
            self.dac_setting = dict(phase_deg=wrap_degrees(phase_code * 360 / 1024),
                                    gain=gain_code / 256, enabled=bool(enabled))
            return self.dac_setting.copy()

    def stop_dac(self):
        return self.set_dac(**{**self.dac_setting, 'enabled': False})

    def capture(self, test_mode=False, timeout=2.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be positive and finite')
        with self._lock:
            if self._failed_buffer is not None:
                raise RuntimeError('Previous DMA failed; call recover() before retrying')
            if self.status['busy']:
                raise RuntimeError('Acquisition is busy; recover() if the previous transfer was interrupted')
            mode = (2 if test_mode else 0) | (4 if self.encoding == 'twos_complement' else 0)
            self.gpio.write(0x00, mode)
            time.sleep(0.001)  # rearm and hold mode stable before start crosses CDC
            buf = self._allocate(shape=(FRAME_WORDS,), dtype=np.uint32)
            try:
                self.dma.recvchannel.transfer(buf)  # always arm DMA before PL capture
                self.gpio.write(0x00, mode | 1)
                deadline = time.monotonic() + timeout
                while True:
                    sr = self.dma.read(0x34)
                    if sr & 0x71:
                        raise RuntimeError(f'DMA error: DMASR=0x{sr:08x}, ADC={self.status}')
                    if sr & 2:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'DMA timeout: DMASR=0x{sr:08x}; call recover()')
                    time.sleep(0.0005)
                self.dma.recvchannel.wait()  # PYNQ cache invalidation and driver bookkeeping
                if self.dma.read(0x58) != buf.nbytes:
                    raise RuntimeError('DMA frame byte count mismatch; call recover()')
                words = np.array(buf, dtype=np.uint32, copy=True)
            except BaseException:
                self._failed_buffer = buf  # also retain memory on KeyboardInterrupt
                raise
            finally:
                self.gpio.write(0x00, mode)
            buf.freebuffer()
            result = decode_frame(words)
            result['calibrated_phase_deg'] = wrap_degrees(result['phase_deg'] - self.phase_zero_deg)
            return result

    def test_link(self):
        result = self.capture(test_mode=True)
        if not result['test_mode'] or not np.array_equal(result['words'][16:], np.arange(SAMPLE_COUNT, dtype=np.uint32)):
            raise AssertionError('DMA counter link test failed')
        return True

    def calibrate_zero(self, frames=8):
        """Call with physically equal-phase inputs; stores channel/cable phase offset."""
        if not isinstance(frames, int) or frames < 1:
            raise ValueError('frames must be a positive integer')
        phases = [self.capture()['phase_deg'] for _ in range(frames)]
        if not np.all(np.isfinite(phases)):
            raise RuntimeError('Calibration requires valid, unclipped signals on both channels')
        vector = np.mean(np.exp(1j * np.deg2rad(phases)))
        if abs(vector) < 0.95:
            raise RuntimeError('Calibration phase is unstable; check signal and channel pairing')
        self.phase_zero_deg = float(np.angle(vector, deg=True))
        return self.phase_zero_deg
