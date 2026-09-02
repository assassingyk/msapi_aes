# -*- coding: utf-8 -*-
import os
import sys

import requests

import encrypt
import notify

client_id = os.environ.get('CLIENT_ID', '')
client_secret = os.environ.get('CLIENT_SECRET', '')
aes_key = os.environ.get('AES_KEY', '')

if not (client_id and client_secret and aes_key):
    print('::error::the environment variables CLIENT_ID/CLIENT_SECRET/AES_KEY are not set correctly')
    sys.exit(1)

TOKEN_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
APIROOT = 'https://graph.microsoft.com/v1.0'

ENDPOINTS = [
    '/me/drive/root',
    '/me/drive',
    '/drive/root',
    '/users',
    '/me/messages',
    '/me/mailFolders/inbox/messageRules',
    '/me/mailFolders/Inbox/messages/delta',
    '/me/drive/root/children',
    '/me/mailFolders',
    '/me/outlook/masterCategories',
]

# Exit codes:
#   1 = generic / transient (the next scheduled run will simply retry)
#   2 = refresh token is dead, a human must re-authorize (reauth.py)
#   3 = app configuration problem (client id/secret/scopes)
EXIT_GENERIC = 1
EXIT_REAUTH = 2
EXIT_CONFIG = 3

REAUTH_HINT = (
    '微软判定该 refresh token 已失效（个人账号签发的 token 满 90 天即到期，'
    '服务端无法续期，只能重新授权一次）。\n'
    '在本仓库目录运行下面命令完成重授权（会自动加密写回并推送到 GitHub，'
    '之后无需再手动改任何 Secrets）：\n'
    '    python reauth.py --push\n'
)


def fatal(msg, hint, exit_code):
    print('::error::{}'.format(msg))
    print(hint)
    notify.send('E5 keepalive: {}'.format(msg), hint)
    sys.exit(exit_code)


def token_file_name():
    return 'token_{}.txt'.format(os.environ.get('TOKEN_PATH', '?'))


def get_access_token():
    """Redeem the stored refresh token for a new access token.

    On success the (possibly rotated) refresh token is saved back to the
    encrypted token file. Exit codes are distinct so the GitHub Actions run
    clearly shows whether a human must act (2) or not (1/3).
    """
    try:
        refresh_token = encrypt.load(aes_key)
    except Exception as e:
        fatal(
            'cannot read token file {}'.format(token_file_name()),
            '无法读取加密的 refresh token 文件 {}\n{}\n\n首次部署或文件丢失时，'
            '请先运行一次:\n    python reauth.py --push'.format(token_file_name(), e),
            EXIT_REAUTH,
        )

    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': 'http://localhost:53682/',
    }
    try:
        req = requests.post(TOKEN_URL, data=data, timeout=30)
    except requests.RequestException as e:
        print('::error::token endpoint unreachable: {}'.format(e))
        sys.exit(EXIT_GENERIC)  # transient, next scheduled run retries

    try:
        body = req.json()
    except ValueError:
        print('::error::token endpoint returned non-JSON (HTTP {})'.format(req.status_code))
        sys.exit(EXIT_GENERIC)

    if body.get('error'):
        codes = [str(c) for c in (body.get('error_codes') or [])]
        desc = body.get('error_description') or ''
        print('::error::refresh token request failed')
        print(body)

        desc_l = desc.lower()
        if ('700082' in codes or 'inactivity' in desc_l or 'expired due to inactivity' in desc_l):
            fatal('REFRESH TOKEN EXPIRED DUE TO INACTIVITY (AADSTS700082)', REAUTH_HINT, EXIT_REAUTH)
        elif body.get('error') in ('invalid_client', 'unauthorized_client', 'invalid_scope'):
            hint = ('应用配置问题（CLIENT_ID / CLIENT_SECRET / 授权范围）。'
                    '请核对 GitHub Secrets 与 Azure 应用注册，若 client secret 过期需在 Azure 门户新建。\n'
                    + desc)
            fatal('APP CONFIG ERROR', hint, EXIT_CONFIG)
        elif body.get('error') == 'invalid_grant':
            fatal('REFRESH GRANT REJECTED', REAUTH_HINT + '\n服务端返回: ' + desc, EXIT_REAUTH)
        else:
            fatal('TOKEN ERROR ({})'.format(body.get('error')), desc, EXIT_GENERIC)

    access_token = body['access_token']
    new_refresh_token = body.get('refresh_token')
    if new_refresh_token:
        if new_refresh_token == refresh_token:
            # Typical for personal Microsoft accounts: the server never rotates
            # the refresh token, so it dies 90 days after issuance no matter
            # how often we refresh (AADSTS700082). Just an informative log.
            print('[info] server returned the same refresh token (no rotation; '
                  'personal-MSA token, expect 90-day expiry)')
        encrypt.save(new_refresh_token, aes_key)
    return access_token


def call_endpoints(access_token):
    headers = {
        'Authorization': 'Bearer ' + access_token,
        'Content-Type': 'application/json',
    }
    ok = 0
    failures = []
    for endpoint in ENDPOINTS:
        try:
            res = requests.get(APIROOT + endpoint, headers=headers, timeout=30)
            if res.status_code == 200:
                ok += 1
                print('call {} successed'.format(endpoint))
            else:
                failures.append((endpoint, res.status_code, res.text[:300]))
                print('::error::call {} failed'.format(endpoint))
                print(res.text[:500])
        except Exception as e:
            failures.append((endpoint, 'exception', str(e)))
            print('::error::call {} exception catched'.format(endpoint))
            print(e)

    if ok == 0 and failures:
        detail = '\n'.join(
            '{} -> {}: {}'.format(ep, code, text[:200]) for ep, code, text in failures)
        notify.send(
            'E5 keepalive: 所有 Graph 调用失败',
            '本次运行没有任何成功的 Graph 请求（可能授权/权限被撤销，或网络问题）。\n' + detail,
        )
    return ok


def main():
    access_token = get_access_token()
    call_endpoints(access_token)


main()
