#!/usr/bin/env python3
"""KOL Desk: local decision workspace, with optional account login. Python 3.9+, stdlib only."""
import argparse
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import sqlite3
import time
import threading
import webbrowser
import discovery
import i18n
from reports import decision_report_en
from contextlib import contextmanager
from datetime import datetime, timezone, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('KOL_DATA_DIR', str(ROOT / 'data')))
ROLES = {'admin', 'editor', 'reviewer'}
FORMATS = ['长视频', '短视频', '直播', '图文']
PLATFORMS = ['YouTube', 'TikTok', 'Twitch', 'Instagram', 'Bilibili', '其他']
GOALS = ['愿望单', '安装激活', '有效曝光', '留存玩家']
SESSION_SECONDS = 24 * 60 * 60
CSV_FIELDS = ['name', 'platform', 'account_id', 'profile_url', 'language', 'content_genre',
              'format', 'audience_market', 'audience_pct', 'audience_source', 'fit_note',
              'fee', 'currency', 'deliverables', 'source_url']


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def uid():
    return secrets.token_hex(12)


@contextmanager
def db(write=False):
    conn = sqlite3.connect(str(DATA / 'workspace.sqlite3'), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            identity_key TEXT NOT NULL, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            selected INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'draft',
            approved_version INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(project_id, identity_key));
        CREATE TABLE IF NOT EXISTS discovery_runs (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
            credential_hash TEXT NOT NULL, data TEXT NOT NULL, raw TEXT);
        CREATE TABLE IF NOT EXISTS discovery_links (
            project_id TEXT NOT NULL REFERENCES projects(id), source_key TEXT NOT NULL,
            candidate_id TEXT NOT NULL REFERENCES candidates(id), PRIMARY KEY(project_id,source_key));
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id),
            candidate_id TEXT, user_id TEXT NOT NULL REFERENCES users(id),
            action TEXT NOT NULL, note TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')


def ensure_local_user():
    with db(True) as c:
        row = c.execute("SELECT id FROM users WHERE username='__local_workspace__'").fetchone()
        if row:
            return row['id']
        user_id = uid()
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)', (user_id, '本地工作台', '__local_workspace__', password_hash(secrets.token_urlsafe(48)), 'admin', now()))
        return user_id


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise Problem('密码请使用 10–256 个字符。')
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex()
    return salt + ':' + digest


def password_ok(password, encoded):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        return False
    salt = encoded.split(':', 1)[0]
    return hmac.compare_digest(password_hash(password, salt), encoded)


