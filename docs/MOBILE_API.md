# 手机 App 接入指南

## 先运行本地后端

按 README 启动本地演示，API 基地址使用 `http://127.0.0.1:5083`。默认只监听本机；手机模拟器和真机的 localhost 与电脑不同，需要自行配置开发网络/转发。不要用线上网站测试写入、预约或登分。

网页主服务提供统一地址和登录会话，把部分 `/api/…` 请求转发到私有 FastAPI 服务。App 应访问网页主服务，不要绕过它直接连接私有 API。正式地址使用 HTTPS。

## 当前认证约定

普通成员使用 `GET /api/players` 搜索本人条目后，向 `POST /api/login` 提交返回的 `player_id`，无需重新注册或管理员审核。管理员使用用户名和密码单独登录。以下用户名密码请求仍可用于本地演示和管理员入口：

```json
{"username":"Alice","password":"LocalTest!2026"}
```

成功返回 `ok: true`，并设置 `mahjong_session` HTTP-only Cookie。原生客户端需要 Cookie jar，后续请求携带同一 Cookie；WebView 使用其 Cookie store，浏览器 fetch 使用 `credentials: "include"`。不要将用户密码或服务端密钥写入 App。

- `GET /api/session` 返回 `user` 和 `profile`；未登录时二者为 null。使用 `profile.id` 作为稳定账号身份，界面显示 `profile.name`。
- `POST /api/logout` 注销会话。
- 当前为统一 Cookie 会话；尚无供原生 App 使用的 JWT/access-token/refresh-token 签发流程。
- 生产身份来自服务端会话。不要传任意 `user_id` 充当登录身份，也不要使用测试专用 `Bearer demo-1`。
- 网站写接口有同源检查。浏览器/WebView 应保持同源；跨域移动 Web 前端需另行设计允许来源与 Cookie/CSRF 策略，不能仅添加 `Access-Control-Allow-Origin: *`。
- 已有账号 ID、俱乐部 Player ID、Guest ID 是不同概念，不要自行合并。已有成员选择原玩家记录登录；旧玩家重新注册与认领的公开入口已移除。

## 常用接口

表中为当前实现的路径；JSON 字段和错误码可查看对应源码与测试。`{tableId}` 使用接口返回的标识，不能假定桌号等于数据库 ID。

| 方法和路径 | 用途 | 权限 |
| --- | --- | --- |
| `GET /api/dashboard` | 排行榜、Recent Match 等 | 登录 |
| `GET /api/players` | 历史玩家姓名，包括尚未注册者 | 公开 |
| `GET /api/competitions/featured` | 当前展示活动及榜单 | 公开 |
| `GET /api/competitions/{slug}` | 活动详情、榜单 | 公开 |
| `POST /api/register` | 新玩家注册 | 无需登录 |
| `POST /api/forgot-password` | 请求管理员发放重置码，专用 Discord 频道通知 | 无需登录；账号冷却与接口限流 |
| `POST /api/admin/password-reset` | 生成一次性码，不接受新密码 | 管理员；特权账号须超级管理员 |
| `POST /api/reset-password` | 用重置码自行设置新密码 | 无需登录；必须持有有效码 |
| `GET /api/registered-users?q=…` | 已注册用户搜索 | 登录 |
| `GET /api/club-tables` | 桌子列表及状态 | 登录 |
| `GET /api/club-tables/{tableId}` | 桌子与预约详情 | 登录 |
| `GET /api/club-tables/{tableId}/seat-map` | 座位显示信息 | 公开 |
| `PUT /api/club-tables/{tableId}/my-seat` | 当前用户入座/同桌换座 | 登录 |
| `POST /api/club-tables/{tableId}/leave` | 当前用户下桌 | 登录 |
| `POST /api/club-tables/{tableId}/reservations` | 创建预约 | 登录 |
| `POST /api/table-reservations/{reservationId}` | 预约操作 | 登录及成员权限 |
| `POST /api/recognize_photo` | 上传终局照片识别 | 登录；multipart |
| `POST /api/confirm_scores` | 确认校对后成绩 | 登录及对应对局权限 |
| `POST /api/manual-score/preview` | 手动登分预览 | 登录 |
| `POST /api/manual-score/confirm` | 确认手动登分 | 登录及业务权限 |
| `GET /api/tournaments` | 比赛列表 | 以服务端权限检查为准 |

