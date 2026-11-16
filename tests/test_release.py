"""Release boundaries: localization preserves data; English edits retain business rules."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from test_workbench import app, Client, QuietHandler
import discovery
import i18n


class LocalizationTest(unittest.TestCase):
    def test_translates_system_fields_but_preserves_business_information(self):
        source = {'name':'达人', 'notes':'合作审批', 'language':'中文', 'fit_note':'可提交决策',
                  'format':'长视频', 'goal':'愿望单', 'assessment':{'label':'可提交决策','blockers':['档期未确认']},
                  'events':[{'action':'comment','note':'合作审批'}],
                  'response':{'format':'长视频','error':'未确认'}}
        original = copy.deepcopy(source)
        localized = i18n.localize_payload(source)
        self.assertEqual(localized['format'], 'Long video')
        self.assertEqual(localized['goal'], 'Wishlists')
        self.assertEqual(localized['assessment']['blockers'], ['Availability unconfirmed'])
        for key in ('name','notes','language','fit_note','events','response'):
            self.assertEqual(localized[key], source[key])
        self.assertEqual(source, original)

    def test_generated_assets_match_catalog(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'scripts/build_locales.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_existing_diagnostics_have_english_translations(self):
        source = {'error': '总预算 必须是有效数值。', 'reason': '最多导入 500 条达人。'}
        self.assertNotRegex(i18n.localize_payload(source)['error'], '[\u3400-\u9fff]')


class EnglishFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DATA = Path(self.tmp.name)
        app.init_db()
        self.httpd = app.ThreadingHTTPServer(('127.0.0.1',0), QuietHandler)
        self.httpd.local_user_id = app.ensure_local_user()
        self.httpd.failed_logins = []
        self.httpd.discovery = discovery.DiscoveryManager(request=lambda *args: {})
        self.httpd.discovery.keys = {'club':'','nox':''}
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.httpd.server_port)
        self.client.call('/api/bootstrap')
        self.headers = {'X-KOL-Language':'en'}

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(); self.tmp.cleanup()

    def test_english_create_edit_csv_report_and_chinese_roundtrip(self):
        p = {'name':'合作审批', 'game':'中文游戏', 'market':'Germany', 'language':'English',
             'goal':'Wishlists', 'format':'Long video', 'budget':2000, 'currency':'USD'}
        status, result = self.client.call('/api/projects',p,headers=self.headers)
        self.assertEqual(status,201,result)
        route = '/api/projects/'+result['id']
        status, data = self.client.call(route,headers=self.headers)
        self.assertEqual(data['project']['goal'],'Wishlists')
        self.assertEqual(data['project']['name'],'合作审批')
        data['project']['notes']='达人'
        self.assertEqual(self.client.call(route,data['project'],'PATCH',self.headers)[0],200)
        zh = self.client.call(route)[1]['project']
        self.assertEqual(zh['format'],'长视频'); self.assertEqual(zh['notes'],'达人')
        csv = 'name,platform,account_id,format\nCreator,YouTube,channel-1,Long video\n'
        self.assertEqual(self.client.call(route+'/import',{'csv':csv},headers=self.headers)[0],200)
        data = self.client.call(route,headers=self.headers)[1]
        d = data['candidates'][0]
        self.assertEqual(d['format'],'Long video')
        self.assertTrue(d['assessment']['blockers'])
        self.assertNotRegex(' '.join(d['assessment']['blockers']),'[\u3400-\u9fff]')
        d['fit_note']='合作审批'
        self.assertEqual(self.client.call('/api/candidates/'+d['id'],d,'PATCH',self.headers)[0],200)
        report = self.client.call(route+'/report?lang=en')[1]
        self.assertIn('Creator partnership decision report',report)
        self.assertIn('中文游戏',report)
        self.assertIn('合作审批',report)
        self.assertNotIn('预算：',report)
        exported = self.client.call(route+'/export?lang=en')[1]
        self.assertIn('Long video',exported)
        self.assertIn('Availability unconfirmed',exported)

    def test_health_assets_errors_and_csv_injection(self):
        self.assertEqual(self.client.call('/api/health')[1]['app'],'kol-desk')
        for path in ('/locale.js','/en/app.js','/en/discovery.js'):
            self.assertEqual(self.client.call(path)[0],200)
        status, error = self.client.call('/api/discovery/preview',{'provider':'club','platform':'youtube','topic':'strategy'},headers=self.headers)
        self.assertEqual(status,400)
        self.assertIn('Connect a creator database',error['error'])
        self.assertEqual(app.csv_safe(' =HYPERLINK("x")'),'\' =HYPERLINK("x")')


class PricingTest(unittest.TestCase):
    def test_unknown_pricing_and_account_fields_do_not_leak(self):
        m = discovery.DiscoveryManager(request=lambda *args: {'data':None})
        m.configure('nox','fake')
        with self.assertRaises(discovery.DiscoveryError): m.price('nox',5)
        m.request = lambda *args: {'data':{'items':[{'action':'creator_search','unit_credit':1,'standard_quantity':100}]}}
        with self.assertRaises(discovery.DiscoveryError): m.price('nox',5)
        m.request = lambda *args: {'email':'private@example.com','credits':20}
        self.assertEqual(set(m.check('nox')),{'verified_at'})
        with self.assertRaises(discovery.DiscoveryError): m.check(['invalid'])

if __name__ == '__main__':
    unittest.main()
