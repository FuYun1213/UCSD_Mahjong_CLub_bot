# DORA Mahjong Club — Web & Discord

UC San Diego 麻将俱乐部的网站、登分服务和 Discord 机器人。此仓库包含新版网页的前端、后端及自动化测试，可作为手机 App 的服务端和交互参考。

- 网站：[ucsdmj.org](https://ucsdmj.org)
- 手机端开发：[接口与登录说明](docs/MOBILE_API.md)
- 自行运行：[配置与部署说明](docs/DEVELOPMENT.md)
- 许可证：[MIT](LICENSE)；第三方依赖和品牌素材见 [NOTICE](NOTICE.md)。

## 已有功能

- 中英文网页、玩家资料、排行榜、Recent Match 和历史对局筛选；Recent Match 可不登录查看。
- 新玩家注册；已有玩家按录入姓名认领原 Player ID，管理员审核后保留原有成绩。
- 全站统一登录、头像、Discord 绑定；可选 Discord OAuth。
- 点击东南西北座位入座、同桌换座；再次点击自己的座位或下桌按钮下桌。已开始或待结算的对局保留服务端限制。
- 拍照识别、照片校对、手动登分、成绩确认与历史入库。
- 登录后预约、按时间分组、预约开始前一小时的 Discord 提醒。
- 比赛分桌、签到、Guest 身份、计分方式；按日期范围统计的活动排行榜。
- 管理员玩家与成绩管理、二维码与 NFC、外部赛事系统对接。

## 本地演示：无需 Discord 或线上数据库

需要 Python 3.10+（建议 3.12）和 Node.js 20+。先克隆：

```sh
git clone https://github.com/FuYun1213/UCSD_Mahjong_CLub_bot.git
cd UCSD_Mahjong_CLub_bot
python -m venv .venv
```

激活虚拟环境：Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1`；macOS/Linux 使用 `source .venv/bin/activate`。然后：

```sh
python -m pip install -r requirements-api-vision.txt
npm ci
python scripts/run_challenge_preview.py --port 5083
```

打开 **http://127.0.0.1:5083/**。演示账号为 `Alice`、`Bob`、`Carol`、`PreviewAdmin`，密码均为 `LocalTest!2026`；最后一个为演示管理员。

演示只监听本机，账号和样例对局写入 `.local_challenge_v11/`，不会连接生产账号、Google Sheets 或发送 Discord 提醒。此启动方式和上述公开密码仅用于本地开发，不能直接用于公网部署。停止时按 Ctrl+C。

这是可读、可运行的源码快照，**不包含俱乐部真实账号、密码哈希、数据库、上传照片、凭据或生产部署文件**。演示中的日期活动和成绩是样例，线上后台修改的活动内容属于数据库数据，不会随源码复制。

## 项目结构

| 位置 | 作用 |
| --- | --- |
| `web/` | React 网页、样式、翻译和品牌配置 |
| `web_server.py` | 网页服务、登录会话、历史数据、同源接口转发 |
| `mahjong_api/` | FastAPI：座位、预约、识别登分、比赛与提醒 |
| `account_*.py`、`registered_names.py` | 注册、旧玩家认领、Discord、统一身份 |
| `mahjong_store.py`、`competition_*.py` | 历史数据库、积分与日期活动 |
| `main.py`、`cogs/` | 可选 Discord 机器人 |
| `scripts/` | 本地启动、二维码和维护工具 |
| `tests/` | 业务、权限、并发和浏览器测试 |

## 测试

```sh
python -m pip install -r requirements-api-dev.txt -r requirements-api-vision.txt
npm ci
npx playwright install chromium
python -m pytest tests/test_seat_cards.py tests/test_registration_v10.py tests/test_placement_challenge.py -q
python -m pytest tests -q
```

浏览器测试默认使用 Playwright Chromium，也可设置 `PLAYWRIGHT_CHANNEL=msedge` 使用本机 Edge。完整测试包含真实浏览器及 OCR 测试，运行时间较长。测试使用隔离数据；私有生产部署脚本及其专项测试不在此仓库中。

前端目前为 React JSX，普通启动使用 CDN，本地演示会编译并使用本机依赖。仓库暂未提供原生 Android/iOS 工程；手机端可复用后端业务接口，详见接入文档。
