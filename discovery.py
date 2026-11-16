"""Read-only creator discovery adapters. Contracts: supplied IC MCP and Nox CLI 0.5.12.
No vendor package is executed or bundled. No outreach, profile unlock, or auto-retry.
"""
import hashlib
import json
import math
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

PROVIDERS = {
    'club': {'name': 'Influencers Club', 'base': 'https://api-dashboard.influencers.club',
             'platforms': ['youtube', 'tiktok', 'instagram', 'twitch'], 'env': 'INFLUENCERS_CLUB_API_KEY',
             'portal': 'https://dashboard.influencers.club', 'quota': '/public/v1/accounts/credits/'},
    'nox': {'name': 'NoxInfluencer', 'base': 'https://skill.noxinfluencer.com',
            'platforms': ['youtube', 'tiktok', 'instagram'], 'env': 'NOXINFLUENCER_API_KEY',
            'portal': 'https://cn.noxinfluencer.com/skills/dashboard', 'quota': '/api/v1/quota'},
}
PLATFORM_NAMES = {'youtube': 'YouTube', 'tiktok': 'TikTok', 'instagram': 'Instagram', 'twitch': 'Twitch'}


class DiscoveryError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status
        super().__init__(message)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def clean_text(value, limit=2000):
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def numeric(value):
    if isinstance(value, bool) or value is None or value == '':
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def safe_url(value):
    value = clean_text(value)
    p = urlparse(value)
    return value if p.scheme in ('https', 'http') and p.netloc and not p.username and not p.password else ''


