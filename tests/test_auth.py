import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import auth
from backend.app import app


class AuthenticationModeTests(unittest.TestCase):
    def setUp(self):
        self.environment=patch.dict(os.environ,{'POSTURE_AUTH_MODE':'strict',
            'POSTURE_INGEST_TOKEN':'synthetic-test-token-at-least-24-characters'})
        self.environment.start()
        self.database=patch.object(auth,'db')
        self.db=self.database.start()
        self.db.auth_sessions.find_one.return_value=None
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.database.stop)

    def request(self,authorization=None,cookie=None):
        headers=[]
        if authorization is not None: headers.append((b'authorization',authorization.encode()))
        if cookie is not None: headers.append((b'cookie',('posture_session='+cookie).encode()))
        return Request({'type':'http','headers':headers})

    def test_strict_default_and_unknown_configuration(self):
        os.environ.pop('POSTURE_AUTH_MODE')
        self.assertEqual(auth.auth_mode(),'strict')
        with self.assertRaises(HTTPException) as error: auth.principal(self.request())
        self.assertEqual(error.exception.status_code,401)
        os.environ['POSTURE_AUTH_MODE']='typo'
        with self.assertRaises(RuntimeError): auth.auth_mode()

    def test_development_anonymous_access_is_explicit_and_auditable(self):
        os.environ['POSTURE_AUTH_MODE']='development'
        for authenticate in (auth.principal,auth.editor,auth.admin):
            request=self.request()
            user=authenticate(request)
            self.assertEqual(user,{'username':'development','role':'admin','unauthenticated':True})
            self.assertTrue(request.state.auth_bypassed)
        self.db.auth_sessions.find_one.assert_not_called()

    def test_bad_credentials_are_never_promoted_to_anonymous_admin(self):
        os.environ['POSTURE_AUTH_MODE']='development'
        for request in (self.request('Bearer invalid'),self.request('Basic invalid'),self.request(cookie='expired')):
            with self.assertRaises(HTTPException) as error: auth.editor(request)
            self.assertEqual(error.exception.status_code,401)
            self.assertFalse(getattr(request.state,'auth_bypassed',False))

    def test_viewer_permissions_and_device_limits_remain_in_both_modes(self):
        for mode in ('strict','development'):
            os.environ['POSTURE_AUTH_MODE']=mode
            self.db.auth_sessions.find_one.return_value={'username':'reader'}
            self.db.users.find_one.return_value={'username':'reader','role':'viewer'}
            self.assertEqual(auth.principal(self.request(cookie='valid'))['role'],'viewer')
            for authenticate in (auth.admin,auth.editor):
                with self.assertRaises(HTTPException) as error: authenticate(self.request(cookie='valid'))
                self.assertEqual(error.exception.status_code,403)
            self.db.auth_sessions.find_one.return_value=None
            request=self.request('Bearer '+os.environ['POSTURE_INGEST_TOKEN'])
            self.assertEqual(auth.editor(request)['role'],'device')
            with self.assertRaises(HTTPException): auth.admin(request)

    def test_http_warning_and_strict_transition(self):
        client=TestClient(app)
        os.environ['POSTURE_AUTH_MODE']='development'
        response=client.get('/api/v1/auth/me')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['X-POSTURE-Auth-Mode'],'development')
        self.assertEqual(response.headers['X-POSTURE-Auth-Bypass'],'true')
        self.assertIn('administrator',response.headers['X-POSTURE-Auth-Warning'])
        self.assertEqual(client.post('/api/v1/auth/password',json={}).status_code,401)
        os.environ['POSTURE_AUTH_MODE']='strict'
        response=client.get('/api/v1/auth/me')
        self.assertEqual(response.status_code,401)
        self.assertEqual(response.headers['X-POSTURE-Auth-Mode'],'strict')
        self.assertNotIn('X-POSTURE-Auth-Warning',response.headers)
        self.assertNotIn('X-POSTURE-Auth-Bypass',response.headers)

    def test_openapi_matches_active_mode_without_losing_security_definitions(self):
        self.addCleanup(setattr,app,'openapi_schema',None)
        for mode in ('strict','development'):
            os.environ['POSTURE_AUTH_MODE']=mode
            app.openapi_schema=None
            schema=app.openapi()
            operation=schema['paths']['/api/v1/iterations']['post']
            self.assertEqual(schema['info']['x-posture-auth-mode'],mode)
            self.assertEqual({} in operation['security'],mode=='development')
            self.assertIn('HTTPBearer',schema['components']['securitySchemes'])
            self.assertIn('APIKeyCookie',schema['components']['securitySchemes'])


if __name__=='__main__': unittest.main()
