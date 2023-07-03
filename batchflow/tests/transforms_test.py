# pylint: disable=redefined-outer-name, missing-docstring
import sys
import pytest
import numpy as np

sys.path.append('..')
from batchflow import make_rng, Normalizer, Quantizer


@pytest.fixture
def array():
    return np.arange(0, 100).astype('float32')

@pytest.fixture
def normal_array():
    return make_rng(42).normal(size=1000).astype('float32')

class TestNormalizer:
    def test_mean_normalization(self, array):
        result = Normalizer(mode='mean').normalize(array)
        assert np.isclose(result, array - np.mean(array)).all()

    def test_meanstd_normalization(self, array):
        result = Normalizer(mode='meanstd').normalize(array)
        assert np.isclose(result, (array - np.mean(array)) / np.std(array)).all()

    def test_minmax_normalization(self, array):
        result = Normalizer(mode='minmax').normalize(array)
        assert np.isclose(result, (array - np.min(array)) / np.ptp(array)).all()

    def test_callable(self, array):
        callable = lambda x, stats: (x - np.mean(x)) / np.std(x)
        result = Normalizer(mode=callable).normalize(array)
        assert np.isclose(result, callable(array, None)).all()

    def test_clipping(self, array):
        result = Normalizer(mode='meanstd', clip_to_quantiles=True).normalize(array)
        q = np.quantile(array, (0.01, 0.99))
        target = np.clip(array, *q)
        target = (target - np.mean(target)) / np.std(target)
        assert np.isclose(result, target).all()

    @pytest.mark.parametrize('mode', ['min', 'minmax', 'meanstd'])
    def test_denormalize(self, array, mode):
        normalizer = Normalizer(mode=mode)
        result, stats = normalizer.normalize(array, return_stats=True)
        result = normalizer.denormalize(result, normalization_stats=stats)
        assert np.isclose(array, result, atol=1e-5).all()

    @pytest.mark.parametrize('mode', ['min', 'minmax', 'meanstd'])
    def test_denormalize_with_clipping(self, array, mode):
        normalizer = Normalizer(mode=mode, clip_to_quantiles=True)
        result, stats = normalizer.normalize(array, return_stats=True)
        result = normalizer.denormalize(result, normalization_stats=stats)

        q = np.quantile(array, (0.01, 0.99))
        target = np.clip(array, *q)

        assert np.isclose(result, target, atol=1e-5).all()

    def test_outer_stats(self, array):
        stats = {'mean': 20, 'std': 3}

        normalizer = Normalizer(mode='meanstd', normalization_stats=stats)
        result = normalizer.normalize(array)

        assert np.isclose(result, (array - 20) / 3, atol=1e-5).all()

    def test_outer_stats_denormalize(self, array):
        stats = {'q': (5, 95)}

        normalizer = Normalizer(mode='minmax', normalization_stats=stats, clip_to_quantiles=True)
        result = normalizer.normalize(array)
        result = normalizer.denormalize(result)

        target = np.clip(array, 5, 95)

        assert np.isclose(result, target, atol=1e-5).all()

class TestQuantizer:
    def test_quantize(self, normal_array):
        ranges = (np.min(normal_array), np.max(normal_array))
        quantizer = Quantizer(ranges=ranges)
        quantized = quantizer.quantize(normal_array)
        dequantized = ((quantized + 128) / 255) * normal_array.ptp() + normal_array.min()

        assert (np.abs(dequantized - normal_array) < quantizer.error).all()

    def test_dequantize(self, normal_array):
        ranges = (np.min(normal_array), np.max(normal_array))
        quantizer = Quantizer(ranges=ranges, copy=True)
        quantized = quantizer.quantize(normal_array)
        dequantized = quantizer.dequantize(quantized)

        assert (np.abs(normal_array - dequantized) < quantizer.error).all()

    @pytest.mark.parametrize('clip', [False, True])
    def test_ranges(self, normal_array, clip):
        ranges = np.quantile(normal_array, (0.05, 0.95))
        quantizer = Quantizer(ranges=ranges, clip=clip, copy=True)
        quantized = quantizer.quantize(normal_array)
        dequantized = quantizer.dequantize(quantized)

        diff = np.abs(normal_array - dequantized)
        central_mask = np.logical_and(normal_array > ranges[0], normal_array < ranges[1])

        assert (diff[central_mask] < quantizer.error).all()
        if clip:
            assert set(quantized[~central_mask]) == set([-127, 127])
        else:
            assert set(quantized[~central_mask]) == set([-128, 127])

    def test_zero_transform(self, normal_array):
        ranges = np.quantile(normal_array, (0.05, 0.95))
        ranges = np.abs(ranges).min()
        ranges = (-ranges, ranges)

        quantizer = Quantizer(ranges=ranges, copy=True)

        assert quantizer.quantize([0]) == [0]

    