def text(value, field, limit=4000, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise Problem(f'{field} 必须是文字。')
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise Problem(f'{field} 不能为空或超过 {limit} 字。')
    return value


def number(value, field, optional=True, max_value=1e12):
    if value is None or value == '':
        if optional:
            return None
        raise Problem(f'请填写{field}。')
    if isinstance(value, bool):
        raise Problem(f'{field} 必须是有效数值。')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise Problem(f'{field} 必须是有效数值。')
    if not math.isfinite(value) or value < 0 or value > max_value:
        raise Problem(f'{field} 超出有效范围。')
    return round(value, 6)


def boolean(value, field, default=False):
    if value is None:
        return default
    if not isinstance(value, bool):
        raise Problem(f'{field} 必须是布尔值。')
    return value


def choice(value, options, field, default=None):
    value = i18n.canonical_option(value or default, options)
    if value not in options:
        raise Problem(f'{field} 的选项无效。')
    return value


def link(value, field):
    value = text(value, field, 2000)
    if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
        raise Problem(f'{field} 请使用完整的 http/https 链接。')
    return value


def day(value, field):
    value = text(value, field, 10)
    if value:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise Problem(f'{field} 日期无效。')
    return value


def project_data(d):
    if not isinstance(d, dict):
        raise Problem('项目数据格式无效。')
    return {
        'name': text(d.get('name'), '项目名称', 120, True),
        'game': text(d.get('game'), '游戏名称', 120, True),
        'genre': text(d.get('genre'), '游戏品类', 120),
        'market': text(d.get('market'), '目标市场', 120, True),
        'language': text(d.get('language'), '内容语言', 120),
        'goal': choice(d.get('goal'), GOALS, '项目目标', '愿望单'),
        'format': choice(d.get('format'), FORMATS, '合作形式', '长视频'),
        'currency': choice(d.get('currency'), ['USD', 'EUR', 'CNY', 'GBP', 'JPY'], '币种', 'USD'),
        'budget': number(d.get('budget'), '总预算', False),
        'launch_date': day(d.get('launch_date'), '上线日期'),
        'min_audience_pct': number(d.get('min_audience_pct'), '目标受众最低占比', True, 100),
        'require_audience': boolean(d.get('require_audience'), '受众证据', True),
        'require_paid_rights': boolean(d.get('require_paid_rights'), '广告投放权'),
        'notes': text(d.get('notes'), '项目要求'),
        'is_demo': boolean(d.get('is_demo'), '示例标记'),
    }


def candidate_data(d, source_ref=None):
    if not isinstance(d, dict):
        raise Problem('达人数据格式无效。')
    q = d.get('quote') or {}
    if not isinstance(q, dict):
        raise Problem('报价数据格式无效。')
    result = {
        'name': text(d.get('name'), '达人名称', 120, True),
        'platform': choice(d.get('platform'), PLATFORMS, '平台', 'YouTube'),
        'account_id': text(d.get('account_id'), '平台账号 ID', 200),
        'profile_url': link(d.get('profile_url'), '主页链接'),
        'language': text(d.get('language'), '内容语言', 100),
        'content_genre': text(d.get('content_genre'), '内容品类', 200),
        'format': choice(d.get('format'), FORMATS, '合作形式', '长视频'),
        'followers': number(d.get('followers'), '粉丝数'),
        'audience_market': text(d.get('audience_market'), '受众市场', 120),
        'audience_pct': number(d.get('audience_pct'), '受众占比', True, 100),
        'audience_source': text(d.get('audience_source'), '受众依据', 2000),
        'audience_verified': boolean(d.get('audience_verified'), '人工核验受众'),
        'fit': choice(d.get('fit'), ['unknown', 'match', 'mismatch'], '玩家匹配', 'unknown'),
        'fit_note': text(d.get('fit_note'), '匹配依据'),
        'source_url': link(d.get('source_url'), '代表内容链接'),
        'evidence_date': day(d.get('evidence_date'), '证据日期'),
        'evidence_note': text(d.get('evidence_note'), '内容样本说明'),
        'availability': choice(d.get('availability'), ['unknown', 'confirmed', 'unavailable'], '档期', 'unknown'),
        'exclusivity': choice(d.get('exclusivity'), ['unknown', 'clear', 'conflict'], '排他状态', 'unknown'),
        'terms_note': text(d.get('terms_note'), '条款与核验记录'),
        'owner_id': text(d.get('owner_id'), '负责人', 100),
        'next_action': text(d.get('next_action'), '下一步', 1000),
        'due_date': day(d.get('due_date'), '待办日期'),
        'quote': {
            'currency': choice(q.get('currency'), ['USD', 'EUR', 'CNY', 'GBP', 'JPY'], '报价币种', 'USD'),
            **{k: number(q.get(k), title) for k, title in [
                ('fee', '达人费'), ('usage', '授权费'), ('exclusivity_fee', '排他费'),
                ('production', '制作及本地化费'), ('tax', '税费/代理/支付费'), ('bonus_cap', '绩效奖金上限')]},
            'deliverables': text(q.get('deliverables'), '交付范围', 2000),
            'payment': text(q.get('payment'), '付款与取消条件', 2000),
            'rights': text(q.get('rights'), '素材权利范围', 2000),
            'paid_rights': choice(q.get('paid_rights'), ['unknown', 'included', 'not_included'], '付费投放授权', 'unknown'),
            'cost_complete': boolean(q.get('cost_complete'), '费用完整性'),
            'confirmed': boolean(q.get('confirmed'), '已核对报价范围'),
            'quoted_at': day(q.get('quoted_at'), '报价日期'),
            'valid_until': day(q.get('valid_until'), '报价有效期'),
            'expected_views': number(q.get('expected_views'), '情景预期播放'),
            'expected_actions': number(q.get('expected_actions'), '情景预期目标行为'),
            'forecast_basis': text(q.get('forecast_basis'), '预测依据与窗口', 2000),
        },
    }
    if source_ref:
        result['source_ref'] = source_ref
    if not result['account_id'] and not result['profile_url'] and not source_ref:
        raise Problem('至少填写平台账号 ID 或主页链接，以免把同名达人误合并。')
    return result


def identity(d):
    # Handles/IDs can be case sensitive. Never deduplicate by display name.
    if d['account_id']:
        return d['platform'] + ':id:' + d['account_id']
    if not d['profile_url'] and d.get('source_ref'):
        return d['platform'] + ':source:' + d['source_ref']['provider'] + ':' + d['source_ref']['provider_id']
    p = urlparse(d['profile_url'])
    return d['platform'] + ':url:' + p.netloc.lower() + p.path.rstrip('/')


def event(c, project_id, candidate_id, user_id, action, note, snapshot):
    c.execute('INSERT INTO events(project_id,candidate_id,user_id,action,note,snapshot,created_at) VALUES(?,?,?,?,?,?,?)',
              (project_id, candidate_id, user_id, action, note, json.dumps(snapshot, ensure_ascii=False), now()))


def get_project(c, project_id):
    row = c.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
    if not row:
        raise Problem('项目不存在。', 404)
    return {**json.loads(row['data']), 'id': row['id'], 'version': row['version'], 'updated_at': row['updated_at']}


def get_candidate(c, candidate_id):
    row = c.execute('SELECT * FROM candidates WHERE id=?', (candidate_id,)).fetchone()
    if not row:
        raise Problem('达人记录不存在。', 404)
    return {**json.loads(row['data']), 'id': row['id'], 'project_id': row['project_id'],
            'version': row['version'], 'selected': bool(row['selected']), 'state': row['state'],
            'approved_version': row['approved_version'], 'updated_at': row['updated_at']}


def assess(d, p):
    q = d['quote']
    fields = ['fee', 'usage', 'exclusivity_fee', 'production', 'tax', 'bonus_cap']
    known = round(sum(q[k] for k in fields if q[k] is not None), 2)
    fixed = sum(q[k] for k in fields[:-1] if q[k] is not None)
    complete = q['cost_complete'] and all(q[k] is not None for k in fields)
    blockers, warnings = [], []
    if d['fit'] != 'match':
        blockers.append('玩家匹配尚未确认' if d['fit'] == 'unknown' else '玩家匹配不满足项目要求')
    elif not d['fit_note'] or not d['source_url'] or not d['evidence_date']:
        blockers.append('匹配判断缺少依据、内容链接或证据日期')
    if d['format'] != p['format']:
        blockers.append('合作形式与项目不一致')
    if p['language'] and d['language'].casefold() != p['language'].casefold():
        blockers.append('内容语言与项目要求不一致或未知')
    if p['require_audience'] or p['min_audience_pct'] is not None:
        if not d['audience_verified'] or not d['audience_source'] or d['audience_pct'] is None:
            blockers.append('目标受众数据缺失或未经人工核验')
        elif d['audience_market'].casefold() != p['market'].casefold():
            blockers.append('受众数据市场与目标市场不一致')
        elif p['min_audience_pct'] is not None and d['audience_pct'] < p['min_audience_pct']:
            blockers.append('目标受众占比未达到项目门槛')
    elif not d['audience_verified']:
        warnings.append('受众构成未核实，当前项目未设为硬性条件')
    if d['availability'] != 'confirmed':
        blockers.append('档期不可用' if d['availability'] == 'unavailable' else '档期未确认')
    if d['exclusivity'] != 'clear':
        blockers.append('存在排他冲突' if d['exclusivity'] == 'conflict' else '排他条款未核实')
    if not d['terms_note']:
        blockers.append('档期与排他缺少核验记录')
    if q['currency'] != p['currency']:
        blockers.append('报价与预算币种不同，需先确认换汇后的报价')
    if not complete:
        blockers.append('费用范围未完整确认；空白费用不按零处理')
    if not q['confirmed'] or not q['deliverables'] or not q['payment'] or not q['rights'] or not q['quoted_at']:
        blockers.append('交付、付款、素材权利或报价依据未完整确认')
    if q['valid_until'] and q['valid_until'] < date.today().isoformat():
        blockers.append('报价已过有效期')
    if p['require_paid_rights'] and q['paid_rights'] != 'included':
        blockers.append('项目所需付费投放权尚未确认包含')
    if q['currency'] == p['currency'] and known > p['budget']:
        blockers.append('已知最高承诺费用超过项目总预算')
    if not q['valid_until']:
        warnings.append('报价未注明有效期，采购前应复核')
    if not q['forecast_basis'] and (q['expected_views'] is not None or q['expected_actions'] is not None):
        warnings.append('情景预期缺少依据，未据此计算效率')
    max_cost = round(known, 2) if complete else None
    cpv = (max_cost / q['expected_views']) if complete and q['forecast_basis'] and q['expected_views'] else None
    cpa = (max_cost / q['expected_actions']) if complete and q['forecast_basis'] and q['expected_actions'] else None
    return {'blockers': blockers, 'warnings': warnings, 'ready': not blockers, 'known_cost': round(known, 2),
            'fixed_cost': round(fixed, 2), 'max_cost': max_cost, 'cost_complete': complete,
            'forecast_cpv': cpv, 'forecast_cpa': cpa,
            'label': '可提交决策' if not blockers else ('条件不满足' if d['fit'] == 'mismatch' or d['exclusivity'] == 'conflict' or d['availability'] == 'unavailable' else '待补证据/条款')}


def project_detail(c, project_id):
    p = get_project(c, project_id)
    candidates = []
    for row in c.execute('SELECT id FROM candidates WHERE project_id=? ORDER BY created_at,rowid', (project_id,)):
        item = get_candidate(c, row['id'])
        item['assessment'] = assess(item, p)
        candidates.append(item)
    selected = [d for d in candidates if d['selected'] or d['state'] == 'approved']
    known_cost = round(sum(d['assessment']['known_cost'] for d in selected if d['quote']['currency'] == p['currency']), 2)
    comparable = all(d['quote']['currency'] == p['currency'] and d['assessment']['cost_complete'] for d in selected)
    summary = {
        'total': len(candidates), 'ready': sum(d['assessment']['ready'] for d in candidates),
        'pending': sum(d['state'] == 'pending' for d in candidates),
        'approved': sum(d['state'] == 'approved' for d in candidates),
        'selected_count': len(selected), 'known_selected_cost': round(known_cost, 2),
        'selection_complete': comparable, 'selected_max_cost': round(known_cost, 2) if comparable else None,
        'remaining': round(p['budget'] - known_cost, 2) if comparable else None,
        'over_budget': known_cost > p['budget'],
    }
    logs = [dict(r) for r in c.execute('SELECT e.id,e.candidate_id,e.action,e.note,e.created_at,e.snapshot,u.name AS user_name FROM events e JOIN users u ON u.id=e.user_id WHERE e.project_id=? ORDER BY e.id DESC LIMIT 250', (project_id,))]
    for log in logs:
        log['snapshot'] = json.loads(log['snapshot'])
    return {'project': p, 'candidates': candidates, 'summary': summary, 'events': logs}


def add_candidate(c, project_id, d, user_id):
    cid = uid()
    try:
        c.execute('INSERT INTO candidates(id,project_id,identity_key,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                  (cid, project_id, identity(d), json.dumps(d, ensure_ascii=False), now(), now()))
    except sqlite3.IntegrityError:
        raise Problem('此项目已存在相同平台账号。导入或新增不会覆盖原记录。', 409)
    event(c, project_id, cid, user_id, 'created', '加入候选池', d)
    return cid


def import_preview(c, project_id, body):
    p = get_project(c, project_id)
    raw = body.get('csv')
    if not isinstance(raw, str) or len(raw) > 1_500_000:
        raise Problem('名单文件为空或超过 1.5 MB，请检查后重新上传。')
    reader = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')))
    if not reader.fieldnames or not {'name', 'platform'}.issubset(reader.fieldnames):
        raise Problem('名单缺少达人名称或平台列，请下载模板填写并保留原表头。')
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise Problem('名单中有重复的表头，请先修正。')
    known = {r[0] for r in c.execute('SELECT identity_key FROM candidates WHERE project_id=?', (project_id,))}
    accepted, errors, duplicates = [], [], []
    for index, row in enumerate(reader, 2):
        if index > 501:
            raise Problem('每次最多导入 500 条达人。')
        try:
            if None in row:
                raise Problem('列数与表头不一致。')
            item = candidate_data({**row, 'format': row.get('format') or p['format'],
                                   'quote': {'fee': row.get('fee'), 'currency': row.get('currency') or p['currency'],
                                             'deliverables': row.get('deliverables')}})
            key = identity(item)
            if key in known:
                duplicates.append({'row': index, 'name': item['name'], 'reason': '相同平台账号，保留既有记录'})
                continue
            known.add(key)
            accepted.append(item)
        except Problem as exc:
            errors.append({'row': index, 'name': row.get('name', ''), 'reason': exc.message})
    return {'records': accepted, 'errors': errors, 'duplicates': duplicates,
            'unmapped_columns': [x for x in reader.fieldnames if x not in CSV_FIELDS], 'count': len(accepted)}


def csv_safe(value):
    s = '' if value is None else str(value)
    return "'" + s if s.lstrip().startswith(('=', '+', '-', '@')) else s


def decision_report(data, user):
    p, s = data['project'], data['summary']
    def md(value):
        return str(value).replace('|', '\\|').replace('\n', ' / ').replace('\r', '')
    lines = [f"# {p['name']} · KOL 决策报告", '', f"导出：{now()} · 操作人：{user['name']}",
             '', f"游戏：{p['game']}；市场：{p['market']}；目标：{p['goal']}；形式：{p['format']}。",
             f"预算：{p['currency']} {p['budget']:,.2f}。费用按最高承诺范围比较，包含已录入奖金上限。",
             f"目标受众最低占比：{p['min_audience_pct'] if p['min_audience_pct'] is not None else '未设置'}；需核验受众：{'是' if p['require_audience'] else '否'}；需要付费投放权：{'是' if p['require_paid_rights'] else '否'}。",
             f"组合：{s['selected_count']} 位；已知同币种费用 {p['currency']} {s['known_selected_cost']:,.2f}。" + ('组合成本已完整。' if s['selection_complete'] else '存在费用或币种缺口，不可视为完整预算。'),
             '', '内部批准仅记录本团队决策，不代表达人已接受或已经签约。情景效率是预测，不是实际投放结果。']
    if p['is_demo']:
        lines += ['', '**本项目为合成示例，不代表真实达人、报价或表现。**']
    for d in data['candidates']:
        a, q = d['assessment'], d['quote']
        lines += ['', f"## {md(d['name'])} · {d['platform']}", '',
                  f"状态：{d['state']}；记录版本：{d['version']}；是否入组合：{'是' if d['selected'] else '否'}。",
                  f"主页：{d['profile_url'] or d['account_id']}",
                  f"业务判断：{a['label']}。匹配依据：{d['fit_note'] or '未填写'}。",
                  f"内容证据：{d['source_url'] or '未填写'}；日期：{d['evidence_date'] or '未知'}；样本说明：{d['evidence_note'] or '未知'}。",
                  f"受众：{d['audience_market'] or '未知'}，占比 {d['audience_pct'] if d['audience_pct'] is not None else '未知'}%；核验：{'是' if d['audience_verified'] else '否'}；依据：{d['audience_source'] or '未填写'}。",
                  f"报价：{q['currency']}，已知金额 {a['known_cost']:,.2f}；最高承诺总价：{a['max_cost'] if a['max_cost'] is not None else '待补齐'}。",
                  f"交付：{q['deliverables'] or '未知'}；权利：{q['rights'] or '未知'}；付款：{q['payment'] or '未知'}。",
                  '费用明细：' + '；'.join(f"{title} {q['currency']} {q[key] if q[key] is not None else '未知'}" for title,key in [('达人费','fee'),('授权','usage'),('排他','exclusivity_fee'),('制作/本地化','production'),('税费/代理/支付','tax'),('奖金上限','bonus_cap')]) + '。',
                  f"报价日期：{q['quoted_at'] or '未知'}；有效期：{q['valid_until'] or '未约定'}；档期与排他依据：{d['terms_note'] or '未核实'}。",
                  f"情景预期播放：{q['expected_views'] if q['expected_views'] is not None else '未知'}；情景预期目标行为：{q['expected_actions'] if q['expected_actions'] is not None else '未知'}；情景 CPV：{a['forecast_cpv'] if a['forecast_cpv'] is not None else '未计算'}；情景目标行为成本：{a['forecast_cpa'] if a['forecast_cpa'] is not None else '未计算'}（均以 {q['currency']} 计价）。",
                  f"预测依据：{q['forecast_basis'] or '未提供，不能给出预测效率'}。",
                  f"阻断项：{'；'.join(a['blockers']) or '无已识别阻断项'}。",
                  f"提醒：{'；'.join(a['warnings']) or '无'}。",
                  f"下一步：{d['next_action'] or '待安排'}；期限：{d['due_date'] or '待定'}。"]
    lines += ['', '## 决策与变更记录', '']
    for e in reversed(data['events']):
        lines.append(f"- {e['created_at']} · {md(e['user_name'])} · {e['action']}：{md(e['note'])}")
    return '\n'.join(lines) + '\n'


def discovery_run(c, run_id):
    row = c.execute('SELECT status,data FROM discovery_runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise Problem('搜索记录不存在。', 404)
    return {**json.loads(row['data']), 'status': row['status']}


class Handler(BaseHTTPRequestHandler):
    server_version = 'KOLDesk/1.0'

    def log_message(self, fmt, *args):
        # No request body, credentials or session token is logged.
        super().log_message(fmt, *args)

    def response(self, data, status=200, content_type='application/json; charset=utf-8', extra=None):
        # Queue the reply until the transaction commits successfully.
        self.pending_response = (data, status, content_type, extra)

    def english_requested(self):
        return self.headers.get('X-KOL-Language') == 'en' or parse_qs(urlparse(self.path).query).get('lang') == ['en']

    def send_payload(self, data, status=200, content_type='application/json; charset=utf-8', extra=None):
        if self.english_requested() and content_type.startswith('application/json') and not (extra or {}).get('Content-Disposition'):
            data = i18n.localize_payload(data, getattr(self.server, 'local_user_id', None))
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if content_type.startswith('application/json') else (data.encode() if isinstance(data, str) else data)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            raise Problem('请求长度无效。')
        if length < 0 or length > 2_000_000:
            raise Problem('请求超过大小限制。', 413)
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError, UnicodeDecodeError):
            raise Problem('JSON 格式无效。')
        if not isinstance(body, dict):
            raise Problem('请求必须是对象。')
        return body

    def origin_check(self):
        # The server deliberately binds to loopback; Host checking also blocks DNS rebinding.
        host = self.headers.get('Host', '')
        if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            raise Problem('仅接受本机工作台地址。', 403)
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            raise Problem('跨站请求被拒绝。', 403)

    def auth(self, c):
        cookies = {}
        for part in self.headers.get('Cookie', '').split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                cookies[k] = v
        token = cookies.get('kol_session', '')
        key = hashlib.sha256(token.encode()).hexdigest()
        row = c.execute('SELECT u.id,u.name,u.username,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?', (key, time.time())).fetchone()
        if row and getattr(self.server, 'local_user_id', None) and row['id'] != self.server.local_user_id:
            return None
        return dict(row) if row else None

    def login_session(self, c, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.session_csrf = csrf
        c.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, time.time() + SESSION_SECONDS))
        return {'Set-Cookie': f'kol_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}'}

    def require_role(self, user, roles):
        if user['role'] not in roles:
            raise Problem('当前角色没有执行此操作的权限。', 403)

    def dispatch(self):
        self.origin_check()
        path = urlparse(self.path).path
        if not path.startswith('/api/'):
            if self.command != 'GET':
                raise Problem('不支持此请求。', 405)
            allowed = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/discovery.js': ('discovery.js', 'text/javascript; charset=utf-8'), '/locale.js': ('locale.js', 'text/javascript; charset=utf-8'), '/en/app.js': ('en/app.js', 'text/javascript; charset=utf-8'), '/en/discovery.js': ('en/discovery.js', 'text/javascript; charset=utf-8')}
            if path not in allowed:
                raise Problem('页面不存在。', 404)
            f, kind = allowed[path]
            return self.response((ROOT / 'static' / f).read_bytes(), content_type=kind)
        if path == '/api/health' and self.command == 'GET':
            return self.response({'app': 'kol-desk', 'version': '1.2.0'})
        write = self.command != 'GET'
        body = self.body() if write else {}
        if path.startswith('/api/discovery'):
            return self.discovery_dispatch(path, write, body)
        local_user_id = getattr(self.server, 'local_user_id', None)
        with db(write or (local_user_id and path == '/api/bootstrap')) as c:
            user = self.auth(c)
            count = c.execute("SELECT count(*) FROM users WHERE username!='__local_workspace__'").fetchone()[0]
            if local_user_id and path in ('/api/setup', '/api/login', '/api/logout', '/api/users', '/api/password'):
                raise Problem('当前为免登录本地模式，无需管理登录账号。', 403)
            if path == '/api/bootstrap' and not write:
                extra = None
                if local_user_id and not user:
                    extra = self.login_session(c, local_user_id)
                    user = dict(c.execute('SELECT id,name,username,role FROM users WHERE id=?', (local_user_id,)).fetchone())
                    user['csrf'] = self.session_csrf
                projects = [get_project(c, r[0]) for r in c.execute('SELECT id FROM projects ORDER BY updated_at DESC')] if user else []
                users = [dict(r) for r in c.execute('SELECT id,name,username,role FROM users ORDER BY created_at')] if user else []
                return self.response({'needs_setup': count == 0 and not local_user_id, 'local_mode': bool(local_user_id), 'user': user, 'projects': projects, 'users': users}, extra=extra)
            if path == '/api/setup' and self.command == 'POST':
                if count:
                    raise Problem('管理员已创建，请登录。', 409)
                name = text(body.get('name'), '姓名', 80, True)
                username = text(body.get('username'), '登录名', 80, True).lower()
                if not re.fullmatch(r'[a-z0-9_.-]{3,80}', username):
                    raise Problem('登录名请使用至少 3 位英文、数字、点、横线或下划线。')
                user_id = uid()
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)', (user_id, name, username, password_hash(body.get('password')), 'admin', now()))
                return self.response({'ok': True}, extra=self.login_session(c, user_id))
            if path == '/api/login' and self.command == 'POST':
                # Bounded in-memory throttling; no credentials retained.
                recent = [t for t in self.server.failed_logins if t > time.time() - 60]
                self.server.failed_logins = recent
                if len(recent) >= 10:
                    raise Problem('尝试次数过多，请一分钟后重试。', 429)
                row = c.execute('SELECT * FROM users WHERE username=?', (text(body.get('username'), '登录名', 80).lower(),)).fetchone()
                if not row or row['username'] == '__local_workspace__' or not password_ok(body.get('password'), row['password']):
                    self.server.failed_logins.append(time.time())
                    raise Problem('登录名或密码不正确。', 401)
                return self.response({'ok': True}, extra=self.login_session(c, row['id']))
            if not user:
                raise Problem('请先登录。', 401)
            if write and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
                raise Problem('会话校验失败，请刷新后重试。', 403)
            if path == '/api/logout' and self.command == 'POST':
                c.execute('DELETE FROM sessions WHERE user_id=? AND csrf=?', (user['id'], user['csrf']))
                return self.response({'ok': True}, extra={'Set-Cookie': 'kol_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
            if path == '/api/users' and self.command == 'POST':
                self.require_role(user, {'admin'})
                username = text(body.get('username'), '登录名', 80, True).lower()
                if not re.fullmatch(r'[a-z0-9_.-]{3,80}', username):
                    raise Problem('登录名需为至少 3 位英文或数字，可含 . _ -。')
                try:
                    c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)', (uid(), text(body.get('name'), '姓名', 80, True), username, password_hash(body.get('password')), choice(body.get('role'), ROLES, '角色'), now()))
                except sqlite3.IntegrityError:
                    raise Problem('该登录名已存在。', 409)
                return self.response({'ok': True})
            if path == '/api/password' and self.command == 'POST':
                row = c.execute('SELECT password FROM users WHERE id=?', (user['id'],)).fetchone()
                if not password_ok(body.get('old_password'), row[0]):
                    raise Problem('原密码不正确。', 403)
                c.execute('UPDATE users SET password=? WHERE id=?', (password_hash(body.get('new_password')), user['id']))
                c.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
                return self.response({'ok': True}, extra=self.login_session(c, user['id']))
            if path == '/api/csv-template' and not write:
                buf = io.StringIO()
                csv.writer(buf).writerow(CSV_FIELDS)
                return self.response('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8', extra={'Content-Disposition': 'attachment; filename="kol-import-template.csv"'})
            if path == '/api/projects' and self.command == 'POST':
                self.require_role(user, {'admin', 'editor'})
                p, pid = project_data(body), uid()
                c.execute('INSERT INTO projects(id,data,created_by,created_at,updated_at) VALUES(?,?,?,?,?)', (pid, json.dumps(p, ensure_ascii=False), user['id'], now(), now()))
                event(c, pid, None, user['id'], 'project_created', '创建项目与决策条件', p)
                return self.response({'id': pid}, 201)
            if path == '/api/demo' and self.command == 'POST':
                self.require_role(user, {'admin', 'editor'})
                return self.response({'id': make_demo(c, user['id'])}, 201)
            match = re.fullmatch(r'/api/projects/([a-f0-9]+)/?(candidates|import-preview|import|export|report)?', path)
            if match:
                pid, action = match.groups()
                p = get_project(c, pid)
                if not action and not write:
                    return self.response(project_detail(c, pid))
                if not action and self.command == 'PATCH':
                    self.require_role(user, {'admin', 'editor'})
                    if body.get('version') != p['version']:
                        raise Problem('项目已被其他成员修改，请刷新后重试。', 409)
                    clean = project_data(body)
                    c.execute('UPDATE projects SET data=?,version=version+1,updated_at=? WHERE id=?', (json.dumps(clean, ensure_ascii=False), now(), pid))
                    c.execute("UPDATE candidates SET state='pending',approved_version=NULL,version=version+1,updated_at=? WHERE project_id=? AND state IN ('approved','pending')", (now(), pid))
                    event(c, pid, None, user['id'], 'project_updated', '项目条件已变更，原批准记录转为待复核', {'before': p, 'after': clean})
                    return self.response({'ok': True})
                if action == 'candidates' and self.command == 'POST':
                    self.require_role(user, {'admin', 'editor'})
                    d = candidate_data(body)
                    self.check_owner(c, d)
                    return self.response({'id': add_candidate(c, pid, d, user['id'])}, 201)
                if action in ('import-preview', 'import') and self.command == 'POST':
                    self.require_role(user, {'admin', 'editor'})
                    preview = import_preview(c, pid, body)
                    if action == 'import-preview':
                        return self.response(preview)
                    if preview['errors']:
                        raise Problem('仍有无效行，请修正后导入；未写入任何记录。')
                    ids = [add_candidate(c, pid, d, user['id']) for d in preview['records']]
                    return self.response({'count': len(ids), 'skipped': len(preview['duplicates'])})
                if action == 'report' and not write:
                    report_data = project_detail(c, pid)
                    report = decision_report_en(report_data, user, now()) if self.english_requested() else decision_report(report_data, user)
                    return self.response(report, content_type='text/markdown; charset=utf-8', extra={'Content-Disposition': 'attachment; filename="kol-decision-report.md"'})
                if action == 'export' and not write:
                    data = project_detail(c, pid)
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    headers = CSV_FIELDS + ['state', 'selected', 'known_cost', 'max_cost', 'blockers']
                    writer.writerow(headers)
                    for d in data['candidates']:
                        flat = {**d, 'fee': d['quote']['fee'], 'currency': d['quote']['currency'], 'deliverables': d['quote']['deliverables'], **d['assessment']}
                        if self.english_requested():
                            flat['format'] = i18n.english(flat['format'])
                            flat['platform'] = i18n.english(flat['platform'])
                            flat['blockers'] = [i18n.english(x) for x in flat['blockers']]
                        flat['blockers'] = '; '.join(flat['blockers'])
                        writer.writerow([csv_safe(flat.get(k)) for k in headers])
                    return self.response('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8', extra={'Content-Disposition': 'attachment; filename="kol-candidates.csv"'})
            match = re.fullmatch(r'/api/candidates/([a-f0-9]+)(?:/(select|submit|review|comment))?', path)
            if match and write:
                cid, action = match.groups()
                if action and self.command != 'POST':
                    raise Problem('此操作必须使用 POST。', 405)
                old = get_candidate(c, cid)
                pid, p = old['project_id'], get_project(c, old['project_id'])
                if body.get('version') != old['version'] and action != 'comment':
                    raise Problem('此记录已被其他成员修改，请刷新后再操作。', 409)
                if not action and self.command == 'PATCH':
                    self.require_role(user, {'admin', 'editor'})
                    clean = candidate_data(body, source_ref=old.get('source_ref'))
                    self.check_owner(c, clean)
                    state = 'pending' if old['state'] in ('approved', 'pending') else 'draft'
                    try:
                        c.execute('UPDATE candidates SET data=?,identity_key=?,version=version+1,state=?,approved_version=NULL,updated_at=? WHERE id=?', (json.dumps(clean, ensure_ascii=False), identity(clean), state, now(), cid))
                    except sqlite3.IntegrityError:
                        raise Problem('修改后的账号与项目中另一条记录重复。', 409)
                    event(c, pid, cid, user['id'], 'updated', '更新证据或合作条件；如有原审批，须重新确认', {'before': old, 'after': clean})
                    return self.response({'ok': True})
                if action == 'select':
                    self.require_role(user, {'admin', 'editor'})
                    selected = boolean(body.get('selected'), '组合选择')
                    if old['state'] == 'approved' and not selected:
                        raise Problem('已批准的合作仍占用预算。请先由审批人退回或撤销批准，再移出组合。', 409)
                    if selected == old['selected']:
                        return self.response({'ok': True})
                    c.execute('UPDATE candidates SET selected=?,version=version+1,updated_at=? WHERE id=?', (int(selected), now(), cid))
                    event(c, pid, cid, user['id'], 'selected', '加入组合' if selected else '移出组合', {'selected': selected})
                    return self.response({'ok': True})
                if action == 'submit':
                    self.require_role(user, {'admin', 'editor'})
                    if old['state'] == 'approved':
                        raise Problem('当前版本已经批准。', 409)
                    c.execute("UPDATE candidates SET state='pending',selected=1,version=version+1,approved_version=NULL,updated_at=? WHERE id=?", (now(), cid))
                    event(c, pid, cid, user['id'], 'submitted', '提交内部合作决策', old)
                    return self.response({'ok': True})
                if action == 'review':
                    self.require_role(user, {'admin', 'reviewer'})
                    verdict = choice(body.get('verdict'), ['approve', 'changes', 'reject'], '审批结果')
                    note = text(body.get('note'), '决策理由', 3000, True)
                    combination = None
                    if verdict == 'approve':
                        if old['state'] != 'pending':
                            raise Problem('只能批准已提交且待审批的记录。', 409)
                        if not old['selected']:
                            raise Problem('请先重新提交，将此达人加入预算组合后再审批。')
                        a = assess(old, p)
                        if a['blockers']:
                            raise Problem('不能批准：' + '；'.join(a['blockers']))
                        detail = project_detail(c, pid)
                        if not detail['summary']['selection_complete']:
                            raise Problem('组合内存在费用缺失或币种不一致，请先补齐或移出未确定候选。')
                        combination = {'summary': detail['summary'], 'candidates': [d for d in detail['candidates'] if d['selected'] or d['state'] == 'approved']}
                        if detail['summary']['over_budget']:
                            raise Problem('组合最高承诺总成本超过预算，请先调整组合。')
                    state = {'approve': 'approved', 'changes': 'changes', 'reject': 'rejected'}[verdict]
                    version = old['version'] + 1
                    c.execute('UPDATE candidates SET state=?,version=?,approved_version=?,updated_at=? WHERE id=?', (state, version, version if verdict == 'approve' else None, now(), cid))
                    event(c, pid, cid, user['id'], 'review_' + verdict, note, {'record': old, 'project': p, 'verdict': verdict, 'combination': combination})
                    return self.response({'ok': True})
                if action == 'comment':
                    note = text(body.get('note'), '讨论内容', 3000, True)
                    event(c, pid, cid, user['id'], 'comment', note, {'candidate_name': old['name']})
                    return self.response({'ok': True})
            raise Problem('接口不存在或请求方式不支持。', 404)

    def discovery_dispatch(self, path, write, body):
        manager = self.server.discovery
        with db() as c:
            user = self.auth(c)
        if not user:
            raise Problem('请刷新工作台后重试。', 401)
        if write and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
            raise Problem('会话校验失败，请刷新后重试。', 403)
        if write and self.command != 'POST':
            raise Problem('此操作必须使用 POST。', 405)
        if path == '/api/discovery' and not write:
            with db() as c:
                recent = [discovery_run(c, r[0]) for r in c.execute('SELECT id FROM discovery_runs ORDER BY rowid DESC LIMIT 25')]
            return self.response({'providers': manager.status(), 'runs': recent})
        if path == '/api/discovery/config' and write:
            self.require_role(user, {'admin'})
            return self.response({'providers': manager.configure(body.get('provider'), body.get('key'))})
        if path == '/api/discovery/check' and write:
            self.require_role(user, {'admin'})
            # Quota inspection only; never runs a search or unlocks creator detail.
            return self.response(manager.check(body.get('provider')))
        if path == '/api/discovery/preview' and write:
            self.require_role(user, {'admin', 'editor'})
            page, cursor = 1, None
            with db() as c:
                if body.get('parent_id'):
                    previous = discovery_run(c, body['parent_id'])
                    if previous['status'] != 'done' or not previous['more_available']:
                        raise Problem('这次搜索暂时没有更多达人可查看。')
                    query, page, cursor = previous['query'], previous['page'] + 1, previous['next_cursor']
                else:
                    query = discovery.query_data(body)
            payload = discovery.request_body(query, page, cursor)
            key_fingerprint = manager.fingerprint(query['provider'])
            price = manager.price(query['provider'], query['limit'], key_fingerprint)
            rid = uid()
            plan = {'id': rid, 'query': query, 'page': page, 'payload': payload, 'price': price,
                    'prepared_at': time.time(), 'created_at': now(), 'items': [], 'next_cursor': None,
                    'more_available': False, 'total': None, 'error': None, 'fetched_at': None}
            with db(True) as c:
                c.execute('INSERT INTO discovery_runs(id,user_id,status,credential_hash,data) VALUES(?,?,?,?,?)',
                          (rid, user['id'], 'prepared', key_fingerprint, json.dumps(plan, ensure_ascii=False)))
            return self.response({**plan, 'status': 'prepared'})
        match = re.fullmatch(r'/api/discovery/runs/([a-f0-9]+)(?:/(execute|import|raw))?', path)
        if not match:
            raise Problem('搜索接口不存在。', 404)
        rid, action = match.groups()
        if not action and not write:
            with db() as c:
                return self.response(discovery_run(c, rid))
        if action == 'raw' and not write:
            with db() as c:
                row = c.execute('SELECT raw,data FROM discovery_runs WHERE id=?', (rid,)).fetchone()
                if not row:
                    raise Problem('找不到这次搜索记录。', 404)
                if not row['raw']:
                    raise Problem('这次搜索还没有可下载的留档。', 404)
                saved = json.loads(row['data'])
                data = {'query': saved['query'], 'payload': saved['payload'], 'fetched_at': saved['fetched_at'], 'response': json.loads(row['raw'])}
            return self.response(data, extra={'Content-Disposition': 'attachment; filename="creator-search-evidence.json"'})
        if action == 'execute' and write:
            self.require_role(user, {'admin', 'editor'})
            if body.get('accept_cost') is not True:
                raise Problem('请先确认本次找达人的条件和服务积分。')
            with db(True) as c:
                row = c.execute('SELECT * FROM discovery_runs WHERE id=?', (rid,)).fetchone()
                if not row:
                    raise Problem('找不到这次搜索记录。', 404)
                if row['user_id'] != user['id']:
                    raise Problem('请由准备这次搜索的同事确认开始，或重新填写搜索条件。', 403)
                run = discovery_run(c, rid)
                if row['status'] == 'done':
                    return self.response(run)  # Browser retry reads the saved result, never charges again.
                if row['status'] != 'prepared':
                    raise Problem('这次搜索已经开始或结束，请在“找过的名单”中查看进度。不会自动再次搜索或扣积分。', 409)
                if time.time() - run['prepared_at'] > 600:
                    raise Problem('距离上次确认已超过 10 分钟，请重新确认搜索条件和当前服务积分。', 409)
                if row['credential_hash'] != manager.fingerprint(run['query']['provider']):
                    raise Problem('使用的达人库账号已更换，请重新确认搜索条件和服务积分。', 409)
                c.execute("UPDATE discovery_runs SET status='running' WHERE id=?", (rid,))
            raw = None
            try:
                query = run['query']
                if query['provider'] == 'nox':
                    current = manager.price('nox', query['limit'], row['credential_hash'])
                    if current['unit_credit'] != run['price']['unit_credit'] or any(current.get('server_price', {}).get(k) != run['price'].get('server_price', {}).get(k) for k in ('unit', 'pricing_model', 'standard_quantity')):
                        raise discovery.DiscoveryError('Nox 搜索所需积分已变化，尚未开始搜索；请重新确认。', 409)
                raw = manager.search(query, run['payload'], row['credential_hash'])
                run['fetched_at'] = now()
                # Persist the paid response before parsing so a schema change does not lose evidence.
                with db(True) as c:
                    c.execute('UPDATE discovery_runs SET raw=?,data=? WHERE id=?', (json.dumps(raw, ensure_ascii=False), json.dumps(run, ensure_ascii=False), rid))
                items, container = discovery.normalize(query['provider'], query, raw)
                run['items'] = items
                total = discovery.numeric(container.get('total_size') if query['provider'] == 'nox' else container.get('total'))
                run['total'] = total
                run['next_cursor'] = container.get('search_after') if query['provider'] == 'nox' else None
                more = bool(items) and (run['page'] * query['limit'] < total if total is not None else len(items) >= query['limit'])
                if query['provider'] == 'nox':
                    more = more and isinstance(run['next_cursor'], list) and bool(run['next_cursor'])
                run['more_available'] = more
                run['error'] = None
                with db(True) as c:
                    c.execute("UPDATE discovery_runs SET status='done',data=? WHERE id=?", (json.dumps(run, ensure_ascii=False), rid))
                return self.response({**run, 'status': 'done'})
            except Exception as exc:
                message = exc.message if isinstance(exc, discovery.DiscoveryError) else '处理搜索响应失败，结果或用量可能已产生；请查看历史记录，未自动重试。'
                run['error'] = message
                with db(True) as c:
                    c.execute("UPDATE discovery_runs SET status='failed',data=? WHERE id=?", (json.dumps(run, ensure_ascii=False), rid))
                raise Problem(message, getattr(exc, 'status', 502))
        if action == 'import' and write:
            self.require_role(user, {'admin', 'editor'})
            indices, pid = body.get('indices'), body.get('project_id')
            if not isinstance(indices, list) or not 1 <= len(indices) <= 20 or any(isinstance(v, bool) or not isinstance(v, int) for v in indices):
                raise Problem('请勾选 1–20 位搜索结果。')
            with db(True) as c:
                run, p = discovery_run(c, rid), get_project(c, pid)
                if run['status'] != 'done':
                    raise Problem('只有成功的搜索结果可以加入候选池。')
                if any(i < 0 or i >= len(run['items']) for i in indices):
                    raise Problem('选择的结果不存在。')
                ids, skipped = [], 0
                for index in dict.fromkeys(indices):
                    item = run['items'][index]
                    if not item['importable']:
                        raise Problem('有结果缺少稳定标识，不能加入候选池。')
                    provider_id = item['provider_id'] or item['account_id'] or item['profile_url']
                    source_key = run['query']['provider'] + ':' + run['query']['platform'] + ':' + provider_id
                    exists = c.execute('SELECT candidate_id FROM discovery_links WHERE project_id=? AND source_key=?', (pid, source_key)).fetchone()
                    if exists:
                        skipped += 1
                        continue
                    source = {'provider': run['query']['provider'], 'provider_name': discovery.PROVIDERS[run['query']['provider']]['name'],
                              'provider_id': provider_id, 'run_id': rid, 'result_index': index, 'fetched_at': run['fetched_at'],
                              'query': run['query'], 'metrics': {'followers': item['followers'], 'average_views': item['average_views'], 'metric_label': item['metric_label']},
                              'gaps': item['gaps']}
                    d = candidate_data({'name': item['name'], 'platform': item['platform'], 'account_id': item['account_id'],
                        'profile_url': item['profile_url'], 'followers': item['followers'], 'language': item['language'],
                        'content_genre': item['tags'], 'format': p['format'], 'owner_id': user['id'],
                        'evidence_note': (f"{source['provider_name']} search archive · {run['fetched_at']}; topic: {run['query']['topic']}. Provider result; campaign suitability still needs review." if self.english_requested() else f"{source['provider_name']} 搜索留档 · {run['fetched_at']}；主题：{run['query']['topic']}。来自达人库搜索，仍需人工确认是否适合本次推广。"),
                        'next_action': '核验公开账号、代表作品与目标受众，补充完整报价和合作条件。',
                        'quote': {'currency': p['currency']}}, source_ref=source)
                    canonical = c.execute('SELECT id FROM candidates WHERE project_id=? AND identity_key=?', (pid, identity(d))).fetchone()
                    if canonical:
                        cid = canonical['id']; skipped += 1
                    else:
                        cid = add_candidate(c, pid, d, user['id']); ids.append(cid)
                    c.execute('INSERT INTO discovery_links(project_id,source_key,candidate_id) VALUES(?,?,?)', (pid, source_key, cid))
                return self.response({'count': len(ids), 'skipped': skipped, 'ids': ids})
        raise Problem('搜索接口请求方式不支持。', 405)

    def check_owner(self, c, d):
        if d['owner_id'] and not c.execute('SELECT id FROM users WHERE id=?', (d['owner_id'],)).fetchone():
            raise Problem('负责人不存在。')

    def handle_request(self):
        self.pending_response = None
        try:
            self.dispatch()
        except (Problem, discovery.DiscoveryError) as exc:
            self.response({'error': exc.message}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            print('Server error:', type(exc).__name__, flush=True)
            self.response({'error': '服务处理失败，数据未提交。请重试或查看本地日志。'}, 500)

        if self.pending_response is not None:
            try:
                self.send_payload(*self.pending_response)
            except (BrokenPipeError, ConnectionResetError):
                pass

    do_GET = handle_request
    do_POST = handle_request
    do_PATCH = handle_request


def make_demo(c, user_id):
    p = project_data({'name': '星港纪元 · 欧洲试玩计划', 'game': '星港纪元（示例）', 'genre': '太空策略 / PC',
                      'market': '德国', 'language': '德语', 'goal': '愿望单', 'format': '长视频', 'currency': 'EUR',
                      'budget': 12000, 'min_audience_pct': 40, 'require_audience': True,
                      'require_paid_rights': False, 'is_demo': True,
                      'notes': '合成示例：以德语玩家的试玩兴趣和 Steam 愿望单为目标。内容需展示真实策略循环；竞品经验可作为品类证据。'})
    pid = uid()
    c.execute('INSERT INTO projects(id,data,created_by,created_at,updated_at) VALUES(?,?,?,?,?)', (pid, json.dumps(p, ensure_ascii=False), user_id, now(), now()))
    event(c, pid, None, user_id, 'project_created', '创建合成示例；所有达人与报价均为演示数据', p)
    specs = [('Orbit Tactics', 'orbit-demo', 84000, 68, 2800, 'match', True, 26000, 420,
              '专注策略游戏深度试玩。竞品攻略证明品类经验，已确认本次无排他冲突。'),
             ('Pixel Voyage', 'pixel-demo', 420000, None, 4100, 'unknown', False, None, None,
              '历史热门内容以 Shorts 为主，尚缺长视频样本与德国受众证据。'),
             ('Northbound Plays', 'north-demo', 126000, 54, 3600, 'match', True, 34000, 510,
              '德语 PC 游戏评测，能解释复杂机制。合作包含一次补录与自然转载。'),
             ('Cozy Signal', 'cozy-demo', 62000, 57, 1900, 'mismatch', True, 18000, 140,
              '内容以治愈经营为主，与本轮硬核策略玩家的动机存在偏差，适合另行测试。')]
    for name, account, followers, pct, fee, fit, verified, views, actions, note in specs:
        d = candidate_data({'name': name, 'platform': 'YouTube', 'account_id': account,
            'profile_url': 'https://example.com/creators/' + account, 'language': '德语', 'content_genre': '策略 / 模拟',
            'format': '长视频', 'followers': followers, 'audience_market': '德国', 'audience_pct': pct,
            'audience_source': '合成后台报告，样本窗口为最近 90 天' if verified else '', 'audience_verified': verified,
            'fit': fit, 'fit_note': note, 'source_url': 'https://example.com/evidence/' + account,
            'evidence_date': date.today().isoformat(), 'evidence_note': '合成示例：6 条同形式商业长视频，发布后第 7 天快照；不含 Shorts 与付费加热。' if verified else '缺少可比长视频证据。',
            'availability': 'confirmed' if verified else 'unknown', 'exclusivity': 'clear' if verified else 'unknown',
            'terms_note': '示例商务记录：档期、游戏访问与品类排他已逐项核实。' if verified else '',
            'owner_id': user_id, 'next_action': '核对合作包后提交审批' if verified else '补充受众后台与可比长视频证据',
            'quote': {'currency': 'EUR', 'fee': fee, 'usage': 300 if verified else None, 'exclusivity_fee': 0 if verified else None,
                      'production': 200 if verified else None, 'tax': 100 if verified else None, 'bonus_cap': 0 if verified else None,
                      'deliverables': '1 条 8–12 分钟试玩长视频；描述区链接；一次小修改；保留 90 天。',
                      'rights': '自然转载 30 天，含中文字幕改编；不含付费投放。' if verified else '',
                      'payment': '定稿后 50%，发布验收后 50%；取消按已完成阶段结算。' if verified else '',
                      'paid_rights': 'not_included', 'cost_complete': verified, 'confirmed': verified,
                      'quoted_at': date.today().isoformat(), 'expected_views': views, 'expected_actions': actions,
                      'forecast_basis': '合成情景：同形式、同龄期样本与既有追踪窗口，仅用于展示测算，不是效果承诺。' if verified else ''}})
        cid = add_candidate(c, pid, d, user_id)
        if account in ('orbit-demo', 'north-demo'):
            c.execute('UPDATE candidates SET selected=1 WHERE id=?', (cid,))
    return pid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--require-login', action='store_true', help='启用可选的账号登录模式；默认直接进入本地工作台')
    parser.add_argument('--open-browser', action='store_true', help='启动后打开本机浏览器')
    args = parser.parse_args()
    global DATA
    if args.data_dir:
        DATA = args.data_dir.resolve()
    init_db()
    with db(True) as c:
        for row in c.execute("SELECT id,data FROM discovery_runs WHERE status='running'").fetchall():
            data = json.loads(row['data'])
            data['error'] = '上次搜索时程序被关闭，结果及扣积分情况待确认。没有再次搜索，请先到达人库核对积分记录。'
            c.execute("UPDATE discovery_runs SET status='failed',data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), row['id']))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as exc:
        parser.exit(1, f'无法启动端口 {args.port}：{exc}。若已启动，请打开 http://127.0.0.1:{args.port}；或使用 --port 更换端口。\n')
    server.failed_logins = []
    server.discovery = discovery.DiscoveryManager()
    server.local_user_id = None if args.require_login else ensure_local_user()
    print(f'KOL Desk: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Data: {DATA.resolve()}\nCtrl+C to stop.', flush=True)
    if args.open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f'http://127.0.0.1:{server.server_port}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
