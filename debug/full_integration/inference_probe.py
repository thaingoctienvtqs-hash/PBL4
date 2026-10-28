"""Bounded OFFLINE_AI_TEST on existing JPEGs; inert on import, no EventStore.
Explicit local weights only. This is not a physical touch/ALERT evaluation.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXPECTED_FIRST_SHA = 'c03f38a947d426b39b7538a5478f823799d98b34e0fb299ec35a6520342a342a'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def preflight(run_root, images, second_weights, repeat):
    root = Path(run_root).expanduser().resolve()
    if not root.is_dir() or inside(root, REPO) or inside(REPO, root):
        raise ValueError('existing_external_run_root_required')
    if not 1 <= len(images) <= 2 or not 1 <= int(repeat) <= 2:
        raise ValueError('bounded_1_or_2_images_and_repeats_required')
    paths = [Path(p).expanduser().resolve() for p in images]
    if any(not p.is_file() or p.suffix.lower() not in ('.jpg', '.jpeg') for p in paths):
        raise ValueError('existing_jpeg_inputs_required')
    second = Path(second_weights).expanduser().resolve()
    if not second.is_file():
        raise ValueError('existing_local_second_stream_weights_required')
    first = REPO / 'models' / 'combined_data_model.pth'
    if not first.is_file() or digest(first) != EXPECTED_FIRST_SHA:
        raise ValueError('first_stream_checkpoint_identity_mismatch')
    protected = [first, second, REPO / 'src/core/contacthands_compat.py',
                 REPO / 'src/detect_compat.py', REPO / 'src/configs/ContactHands.yaml',
                 REPO / 'src/configs/second_stream.yaml'] + paths
    return root, paths, first, second, {str(p): digest(p) for p in protected}


def run_probe(args):
    root, images, first, second, before = preflight(args.run_root, args.image, args.second_stream_weights, args.repeat)
    output = root / ('offline_inference_' + uuid.uuid4().hex)
    output.mkdir(exist_ok=False)
    for key in ('CUDA_CACHE_PATH', 'TORCH_HOME', 'XDG_CACHE_HOME', 'TORCH_EXTENSIONS_DIR', 'MPLCONFIGDIR'):
        value = output / key.lower(); value.mkdir(exist_ok=False); os.environ[key] = str(value)
    temporary = output / 'tmp'; temporary.mkdir(exist_ok=False)
    for key in ('TMPDIR', 'TEMP', 'TMP'):
        os.environ[key] = str(temporary)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['MPLBACKEND'] = 'Agg'
    os.environ['CONTACTHANDS_MODEL_WEIGHTS'] = str(first)
    os.environ['CONTACTHANDS_SECOND_STREAM_WEIGHTS'] = str(second)
    sys.dont_write_bytecode = True
    for p in (str(REPO), str(REPO / 'src')):
        if p not in sys.path:
            sys.path.insert(0, p)
    # Explicit local models plus a network guard: never download a missing asset.
    import socket
    original_connect = socket.socket.connect
    original_create = socket.create_connection
    def deny_network(*unused, **kwargs):
        raise OSError('offline_probe_network_forbidden')
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    result = {'data_origin': 'OFFLINE_AI_TEST', 'status': 'FAIL', 'ground_truth': 'NOT_AVAILABLE',
              'accuracy': 'NOT_EVALUATED', 'physical_contact_latency': 'NOT_AVAILABLE',
              'camera_accessed': False, 'eventstore_accessed': False, 'output': str(output),
              'predictions': [], 'protected_sha256_before': before}
    start = time.perf_counter()
    try:
        import cv2
        import torch
        import detectron2
        import detectron2._C
        if not torch.cuda.is_available():
            raise RuntimeError('verified_cuda_environment_required_no_cpu_fallback')
        from src.core.contacthands_compat import ContactHandsDetector
        from src.utils.config_compat import DEFAULTS
        result['runtime'] = {'python': sys.version, 'torch': torch.__version__,
            'detectron2': detectron2.__version__, 'detectron2_C': 'IMPORTED',
            'gpu': torch.cuda.get_device_name(0)}
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        init_start = time.perf_counter()
        detector = ContactHandsDetector(config=REPO / 'src/configs/ContactHands.yaml', weights=first,
            score_thresh=DEFAULTS['thresholds']['hand_score'],
            second_stream_config=REPO / 'src/configs/second_stream.yaml', second_stream_weights=second,
            device='cuda')
        torch.cuda.synchronize()
        result['model_initialization_wall_ms'] = (time.perf_counter() - init_start) * 1000
        result['unchanged_thresholds'] = dict(DEFAULTS['thresholds'])
        sequence = 0
        for path in images:
            read_start = time.perf_counter()
            frame = cv2.imread(str(path))
            if frame is None:
                raise RuntimeError('unreadable_jpeg')
            decode_ms = (time.perf_counter() - read_start) * 1000
            for iteration in range(args.repeat):
                torch.cuda.synchronize()
                begin = time.perf_counter()
                instances = detector.predict(frame)
                torch.cuda.synchronize()
                elapsed = (time.perf_counter() - begin) * 1000
                cpu = instances.to('cpu')
                boxes = cpu.pred_boxes.tensor.tolist() if len(cpu) else []
                scores = cpu.scores.tolist() if len(cpu) else []
                contacts = cpu.pred_cats.tolist() if len(cpu) else []
                result['predictions'].append({'image': str(path), 'image_sha256': before[str(path)],
                    'width': int(frame.shape[1]), 'height': int(frame.shape[0]),
                    'repeat_index': iteration, 'inference_sequence': sequence,
                    'timing_class': 'COLD_FIRST_INFERENCE' if sequence == 0 else 'SUBSEQUENT_INFERENCE',
                    'decode_read_wall_ms': decode_ms, 'inference_synchronized_wall_ms': elapsed,
                    'timing_scope': 'CPU_preprocess_plus_two_stream_GPU_plus_postprocess; not CUDA_kernel_only',
                    'hand_count': len(cpu), 'boxes_xyxy': boxes, 'hand_detection_scores': scores,
                    'contact_scores_order': ['No-Contact', 'Self-Contact', 'Other-Person-Contact', 'Object-Contact'],
                    'contact_scores': contacts, 'alert_evaluated': False})
                sequence += 1
        result['gpu_peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['status'] = 'PASS'
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        result['error'] = str(exc)
    finally:
        socket.socket.connect, socket.create_connection = original_connect, original_create
        result['elapsed_wall_seconds'] = time.perf_counter() - start
        result['protected_sha256_after'] = {p: digest(p) for p in before}
        result['protected_unchanged'] = result['protected_sha256_after'] == before
        if not result['protected_unchanged']:
            result['status'] = 'FAIL'
        with (output / 'result.json').open('x', encoding='utf8') as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'PASS' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--image', action='append', required=True)
    parser.add_argument('--second-stream-weights', required=True)
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--allow-inference', action='store_true')
    args = parser.parse_args(argv)
    if not args.allow_inference:
        parser.error('explicit --allow-inference required; import and help are inert')
    return run_probe(args)


if __name__ == '__main__':
    raise SystemExit(main())
