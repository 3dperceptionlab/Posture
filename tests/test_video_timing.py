import unittest
from backend.video_timing import PresentationClock


class PresentationClockTests(unittest.TestCase):
    def test_variable_rate_uses_presentation_time(self):
        clock=PresentationClock(5)
        frames=[clock.observe(t) for t in (0,40,81,121,162,203,266)]
        self.assertEqual([round(t,3) for t,keep in frames if keep],[0,.203])
        self.assertAlmostEqual(frames[-1][0],.266)

    def test_nonzero_source_start_is_normalized_once(self):
        clock=PresentationClock(5)
        self.assertEqual(clock.observe(42000),(0,True))
        offset,selected=clock.observe(42266)
        self.assertAlmostEqual(offset,.266)
        self.assertTrue(selected)
        self.assertEqual(clock.origin_s,42)

    def test_recording_pause_does_not_trigger_catchup_samples(self):
        clock=PresentationClock(5)
        self.assertEqual([clock.observe(t)[1] for t in (0,40,10000,10040,10080,10120,10200)],
                         [True,False,True,False,False,False,True])

    def test_timestamps_must_be_valid_and_advance(self):
        for invalid in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):PresentationClock(5).observe(invalid)
        clock=PresentationClock(5);clock.observe(100)
        for timestamp in (100,99):
            with self.assertRaises(ValueError):clock.observe(timestamp)

    def test_constant_rate_is_preserved(self):
        clock=PresentationClock(5)
        selected=[i for i in range(25) if clock.observe(i*40)[1]]
        self.assertEqual(selected,[0,5,10,15,20])


if __name__=='__main__':unittest.main()
