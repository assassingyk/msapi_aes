# ms-tester-encrypted（单账号版）

[English](./README.md) [简体中文](./README_zh.md)

## 这是什么

复刻自 [AutoApiSecret](https://github.com/wangziyingwen/AutoApiSecret)，用于给 **Microsoft 365 Developer（E5）订阅**“保活”：用 GitHub Actions 定时用 refresh token 换取 access token 并调用 Microsoft Graph，模拟账号活跃，防止订阅因不活跃被回收。

refresh token 使用 AES-256 加密后保存在仓库的 `token_*.txt` 中（AES_KEY 不落盘）。

## 工作原理（先读这段，能省很多事）

```
GitHub Actions (keepalive.yml, 每天 8:35/16:35/20:35 UTC)
   └─ main.py
        ├─ 用 refresh token 换 access token（每次成功都会把返回的新 token 加密写回 token_*.txt 并提交）
        └─ 用 access token 调用一批 Graph 端点
```

**重要事实：** 用**个人微软账号（hotmail/outlook）**、经 `/common` 端点授权拿到的 refresh token，微软**不会轮换**，并且**签发后 90 天准时失效**（报错 `AADSTS700082: The refresh token has expired due to inactivity`）。每天刷新多少次都没用，服务端无法续期，只能**人工重新授权一次**——这是微软的硬限制，本项目无法绕过，只能把“重新授权”这件事做得又快又不容易漏：

1. token 失效当天，GitHub Actions 会报错，若配置了通知（见下）会立刻推送消息；
2. 在本仓库目录跑一条命令即可完成重授权并自动推送到 GitHub：

   ```bash
   python reauth.py --push     # 打开浏览器 -> 登录 -> 输入代码 -> 完事
   ```

> 提示：如果把授权账号换成 E5 订阅自带的 Azure AD 租户账号（非个人 MSA），微软会正常轮换 token、每次刷新重置 90 天窗口，理论上可长期免维护；本项目默认按个人账号场景维护。

## 部署

1. 打开 <https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade> 注册应用：账号类型选“任何组织目录…和个人 Microsoft 帐户”，重定向 URI 选 `Web` 填 `http://localhost:53682/`；记下**应用程序(客户端) ID**。
2. 在“证书和机密”新建**客户端机密**，记下该机密的值。
3. 添加 Microsoft Graph **委托权限**：`Files.Read.All Files.ReadWrite.All Sites.Read.All Sites.ReadWrite.All User.Read.All User.ReadWrite.All Directory.Read.All Directory.ReadWrite.All Mail.Read Mail.ReadWrite MailboxSettings.Read MailboxSettings.ReadWrite`。
4. 在 GitHub 仓库 Settings -> Secrets and variables -> Actions 配置以下 Secrets（沿用现有命名即可）：

   | Name | 值 |
   |---|---|
   | `CLIENT_ID2` | 应用程序(客户端) ID |
   | `CLIENT_SECRET2` | 客户端机密的值 |
   | `AES_KEY` | 任意随机字符串（用于加密 token 文件，改动会导致无法解密） |
   | `REFRESH_TOKEN2` | 可选。首次运行时用于生成 token 文件；之后建议直接用下面的 `reauth.py` |

5. 首次拿 refresh token（二选一）：
   - 推荐：运行 `python reauth.py`（设备码流程，任何浏览器都行），它会直接把加密 token 文件写好；
   - 或运行 `auth.ps1`（授权码流程，需本机监听 localhost:53682），把输出的 token 填进 `REFRESH_TOKEN2`。
6. 手动触发一次 Actions（Actions 页 -> keepalive -> Run workflow），确认绿色通过。

## token 失效（700082）怎么办

看到 `AADSTS700082` / “REFRESH TOKEN EXPIRED” 时：

```bash
# 在本仓库目录（需能访问 GitHub 远程仓库的权限）：
python reauth.py --client-id <应用ID> --client-secret <机密> --aes-key <AES_KEY> --push
# 或者先把 CLIENT_ID / CLIENT_SECRET / AES_KEY 设为环境变量再直接：
python reauth.py --push
```

浏览器打开提示的网址并输入代码，登录并同意后脚本会自动加密写回 `token_*.txt` 并 `git push`，下一次定时任务即恢复正常。**不需要**再改任何 GitHub Secrets。

> 若 reauth.py 报“public client / 需要允许公共客户端流”，请在 Azure 应用注册 -> 身份验证 开启“允许公共客户端流”，或改用 `auth.ps1`。

## 失效即时通知（推荐配置）

在 GitHub Secrets 中按需添加以下任一/多个（`main.py` 检测到 token 失效或 Graph 全部调用失败时自动推送）：

| Name | 说明 |
|---|---|
| `NOTIFY_SERVERCHAN_KEY` | Server酱 Turbo SendKey（https://sct.ftqq.com） |
| `NOTIFY_BARK_KEY` | Bark key（https://api.day.app） |
| `NOTIFY_TELEGRAM_BOT_TOKEN` + `NOTIFY_TELEGRAM_CHAT_ID` | Telegram 机器人 |
| `NOTIFY_WEBHOOK_URL` | 通用 Webhook，收到 POST JSON `{"title":..., "message":...}` |

## 清理说明（2026-09 整理）

- 已删除不再需要的 `tester.yml` / `tester2.yml`，统一为单个 `keepalive.yml`（tester2 即实际在跑的流程，沿用 `CLIENT_ID2` 等 Secrets）。
- 已删除已注销账号遗留的旧 token 文件（`token_1fec…`、`token_a795…`、`token_efd045…`）。
- 旧账号遗留的 `CLIENT_ID` / `CLIENT_SECRET` / `REFRESH_TOKEN` Secrets 可在 GitHub Settings 中手动删除。

## 注意事项

- 本仓库含加密的 token 文件，建议设为 **private**。
- 所有运行记录显示在 Actions 页；`main.py` 退出码：`2`=需要重新授权，`3`=应用配置问题，`1`=临时错误（下次自动重试）。
- 不要改动 `AES_KEY`，否则无法解密现有 token 文件，需重新授权。
