# REMAC 云邻 e家 · Home Assistant 集成

[![hassfest](https://img.shields.io/github/actions/workflow/status/kaen/ha-remac-ehome/hassfest.yml?label=hassfest)](https://github.com/kaen-w/ha-remac-ehome/actions/workflows/hassfest.yml)
[![HACS](https://img.shields.io/github/actions/workflow/status/kaen/ha-remac-ehome/hacs.yml?label=HACS)](https://github.com/kaen-w/ha-remac-ehome/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/kaen/ha-remac-ehome)](LICENSE)

把**睿住（REMAC）X-Brain 系列网关**下的智能门锁接入 Home Assistant。
支持实时开锁事件、状态监控、电量告警与**一次性临时密码生成**。

> An unofficial Home Assistant integration for **REMAC 云邻 e家** smart door
> locks (Midea DC / 美的置业). Adds live unlock events, status sensors and
> temporary passcode generation. Reverse engineered from the official app —
> see [docs/PROTOCOL.md](docs/PROTOCOL.md).

---

## ⚠️ 免责声明

- 本项目**不是**官方集成，与睿住智能、广东睿住智能科技有限公司、美的置业集团**没有任何关系**。
- 协议通过抓包官方 App 还原，**可能随服务端更新随时失效**。
- 使用本集成造成的任何后果（包括但不限于账号异常、设备不可用）由使用者自行承担。
- 请仅在你**自己拥有**的账号和设备上使用。抓包与逆向仅供个人互操作研究。

---

## 功能

| 功能 | 状态 | 说明 |
|---|---|---|
| 门锁状态（开/关） | ✅ | 实时同步 |
| 电量 & 低电量告警 | ✅ | 已修正云端返回的错误字段 |
| 在线状态 | ✅ | |
| **开锁实时事件** | ✅ | 默认 5 秒、可调到 3 秒，触发 HA 事件，可直接做自动化 |
| 开锁动态历史 | ✅ | 最近 20 条记录，每条带可读文案（`指纹开锁 · 屋主`）+ 完整原始字段 |
| **生成临时密码** | ✅ | 1–30 分钟，步长 1 分钟（与官方 App 一致） |
| 临时密码一次性 | ✅ | 被用掉或超过有效期后自动失效，不会一直挂在面板上 |
| 用户台账（指纹/密码/卡） | ✅ | `userRole` 里的名字 + 凭证类型；开锁方式按 `openRecord` 位规则推导 |
| 远程开锁 | ❌ | 该门锁系列**不提供**远程开门，只有凭证管理 |
| 智慧屏开关控制 | ❌ | 控制命令尚未抓取 |

> **关于远程开锁**：这不是偷懒。实测该门锁的透传通道（`/subdevice/operation`）
> 只暴露只读命令，App 里的门锁页做的是「权限管理」——指纹、密码、临时密码、
> 时段授权。远程开门在硬件/固件层面就没有开放。

---

## 安装

> 需要 **Home Assistant 2025.1 或更高**（用了新版 `config_entry.runtime_data`
> 和 `AddConfigEntryEntitiesCallback` 接口）。

### 方式一：HACS（推荐）

1. 打开 HACS → 右上角 **⋮** → **自定义存储库**
2. 填入仓库地址 `https://github.com/kaen-w/ha-remac-ehome`，类别选 **集成**
3. 在 HACS 中搜索 **REMAC 云邻 e家** 并下载
4. **重启 Home Assistant**

### 方式二：手动

把 `custom_components/remac_ehome` 整个目录复制到你的 HA 配置目录：

```
<config>/custom_components/remac_ehome/
```

然后重启 Home Assistant。

---

## 配置

**设置 → 设备与服务 → 添加集成 → 搜索「REMAC 云邻 e家」**

| 字段 | 必填 | 说明 |
|---|---|---|
| 手机号 | ✅ | 云邻e家 App 的登录手机号 |
| 密码 | 🟡 | 密码模式必填；填了「令牌来源地址」后可以留空 |
| 房屋 ID | ❌ | 默认 `10000001`，多套房时按需修改 |
| 客户端指纹 | ❌ | 默认值可用，一般不用改；它是云端眼中的「设备」，换个值等于换台手机 |
| 扫描间隔 | ❌ | 默认 5 秒，可设 3–60 秒，直接决定开锁事件延迟 |
| 令牌来源地址 | ❌ | 填了就走「借用 App token」模式，永不登录（见下） |

添加之后随时可以点「配置」改**手机号 / 密码 / 令牌来源 / 扫描间隔**：密码留空表示
不改；令牌来源留空表示退回密码模式。在令牌来源模式下保存配置**不会**触发登录。

密码的处理方式：先用 `POST /sl/home/config/getConfig {"type":"rsa"}` 取云端
1024 位 RSA 公钥，再按 `base64(RSA_PKCS1v15(password))` 加密后提交。
密码会保存在 HA 的配置项里（和大多数云集成一样），**不会明文出现在日志或诊断数据中**。

### ⚠️ 这个账号是单会话的（重要）

实测：**每次登录都会作废之前所有 token**，只有最新的有效。下面那次测试之所以
「26 分钟就失效」，就是因为期间官方 App 又登录了一次。

| token | 签发 | 26 分钟后测试 |
|---|---|---|
| 较早的 | 00:34 | ❌ 3000 失效 |
| 较新的 | 01:00 | ❌ 3000 失效 |
| 最新 | 01:12 | ✅ 有效 |

所以：**HA 和官方 App 不能各自登录**，会互相踢下线。

集成提供两种凭据模式：

| 模式 | 影响 App | 适用场景 |
|---|---|---|
| **令牌来源 `token_source`**（推荐） | ✅ 完全不影响 | 你有一台常开的机器能拿到 App 当前 token |
| 手机号 + 密码 | ⚠️ 互踢 | 你不再用官方 App，只用 HA |

#### 令牌来源模式怎么用

在配置表单的「令牌来源地址」填一个返回如下 JSON 的 URL：

```json
{"token": "<App 当前的 accessToken>", "device_id": "<deviceId>"}
```

填了它之后，集成**永不调用登录接口**，token 失效时会重新拉取；
拉不到就把实体标为不可用，并提示"打开 App 让它刷新一次会话"。

> 怎么拿到这个 token？用透明代理截获 App 的 `Authorization` 请求头即可。
> 因为 Flutter 不读系统代理，需要做 NAT 层劫持（见 [docs/PROTOCOL.md §6](docs/PROTOCOL.md)）。

### 为什么也支持密码

云端的 `accessToken` 寿命就是接口声称的 **7200 秒（2 小时）**，实测在 App 不登录的
情况下能完整用完：日志里 `logged in as …` 出现在 `08:59 → 10:59 → 12:59`，正好每两
小时一次，中间没有任何失败重试。

> 早期文档里写过「实际只有 15 分钟」，那是**互踢期间**测到的假象——你在测的时候
> 反复打开官方 App，它每登录一次就作废了 HA 手里的 token。

刷新端点 `/sl/cas/authorize/token/refresh` 在服务端本身就是坏的——官方 App 自己调用
也会收到 `7001 refreshToken not exist`，它是靠**本地存密码重新登录**。

所以本集成采用同样的策略：token 失效时自动用密码重新登录。

---

## 实体

| 实体 | 类型 | 说明 |
|---|---|---|
| `lock.<门锁>` | lock | 门锁状态（只读） |
| `sensor.<门锁>_battery` | sensor | 真实电量百分比 |
| `sensor.<门锁>_door_state` | sensor | `open` / `closed` |
| `sensor.<门锁>_last_activity` | sensor | **最近动态**，状态是一句话（如 `指纹开锁 · 屋主 · 22:06:42`），属性 `last_event` / `last_unlock` / `recent`（最近 20 条，带 `text`） |
| `sensor.<门锁>_temporary_passcode` | sensor | **当前可用的**临时密码 + 过期时间；一次性，用掉或过期后自动清空，`status` 变为 `used`/`expired` |
| `binary_sensor.<门锁>_online` | binary_sensor | 云端在线状态 |
| `binary_sensor.<门锁>_low_battery` | binary_sensor | 电量低告警 |
| `button.<门锁>_generate_temporary_passcode` | button | **生成临时密码** |
| `number.<门锁>_temporary_passcode_duration` | number | 有效期 1–30 分钟 |
| `text.<门锁>_temporary_passcode_holder` | text | 使用者名称 |

> 实体的英文/中文名称跟随你的 Home Assistant 界面语言。

---

## 生成临时密码

面板上有两种用法。

**方法一：用控件（推荐，适合面板卡片）**

1. 调 `number.*_temporary_passcode_duration` 选有效期（1–30 分钟）
2. 改 `text.*_temporary_passcode_holder` 填使用者（快递 / 保洁 / 访客）
3. 按 `button.*_generate_temporary_passcode`
4. 密码出现在 `sensor.*_temporary_passcode`，同时弹出持久通知

**方法二：直接调用服务**

```yaml
service: remac_ehome.generate_temp_password
data:
  username: 快递
  expire: 1800   # 60–1800 秒
```

无论哪种方式，都会触发事件 `remac_ehome_temp_password_created`：

```json
{
  "passcode": "078632",
  "username": "访客",
  "expire_seconds": 1620,
  "expires_at": "2026-10-24T01:16:55+08:00"
}
```

### 一次性：用掉或过期就自动失效

临时密码**只能用一次**。集成会在 5 秒内（跟着轮询节奏）发现下面两种情况，并且
把密码从实体状态里清掉、同时撤掉那条带明文密码的持久通知：

| 情况 | 判定依据 | `status` |
|---|---|---|
| 被用掉 | 门锁上报的 `0x2100` 临时密码开锁记录，且时间晚于本次生成时刻 | `used`（附 `used_at`） |
| 过期 | 生成时间 + 有效期已过去 | `expired`（附 `expired_at`） |

失效后 `sensor.*_temporary_passcode` 的状态变成 `unknown`（不再泄露密码），
属性里保留 `status` / `username` / `used_at` / `expired_at` 供追溯。
这时会再触发一个事件 `remac_ehome_temp_password_retired`：

```json
{"status": "used", "username": "访客", "at": "2026-10-27 22:45:38"}
```

> 这个判定能扛重启：重启后不会把已经失效的旧密码从恢复状态里捡回来。

---

## 实时开锁事件

集成默认**每 5 秒一个周期**（可调到 3 秒），每个周期先拉 `status`，只有发现门锁
真有新上报时才去拉活动日志（见下文「轮询并不是每个周期都打两个接口」）。每条新记录
都会触发 HA 事件：

```
event_type: remac_ehome_door
```

事件数据：

| 字段 | 说明 |
|---|---|
| `type` | `unlock` / `door` / `outside_open` / `battery` |
| `text` | **给人看的一句话**，如 `指纹开锁 · 屋主`、`门已打开`、`电量 17%` |
| `method` | 开锁方式：`指纹` / `密码` / `临时密码` / `感应卡` / `未知` |
| `temporary` | `true` 表示这是临时密码开锁（`0x2100`） |
| `category` / `member` | `openRecord` 拆出来的类别与成员序号，如 `0x02` / `1` |
| `credential_confirmed` | `true` = 台账里查到了这个人；`false` = 只知方式不知人 |
| `record_hex` | 原始 `openRecord` 值，如 `0x0200` / `0x0201` / `0x1100` / `0x2100` |
| `bits` | 置位列表，如 `[9]`（仅供排错，判断身份请用 `category`/`member`） |
| `unmatched_bits` | 无法解释的置位，出现即说明遇到了没解出来的编码 |
| `door_open` / `door_label` | 门磁（`type == door` 时），如 `false` / `门已关闭` |
| `user_no` / `user_name` / `user_type` | 命中的凭证编号、名字、类型（如 `1` / `屋主` / `普通指纹`） |
| `user_label` | 凭证没起名字时的兜底文案，如 `凭证2` |
| `time` | 云端记录时间 `YYYY-MM-DD HH:MM:SS` |
| `dev_code` | 门锁设备码 |

### 这些事件也进「设备活动」

集成注册了 logbook 描述（`logbook.py`），所以每条事件都会出现在
「设置 → 设备与服务 → 智能门锁 → 活动」和实体历史里，带图标和中文文案：

```
15:42  指纹开锁 · 家人
15:42  门已打开
15:42  室外开锁
15:42  电量 17%
15:43  门已关闭
```

临时密码的两个事件同样有描述（`生成临时密码（访客，30 分钟有效）`、
`临时密码（访客）已被使用，已失效`），归属到临时密码实体上。

> 设备活动里同时还能看到实体自己的状态变化行（例如 `最近动态 已变为 …`），
> 那是 Home Assistant 的通用行为，不是重复记录。

### 自动化示例

```yaml
# 临时密码开锁 → 小爱播报
- alias: 临时密码开锁播报
  trigger:
    - platform: event
      event_type: remac_ehome_door
      event_data:
        type: unlock
        method: 临时密码
  action:
    - service: xiaomi_miot.intelligent_speaker
      data:
        entity_id: media_player.xiao_ai_speaker
        text: 临时密码验证通过，请进
        execute: true

# 指纹开锁 → 欢迎回家
- alias: 指纹开锁欢迎回家
  trigger:
    - platform: event
      event_type: remac_ehome_door
      event_data:
        type: unlock
        method: 指纹
  action:
    - service: xiaomi_miot.intelligent_speaker
      data:
        entity_id: media_player.xiao_ai_speaker
        text: 欢迎回家
        execute: true

# 只要是开门动作就播报
- alias: 门打开播报
  trigger:
    - platform: event
      event_type: remac_ehome_door
      event_data:
        type: door
        door_open: true
  action:
    - service: xiaomi_miot.intelligent_speaker
      data:
        entity_id: media_player.xiao_ai_speaker
        text: 门开了
        execute: true

# 门没关好 2 分钟提醒
- alias: 门未关提醒
  trigger:
    - platform: event
      event_type: remac_ehome_door
      event_data:
        type: door
        door_open: true
  action:
    - delay: "00:02:00"
    - condition: state
      entity_id: sensor.my_door_door_state
      state: "open"
    - service: notify.notify
      data:
        message: 门已经开了 2 分钟，确认一下
```

### 完整示例：按开锁方式播放不同欢迎语

[`examples/unlock_welcome_tts.yaml`](examples/unlock_welcome_tts.yaml) 是一个可以直接
粘贴使用的成品自动化，做的事情是：

| 开锁方式 | 播报 |
|---|---|
| 指纹 | `晚上好，屋主，欢迎回家`（自动带上凭证里填的名字） |
| 密码 | `晚上好，密码已验证，欢迎回家` |
| 临时密码 | `晚上好，临时密码已验证，访客请进` |
| 其他（卡片/人脸/未知） | `晚上好，门已打开` |

问候语会随时段变化（早上好 / 上午好 / 中午好 / 下午好 / 晚上好 / 夜深了），
夜里自动降到 28% 音量、白天保证不低于 35%，播完还原；小爱的「勿扰」开着就
直接不播报（相当于总开关）。

### 延迟说明（重要）

**本集成是轮询，不是推送。** 官方 App 能做到「开锁瞬间」是因为它保持了一条
到 **阿里云 EMAS 推送**的私有长连接（`emas-link-service.aliyuncs.com:9001`），
这个通道第三方无法复用。

已验证的替代方案都不可行：

| 方案 | 结论 |
|---|---|
| 复刻 EMAS 推送 | ❌ 需要 App 密钥 + 私有协议 |
| 云端 WebSocket / SSE | ❌ 抓包 236 条请求中一个都没有 |
| 网关本地 API | ❌ 对 `192.168.31.64` 做 1–65535 全端口扫描，**0 个开放端口** |
| **轮询活动日志** | ✅ 本集成采用，延迟 = 轮询间隔 |

好消息是：**云端日志是实时写入的**（开锁后 1–3 秒就能查到），所以延迟基本等于你设的间隔。

可在「设置 → 设备与服务 → 云邻e家 → 配置」里调：

- 默认 **5 秒**，最小 **3 秒**、最大 **60 秒**

### 轮询并不是每个周期都打两个接口

每个周期只请求 **`/device/status/get`**（轻、稳定），顺手读它的
`lastStatusUpdate` —— 那是网关最后上报的时间戳，门锁一有动静它就变。
只有它变了才去请求**活动日志**（`/device/log/list`，重、而且会偶发
`9999 智能服务未响应`），另外每 10 个周期兜底拉一次。

所以间隔设成 3 秒时，一天的请求量是：

| 端点 | 3 秒间隔 | 5 秒间隔 | 说明 |
|---|---|---|---|
| `status/get` | 28,800/天 | 17,280/天 | 每个周期一次（约 0.33 / 0.2 rps），带 `lastStatusUpdate` |
| `log/list` | ≈2,900/天 + 事件触发 | ≈1,730/天 + 事件触发 | 每 10 个周期兜底一次；真的有人开锁/开门时立即拉 |
| `lock/user/list` | 720/天 | 432/天 | 凭证台账，10 分钟一次 |
| **合计** | **≈3.2 万/天** | **≈1.9 万/天** | |

改造前是每个周期都拉日志：3 秒会是 **36,720 次/天**，其中 28,800 次打在老是
`9999` 的日志服务上。现在延迟一样，日志服务的请求量只有原来的 1/10，而且
`status` 这个稳的端点每 3 秒就把门磁 / 在线 / 电量刷一遍。

> 想再省，就把间隔调大（比如 10 秒 ≈ 8,600 次/天）；想更快，3 秒是下限 ——
> 云端日志本身要 1–3 秒才写进去，再快也追不回那 1 秒。

> 如果你要的是**真正毫秒级**，只有 Zigbee 侧方案能做到（门锁直连 ZHA/Zigbee2MQTT，
> 或做 802.15.4 抓包），代价是脱离睿住 App 的云端功能。

---

## 已知限制

1. **token 每 2 小时过期** —— 过期后必须重新登录，所以「密码」或「令牌来源地址」
   至少要配一个；两个都空的话集成会一直报 `invalid_auth`。
2. **开锁方式映射** —— `openRecord = (类别 << 8) | 成员序号`，已确认
   `0x02` = 成员指纹（`0x0200` = 成员 0、`0x0201` = 成员 1）、`0x11` = 键盘密码、
   `0x21` = 临时密码。其它类别（感应卡 / 人脸 / 钥匙）还没样本，遇到会显示
   `未知` 并把原始 `bits` 放进 `unmatched_bits`。想帮忙补全：用不同方式各开一次门，
   把 `sensor.*_last_activity` 的 `recent` 属性发到 issue 里。
   成员序号查不到对应凭证时**不会猜人名**，只显示 `指纹开锁 · 待确认`。
3. **凭证名字来自 `userRole`** —— `/subdevice/lock/user/list` 返回的 `typeName`
   只是「普通指纹」这类类型名，名字要读 `userRole`；没填名字的凭证会退化成类型名。
4. **只支持门锁** —— 网关下的「智慧屏开关」(`remac.padSwitch.001`) 只纳入了设备发现，
   没有建 switch 实体，因为开关控制命令还没抓到。
5. **凭证管理只读** —— 能读台账、能生成临时密码，但没有增删指纹/改密码的实体。
6. **凭证要起名字** —— 没起名字的凭证只能显示成 `凭证2` 这种编号；在云邻e家 App 里
   给它填个名字，HA 里立刻就能显示人名。

---

## 排错

**实体全部 `unavailable`**
→ 看日志里有没有 `ConfigEntryAuthFailed`。多半是密码改了，去
「设置 → 设备与服务 → 云邻e家 → 配置」重新填一次。

**一直提示 `cannot_connect`**
→ 检查 HA 主机能不能访问 `app.smartmideazy.com`。这个域名在国内可以直连；
如果 HA 走了代理，确认代理没有拦它。

**开锁了但没触发事件**
→ 确认 `sensor.*_last_activity` 的状态在变。如果它不变，说明云端日志没更新；
如果它在变但事件没触发，请开 debug 日志：

```yaml
logger:
  logs:
    custom_components.remac_ehome: debug
```

**临时密码生成失败**
→ 云端偶尔会返回 Dubbo 超时（`Invoke remote method timeout`），但密码其实
已经生成了。重试一次即可。

**事件偶尔迟到十几秒**
→ 正常情况下延迟 = 轮询间隔 + 云端写入的 1–3 秒。如果明显更慢，多半是活动日志
接口在返回 `9999 智能服务未响应`（集成会保留缓存并下个周期重试，不会丢事件）。
把 debug 日志打开就能看到 `activity log fetched` / `keeping N cached record(s)`。

**开锁事件一直不触发，但状态在变**
→ 说明 `status` 正常、日志接口没拉到。看日志里有没有
`activity log fetch failed ... keeping N cached record(s)`，或者直接把间隔调大一点。

---

## 它是怎么被还原的

完整协议文档在 **[docs/PROTOCOL.md](docs/PROTOCOL.md)**，包含：

- 登录链路（RSA 密码加密、salt、token 生命周期）
- 全部接口清单与请求/响应样例
- `openRecord` 位编码分析
- 踩坑记录（Flutter 不读系统代理、Clash fake-ip、conntrack 钉死老连接…）

简单说：安卓包被**百度加固**了，但里面是 **Flutter** 写的，业务字符串全在
`libapp.so` 的 AOT 快照里，没被加固——接口路径直接从那里挖出来。
请求参数则靠 SNI 感知的透明 MITM 代理抓的。

---

## 贡献

欢迎 PR。最有价值的贡献是**补充开锁样本**（见「已知限制」第 2、3 点）。
提交前请确保：

```bash
ruff check custom_components
ruff format --check custom_components
```

---

## 更新日志

每个版本改了什么写在 **[CHANGELOG.md](CHANGELOG.md)**，格式遵循 Keep a Changelog。

---

## License

[MIT](LICENSE)

---

## 致谢

- [Home Assistant](https://www.home-assistant.io/)
- [HACS](https://hacs.xyz/)
- 所有帮忙抓样本、报 bug 的用户
