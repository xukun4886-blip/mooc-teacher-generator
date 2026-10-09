from __future__ import annotations

import math
import os
import re
from urllib.parse import urlsplit

import httpx

from mooc_m1.core import Failure
from mooc_m2.content import fingerprint

PROTOCOL = 'mooc.photo-worker.v1'


def settings(value, *, loopback=False):
    """Credentials stay in the workstation environment, never in SQLite."""
    if not isinstance(value, dict) or value.get('mode', 'local') not in {'local', 'cloud'}:
        raise Failure('INPUT_INCOMPATIBLE', '请选择本机或云端照片处理')
    if value.get('mode', 'local') == 'local':
        return {'mode': 'local'}
    url = str(value.get('url', '')).strip().rstrip('/')
    parsed = urlsplit(url)
    local = loopback and parsed.hostname in {'127.0.0.1', 'localhost'}
    if (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Failure('INPUT_INCOMPATIBLE', '云端地址须为不含凭据、查询或片段的 HTTPS 地址')
    env = value.get('token_env', 'MOOC_CLOUD_TOKEN')
    if not isinstance(env, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', env):
        raise Failure('INPUT_INCOMPATIBLE', '请填写访问令牌的环境变量名称')
    batch = value.get('batch_size', 1)
    limit = value.get('timeout_seconds', 1800)
    if type(batch) is not int or batch not in {1, 2, 4} or type(limit) is not int or not 30 <= limit <= 7200:
        raise Failure('INPUT_INCOMPATIBLE', 'batch 须为1/2/4，单片段时限须为30–7200秒')
    budget = value.get('max_cost', 0)
    if type(budget) not in {int, float} or not math.isfinite(budget) or budget < 0:
        raise Failure('INPUT_INCOMPATIBLE', '单片段费用上限须为非负数')
    return {'mode': 'cloud', 'url': url, 'token_env': env, 'batch_size': batch,
            'timeout_seconds': limit, 'allow_uploads': value.get('allow_uploads') is True,
            'allow_paid': value.get('allow_paid') is True, 'max_cost': float(budget)}


def client(config, *, transport=None):
    token = os.environ.get(config['token_env'], '')
    if not token:
        raise Failure('CLOUD_CONFIG_MISSING', f"本机环境变量 {config['token_env']} 尚未配置")
    return httpx.Client(base_url=config['url'] + '/', headers={'Authorization': 'Bearer ' + token},
                        timeout=httpx.Timeout(30, connect=10), follow_redirects=False, trust_env=False, transport=transport)


def checked(response):
    if not response.is_success:
        # Do not put remote bodies, URLs or request headers into logs/errors.
        raise Failure('CLOUD_REQUEST_FAILED', f'云端请求返回 HTTP {response.status_code}')
    return response


def health(config, *, transport=None):
    with client(config, transport=transport) as http:
        try:
            result = checked(http.get('v1/health')).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Failure('CLOUD_UNAVAILABLE', '云端健康接口无法连接或格式无效') from exc
    identity = result.get('model', {})
    if result.get('protocol') != PROTOCOL or identity.get('provider') != 'SadTalker' or not identity.get('code_revision') or not identity.get('weights') or not identity.get('implementation_sha256'):
        raise Failure('CLOUD_INCOMPATIBLE', '服务器协议或 SadTalker 版本记录不兼容')
    if identity.get('render') != {'size': 256, 'preprocess': 'full', 'enhancer': None, 'fps': 25, 'frame_storage': 'detached_cpu_per_frame_v1'}:
        raise Failure('CLOUD_INCOMPATIBLE', '服务器人物画质配置与当前基线不一致')
    rate = result.get('price', {}).get('hourly_rate')
    if type(rate) not in {int, float} or not math.isfinite(rate) or rate < 0 or not result.get('price', {}).get('currency'):
        raise Failure('CLOUD_INCOMPATIBLE', '服务器须声明小时费率和币种（已有自用服务器可声明0）')
    return {'protocol': PROTOCOL, 'model': identity, 'model_key': fingerprint(identity),
            'price': result['price'], 'ready': result.get('ready') is True,
            'resident_loaded': result.get('resident_loaded') is True,
            'blockers': result.get('blockers', []),
            'scope': '配置与连接检查；未上传素材、未执行人物推理，质量尚未验证'}


def pinned(config, observed):
    if not config.get('allow_uploads'):
        raise Failure('CLOUD_UPLOAD_NOT_AUTHORIZED', '请明确允许当前课程的教师照片和驱动音频发送至指定服务器')
    price = observed['price']
    cost = price['hourly_rate'] * config['timeout_seconds'] / 3600
    if cost > 0 and (not config.get('allow_paid') or cost > config['max_cost']):
        raise Failure('CLOUD_BUDGET_BLOCKED', '单片段最长运行时间的计算费用超过授权上限，请调整时限或预算')
    if not observed['ready']:
        raise Failure('CLOUD_UNAVAILABLE', '服务器配置检查未就绪')
    return {**config, 'protocol': PROTOCOL, 'model': observed['model'], 'model_key': observed['model_key'], 'price': price}
