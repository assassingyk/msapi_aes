# -*- coding: utf-8 -*-
"""One-shot interactive re-authorization using the OAuth device-code flow.

Use this when main.py reports AADSTS700082 / "REFRESH TOKEN EXPIRED":
the old token cannot be revived server-side, so a human must sign in once.
This script makes that step as small as possible:

  1. prints a URL + code to open in any browser (no localhost listener needed),
  2. after you approve, it encrypts the new refresh token into the SAME
     token_<md5>.txt file the GitHub workflow uses (AES_KEY must match the
     GitHub secret),
  3. with --push it commits and pushes the file, so the next scheduled run
     automatically picks up the fresh token.

Usage:
    python reauth.py --client-id <app id> --client-secret <client secret> \
                     --aes-key <AES_KEY> [--push]
or via environment variables CLIENT_ID / CLIENT_SECRET / AES_KEY.

token path defaults to md5(CLIENT_ID + CLIENT_SECRET), which is exactly how
the workflow computes TOKEN_PATH (see .github/workflows/keepalive.yml).

Note: if the app registration rejects the device-code flow (some apps are
registered as "Web" only), enable "Allow public client flows" under
Authentication in the Azure app registration, or fall back to auth.ps1
(authorization-code flow with a localhost redirect).
"""
import argparse
import hashlib
import os
import subprocess
import sys
import time

import requests

SCOPE = (
    'offline_access Files.Read.All Files.ReadWrite.All Sites.Read.All '
    'Sites.ReadWrite.All User.Read.All User.ReadWrite.All Directory.Read.All '
    'Directory.ReadWrite.All Mail.Read Mail.ReadWrite MailboxSettings.Read '
    'MailboxSettings.ReadWrite'
)
DEVICE_CODE_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/devicecode'
TOKEN_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'


def md5_path(client_id, client_secret):
    """Same derivation as the workflow's `md5sum` of CLIENT_ID+CLIENT_SECRET."""
    return hashlib.md5((client_id + client_secret).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description='Re-authorize and renew the keep-alive refresh token')
    ap.add_argument('--client-id', default=os.environ.get('CLIENT_ID', ''),
                    help='Azure app (client) ID')
    ap.add_argument('--client-secret', default=os.environ.get('CLIENT_SECRET', ''),
                    help='Azure app client secret')
    ap.add_argument('--aes-key', default=os.environ.get('AES_KEY', ''),
                    help='the AES_KEY secret (must match GitHub secret)')
    ap.add_argument('--token-path', default='',
                    help='override token file id (default: md5(client_id+client_secret))')
    ap.add_argument('--push', action='store_true',
                    help='git add/commit/push the new token file')
    args = ap.parse_args()

    if not (args.client_id and args.client_secret):
        ap.error('client id and client secret are required '
                 '(use flags or set CLIENT_ID/CLIENT_SECRET env vars)')

    token_path = args.token_path or md5_path(args.client_id, args.client_secret)
    # encrypt.py reads TOKEN_PATH at import time, so set it before importing.
    os.environ['TOKEN_PATH'] = token_path
    import encrypt

    # ---- step 1: ask Microsoft for a device code ---------------------------
    try:
        r = requests.post(DEVICE_CODE_URL,
                          data={'client_id': args.client_id, 'scope': SCOPE},
                          timeout=30)
        b = r.json()
    except Exception as e:
        print('::error::cannot contact device-code endpoint: {}'.format(e))
        sys.exit(1)

    if 'error' in b:
        desc = b.get('error_description') or ''
        print('::error::{}: {}'.format(b.get('error'), desc))
        if 'public client' in desc.lower() or b.get('error') in ('invalid_client',):
            print('提示: 请在 Azure 应用注册 -> 身份验证 中开启 '
                  '“允许公共客户端流 (Allow public client flows)”，或改用 auth.ps1 授权码流程。')
        sys.exit(1)

    print('=' * 64)
    print('1) 在任意浏览器打开: {}'.format(b['verification_uri']))
    print('2) 输入代码:         {}'.format(b['user_code']))
    print('   然后登录【要保活的那个微软账号】并同意所列权限。')
    print('=' * 64, flush=True)

    device_code = b['device_code']
    interval = int(b.get('interval', 5))

    # ---- step 2: poll until the user approves ------------------------------
    refresh_token = None
    while True:
        time.sleep(interval)
        try:
            r = requests.post(TOKEN_URL, data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'client_id': args.client_id,
                'client_secret': args.client_secret,
                'device_code': device_code,
            }, timeout=30)
            b = r.json()
        except Exception as e:
            print('::error::polling token endpoint failed: {}'.format(e))
            sys.exit(1)

        err = b.get('error')
        if not err:
            refresh_token = b.get('refresh_token')
            break
        if err == 'authorization_pending':
            continue
        if err == 'slow_down':
            interval += 5
            continue
        print('::error::{}: {}'.format(err, b.get('error_description')))
        if err in ('authorization_declined', 'expired_token'):
            print('授权被取消或已过期，请重新运行本脚本。')
        sys.exit(1)

    # ---- step 3: encrypt & store, optionally push ---------------------------
    if not args.aes_key:
        print('未提供 AES_KEY，无法加密保存。请妥善保管下面的 refresh_token：')
        print(refresh_token)
        return

    encrypt.save(refresh_token, args.aes_key)
    file_name = 'token_{}.txt'.format(token_path)
    print('新 refresh token 已加密写入: {}'.format(file_name))

    if args.push:
        try:
            subprocess.run(['git', 'add', '--', file_name], check=True)
            subprocess.run(['git', 'commit', '-m', 'renew refresh token via reauth.py'], check=True)
            subprocess.run(['git', 'push'], check=True)
            print('已提交并推送到 GitHub。下一次 scheduled run 将自动使用新 token。')
        except subprocess.CalledProcessError as e:
            print('::error::git 步骤失败 (exit {})，请手动提交并推送: {}'.format(
                e.returncode, file_name))


main()
