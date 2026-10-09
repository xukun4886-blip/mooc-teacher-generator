"""Safe new-deck continuation, including failure and stale-revision boundaries."""
import copy
import pytest
from test_m3 import rig
from mooc_m1.core import digest
from mooc_m2.content import fingerprint, effective


def upload(client, p, content=b'fixture upload; parsing tested with real PPT separately'):
    return client.post(f"/api/projects/{p['id']}/quick-assets/pptx",
        data={'revision': p['revision']}, files={'file': ('new-course.pptx', content,
            'application/vnd.openxmlformats-officedocument.presentationml.presentation')})


def test_reselect_owns_selected_teacher_inputs_without_old_scripts_or_outputs(rig):
    service, p, _, client, _ = rig
    store = service.store
    selected = store.folder(p['id']) / 'chosen-reference.wav'
    selected.write_bytes(store.file(p['id'], 'reference.wav').read_bytes())
    with store.edit(p['id']) as source:
        source['assets']['reference_audio'].update(selected=selected.name, selected_sha256=digest(selected))
        source['scenes'][0]['confirmed'] = {'version_id': source['scenes'][0]['current_version']}
    p = store.get(p['id'])
    old_jobs = copy.deepcopy(store.jobs(p['id']))
    old_output = store.folder(p['id']) / 'old-course.mp4'
    old_output.write_bytes(b'preserve published output')
    response = upload(client, p)
    assert response.status_code == 200, response.text
    result = response.json()
    new = store.get(result['project_id'])
    assert new['id'] != p['id'] and result['source_project_id'] == new['source_project_id'] == p['id']
    assert new['slides'] == new['scenes'] == [] and service.course.latest(new['id']) is None
    assert effective(new, {'overrides': {}})['mode'] == effective(p, {'overrides': {}})['mode']
    assert fingerprint(store.get(p['id'])) == fingerprint(p)
    assert store.jobs(p['id']) == old_jobs and old_output.read_bytes() == b'preserve published output'
    assert not (store.folder(new['id']) / old_output.name).exists()
    for role in ['photo', 'reference_audio']:
        old, new_asset = p['assets'][role], new['assets'][role]
        assert new_asset['id'] != old['id'] and new_asset['teacher_id'] == old['teacher_id']
        assert new_asset['selection'] == old['selection']
        for field in ['original', 'selected']:
            assert digest(store.file(new['id'], new_asset[field])) == digest(store.file(p['id'], old[field]))
    assert len(store.jobs(new['id'])) == 1 and result['state'] == 'queued'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM snapshots WHERE project_id=?', (new['id'],)).fetchone()[0] == 0
    # Independent copies keep working if the source is explicitly deleted.
    store.delete(p['id'])
    assert store.file(new['id'], new['assets']['reference_audio']['selected']).is_file()


@pytest.mark.parametrize('boundary', ['empty', 'stale', 'busy', 'changed_teacher'])
def test_reselect_failure_does_not_create_course_or_modify_source(rig, boundary):
    service, p, _, client, _ = rig
    store = service.store
    if boundary == 'stale':
        with store.edit(p['id']):
            pass
    elif boundary == 'busy':
        store.job(p['id'], 'ai', {'scene_id': p['scenes'][0]['id']})
    elif boundary == 'changed_teacher':
        store.file(p['id'], 'photo.png').write_bytes(b'changed behind the saved hash')
    before = fingerprint(store.get(p['id']))
    projects = {item['id'] for item in store.list()}
    response = upload(client, p, b'' if boundary == 'empty' else b'new PPT content')
    assert response.status_code == (409 if boundary in {'stale', 'busy'} else 422)
    assert {item['id'] for item in store.list()} == projects
    assert fingerprint(store.get(p['id'])) == before


def test_advanced_upload_still_protects_existing_page_mapping(rig):
    service, p, _, client, _ = rig
    response = client.post(f"/api/projects/{p['id']}/assets/pptx",
        data={'revision': p['revision'], 'authorization': 'test', 'teacher_id': 'test-only'},
        files={'file': ('another.pptx', b'another fixture deck', 'application/octet-stream')})
    assert response.status_code == 422
    assert fingerprint(service.store.get(p['id'])) == fingerprint(p)


def test_reselect_carries_current_video_mode_and_not_unselected_photo(rig):
    service, p, _, client, _ = rig
    store = service.store
    # Archive-copy fixture only; this does not claim video decode/model quality.
    original = store.folder(p['id']) / 'unit-video.mp4'
    selected = store.folder(p['id']) / 'unit-selected-video.mp4'
    original.write_bytes(b'test-only original video archive')
    selected.write_bytes(b'test-only selected video archive')
    with store.edit(p['id']) as source:
        source['config']['mode'] = 'video'
        source['assets']['video'] = {'id': 'video', 'original': original.name, 'selected': selected.name,
            'sha256': digest(original), 'selected_sha256': digest(selected), 'state': 'ready',
            'teacher_id': 'test-only', 'selection': {'start': 2, 'end': 7}, 'authorization': {'confirmed': True}}
    p = store.get(p['id'])
    response = upload(client, p)
    assert response.status_code == 200
    new = store.get(response.json()['project_id'])
    assert new['config']['mode'] == 'video' and 'photo' not in new['assets']
    assert new['assets']['video']['selection'] == {'start': 2, 'end': 7}
    assert digest(store.file(new['id'], new['assets']['video']['selected'])) == digest(selected)
    assert fingerprint(store.get(p['id'])) == fingerprint(p)
