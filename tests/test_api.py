import os
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
TEST_DATA=ROOT/'artifacts'/('test-'+uuid.uuid4().hex)
assert TEST_DATA.resolve().is_relative_to(ROOT.resolve())
os.environ['AI_NAM_DATA_DIR']=str(TEST_DATA)
from fastapi.testclient import TestClient
from app.main import app
from app import storage


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.DATA_DIR=TEST_DATA
        cls.context=TestClient(app)
        cls.client=cls.context.__enter__()
        cls.credentials={'username':'test-admin','name':'Test Admin','password':'Test-password-943!','role':'admin'}
        response=cls.client.post('/api/auth/setup',json=cls.credentials)
        assert response.status_code==200,response.text
        cls.admin_cookie=cls.client.cookies.get('ai_nam_session')

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None,None,None)

    def setUp(self):
        self.client.cookies.clear()
        self.client.cookies.set('ai_nam_session',self.admin_cookie)

    def test_bootstrap_is_one_time(self):
        self.assertEqual(self.client.post('/api/auth/setup',json=self.credentials).status_code,409)

    def test_unauthenticated_data_is_not_exposed(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/cases').status_code,401)
        self.assertEqual(self.client.get('/api/users').status_code,401)

    def test_viewer_cannot_analyze_review_or_manage_accounts(self):
        username='viewer-'+uuid.uuid4().hex[:5]
        self.client.post('/api/users',json={'username':username,'name':'Viewer','password':'Viewer-password-123','role':'viewer'})
        r=self.client.post('/api/auth/login',json={'username':username,'password':'Viewer-password-123'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/cases').status_code,200)
        self.assertEqual(self.client.post('/api/demo',json={}).status_code,403)
        self.assertEqual(self.client.patch('/api/cases/fake/findings/f1',json={'status':'confirmed'}).status_code,403)
        self.assertEqual(self.client.get('/api/users').status_code,403)

    def test_cross_origin_write_rejected(self):
        response=self.client.post('/api/demo',json={},headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)

    def test_end_to_end_upload_review_and_exports(self):
        before='1. Функции\n1.1. Организует проверку закупок.\n1.2. Готовит отчет об информационной безопасности.'
        after='1. Функции\n1.1. Организует проверку закупок.'
        response=self.client.post('/api/cases',data={'title':'Acceptance test','use_ai':'false'},files=[('before',('before.txt',before.encode(),'text/plain')),('after',('after.txt',after.encode(),'text/plain'))])
        self.assertEqual(response.status_code,200,response.text)
        cid=response.json()['id']
        case=None
        for _ in range(100):
            case=self.client.get('/api/cases/'+cid).json()
            if case['status']!='processing':break
            time.sleep(.03)
        self.assertEqual(case['status'],'complete',case)
        self.assertNotIn('path',case['manifest'][0])
        finding=next(f for f in case['result']['findings'] if f['kind']=='missing')
        reviewed=self.client.patch(f'/api/cases/{cid}/findings/{finding["id"]}',json={'status':'confirmed','comment':'Verified by reviewer'})
        self.assertEqual(reviewed.status_code,200)
        self.assertEqual(reviewed.json()['reviewer'],'Test Admin')
        for fmt in ['json','html','xlsx','docx']:
            report=self.client.get(f'/api/cases/{cid}/export/{fmt}')
            self.assertEqual(report.status_code,200)
            self.assertIn('attachment',report.headers['content-disposition'])
        did=case['result']['documents'][0]['id']
        download=self.client.get(f'/api/cases/{cid}/documents/{did}/download')
        self.assertEqual(download.content,before.encode())
        self.assertEqual(self.client.get(f'/api/cases/{cid}/documents/missing/download').status_code,404)

    def test_invalid_and_duplicate_files(self):
        data=b'1.1. Test'
        response=self.client.post('/api/cases',data={'title':'Invalid'},files=[('before',('bad.exe',data)),('after',('after.txt',data))])
        self.assertEqual(response.status_code,422)
        response=self.client.post('/api/cases',data={'title':'Duplicate'},files=[('before',('a.txt',data)),('before',('b.txt',data)),('after',('c.txt',data))])
        self.assertEqual(response.status_code,422)

    def test_access_revocation_invalidates_session(self):
        username='reader-'+uuid.uuid4().hex[:5]
        user=self.client.post('/api/users',json={'username':username,'name':'Reader','password':'Reader-password-123','role':'viewer'}).json()
        self.client.cookies.clear()
        self.client.post('/api/auth/login',json={'username':username,'password':'Reader-password-123'})
        viewer_cookie=self.client.cookies.get('ai_nam_session')
        self.client.cookies.clear()
        self.client.cookies.set('ai_nam_session',self.admin_cookie)
        r=self.client.patch('/api/users/'+user['id'],json={'role':'viewer','active':False})
        self.assertEqual(r.status_code,200)
        self.client.cookies.clear()
        self.client.cookies.set('ai_nam_session',viewer_cookie)
        self.assertEqual(self.client.get('/api/cases').status_code,401)

    def test_no_credentials_in_user_list(self):
        for user in self.client.get('/api/users').json():
            self.assertNotIn('password',user)
            self.assertNotIn('token',user)

    def test_private_cases_and_explicit_sharing(self):
        owner=storage.create_user('owner-'+uuid.uuid4().hex[:5],'Owner','analyst','Test-owner-123')
        reader=storage.create_user('other-'+uuid.uuid4().hex[:5],'Other','analyst','Test-other-123')
        cid=storage.create_case('Private case',owner['id'],[])
        self.client.cookies.clear()
        self.client.cookies.set('ai_nam_session',storage.new_session(reader['id']))
        self.assertNotIn(cid,[c['id'] for c in self.client.get('/api/cases').json()])
        for endpoint in ['', '/export/json', '/documents/unknown/download']:
            self.assertEqual(self.client.get('/api/cases/'+cid+endpoint).status_code,404)
        self.assertEqual(self.client.patch('/api/cases/'+cid+'/findings/f1',json={'status':'confirmed'}).status_code,404)
        self.assertEqual(self.client.patch('/api/cases/'+cid+'/sharing',json={'shared':True}).status_code,404)
        self.client.cookies.clear()
        self.client.cookies.set('ai_nam_session',storage.new_session(owner['id']))
        self.assertEqual(self.client.patch('/api/cases/'+cid+'/sharing',json={'shared':True}).status_code,200)
        self.client.cookies.clear()
        self.client.cookies.set('ai_nam_session',storage.new_session(reader['id']))
        self.assertEqual(self.client.get('/api/cases/'+cid).status_code,200)
        self.assertEqual(self.client.patch('/api/cases/'+cid+'/sharing',json={'shared':False}).status_code,403)


if __name__=='__main__':unittest.main()