def sanitized(value, secret=''):
    if isinstance(value, dict):
        return {k: sanitized(v, secret) for k, v in value.items()
                if not re.search(r'password|api.?key|access.?token|refresh.?token|authorization|secret|cookie', k, re.I)}
    if isinstance(value, list):
        return [sanitized(v, secret) for v in value]
    if isinstance(value, str):
        value = value.replace(secret, '[REDACTED]') if secret else value
        return re.sub(r'Bearer\s+\S+', 'Bearer [REDACTED]', value)
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(provider, path, key, payload=None):
    """Fixed HTTPS hosts only; never log credentials or raw upstream errors."""
    url = PROVIDERS[provider]['base'] + path
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
               'Accept': 'application/json', 'User-Agent': 'KOLDesk/1.1'}
    request = urllib.request.Request(url, data=body, headers=headers, method='POST' if body is not None else 'GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=35) as response:
            raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise DiscoveryError('达人库提供的资料过多，暂时无法展示。没有再次搜索，请先到达人库核对是否已扣积分。', 502)
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        codes = {401: '达人库授权码无效或已过期，请重新连接达人库。',
                 402: '达人库服务积分不足，请到账户后台查看或充值。',
                 403: '当前达人库账号暂不能使用此服务，请联系账号负责人检查套餐。',
                 429: '搜索过于频繁，请稍后再试。'}
        raise DiscoveryError(codes.get(exc.code, f'达人库暂时无法完成搜索（服务编号 {exc.code}）。没有再次搜索，请检查账号状态及积分记录。'), 502)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DiscoveryError('暂时联系不上达人库，尚不确定是否已扣积分。没有再次搜索，请先到账户后台核对积分记录。', 502)
    except (ValueError, UnicodeDecodeError):
        raise DiscoveryError('暂时无法读取达人库提供的资料。没有再次搜索，请先核对积分记录。', 502)
    if not isinstance(data, dict):
        raise DiscoveryError('暂时无法展示达人库提供的资料，没有再次搜索。请联系维护人员并核对积分记录。', 502)
    if data.get('success') is False or data.get('error'):
        code = clean_text(data.get('error_code'))
        message = {'INVALID_API_KEY': '达人库授权码不可用，请重新连接达人库。',
                   'INSUFFICIENT_CREDIT': '达人库服务积分不足，请到账户后台查看。',
                   'RATE_LIMITED': '达人库暂时限制搜索，请稍后再试。'}.get(code, '本次搜索未能开始，请检查达人库套餐是否支持，以及筛选条件是否合适。')
        raise DiscoveryError(message, 502)
    return sanitized(data, key)


def query_data(body):
    provider = body.get('provider')
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise DiscoveryError('请选择要使用的达人库。')
    platform = body.get('platform')
    if not isinstance(platform, str) or platform not in PROVIDERS[provider]['platforms']:
        raise DiscoveryError('这个达人库暂时不支持查找该平台的达人。')
    topic = body.get('topic')
    if not isinstance(topic, str) or not 3 <= len(topic.strip()) <= 150:
        raise DiscoveryError('搜索主题请填写 3–150 个字符。')
    limit = body.get('limit', 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise DiscoveryError('每次搜索数量须为 1–20 位。')
    result = {'provider': provider, 'platform': platform, 'topic': topic.strip(), 'limit': limit,
              'content_type': body.get('content_type', 'all')}
    if result['content_type'] not in ('all', 'long', 'short'):
        raise DiscoveryError('内容形式无效。')
    if platform != 'youtube' and result['content_type'] != 'all':
        raise DiscoveryError('长视频 / Shorts 筛选目前仅适用于 YouTube。')
    for field in ('followers_min', 'followers_max', 'average_views_min'):
        raw = body.get(field)
        value = numeric(raw)
        if raw not in (None, '') and (value is None or value > 1e12):
            raise DiscoveryError('粉丝数或播放门槛必须是有效非负数。')
        result[field] = value
    if result['followers_min'] is not None and result['followers_max'] is not None and result['followers_min'] > result['followers_max']:
        raise DiscoveryError('粉丝数下限不能大于上限。')
    # Countries/languages are free-text query context, never silently hard filters.
    return result


def request_body(query, page=1, cursor=None):
    platform, provider = query['platform'], query['provider']
    if provider == 'club':
        filters = {'ai_search': query['topic']}
        bounds = {k: query['followers_' + k] for k in ('min', 'max') if query['followers_' + k] is not None}
        if bounds:
            key = {'youtube': 'number_of_subscribers', 'twitch': 'followers'}.get(platform, 'number_of_followers')
            filters[key] = bounds
        view_field = 'average_views'
        if platform == 'youtube':
            if query['content_type'] == 'long':
                filters['has_videos'] = True
                view_field = 'average_views_on_long_videos'
            elif query['content_type'] == 'short':
                filters['has_shorts'] = True
                view_field = 'average_views_on_shorts'
        if platform == 'twitch':
            view_field = 'average_stream_views'
        if query['average_views_min'] is not None:
            filters[view_field] = {'min': query['average_views_min']}
        return {'platform': platform, 'paging': {'page': page - 1, 'limit': query['limit']},
                'sort': {'sort_by': 'relevancy', 'sort_order': 'desc'}, 'filters': filters}
    result = {'platform': platform, 'keywords': [t.strip() for t in re.split('[,，]', query['topic']) if t.strip()],
              'keyword_match': 'all', 'page_size': query['limit'], 'page_num': page}
    for k in ('min', 'max'):
        if query['followers_' + k] is not None:
            result['follower_' + k] = query['followers_' + k]
    if query['average_views_min'] is not None:
        result['avg_view_min'] = query['average_views_min']
    if query['content_type'] != 'all':
        result['video_type'] = 2 if query['content_type'] == 'long' else 1
    if page > 1:
        if not isinstance(cursor, list) or not cursor:
            raise DiscoveryError('Nox 暂未提供下一批名单，无法继续查看更多达人。')
        result['search_after'] = cursor
    return result


def normalize(provider, query, response):
    if provider == 'nox':
        container = response.get('data')
        records = container.get('items') if isinstance(container, dict) else None
    else:
        container, records = response, response.get('accounts')
    if not isinstance(records, list) or any(not isinstance(x, dict) for x in records):
        raise DiscoveryError('达人库已提供资料，但暂时无法展示，搜索留档已保存。这不代表没有找到达人；请联系维护人员并核对积分记录。', 502)
    output = []
    for index, row in enumerate(records):
        profile = row.get('profile') if isinstance(row.get('profile'), dict) else row
        ref = clean_text(row.get('id') if provider == 'nox' else row.get('user_id'), 2000)
        handle = clean_text(profile.get('username'), 200)
        if provider == 'nox':
            handle = ''  # Nox search IDs and nicknames are not public platform identities.
        url = safe_url(profile.get('url') or profile.get('profile_url') or row.get('profile_url'))
        name = clean_text(row.get('nickname') if provider == 'nox' else profile.get('full_name') or handle, 120) or '未提供公开名称'
        followers = numeric(profile.get('followers') if provider == 'club' else row.get('followers'))
        metric_key = 'avg_views' if provider == 'nox' else 'average_views'
        metric_label = '平均播放量（统计时间待确认）'
        if query['platform'] == 'youtube' and query['content_type'] != 'all':
            metric_key = ({'long':'avg_views_normal','short':'avg_views_shorts'} if provider == 'nox' else {'long':'average_views_on_long_videos','short':'average_views_on_shorts'})[query['content_type']]
            metric_label = '长视频平均播放' if query['content_type'] == 'long' else 'Shorts 平均播放'
        elif query['platform'] == 'twitch':
            metric_key, metric_label = 'average_stream_views', '平均直播观看量（统计时间待确认）'
        average = numeric(profile.get(metric_key))
        gaps = ['目标受众构成尚未人工核验', '合作报价与权利待确认']
        if not url:
            gaps.append('搜索未返回可访问的主页链接')
        if average is None:
            gaps.append('所选内容类型的观看量还需补充')
        if provider == 'nox':
            gaps.append('达人库可能隐藏了部分名称，真实账号仍需确认')
        tags = profile.get('tags') or row.get('tags')
        if isinstance(tags, list):
            tags = '、'.join(clean_text(v, 80) for v in tags if isinstance(v, str))
        else:
            tags = clean_text(tags, 500)
        output.append({'index': index, 'provider_id': ref, 'name': name, 'platform': PLATFORM_NAMES[query['platform']],
                       'account_id': handle, 'profile_url': url, 'followers': followers, 'average_views': average,
                       'metric_label': metric_label, 'language': clean_text(profile.get('language'), 100),
                       'creator_location': clean_text(profile.get('country') or profile.get('location'), 200),
                       'tags': tags, 'description': clean_text(profile.get('biography') or profile.get('description'), 1000),
                       'gaps': gaps, 'importable': bool(ref or handle or url)})
    return output, container


class DiscoveryManager:
    def __init__(self, request=None):
        self.request = request or transport
        self.lock = threading.RLock()
        self.keys = {k: os.environ.get(v['env'], '').removeprefix('Bearer ').strip() for k, v in PROVIDERS.items()}
        self.checked = {}

    def status(self):
        with self.lock:
            return [{'id': k, 'name': v['name'], 'platforms': v['platforms'], 'portal': v['portal'],
                     'configured': bool(self.keys[k]), 'verified_at': self.checked.get(k)} for k, v in PROVIDERS.items()]

    def configure(self, provider, key):
        if not isinstance(provider, str) or provider not in PROVIDERS or not isinstance(key, str) or len(key) > 4096 or any(ch.isspace() for ch in key.strip().removeprefix('Bearer ')):
            raise DiscoveryError('请选择达人库，并检查授权码是否完整、是否多复制了空格。')
        key = key.strip().removeprefix('Bearer ').strip()
        with self.lock:
            self.keys[provider] = key
            self.checked.pop(provider, None)
        return self.status()

    def credential(self, provider):
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise DiscoveryError('请选择要使用的达人库。')
        with self.lock:
            key = self.keys.get(provider)
        if not key:
            raise DiscoveryError('请先点击“连接达人库”，填写该达人库提供的授权码。')
        return key

    def fingerprint(self, provider):
        return hashlib.sha256(self.credential(provider).encode()).hexdigest()

    def check(self, provider):
        key = self.credential(provider)
        data = self.request(provider, PROVIDERS[provider]['quota'], key)
        with self.lock:
            if self.keys[provider] == key:
                self.checked[provider] = stamp()
        return {'verified_at': stamp()}

    def price(self, provider, limit, expected_hash=None):
        key = self.credential(provider)
        if expected_hash and hashlib.sha256(key.encode()).hexdigest() != expected_hash:
            raise DiscoveryError('使用的达人库账号已更换，请重新确认搜索条件和服务积分。', 409)
        if provider == 'club':
            return {'unit_credit': 0.01, 'estimated_credit': round(limit * .01, 6),
                    'basis': '按服务商文档，每找到一位达人预计消耗 0.01 服务积分；这是估算，实际以达人库扣分记录为准。', 'verified_at': None}
        data = self.request(provider, '/api/v1/pricing/tools?action=creator_search', key)
        container = data.get('data')
        rows = container.get('items', []) if isinstance(container, dict) else []
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get('action') == 'creator_search' and numeric(row.get('unit_credit')) is not None:
                if row.get('standard_quantity') is not None and numeric(row['standard_quantity']) != 1:
                    raise DiscoveryError('当前计费方式暂不支持，尚未开始搜索。请联系维护人员。', 502)
                unit = numeric(row['unit_credit'])
                return {'unit_credit': unit, 'estimated_credit': round(limit * unit, 6),
                        'basis': '按当前账号每位达人的搜索单价估算，实际按找到的人数扣除服务积分。',
                        'verified_at': stamp(), 'server_price': sanitized(row, key)}
        raise DiscoveryError('暂时无法确认 Nox 本次需要的服务积分，尚未开始搜索。请检查账号套餐或稍后再试。', 502)

    def search(self, query, payload, expected_hash=None):
        provider = query['provider']
        path = '/public/v1/discovery/' if provider == 'club' else '/api/v1/creators/search'
        key = self.credential(provider)
        if expected_hash and hashlib.sha256(key.encode()).hexdigest() != expected_hash:
            raise DiscoveryError('使用的达人库账号已更换，请重新确认搜索条件和服务积分。', 409)
        return sanitized(self.request(provider, path, key, payload), key)
