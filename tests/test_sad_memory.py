"""Frame ownership/value/order behavior, separate from real GPU verification."""
from mooc_m1.sad_memory import offload_predictions


class Tensor:
    def __init__(self, value, device='cuda'):
        self.value, self.device = value, device
    def detach(self):
        return self
    def cpu(self):
        return Tensor(self.value, 'cpu')


def test_native_animation_receives_all_unchanged_frames_on_cpu():
    calls = []
    def generator(source, index):
        calls.append((source, index))
        return {'prediction': Tensor(index), 'native_extra': 'preserved'}
    def native(source, semantics, targets, model, *, use_exp):
        assert semantics == 'source' and use_exp is True
        result = [model(source, index) for index in targets]
        assert all(r['prediction'].device == 'cpu' and r['native_extra'] == 'preserved' for r in result)
        return [r['prediction'].value for r in result]
    output = offload_predictions(native)('image', 'source', range(1733), generator, use_exp=True)
    assert output == list(range(1733)) and len(calls) == 1733


def test_native_errors_propagate_without_placeholder_frames():
    import pytest
    def generator(*args):
        raise RuntimeError('real native error')
    def native(source, semantics, targets, model):
        return model(source)
    with pytest.raises(RuntimeError, match='real native error'):
        offload_predictions(native)('image', None, None, generator)
