"""Provider contract fixtures are synthetic; these tests never call a paid API."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from test_workbench import app, Client, QuietHandler
import discovery


class AdaptersTest(unittest.TestCase):
    def query(self, **kw):
        return discovery.query_data({'provider':'club','platform':'youtube','topic':'strategy games','limit':5,**kw})

    def test_platform_specific_size_and_video_metrics(self):
        q=self.query(followers_min=1000, content_type='long', average_views_min=2000)
        payload=discovery.request_body(q)
        self.assertEqual(payload['paging'],{'page':0,'limit':5})
        self.assertEqual(payload['filters']['number_of_subscribers'],{'min':1000})
        self.assertEqual(payload['filters']['average_views_on_long_videos'],{'min':2000})
        self.assertNotIn('number_of_followers',payload['filters'])
        q=self.query(platform='twitch',followers_max=20000)
        self.assertEqual(discovery.request_body(q)['filters']['followers'],{'max':20000})

    def test_nox_cursor_and_format_preserved(self):
        q=self.query(provider='nox',content_type='short',average_views_min=3000)
        cursor=[1.25,'opaque-id']
        payload=discovery.request_body(q,2,cursor)
        self.assertEqual(payload['video_type'],1)
        self.assertEqual(payload['search_after'],cursor)
        self.assertEqual(payload['page_num'],2)
        with self.assertRaises(discovery.DiscoveryError):discovery.request_body(q,2)

    def test_unknown_and_masked_identity_stay_unknown(self):
        q=self.query(provider='nox',content_type='long')
        rows,_=discovery.normalize('nox',q,{'data':{'items':[{'id':'opaque-1','nickname':'Gam***','country':'DE','avg_views':900000,'followers':None}]}})
        self.assertEqual(rows[0]['provider_id'],'opaque-1')
        self.assertEqual(rows[0]['profile_url'],'')
        self.assertEqual(rows[0]['account_id'],'')
        self.assertIsNone(rows[0]['average_views'])
        self.assertIsNone(rows[0]['followers'])
        self.assertEqual(rows[0]['creator_location'],'DE')

    def test_bad_inputs_and_response_shape(self):
        for values in [{'provider':'other'},{'limit':100},{'followers_min':True},{'followers_min':20,'followers_max':10},{'platform':'twitch','content_type':'long'}]:
            with self.subTest(values=values),self.assertRaises(discovery.DiscoveryError):self.query(**values)
        with self.assertRaises(discovery.DiscoveryError):discovery.normalize('club',self.query(),{'unexpected':[]})
        self.assertEqual(discovery.safe_url('javascript:alert(1)'),'')

    def test_credentials_never_in_status_or_saved_response(self):
        manager=discovery.DiscoveryManager(request=lambda *args:{})
        manager.configure('club','private-test-value')
        self.assertNotIn('private-test-value',json.dumps(manager.status()))
        data=discovery.sanitized({'api_key':'secret','nested':{'access_token':'other'},'echo':'private-test-value'},'private-test-value')
        self.assertNotIn('private-test-value',json.dumps(data))
        self.assertNotIn('api_key',data)
        self.assertEqual(data['nested'],{})


class DiscoveryFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();app.DATA=Path(self.tmp.name);app.init_db()
        self.httpd=app.ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        self.httpd.failed_logins=[];self.httpd.local_user_id=app.ensure_local_user()
        self.calls=[];self.bad_shape=False;self.fail=False;self.price=.02
        self.httpd.discovery=discovery.DiscoveryManager(request=self.fake)
        self.httpd.discovery.keys={'club':'','nox':''}
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True);self.thread.start()
        self.client=Client(self.httpd.server_port);self.client.call('/api/bootstrap')
        project={'name':'真实项目测试','game':'Game','market':'德国','language':'德语','budget':10000,'currency':'EUR'}
        self.pid=self.client.call('/api/projects',project)[1]['id']

    def tearDown(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join();self.tmp.cleanup()

    def fake(self,provider,path,key,payload=None):
        self.calls.append((provider,path,key,copy.deepcopy(payload)))
        if 'pricing/tools' in path:return {'success':True,'data':{'items':[{'action':'creator_search','unit_credit':self.price,'unit':'creator'}]}}
        if payload is None:return {'credits':100}
        if self.fail:raise discovery.DiscoveryError('数据源超时，未自动重试。',502)
        if self.bad_shape:return {'new_schema':[{'not':'parsed'}]}
        if provider=='club':
            return {'total':7,'accounts':[{'user_id':'club-1','profile':{'username':'fixture_creator','full_name':'Contract fixture only','followers':12000,'country':'DE','average_views':5000,'url':'https://example.com/fixture'}}]}
        return {'success':True,'data':{'items':[{'id':'opaque-nox','nickname':'Ga***','followers':0,'country':'DE','avg_views':80000,'avg_views_normal':None}], 'total_size':10,'search_after':[1,'opaque-nox']}}

    def configure(self,provider='club'):
        self.assertEqual(self.client.call('/api/discovery/config',{'provider':provider,'key':'synthetic-key'})[0],200)

    def preview(self,provider='club',**extra):
        status,result=self.client.call('/api/discovery/preview',{'provider':provider,'platform':'youtube','topic':'strategy games','limit':5,**extra})
        self.assertEqual(status,200,result);return result

    def execute(self,plan):
        return self.client.call('/api/discovery/runs/'+plan['id']+'/execute',{'accept_cost':True})

    def test_no_credentials_no_fabricated_results(self):
        status,result=self.client.call('/api/discovery/preview',{'provider':'club','platform':'youtube','topic':'strategy games'})
        self.assertEqual(status,400)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.client.call('/api/discovery')[1]['runs'],[])

    def test_explicit_cost_gate_and_retry_uses_saved_result(self):
        self.configure();plan=self.preview()
        self.assertEqual(self.calls,[])
        self.assertEqual(self.client.call('/api/discovery/runs/'+plan['id']+'/execute',{})[0],400)
        self.assertEqual(self.execute(plan)[0],200)
        self.assertEqual(self.execute(plan)[0],200)
        self.assertEqual(len([c for c in self.calls if c[3] is not None]),1)
        self.assertNotIn('synthetic-key',json.dumps(self.client.call('/api/discovery')[1]))

    def test_import_preserves_evidence_without_invented_fit_or_price(self):
        self.configure();plan=self.preview();self.execute(plan)
        route='/api/discovery/runs/'+plan['id']+'/import'
        request={'project_id':self.pid,'indices':[0]}
        self.assertEqual(self.client.call(route,request)[1]['count'],1)
        self.assertEqual(self.client.call(route,request)[1]['skipped'],1)
        d=self.client.call('/api/projects/'+self.pid)[1]['candidates'][0]
        self.assertEqual(d['fit'],'unknown');self.assertFalse(d['audience_verified'])
        self.assertEqual(d['audience_market'],'');self.assertIsNone(d['audience_pct'])
        self.assertIsNone(d['quote']['fee']);self.assertEqual(d['language'],'')
        self.assertEqual(d['source_ref']['run_id'],plan['id'])
        d['next_action']='人工核查'
        self.assertEqual(self.client.call('/api/candidates/'+d['id'],d,'PATCH')[0],200)
        changed=self.client.call('/api/projects/'+self.pid)[1]['candidates'][0]
        self.assertEqual(changed['source_ref'],d['source_ref'])

    def test_nox_opaque_identity_and_next_cursor(self):
        self.configure('nox');plan=self.preview('nox',content_type='long')
        status,result=self.execute(plan);self.assertEqual(status,200,result)
        self.assertIsNone(result['items'][0]['average_views'])
        self.assertEqual(result['items'][0]['followers'],0)
        self.assertEqual(self.client.call('/api/discovery/runs/'+plan['id']+'/import',{'project_id':self.pid,'indices':[0]})[1]['count'],1)
        d=self.client.call('/api/projects/'+self.pid)[1]['candidates'][0]
        self.assertEqual(d['account_id'],'');self.assertEqual(d['source_ref']['provider_id'],'opaque-nox')
        self.assertEqual(self.client.call('/api/candidates/'+d['id'],d,'PATCH')[0],200)
        status,next_plan=self.client.call('/api/discovery/preview',{'parent_id':plan['id']})
        self.assertEqual(status,200,next_plan)
        self.assertEqual(next_plan['payload']['search_after'],[1,'opaque-nox'])
        self.assertEqual(next_plan['query'],plan['query'])
        self.assertEqual(next_plan['page'],2)

    def test_errors_and_schema_changes_do_not_turn_into_empty_success(self):
        self.configure();plan=self.preview();self.bad_shape=True
        self.assertEqual(self.execute(plan)[0],502)
        result=self.client.call('/api/discovery/runs/'+plan['id'])[1]
        self.assertEqual(result['status'],'failed')
        self.assertIn('new_schema',self.client.call('/api/discovery/runs/'+plan['id']+'/raw')[1]['response'])
        self.assertEqual(self.execute(plan)[0],409)
        self.assertEqual(len([c for c in self.calls if c[3] is not None]),1)

    def test_account_change_and_price_change_block_execution(self):
        self.configure();plan=self.preview();self.client.call('/api/discovery/config',{'provider':'club','key':'different-key'})
        self.assertEqual(self.execute(plan)[0],409)
        self.assertEqual(len(self.calls),0)
        self.configure('nox');plan=self.preview('nox');self.price=.03
        self.assertEqual(self.execute(plan)[0],409)
        self.assertEqual(len([c for c in self.calls if c[3] is not None]),0)

    def test_concurrent_execution_sends_one_paid_request(self):
        self.configure(); plan=self.preview()
        entered=threading.Event(); release=threading.Event()
        original=self.httpd.discovery.request
        def delayed(*args):
            if len(args)>3 and args[3] is not None:
                entered.set()
                release.wait(5)
            return original(*args)
        self.httpd.discovery.request=delayed
        second=Client(self.httpd.server_port)
        second.cookie=self.client.cookie; second.csrf=self.client.csrf
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.execute(plan)))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            response=second.call('/api/discovery/runs/'+plan['id']+'/execute',{'accept_cost':True})
            self.assertEqual(response[0],409)
        finally:
            release.set();worker.join(5)
        self.assertEqual(results[0][0],200)
        self.assertEqual(len([c for c in self.calls if c[3] is not None]),1)

    def test_transport_failure_requires_new_explicit_plan(self):
        self.configure();plan=self.preview();self.fail=True
        self.assertEqual(self.execute(plan)[0],502)
        self.assertEqual(self.execute(plan)[0],409)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.client.call('/api/discovery/runs/'+plan['id']+'/raw')[0],404)

    def test_saved_query_readable_after_key_cleared(self):
        self.configure();plan=self.preview();self.execute(plan)
        self.client.call('/api/discovery/config',{'provider':'club','key':''})
        result=self.client.call('/api/discovery/runs/'+plan['id'])[1]
        self.assertEqual(result['status'],'done');self.assertEqual(len(result['items']),1)
        self.assertEqual(len(self.calls),1)

    def test_review_only_role_cannot_spend_or_configure(self):
        with app.db(True) as c:
            c.execute("UPDATE users SET role='reviewer' WHERE id=?",(self.httpd.local_user_id,))
        self.assertEqual(self.client.call('/api/discovery/config',{'provider':'club','key':'test'})[0],403)
        self.assertEqual(self.client.call('/api/discovery/preview',{'provider':'club','platform':'youtube','topic':'strategy'})[0],403)
        self.assertEqual(self.client.call('/api/discovery')[0],200)

if __name__=='__main__':unittest.main(verbosity=2)
