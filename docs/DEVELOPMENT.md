# 开发和运行

## 运行模式

README 的 `scripts/run_challenge_preview.py` 为最容易启动的隔离演示：自动生成虚构玩家和对局，编译 JSX/Tailwind，本地数据库可重复使用，禁用外部通知。仅监听 `127.0.0.1`。

普通网站开发可以复制 `.env.nfc.example` 为 `.env.nfc`，按需填写路径，再运行：

```sh
python -m pip install -r requirements-api-vision.txt
python scripts/run_web_with_scores.py --port 8000 --api-port 8001
```

它启动网页和私有 FastAPI，不启动 Discord bot；普通前端需要访问 React、Babel、Tailwind CDN。空数据库没有线上玩家或成绩。公开 demo 密码不用于此模式；实际管理角色须通过可信的数据初始化流程设置。旧系统有按姓名识别历史管理员的兼容逻辑，自建站点前应审阅 `web_server.py` 中的 `DEFAULT_ADMINS` / `DEFAULT_SUPER_ADMINS`，并改为自己的管理策略。

## 数据与配置

| 配置 | 作用 |
| --- | --- |
| `TABLE_ACCOUNT_FILE` | 账号 JSON 路径；相邻目录还有账号索引/认领状态文件 |
| `MAHJONG_DB_FILE` | 俱乐部成绩、玩家及活动 SQLite |
| `NFC_DATABASE_PATH` | 座位、预约、比赛与登分 SQLite |
| `NFC_CLUB_DATABASE_PATH` | 登分同步到同一俱乐部历史库 |
| `TOURNAMENT_CLUB_DATABASE_PATH` | 比赛读取的俱乐部玩家库 |
| `NFC_AUTH_PROFILE_URL` | 私有服务回查主服务 `/api/session` |
| `NFC_MOCK_AUTH_ENABLED` | 正常运行必须为 false |
| `PUBLIC_SITE_URL` | 对外 HTTPS 网站地址 |
| `TRUSTED_PROXY_CIDRS` | 可信反向代理的精确地址范围 |
| `SITE_TIMEZONE` | 默认 America/Los_Angeles |

两个普通启动脚本会设置本机 API 和会话回查地址。持久化目录需可写；数据库、账号索引、待恢复操作文件、上传目录应一并备份。不要把运行数据提交进 Git。默认路径及其他参数见 `.env.nfc.example`、`mahjong_api/config.py`；部分历史机器人配置仍位于 `main.py` 和 `cogs/`。

## 可选功能

- **拍照识别**：`requirements-api-vision.txt` 提供默认段码识别所需 OpenCV/NumPy。无需模型权重。可选神经 OCR 的安装器和依赖单独提供，许可见 NOTICE。
- **Discord 提醒**：在服务端配置自己的 `DISCORD_BOT_TOKEN`、`DISCORD_GUILD_ID` 和 `DISCORD_RESERVATION_REMINDER_CHANNEL_ID`，再启用提醒。缺少配置不应阻止网站预约。
- **Discord OAuth**：配置自己的 client ID、client secret、回调地址。`GET /api/discord/config` 可检查是否可用；源码存在不表示部署环境已启用。
- **Google Sheets / Discord bot**：另装 `requirements.txt` 并配置自己的服务账号和机器人。`main.py` 中旧版 guild/sheet 配置仍为原俱乐部标识，运行前替换；仓库不提供凭据。
- **PostgreSQL**：FastAPI 可使用 `requirements-api-postgres.txt` 和 `NFC_DATABASE_URL`；网站历史数据仍使用 SQLite，不能只改一个 URL 就替换所有存储。

## 部署边界

Dockerfile 和 `entrypoint.py` 是同时启动网站、私有 API 与 Discord bot 的模板。它们需要你自己的环境配置、数据持久化和反向代理；不是包含线上账号的即开即用镜像。只使用网站可选择 `scripts/run_web_with_scores.py`。

主服务会话当前存储在单进程内存；不要直接部署多个网站进程并假定它们共享会话。私有 API 默认仅监听回环地址。公网部署使用 HTTPS，设置可信代理、备份和独立的生产密钥。不要把本地演示脚本改为公网监听。

仓库不含原服务器部署脚本、运维报告、生产数据库或用户上传内容。把此源码推到 GitHub不会修改当前线上站点或迁移其数据。
