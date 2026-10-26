"""Host-side protocol, signal analysis, DMA ownership, and DAC handshake tests."""
from pathlib import Path
import json
import sys
import types
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'board/app'))
from phase_measure import (PhaseMeasure, decode_frame, diagnose_frame, spectrum,
    wrap_degrees, phase_to_direction_deg, phase_to_delay_ns,
    phase_measurement_error_deg, SAMPLE_COUNT, FRAME_WORDS)


def packet(phase=45, twos=False, otr=False, test=False):
    t = np.arange(SAMPLE_COUNT) * np.pi/2 + 0.3
    samples = np.column_stack((np.rint(280*np.sin(t)+19),np.rint(210*np.sin(t+np.deg2rad(phase))-23))).astype(np.int32)
    codes = samples & 1023 if twos else samples+512
    words = np.zeros(FRAME_WORDS,dtype=np.uint32)
    words[:4] = [0x50484D31,1,SAMPLE_COUNT,1 | (64 if twos else 0) | (6 if otr else 0) | (32 if test else 0)]
    z = samples.T @ np.tile([1,-1j,-1,1j], SAMPLE_COUNT//4)
    cross = z[1]*z[0].conjugate()
    angle = np.angle(cross)*2**31/np.pi
    words[4] = round(angle) & 0xFFFFFFFF
    words[5:9] = [int(x)&0xFFFFFFFF for x in (z[0].real,z[0].imag,z[1].real,z[1].imag)]
    for start,val in [(9,int(cross.real)),(11,int(cross.imag))]:
        words[start]=val&0xFFFFFFFF;words[start+1]=(val>>32)&0xFFFFFFFF
    words[13:16]=[50_000_000,12_500_000,0x10000]
    words[16:]=np.arange(SAMPLE_COUNT) if test else codes[:,0]|(codes[:,1]<<16)
    return words


events=[]
buffers=[]
class Buffer(np.ndarray):
    def freebuffer(self):
        self.freed=True;events.append('free')
def allocate(shape,dtype):
    result=np.zeros(shape,dtype=dtype).view(Buffer)
    result.freed=False;buffers.append(result);return result
class GPIO:
    def __init__(self,dac=False):self.value=0;self.dac=dac;self.ack=True;self.busy=False
    def read(self,offset):
        if self.dac:return (self.value>>20)&1 if self.ack else 1-((self.value>>20)&1)
        return int(self.busy)
    def write(self,offset,value):
        if offset==0:
            self.value=value
            if not self.dac and value&1:events.append('start')
class DMA:
    def __init__(self,gpio):self.recvchannel=self;self.gpio=gpio;self.sr=2;self.nbytes=FRAME_WORDS*4;self.interrupt=False
    def transfer(self,buf):
        events.append('transfer');buf[:]=packet(test=bool(self.gpio.value&2),twos=bool(self.gpio.value&4))
    def read(self,offset):return self.sr if offset==0x34 else self.nbytes
    def wait(self):
        events.append('wait')
        if self.interrupt:raise KeyboardInterrupt()
class Overlay:
    def __init__(self,path):
        events.append('overlay');self.axi_gpio_0=GPIO();self.dac_gpio=GPIO(True);self.axi_dma_0=DMA(self.axi_gpio_0)


class Tests(unittest.TestCase):
    def setUp(self):
        events.clear();buffers.clear()
        self.fake=patch.dict(sys.modules,{'pynq':types.SimpleNamespace(Overlay=Overlay,allocate=allocate)})
        self.fake.start();self.addCleanup(self.fake.stop)
    def test_decode_all_quadrants_and_encoding(self):
        for phase in [0,30,45,90,-90,179,-179,180]:
            for twos in [False,True]:
                r=decode_frame(packet(phase,twos))
                self.assertTrue(r['valid'])
                self.assertLess(abs(wrap_degrees(r['phase_deg']-phase)),0.25)
                self.assertLess(abs(wrap_degrees(r['phase_deg']-r['software_phase_deg'])),1e-6)
                self.assertTrue(r['pipeline_consistent'])
                self.assertIn('一致', diagnose_frame(r))
    def test_spectrum_scale_peak(self):
        r=decode_frame(packet())
        freq,db=spectrum(r['samples'])
        self.assertEqual(freq[np.argmax(db[:,0])],12_500_000)
        self.assertAlmostEqual(db[:,0].max(),20*np.log10(280/512),delta=0.04)
    def test_far_field_and_dac_metrics(self):
        self.assertAlmostEqual(phase_to_direction_deg(45), 30, places=9)
        self.assertAlmostEqual(phase_to_direction_deg(-90), -90, places=9)
        self.assertAlmostEqual(phase_to_direction_deg(90.1), 90, places=9)
        self.assertAlmostEqual(phase_to_direction_deg(-90.1), -90, places=9)
        self.assertTrue(np.isnan(phase_to_direction_deg(120)))
        self.assertAlmostEqual(phase_to_delay_ns(45), 10, places=9)
        self.assertAlmostEqual(phase_to_delay_ns(-90), -20, places=9)
        self.assertAlmostEqual(phase_measurement_error_deg(-179, 179), 2, places=9)
        self.assertTrue(np.isnan(phase_to_direction_deg(float('nan'))))
    def test_invalid_signals(self):
        self.assertFalse(decode_frame(packet(otr=True))['valid'])
        self.assertFalse(decode_frame(packet(test=True))['valid'])
        words=packet();words[3]|=16
        self.assertTrue(np.isnan(decode_frame(words)['phase_deg']))
        self.assertFalse(decode_frame(packet(),min_amplitude=300)['valid'])
    def test_corrupt_frame(self):
        for offset in [0,2,13,14,15]:
            words=packet();words[offset]=0
            with self.assertRaises(ValueError):decode_frame(words)
    def test_repeat_dma_order_and_free(self):
        pm=PhaseMeasure()
        for _ in range(3):self.assertTrue(pm.capture()['valid'])
        self.assertTrue(pm.test_link())
        self.assertEqual(events.count('start'),4)
        self.assertLess(events.index('transfer'),events.index('start'))
        self.assertLess(events.index('wait'),events.index('free'))
        self.assertTrue(all(b.freed for b in buffers))
    def test_reusable_dma_has_owned_snapshots_and_explicit_close(self):
        pm=PhaseMeasure()
        first=pm.capture(reuse_buffer=True)
        second=pm.capture(reuse_buffer=True)
        self.assertEqual(len(buffers),1)
        self.assertFalse(buffers[0].freed)
        buffers[0][:]=0
        self.assertEqual(int(first['words'][0]),0x50484D31)
        self.assertEqual(int(second['words'][0]),0x50484D31)
        self.assertEqual(set(first['timings_ms']),{'prepare','allocate','dma','copy','decode','total'})
        self.assertGreaterEqual(first['timings_ms']['total'],0)
        pm.close()
        self.assertTrue(buffers[0].freed)
        self.assertEqual(events.count('free'),1)
        pm.close()
        self.assertEqual(events.count('free'),1)
        with self.assertRaises(RuntimeError):pm.capture(reuse_buffer=True)
    def test_reusable_fault_requires_successful_reset_and_frees_once(self):
        pm=PhaseMeasure();pm.dma.sr=0x10
        with self.assertRaises(RuntimeError):pm.capture(reuse_buffer=True)
        self.assertIs(pm._failed_buffer,pm._rx_buffer)
        with patch.object(pm,'_load_overlay',side_effect=RuntimeError('reset failed')):
            with self.assertRaises(RuntimeError):pm.recover()
        self.assertFalse(buffers[0].freed)
        events.clear();pm.recover()
        self.assertLess(events.index('overlay'),events.index('free'))
        self.assertEqual(events.count('free'),1)
        self.assertIsNone(pm._rx_buffer)
        self.assertTrue(pm.capture(reuse_buffer=True)['valid'])
        pm.close()
    def test_partial_arm_failure_retains_reusable_allocation(self):
        pm=PhaseMeasure()
        with patch.object(pm.dma,'transfer',side_effect=RuntimeError('partial arm')):
            with self.assertRaises(RuntimeError):pm.capture(reuse_buffer=True)
        self.assertFalse(buffers[0].freed)
        with self.assertRaises(RuntimeError):pm.capture(reuse_buffer=True)
        pm.close()
        self.assertTrue(buffers[0].freed)
        self.assertEqual(events.count('free'),1)
    def test_integer_reference_matches_dft_for_arbitrary_adc_codes(self):
        rng=np.random.default_rng(20261025)
        for twos in [False,True]:
            words=packet(twos=twos)
            samples=rng.integers(-500,500,(SAMPLE_COUNT,2),dtype=np.int32)
            codes=samples&1023 if twos else samples+512
            words[16:]=codes[:,0]|(codes[:,1]<<16)
            decoded=decode_frame(words)
            reference=samples.T @ np.tile([1,-1j,-1,1j],SAMPLE_COUNT//4)
            expected=np.column_stack((reference.real,reference.imag)).astype(np.int64).ravel()
            np.testing.assert_array_equal(decoded['iq_expected'],expected)
            self.assertFalse(decoded['pipeline_consistent'])
    def test_error_recovery_memory_ownership(self):
        pm=PhaseMeasure();pm.dma.sr=0x10
        with self.assertRaises(RuntimeError):pm.capture()
        self.assertFalse(buffers[-1].freed)
        with self.assertRaises(RuntimeError):pm.capture()
        events.clear();pm.recover()
        self.assertLess(events.index('overlay'),events.index('free'))
        self.assertTrue(buffers[-1].freed)
        self.assertFalse(pm.dac_setting['enabled'])
    def test_timeout_short_frame_and_keyboardinterrupt(self):
        for cause in ['timeout','short','interrupt']:
            pm=PhaseMeasure()
            if cause=='timeout':pm.dma.sr=0
            if cause=='short':pm.dma.nbytes=100
            if cause=='interrupt':pm.dma.interrupt=True
            with self.assertRaises((TimeoutError,RuntimeError,KeyboardInterrupt)):pm.capture(timeout=0.001)
            self.assertFalse(buffers[-1].freed)
            pm.recover();self.assertTrue(buffers[-1].freed)
    def test_dac_handshake(self):
        pm=PhaseMeasure()
        a=pm.set_dac(30,0.5,True)
        self.assertEqual(a['phase_deg'],85*360/1024)
        self.assertEqual(pm.dac_gpio.value&1023,85)
        self.assertEqual((pm.dac_gpio.value>>10)&511,128)
        pm.stop_dac();self.assertFalse(pm.dac_gpio.value&(1<<19))
        pm.dac_gpio.ack=False
        with self.assertRaises(TimeoutError):pm.set_dac(timeout=0.001)
        with self.assertRaises(RuntimeError):pm.set_dac()
    def test_dac_write_failure_requires_recovery(self):
        pm=PhaseMeasure()
        with patch.object(pm.dac_gpio,'write',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):pm.set_dac(-45,0.5,True)
        self.assertTrue(pm._config_fault)
        with self.assertRaises(RuntimeError):pm.set_dac(45,0.5,True)
        pm.recover()
        self.assertFalse(pm._config_fault)
        pm.close()
    def test_calibration_rejects_pipeline_inconsistency(self):
        pm=PhaseMeasure()
        bad=decode_frame(packet())
        bad['pipeline_consistent']=False
        with patch.object(pm,'capture',return_value=bad):
            with self.assertRaises(RuntimeError):pm.calibrate_zero(frames=2)
        self.assertIsNone(pm.calibration_stats)
        pm.close()
    def test_calibration_replenishes_eight_transients_at_exact_budget(self):
        pm=PhaseMeasure()
        good=decode_frame(packet(phase=0))
        bad_words=packet(phase=0);bad_words[5]+=2
        bad=decode_frame(bad_words)
        self.assertTrue(bad['valid'])
        self.assertFalse(bad['pipeline_consistent'])
        with patch.object(pm,'capture',side_effect=[bad]*8+[good]*32) as capture:
            self.assertAlmostEqual(pm.calibrate_zero(),good['phase_deg'],places=6)
        self.assertEqual(capture.call_count,40)
        self.assertEqual(pm.calibration_stats['frames'],32)
        self.assertEqual(pm.calibration_stats['rejected'],8)
        self.assertEqual(pm.last_calibration_report['status'],'success')
        pm.close()
    def test_calibration_persistent_fault_is_bounded_and_explained(self):
        pm=PhaseMeasure();pm.phase_zero_deg=12;pm.calibration_stats={'frames':32}
        words=packet(phase=0);words[5]+=2
        bad=decode_frame(words)
        with patch.object(pm,'capture',return_value=bad) as capture:
            with self.assertRaisesRegex(RuntimeError,'I/Q最大差=2'):
                pm.calibrate_zero()
        self.assertEqual(capture.call_count,9)
        self.assertEqual(pm.phase_zero_deg,0)
        self.assertIsNone(pm.calibration_stats)
        self.assertEqual(pm.last_calibration_report['accepted'],0)
        self.assertEqual(pm.last_calibration_report['status'],'failed')
        pm.close()
    def test_calibration_invalid_signal_never_enters_zero(self):
        pm=PhaseMeasure()
        bad=decode_frame(packet(phase=90,otr=True))
        good=decode_frame(packet(phase=0))
        with patch.object(pm,'capture',side_effect=[bad,good,good]):
            self.assertAlmostEqual(pm.calibrate_zero(frames=2,max_rejected=1),good['phase_deg'],places=6)
        self.assertEqual(pm.calibration_stats['rejected'],1)
        self.assertIn('OTR',next(iter(pm.last_calibration_report['rejection_counts'])))
        pm.close()
    def test_calibration_transport_error_aborts_without_retry(self):
        pm=PhaseMeasure()
        with patch.object(pm,'capture',side_effect=[decode_frame(packet()),TimeoutError('DMA timeout')]) as capture:
            with self.assertRaisesRegex(TimeoutError,'DMA timeout'):
                pm.calibrate_zero(frames=2)
        self.assertEqual(capture.call_count,2)
        self.assertEqual(pm.last_calibration_report['attempted'],1)
        self.assertEqual(pm.last_calibration_report['rejected'],0)
        self.assertEqual(pm.last_calibration_report['status'],'failed')
        self.assertIsNone(pm.calibration_stats)
        pm.close()
    def test_calibration_unstable_phase_does_not_commit_partial_zero(self):
        pm=PhaseMeasure();pm.phase_zero_deg=12
        with patch.object(pm,'capture',side_effect=[decode_frame(packet(0)),decode_frame(packet(180))]):
            with self.assertRaisesRegex(RuntimeError,'不稳定'):
                pm.calibrate_zero(frames=2)
        self.assertEqual(pm.phase_zero_deg,0)
        self.assertIsNone(pm.calibration_stats)
        pm.close()
    def test_calibration_diagnostics_replays_owned_raw_packets(self):
        pm=PhaseMeasure()
        good=decode_frame(packet(0));bad=decode_frame(packet(90,otr=True))
        with patch.object(pm,'capture',side_effect=[bad,good]):
            pm.calibrate_zero(frames=1,max_rejected=1)
        saved=pm._calibration_packets[0].copy()
        bad['words'][:]=0
        with tempfile.TemporaryDirectory() as temp:
            path=pm.save_calibration_diagnostics(Path(temp)/'diagnostics/run.npz')
            with np.load(path,allow_pickle=False) as data:
                report=json.loads(str(data['report_json']))
                self.assertEqual(report['attempted'],2)
                self.assertEqual([r['accepted'] for r in report['frames']],[False,True])
                np.testing.assert_array_equal(data['words'][0],saved)
                self.assertFalse(decode_frame(data['words'][0])['valid'])
                self.assertTrue(decode_frame(data['words'][1])['pipeline_consistent'])
        for value in [-1,True,1.5]:
            with self.assertRaises(ValueError):pm.calibrate_zero(max_rejected=value)
        pm.close()
    def test_validation_and_calibration(self):
        pm=PhaseMeasure()
        for x in [float('nan'),float('inf'),-1,0]:
            with self.assertRaises(ValueError):pm.capture(timeout=x)
        with self.assertRaises(ValueError):pm.set_dac(gain=1.01)
        zero=pm.calibrate_zero(frames=2)
        self.assertAlmostEqual(zero,45,delta=0.25)
        self.assertAlmostEqual(pm.capture()['calibrated_phase_deg'],0,delta=1e-6)
    def test_notebook_code_compiles(self):
        nb=json.loads((ROOT/'board/app/far_field_radio_df.ipynb').read_text(encoding='utf-8'))
        for cell in nb['cells']:
            if cell['cell_type']=='code':compile(''.join(cell['source']),'notebook','exec')

if __name__=='__main__':unittest.main(verbosity=2)
