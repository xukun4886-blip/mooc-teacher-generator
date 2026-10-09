"""Keep completed SadTalker frames in host memory, not a growing CUDA list.

The upstream animation loop only reads generator['prediction'] after each frame.
Moving that detached float tensor preserves values/order and the native renderer;
it does not change model weights, drive audio, precision or face resolution.
"""
from functools import wraps


def offload_predictions(make_animation):
    @wraps(make_animation)
    def animate(source_image, source_semantics, target_semantics, generator, *args, **kwargs):
        def host_frame(*frame_args, **frame_kwargs):
            result = dict(generator(*frame_args, **frame_kwargs))
            result['prediction'] = result['prediction'].detach().cpu()
            return result
        return make_animation(source_image, source_semantics, target_semantics, host_frame, *args, **kwargs)
    return animate
