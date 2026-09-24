"""Phase-1 standalone acceptance for the teacher agent candidate on :3200; never calls an LLM.

Adapted from the legacy .runtime/verify-teacher-candidate.py (3101 run) and extended with:
material upload/activation, persisted classroom + player entry, classroom attach (draft
isolation, dangling rejection, idempotency). Data directory matches scripts/dev-3200.ps1.
"""
import json
import time
from pathlib import Path

import httpx

BASE_URL = 'http://127.0.0.1:3200'
DATA_ROOT = Path(__file__).resolve().parents[2] / '.runtime' / 'data-3200' / 'course-spaces'


def minimal_scene(scene_id: str, stage_id: str) -> dict:
    return {
        'id': scene_id,
        'stageId': stage_id,
        'type': 'slide',
        'title': scene_id,
        'order': 1,
        'content': {
            'type': 'slide',
            'canvas': {
                'id': f'canvas-{scene_id}',
                'viewportSize': 1000,
                'viewportRatio': 0.5625,
                'theme': {
                    'backgroundColor': '#fff',
                    'themeColors': ['#000'],
                    'fontColor': '#000',
                    'fontName': 'Inter',
                },
                'elements': [],
            },
        },
    }


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=120, trust_env=False) as client:
        def call(method: str, url: str, expected: int = 200, **kwargs):
            response = client.request(method, url, **kwargs)
            assert response.status_code == expected, (url, response.status_code, response.text[:400])
            return response.json()

        call('GET', '/api/health')
        capabilities = call('GET', '/api/teacher-agent/capabilities')
        assert capabilities['entries']['classroomPlayer'] == '/classroom-player/{classroomId}'
        print('PASS health + capabilities (classroomPlayer entry)', flush=True)

        course = call('POST', '/api/course-space', 201,
                      json={'title': 'Integration acceptance 3200', 'teacherId': 'local-teacher'})['course']
        cid = course['id']
        print(f'PASS course created id={cid}', flush=True)

        call('GET', f'/api/classes/{cid}', 404)
        call('POST', f'/api/course-space/{cid}/publish', 409)
        print('PASS class channel closed before publish (404/409)', flush=True)

        upload = call('POST', f'/api/course-space/{cid}/materials', 201,
                      files={'file': ('acceptance.txt', b'Acceptance fixture material. Phase 1 standalone verification content.',
                                      'text/plain')})
        material_id = upload['material']['id']
        print(f'PASS material uploaded id={material_id}', flush=True)

        now = int(time.time() * 1000)
        artifact = {'id': f'acceptance-{cid}', 'jobId': f'job-{cid}', 'courseId': cid,
                    'teacherId': 'local-teacher', 'type': 'lesson-courseware', 'title': 'Synthetic approved content',
                    'content': 'Acceptance fixture, not AI generated.', 'scope': {'type': 'course'},
                    'status': 'approved', 'citations': [{'materialId': 'fixture', 'chunkId': 'fixture-1', 'quote': 'Synthetic source'}],
                    'createdAt': now, 'updatedAt': now, 'approvedAt': now}
        for folder, record in [('artifacts', artifact), ('jobs', {'id': artifact['jobId'], 'courseId': cid,
                'teacherId': 'local-teacher', 'status': 'review', 'createdAt': now, 'updatedAt': now})]:
            directory = DATA_ROOT / folder
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{record['id']}.json").write_text(json.dumps(record), encoding='utf-8')

        call('POST', f'/api/course-space/{cid}/publish', 201)
        assert call('GET', f'/api/classes/{cid}')['resources'] == []
        print('PASS publish gate + empty resources after publish', flush=True)

        activated = call('PATCH', f"/api/course-space/{cid}/artifacts/{artifact['id']}", json={'action': 'activate'})
        publication = activated['artifact']['classPublicationId']
        assert publication.startswith('CLS-A-')
        repeated = call('PATCH', f"/api/course-space/{cid}/artifacts/{artifact['id']}", json={'action': 'activate'})
        assert repeated['artifact']['classPublicationId'] == publication
        call('PATCH', f"/api/course-space/{cid}/artifacts/{artifact['id']}", 409, json={'action': 'deactivate'})
        resources = call('GET', f'/api/classes/{cid}')['resources']
        assert len(resources) == 1, resources
        print(f'PASS artifact activation idempotent ({publication}); deactivate rejected; resources=1', flush=True)

        assert not any(r.get('materialId') == material_id for r in resources)
        material = call('PATCH', f'/api/course-space/{cid}/materials/{material_id}', json={'active': True})['material']
        assert material['classPublicationId'].startswith('CLS-M-')
        resources = call('GET', f'/api/classes/{cid}')['resources']
        assert len(resources) == 2, resources
        print(f'PASS material draft isolation + activation ({material["classPublicationId"]}); resources=2', flush=True)

        stage = {'id': f'acceptance-stage-{cid[:8]}', 'name': 'Acceptance classroom',
                 'createdAt': int(time.time() * 1000), 'updatedAt': int(time.time() * 1000)}
        scenes = [minimal_scene(f'acceptance-scene-{cid[:8]}', stage['id'])]
        created = call('POST', '/api/classroom', 201, json={'stage': stage, 'scenes': scenes})
        classroom_id = created['id']
        fetched = call('GET', f'/api/classroom?id={classroom_id}')
        assert fetched['classroom']['stage']['id'] == stage['id']
        assert len(fetched['classroom']['scenes']) == 1
        print(f'PASS classroom persisted + retrievable id={classroom_id}', flush=True)

        attached = call('POST', f'/api/course-space/{cid}/classrooms/attach',
                        json={'classroomId': classroom_id, 'title': 'Acceptance courseware'})
        attach_artifact = attached['artifacts'][0]
        assert attach_artifact['status'] == 'review'
        resources = call('GET', f'/api/classes/{cid}')['resources']
        assert len(resources) == 2, 'attached courseware must stay invisible before activation'
        again = call('POST', f'/api/course-space/{cid}/classrooms/attach', json={'classroomId': classroom_id})
        assert len(again['artifacts']) == 1 and again['artifacts'][0]['id'] == attach_artifact['id']
        call('POST', f'/api/course-space/{cid}/classrooms/attach', 404, json={'classroomId': 'acceptance-missing'})
        print('PASS classroom attach: review status, no leak, idempotent, dangling rejected', flush=True)

        activated_attach = call('PATCH', f"/api/course-space/{cid}/artifacts/{attach_artifact['id']}",
                                json={'action': 'activate'})['artifact']
        assert activated_attach['classPublicationId'].startswith('CLS-A-')
        resources = call('GET', f'/api/classes/{cid}')['resources']
        assert len(resources) == 3, resources
        publication_ids = [r['publicationId'] for r in resources]
        assert len(set(publication_ids)) == 3, publication_ids
        print(f'PASS attached courseware activated ({activated_attach["classPublicationId"]}); resources=3 distinct', flush=True)

        for page in ['/', f'/teacher-workspace?workspace={cid}', f'/classroom-player/{classroom_id}',
                     '/classroom-player/acceptance-missing']:
            response = client.get(page)
            assert response.status_code == 200, (page, response.status_code)
            print(f'PASS page shell {page}', flush=True)

        print(f'ALL PASS course={cid} classroom={classroom_id} '
              f'publications={publication_ids}', flush=True)


if __name__ == '__main__':
    main()