Recent Match 筛选参数：`quarter`、`match_player`、`table_players`。后者可用 `/` 或逗号分隔姓名。响应中的 `recent_games` 是对局列表；历史成绩页和该接口均要求登录。

新成员注册使用 `POST /api/register`，`username` 为玩家名称，可传本地安全路径 `redirect_url`；创建账号无需先设置密码。已有成员选择原有姓名登录，不通过注册创建第二个玩家记录。`/api/register/players`、`/api/register/claim`、`/api/register/resume` 和 `/api/public-player-history` 已停用并返回 410。

## 座位、下桌和重试

```http
PUT /api/club-tables/1/my-seat
Content-Type: application/json

{"seat":"east"}
```

风位仅支持 `east/south/west/north`。服务器根据会话决定玩家身份，以事务、唯一约束和审计记录执行入座或同桌换座。重复设置同一座位是幂等操作；用户在另一活动桌或目标位置被占用时不能覆盖。

网页“点击自己的座位下桌”是客户端交互：判断为本人后调用下面的下桌接口，**不是再次调用 my-seat**：

```http
POST /api/club-tables/1/leave
Content-Type: application/json

{"reason":"seat_card","match_id":"从当前桌次状态读取的 match_id"}
```

底部本人下桌按钮使用 `reason: "leave_button"`。成功后使用响应的 `table_state` 刷新。未开始对局时，普通登录成员也可通过 `POST /api/club-tables/{tableId}/seats/{userId}/remove` 帮他人下桌，请求携带当前 `match_id` 和目标 `seat`；操作者无需先入座。已开始、待结算和过期桌次会被拒绝。点击他人的位置若要交换，使用独立的双方同意换座流程，详见 `mahjong_api/seat_swap_routes.py`；不得覆盖对方。

创建预约使用唯一 `request_id`，时间字段 `scheduled_at`、`end_at` 传带时区的 ISO 8601 值。不同接口分别使用 `request_id` 或 `Idempotency-Key`，请遵照各自请求模型；一次操作重试时复用原请求标识。不要在超时后创建新的登分或预约请求。

处理 HTTP 401 为重新登录，403 为无权限，409 为状态/座位冲突，422 为参数错误，503 为服务暂不可用。FastAPI 通常返回 `detail.code/message`，网页接口也有顶层 `code/message/ok`；客户端需要兼容两种错误结构。失败时保留上一份桌子显示。

## 接口源码和测试

- 全站登录/历史记录：`web_server.py`、`account_registration.py`
- 网页转发白名单：`mahjong_api/web_proxy.py`
- 认证：`mahjong_api/auth.py`
- 座位/预约：`mahjong_api/table_routes.py`、`table_service.py`、`reservation_operations.py`
- 登分请求模型：`mahjong_api/models.py`、`manual_score_models.py`
- 对照示例：`tests/test_web_score_bridge.py`、`test_seat_leave_public_history.py`、`test_registration_v10.py`、`test_manual_score.py`

使用普通开发启动时，私有 API 的 `http://127.0.0.1:8001/docs` 提供 FastAPI Swagger，`/openapi.json` 提供该服务的 schema。它不包含 `web_server.py` 的登录、历史和活动接口；这些以本指南及源码为准。演示脚本为私有 API 分配随机端口，统一对外入口仍是 5083。

## 密码找回

申请请求体为 `{"username":"玩家注册名"}`，返回统一提示以避免暴露账号状态；通知附带需管理员登录的玩家管理链接。管理接口传 `username`（可附 `user_id` 防止重命名后的选择过期），返回一次性 `reset_code` 与 `expires_at`。不得提交 `new_password` 等密码字段。

玩家兑换请求体为 `{"username":"玩家注册名","reset_code":"XXXX-XXXX-XXXX","new_password":"用户自行输入","confirm_password":"用户再次输入"}`。码 30 分钟有效，一次性使用，重新签发使旧码失效；连续 5 次错误后需要新码。密码和代码在锁定的同一次账号写入中更新，成功后撤销该账号旧会话，需重新登录。普通改密也会使未使用的重置码失效。

通知使用服务器中指定的密码申请频道，不复用 Game Record。此代码快照的频道为 `1488771447915544586`，独立部署时需修改 `request_password_reset` 的目标频道并配置自己的机器人权限。测试均注入假发送器，不发真实消息。
