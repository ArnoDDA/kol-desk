"""Business invariants tested against a real HTTP server and temporary SQLite."""
import copy
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

spec = importlib.util.spec_from_file_location('workbench', Path(__file__).resolve().parents[1] / 'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class QuietHandler(app.Handler):
    def log_message(self, *args):
        pass

class Client:
    def __init__(self, port):
        self.port, self.cookie, self.csrf = port, '', ''

    def call(self, path, body=None, method=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'Cookie': self.cookie, 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        h.update(headers or {})
        conn.request(method or ('POST' if body is not None else 'GET'), path,
                     json.dumps(body).encode() if body is not None else None, h)
        res = conn.getresponse()
        if res.getheader('Set-Cookie'):
            self.cookie = res.getheader('Set-Cookie').split(';')[0]
        raw = res.read().decode('utf-8-sig')
        data = json.loads(raw) if 'application/json' in res.getheader('Content-Type', '') else raw
        status = res.status
        conn.close()
        if path == '/api/bootstrap' and status == 200 and data['user']:
            self.csrf = data['user']['csrf']
        return status, data

class WorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        app.DATA = Path(cls.tmp.name)
        app.init_db()
        cls.httpd = app.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.httpd.failed_logins = []
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.admin = Client(cls.httpd.server_port)
        assert cls.admin.call('/api/setup', {'name':'测试管理员','username':'admin','password':'testing-password-123'})[0] == 200
        cls.admin.call('/api/bootstrap')
        cls.editor = cls.new_user('editor')
        cls.reviewer = cls.new_user('reviewer')

    @classmethod
    def new_user(cls, role):
        assert cls.admin.call('/api/users', {'name':role,'username':role,'password':'testing-password-123','role':role})[0] == 200
        client = Client(cls.httpd.server_port)
        assert client.call('/api/login', {'username':role,'password':'testing-password-123'})[0] == 200
        client.call('/api/bootstrap')
        return client

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def setUp(self):
        status, result = self.editor.call('/api/demo', {})
        self.assertEqual(status, 201)
        self.pid = result['id']
        self.detail = self.read()
        self.cid = self.detail['candidates'][0]['id']

    def read(self):
        status, result = self.admin.call('/api/projects/'+self.pid)
        self.assertEqual(status, 200)
        return result

    def candidate(self, cid=None):
        return next(d for d in self.read()['candidates'] if d['id'] == (cid or self.cid))

    def action(self, action, extra=None, client=None, cid=None):
        cid = cid or self.cid
        return (client or self.editor).call('/api/candidates/'+cid+'/'+action,
            {'version':self.candidate(cid)['version'], **(extra or {})})

    def patch(self, d, client=None):
        return (client or self.editor).call('/api/candidates/'+d['id'], d, 'PATCH')

    def approve(self):
        self.assertEqual(self.action('submit')[0], 200)
        return self.action('review', {'verdict':'approve','note':'匹配证据与完整预算均已核实'}, self.reviewer)

    def test_complete_cost_and_unknowns(self):
        a,b,c,_ = self.detail['candidates']
        self.assertEqual(a['assessment']['max_cost'], 3400)
        self.assertIsNone(b['assessment']['max_cost'])
        self.assertIsNone(b['audience_pct'])
        self.assertEqual(c['assessment']['max_cost'], 4200)
        self.assertEqual(self.detail['summary']['remaining'], 4400)
        self.assertEqual(self.action('select', {'selected':True}, cid=b['id'])[0], 200)
        self.assertIsNone(self.read()['summary']['remaining'])
        self.assertEqual(self.approve()[0], 400)

    def test_approval_and_quote_invalidation(self):
        self.assertEqual(self.approve()[0], 200)
        approved = self.candidate()
        self.assertEqual(approved['version'], approved['approved_version'])
        self.assertEqual(self.action('select', {'selected':True})[0], 200)
        self.assertEqual(self.candidate()['version'], approved['version'])
        self.assertEqual(self.action('select', {'selected':False})[0], 409)
        approved['quote']['usage'] = 500
        self.assertEqual(self.patch(approved)[0], 200)
        changed = self.candidate()
        self.assertEqual(changed['state'], 'pending')
        self.assertIsNone(changed['approved_version'])
        self.assertTrue(any(e['action']=='review_approve' and e['snapshot']['record']['quote']['usage']==300 for e in self.read()['events']))

    def test_project_changes_invalidate_pending_and_approved(self):
        self.assertEqual(self.approve()[0], 200)
        d = self.candidate()
        p = self.read()['project']; p['budget'] = 13000
        self.assertEqual(self.editor.call('/api/projects/'+self.pid, p, 'PATCH')[0],200)
        self.assertEqual(self.candidate()['state'],'pending')
        self.assertGreater(self.candidate()['version'], d['version'])
        stale = self.candidate()
        p = self.read()['project']; p['require_paid_rights'] = True
        self.assertEqual(self.editor.call('/api/projects/'+self.pid,p,'PATCH')[0],200)
        self.assertEqual(self.reviewer.call('/api/candidates/'+self.cid+'/review',{'version':stale['version'],'verdict':'approve','note':'stale'})[0],409)
        self.assertEqual(self.action('review',{'verdict':'approve','note':'now'}, self.reviewer)[0],400)

    def test_overbudget_combination(self):
        d = self.candidate(); d['quote']['fee'] = 8000
        self.assertEqual(self.patch(d)[0],200)
        self.assertTrue(self.read()['summary']['over_budget'])
        self.assertEqual(self.approve()[0],400)
        self.assertEqual(self.candidate()['state'],'pending')

    def test_deselected_pending_cannot_bypass_budget(self):
        self.action('submit')
        self.action('select', {'selected':False})
        self.assertEqual(self.action('review',{'verdict':'approve','note':'check'},self.reviewer)[0],400)

    def test_forecast_requires_basis_and_same_currency(self):
        d = self.candidate()
        self.assertAlmostEqual(d['assessment']['forecast_cpv'],3400/26000)
        d['quote']['forecast_basis']=''
        d['quote']['currency']='USD'
        self.assertEqual(self.patch(d)[0],200)
        self.assertIsNone(self.candidate()['assessment']['forecast_cpv'])
        self.assertIsNone(self.read()['summary']['remaining'])
        self.assertEqual(self.approve()[0],400)

    def test_roles_auth_csrf_and_methods(self):
        guest=Client(self.httpd.server_port)
        self.assertEqual(guest.call('/api/projects/'+self.pid)[0],401)
        self.assertEqual(self.patch(self.candidate(),self.reviewer)[0],403)
        self.action('submit')
        self.assertEqual(self.action('review',{'verdict':'approve','note':'check'},self.editor)[0],403)
        self.assertEqual(self.editor.call('/api/users',{})[0],403)
        self.assertEqual(self.editor.call('/api/demo',{},headers={'X-CSRF-Token':''})[0],403)
        self.assertEqual(self.editor.call('/api/demo',{},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.admin.call('/api/bootstrap',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.editor.call('/api/candidates/'+self.cid+'/submit',{},'PATCH')[0],405)

    def test_stale_write_conflict_and_comment(self):
        d=self.candidate(); changed=copy.deepcopy(d); changed['next_action']='新的动作'
        self.assertEqual(self.patch(changed)[0],200)
        self.assertEqual(self.patch(d)[0],409)
        self.assertEqual(self.action('comment',{'note':'核对完成'},self.reviewer)[0],200)
        self.assertEqual(self.candidate()['next_action'],'新的动作')

    def test_import_all_or_none_dedup_and_formula_export(self):
        path='/api/projects/'+self.pid
        bad='name,platform,account_id,fee\nGood,YouTube,one,100\nBad,YouTube,two,-10\n'
        result=self.editor.call(path+'/import-preview',{'csv':bad})[1]
        self.assertEqual(len(result['errors']),1)
        self.assertEqual(self.editor.call(path+'/import',{'csv':bad})[0],400)
        self.assertEqual(len(self.read()['candidates']),4)
        raw='name,platform,account_id,fee\n=2+2,YouTube,new-id,100\nRenamed,YouTube,orbit-demo,300\n'
        result=self.editor.call(path+'/import',{'csv':raw})[1]
        self.assertEqual(result,{'count':1,'skipped':1})
        self.assertIn("'=2+2",self.admin.call(path+'/export')[1])
        self.assertEqual(self.editor.call(path+'/import',{'csv':raw})[1]['count'],0)
        imported=self.read()['candidates'][-1]
        self.assertFalse(imported['assessment']['ready'])
        self.assertIsNone(imported['assessment']['max_cost'])

    def test_report_and_persistence(self):
        report=self.admin.call('/api/projects/'+self.pid+'/report')[1]
        self.assertIn('合成示例',report)
        self.assertIn('不是实际投放结果',report)
        self.assertIn('EUR',report)
        app.init_db()
        self.assertEqual(len(self.read()['candidates']),4)
        with app.db() as c:
            passwords=[r[0] for r in c.execute('SELECT password FROM users')]
        self.assertTrue(all('testing-password' not in x for x in passwords))

    def test_input_validation(self):
        d=self.candidate(); d['quote']['fee']=True
        self.assertEqual(self.patch(d)[0],400)
        d=self.candidate(); d['source_url']='javascript:alert(1)'
        self.assertEqual(self.patch(d)[0],400)
        d=self.candidate(); d['audience_pct']=101
        self.assertEqual(self.patch(d)[0],400)
        d=self.candidate(); d['quote']['tax']=None
        self.assertEqual(self.patch(d)[0],200)
        self.assertEqual(self.approve()[0],400)

    def test_expired_quote_and_audience_gate(self):
        d=self.candidate(); d['quote']['valid_until']='2000-01-01'
        self.assertEqual(self.patch(d)[0],200)
        self.assertEqual(self.approve()[0],400)
        d=self.candidate(); d['quote']['valid_until']=''; d['audience_pct']=39
        self.assertEqual(self.patch(d)[0],200)
        self.assertIn('目标受众占比未达到项目门槛',self.candidate()['assessment']['blockers'])

    def test_decimal_budget_and_approval_combination_snapshot(self):
        d=self.candidate()
        for k in ['fee','usage','exclusivity_fee','production','tax','bonus_cap']:
            d['quote'][k]=0
        d['quote']['fee']=0.1; d['quote']['usage']=0.2
        p=self.read()['project']; p['budget']=0.3
        self.assertEqual(app.assess(app.candidate_data(d),p)['max_cost'],0.3)
        self.assertNotIn('已知最高承诺费用超过项目总预算',app.assess(app.candidate_data(d),p)['blockers'])
        self.assertEqual(self.approve()[0],200)
        entry=next(e for e in self.read()['events'] if e['action']=='review_approve')
        self.assertEqual(entry['snapshot']['combination']['summary']['selected_max_cost'],7600)
        self.assertEqual(len(entry['snapshot']['combination']['candidates']),2)

    def test_password_rotation_invalidates_other_sessions(self):
        other=Client(self.httpd.server_port)
        other.call('/api/login',{'username':'admin','password':'testing-password-123'})
        other.call('/api/bootstrap')
        self.assertEqual(self.admin.call('/api/password',{'old_password':'testing-password-123','new_password':'testing-password-456'})[0],200)
        self.admin.call('/api/bootstrap')
        self.assertIsNone(other.call('/api/bootstrap')[1]['user'])
        self.assertEqual(self.admin.call('/api/password',{'old_password':'testing-password-456','new_password':'testing-password-123'})[0],200)
        self.admin.call('/api/bootstrap')

class LocalModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DATA = Path(self.tmp.name)
        app.init_db()
        self.httpd = app.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.httpd.failed_logins = []
        self.httpd.local_user_id = app.ensure_local_user()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.httpd.server_port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_open_without_registration_and_keep_history(self):
        status,b = self.client.call('/api/bootstrap')
        self.assertEqual(status,200)
        self.assertFalse(b['needs_setup'])
        self.assertTrue(b['local_mode'])
        self.assertEqual(b['user']['name'],'本地工作台')
        self.assertEqual(b['projects'],[])
        status,result = self.client.call('/api/demo',{})
        self.assertEqual(status,201)
        pid=result['id']
        other=Client(self.httpd.server_port)
        fresh=other.call('/api/bootstrap')[1]
        self.assertEqual(fresh['user']['id'],b['user']['id'])
        self.assertIn(pid,[p['id'] for p in fresh['projects']])
        detail=other.call('/api/projects/'+pid)[1]
        self.assertTrue(all(e['user_name']=='本地工作台' for e in detail['events']))
        self.assertEqual(app.ensure_local_user(),b['user']['id'])

    def test_no_login_management_but_request_checks_remain(self):
        self.client.call('/api/bootstrap')
        for path in ['setup','login','logout','users','password']:
            self.assertEqual(self.client.call('/api/'+path,{})[0],403)
        self.assertEqual(self.client.call('/api/demo',{},headers={'X-CSRF-Token':''})[0],403)
        self.assertEqual(self.client.call('/api/bootstrap',headers={'Origin':'https://other.example'})[0],403)

    def test_expired_session_reopens_without_login(self):
        self.client.call('/api/bootstrap')
        old_cookie=self.client.cookie
        with app.db(True) as c:
            c.execute('DELETE FROM sessions')
        status,b=self.client.call('/api/bootstrap')
        self.assertEqual(status,200)
        self.assertTrue(b['local_mode'])
        self.assertNotEqual(self.client.cookie,old_cookie)
        self.assertEqual(self.client.call('/api/demo',{})[0],201)

if __name__=='__main__':
    unittest.main(verbosity=2)
