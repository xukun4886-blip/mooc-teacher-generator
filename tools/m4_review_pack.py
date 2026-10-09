"""Prepare empty human review forms bound to actual unreviewed outputs.

Never writes project reviews, teacher confirmations or scores. Existing forms
are preserved so rerunning after the second course finishes cannot erase work.
"""
from pathlib import Path
import random
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.store import Store
from mooc_m3.timeline import course_timeline

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = read_json(ROOT / 'docs/evidence/M3/external-long-courses.json')
    store = Store(ROOT / 'storage/m2')
    folder = ROOT / 'storage/m4-review'
    folder.mkdir(parents=True, exist_ok=True)
    index = read_json(ROOT / 'docs/evidence/M4/review-materials.json')
    index.setdefault('media_review_forms', {})
    for mode, entry in source['paths'].items():
        state = entry.get('status') or {}
        if state.get('state') != 'completed':
            continue
        media = state['media']
        job = next(j for j in store.jobs(entry['project_id']) if j['id'] == media['id'])
        pages, cues, duration = course_timeline(job['scenes'])
        result = job['result']
        path = folder / (mode + '-' + media['id'] + '-human-review.json')
        if not path.exists():
            # Seed and selected indices are retained, permitting exact resampling.
            seed = result['sha256']
            selected = sorted(random.Random(seed).sample(range(len(cues)), min(20, len(cues))))
            point = lambda i: {'cue_index': i + 1, 'scene': next(p for p in pages if p['start'] <= cues[i]['start'] < p['end'])['scene_id'],
                               'subtitle_start_seconds': cues[i]['start'], 'subtitle_end_seconds': cues[i]['end'], 'text': cues[i]['text']}
            form = {'created_at': stamp(), 'status': 'pending_human_review', 'scope': 'engineering draft familiarization; not formal baseline acceptance',
                    'mode': mode, 'project_id': entry['project_id'], 'job_id': media['id'], 'media_sha256': result['sha256'],
                    'video_path': str(store.file(entry['project_id'], result['path'])), 'duration_seconds': duration,
                    'teacher_confirmation_submitted': False, 'metrics_frozen': False,
                    'sampling': {'method': 'sample 20 distinct actual subtitle cues without replacement', 'seed': seed, 'selected_indices_1_based': [i + 1 for i in selected]},
                    'subtitle_samples': [{**point(i), 'human_speech_start_seconds': None, 'human_speech_end_seconds': None,
                                          'start_error_ms': None, 'end_error_ms': None, 'reviewer': None, 'reviewed_at': None} for i in selected],
                    'lipsync_candidates': [{**point(i), 'note': 'Subtitle cue is navigation only. Reviewer must select a clear phoneme onset and inspect waveform/frame; no automatic lipsync measurement.',
                                            'measurable': None, 'exclusion_reason': None, 'speech_onset_seconds': None, 'mouth_onset_seconds': None,
                                            'error_ms': None, 'evidence_path': None, 'reviewer': None} for i in selected],
                    'ten_second_samples': [{'start_seconds': (duration - 10) * i / 4, 'end_seconds': (duration - 10) * i / 4 + 10,
                                            'reviewers': [{'role': role, 'name': None, 'voice_score': None, 'identity_score': None, 'naturalness_score': None, 'notes': None}
                                                          for role in ['teacher', 'reviewer_1', 'reviewer_2']]} for i in range(5)],
                    'whole_course_review': [{'name': None, 'coherence_score': None, 'comprehensibility_score': None, 'terms_numbers_formulas_correct': None,
                                             'original_pages_readable': None, 'no_key_region_occlusion': None, 'video_turnaround_seams': None, 'notes': None} for _ in range(3)]}
            assert duration >= 10 and len(selected) == 20
            assert all(0 <= s['start_seconds'] < s['end_seconds'] <= duration for s in form['ten_second_samples'])
            write_json(path, form)
        saved = read_json(path)
        assert saved['media_sha256'] == result['sha256'] and saved['job_id'] == media['id']
        index['media_review_forms'][mode] = {'path': str(path), 'sha256': digest(path), 'job_id': media['id'], 'status': saved['status'],
                                             'subtitle_samples': 20, 'lipsync_candidates': 20, 'ten_second_samples': 5,
                                             'counts_as_formal_acceptance': False, 'existing_form_preserved': True}
    index['updated_at'] = stamp()
    write_json(ROOT / 'docs/evidence/M4/review-materials.json', index)
    print({k: v['status'] for k, v in index['media_review_forms'].items()})


if __name__ == '__main__':
    main()
