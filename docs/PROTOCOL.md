# REMAC 云邻 e家 协议笔记

> 本文档记录的是 **2026-10** 对 `云邻e家 v3.4.0` 的逆向结果。
> 服务端随时可能改动，若接口失效请提 issue。

---

## 0. 结论速览

| 项 | 值 |
|---|---|
| API 基址 | `https://app.smartmideazy.com` |
| 静态资源 | `remac-static.oss-cn-hangzhou.aliyuncs.com/ehome/...` |
| 明文 IoT 接口 | `http://btiot012.100tun.com/api/int/device/`（备用通道） |
| 认证方式 | `Authorization: <accessToken>`（**无 Bearer 前缀**） |
| Token 实测寿命 | **约 15 分钟**（接口声称 7200 秒，实测不符） |
| 刷新端点 | `/sl/cas/authorize/token/refresh`（服务端有 bug，官方 App 也失败） |
| 包名 | `com.mideadc.smartlife` |

---

## 1. 客户端结构（为什么能被逆向）

APK 用了**百度加固**，业务 dex 是加密的（`libbaiduprotect.so` 运行时解密），
`Lcom/mideadc/` 在 dex 里零引用。

但是它是一个 **Flutter** 应用，Dart 代码编译成 AOT 快照放在
`lib/arm64-v8a/libapp.so`（12.9 MB），**这一层没有加固**。
所有接口路径、字段名、包名都以明文字符串存在于快照中：

```bash
unzip yunlin.apk 'lib/arm64-v8a/libapp.so'
strings libapp.so | grep '/sl/home/'
```

能直接捞到 60+ 个 `/sl/home/...` 路径。但**请求参数和加密逻辑抓不到**，
因为登录/控制逻辑在加固的 Java 层 + 原生插件里（日志里 `requestOrigin: "plugin"`）。

---

## 2. 通用请求约定

```
POST /sl/home/<path>?appId=1010&src=23&stamp=<YYYYMMDDHHMMSS>
```

| Header | 值 |
|---|---|
| `Authorization` | accessToken（纯 token） |
| `app-agent` | `{"deviceId":"<32hex>","buildVersion":"260617.2","os":"18.7.8","clientType":"iOS","model":"iPhone13,2","version":"3.4.0","ip":"<ip>"}` |
| `language` | `zh_CN` |
| `version` | 空串 |
| `X-PACKAGES-ENV` | `xxxx` |
| `User-Agent` | `SmartLifeCommunity/3.4.0 (iPhone; iOS 18.7.8; Scale/3.00)` |
| `Content-Type` | `application/json` |

响应统一信封：

```json
{ "data": ..., "errorCode": 0, "msg": "ok", "msgId": "..." }
```

### 错误码

| code | msg | 含义 |
|---|---|---|
| `0` | ok | 成功 |
| `3000` | authenticationError | token 无效/过期 |
| `3153` | 手机号或密码错误 | 解密成功但凭证错 |
| `4003` | param invalid | 缺必填参数 |
| `4010` | DECRYPT_ERROR | RSA 解密失败（格式不对） |
| `7001` | refreshToken not exist | 刷新令牌已被消费或不存在 |
| `9999` | 智能服务未响应 | 缺参数或后端服务异常 |

> **`9999` 是最坑的一个**：它不告诉你缺什么。`/device/v2/list` 漏了
> `fields` 数组就会得到它，而不是一个明确的参数错误。

---

## 3. 登录链路

### 3.1 取 RSA 公钥

```http
POST /sl/home/config/getConfig
{"type": "rsa"}
```

```json
{
  "data": {
    "rsa": {
      "publicKey": [
        "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCw42IVNW1q7bw4evuovdDZZpq5..."
      ]
    }
  },
  "errorCode": 0
}
```

1024 位 RSA，PKCS#1 v1.5。加密后的密文是 128 字节 → base64 后 **172 字符**。

### 3.2 取盐（可选）

```http
POST /sl/home/user/salt
{"mobile": "13800138000"}
```

```json
{"data": {"salt": "4f5fa0e2-0411-4314-aefb-1a4c40c466e4"}, "errorCode": 0}
```

### 3.3 登录换 token

```http
POST /sl/cas/authorize/token
{
  "loginId":  "13800138000",
  "password": "base64(RSA_PKCS1v15(公钥, 密码明文))",
  "clientId": "<deviceId>",
  "pushData": {
    "appDeviceId": "", "appDeviceToken": "",
    "appDeviceOs": "iOS", "providerNo": "AliyunPush"
  },
  "encrypt": true
}
```

> 下面样例里的 token、手机号、nickname、userId 都是**占位符**，不是可用凭据。

```json
{
  "data": {
    "expires": 7200,
    "expires_re": 5184000,
    "salt": "4f5fa0e2-...",
    "loginType": "mobile",
    "mobile": "13800138000",
    "nickname": "屋主",
    "language": "zh_CN",
    "accessToken": "<access-token>",
    "userId": 1000001,
    "refreshToken": "a19109ed...-3ed5-48ce-..."
  },
  "errorCode": 0
}
```

### 3.4 验证加密格式的技巧

不知道真实密码时，可以**故意加密一个错密码**：

- 返回 `3153 手机号或密码错误` → **加密格式正确**（服务端成功解密了）
- 返回 `4010 DECRYPT_ERROR` → 加密格式不对

用这个方法可以零风险确认算法，不用碰真实密码。

### 3.5 token 生命周期（重要）

接口声称 `expires: 7200`（2 小时），实际情况分两种：

| 场景 | 实测寿命 |
|---|---|
| App 不登录（只有本集成在轮询） | **用满 7200 秒**：日志里 `logged in as …` 正好每 2 小时出现一次 |
| 期间有人打开官方 App | 立刻失效 —— 账号**单会话**，App 每登录一次就作废所有旧 token |

早期这里写过「实际寿命 ≈ 15 分钟」，那是**互踢期间**测出来的假象：

| 时间 | 事件 |
|---|---|
| 00:34:17 | 登录，拿到 token |
| 00:49:55 | 该 token 仍可用（生成临时密码成功） |
| 00:52:00 | 该 token 已失效（`3000`） |

那 15 分钟里官方 App 又登录过（详见 §9）。所以在「App 完全不用」的前提下，token 该活满
2 小时；如果你看到它十几分钟就死，先检查是不是有人开了 App。

刷新端点：

```http
POST /sl/cas/authorize/token/refresh
{"refreshToken": "<明文>", "idKey": "uuid", "idValue": "<deviceId>"}
```

抓包里 App 自己调用了两次，**两次都失败**：

```json
{"errorCode": 7001, "msg": "refreshToken not exist"}
```

紧接着 App 就做了一次完整登录。结论：**刷新链路在服务端是坏的，
官方 App 的策略就是本地存密码、失效重登**。本集成照做。

---

## 4. 设备与状态

### 4.1 设备列表（`fields` 必填！）

```http
POST /sl/home/device/v2/list
{
  "houseId": "10000001",
  "fields": ["domain","house","master","status","switches",
             "orviboUid","remote","isVirtual","extraAttr","td"]
}
```

实测返回：

| devName | modelId | devCode | 说明 |
|---|---|---|---|
| 智能门锁 | `midea.doorlock.031` | `1234567890123456` | 目标设备 |
| 智慧屏开关1 | `remac.padSwitch.001` | `5348033953340069` | 未实现控制 |
| 智慧屏开关2 | `remac.padSwitch.001` | `9390129339681389` | 未实现控制 |
| 2024款X-Brain4 | `MSGWG17` | `65432109876543` | 网关本体 |

门锁的 Zigbee `identifier` 是 `0011223344556677`。

### 4.2 实时状态

```http
POST /sl/home/device/status/get
{"devCode": "1234567890123456", "requestOrigin": "plugin"}
```

```json
{
  "data": {
    "BatteryRemaining": 100,
    "batteryRemaining": 19,
    "doorState": 1,
    "DoorState": 1,
    "onlineStatus": 1,
    "lowBattery": 1,
    "BatteryAlarmState": 0,
    "openRecord": 512,
    "OpenRecord": 0,
    "outsideOpen": 1,
    "guard": 0,
    "LockVolumeLevel": 1,
    "ZoneStatus": 1,
    "bluetoothmac": "",
    "lastStatusUpdate": "1792768973536",
    "isAlarmDevice": "0"
  },
  "errorCode": 0
}
```

#### ⚠️ 电量字段是个坑

`BatteryRemaining` **恒为 100**（满量程常量），真实电量在 `batteryRemaining`。

实测证据：App 界面显示「电量低」时，云端同时返回
`BatteryRemaining: 100` 和 `batteryRemaining: 19`。

#### 字段含义

| 字段 | 实测值 | 推断 |
|---|---|---|
| `doorState` / `DoorState` | `0`=开 / `1`=关 | 已确认 |
| `batteryRemaining` | 19 | **真实电量** |
| `BatteryRemaining` | 100 | 假值，忽略 |
| `lowBattery` | 1 | 电量低告警 |
| `onlineStatus` | 1 | 在线 |
| `openRecord` | 见 §5 | 开锁方式位域 |
| `outsideOpen` | 1 | 室外开锁标记 |
| `guard` | 0 | 布防 |
| `LockVolumeLevel` | 1 | 音量档位 |

### 4.3 活动日志（事件来源）

```http
POST /sl/home/device/log/list
{
  "devCode": "1234567890123456",
  "requestOrigin": "plugin",
  "page": {"pageSize": 100, "pageNo": 1}
}
```

记录结构（`data` 是**字符串化的 JSON**）：

```json
{
  "createTime": "2026-10-24 00:44:52",
  "devCode": "1234567890123456",
  "masterCode": "65432109876543",
  "identifier": "0011223344556677",
  "modelId": "midea.doorlock.031",
  "name": "智能门锁",
  "appId": 1000,
  "data": "{\"openRecord\":8448}"
}
```

实测时序（一次临时密码开门）：

```
23:22:41  {"batteryRemaining":19}
23:22:45  {"doorState":1}        ← 关
23:22:48  {"doorState":0}        ← 开
23:22:49  {"openRecord":512}
23:22:49  {"outsideOpen":1}
23:22:53  {"doorState":1}        ← 关
```

云端写入日志是**实时**的，所以轮询日志就能做准实时事件。

### 4.4 用户台账

```http
POST /sl/home/device/subdevice/lock/user/list
{"devCode": "1234567890123456", "requestOrigin": "plugin"}
```

不带 `userType` 只返回一个桶：

```json
{"data": [{"userNo": "0", "typeName": "普通指纹", "userType": "2",
           "userRole": "", "isAntiHijacking": false, "isOpenDoorAlarm": false}]}
```

需要按 `userType`（1/2/3…）分别查询再合并，才能拿到密码用户、指纹用户、感应卡用户。

### 4.5 临时密码

```http
POST /sl/home/device/subdevice/unlock/generate
{
  "devCode":    "1234567890123456",
  "masterCode": "65432109876543",
  "username":   "快递",
  "expire":     1800,
  "requestOrigin": "plugin"
}
```

```json
{"data": {"passcode": "140569", "expire": 1800, "result": "..."}, "errorCode": 0}
```

`expire` 取值 60–1800 秒（App 界面是 1–30 分钟，步长 1 分钟）。

`result` 字段里经常带一段 Dubbo 超时报错，但**密码通常已经生成成功**，忽略即可。

### 4.6 网关透传（只读）

```http
POST /sl/home/device/gateway/transport
{
  "devCode": "65432109876543",
  "transportBody": {
    "topic": "/subdevice/operation",
    "data": {"gatewayId": "65432109876543", "operation": "ip"}
  }
}
```

```json
{"data": {"gatewayIp": "192.168.31.64"}, "errorCode": 0, "msg": "success"}
```

目前只见过 `operation: "ip"`。**没有发现远程开门的 operation**，
这也印证了该门锁不支持远程开门。

### 4.7 其它接口

| 接口 | 说明 |
|---|---|
| `/sl/home/house/domain/list` | 房间列表 |
| `/sl/home/house/list` | 房屋列表（实测返回空） |
| `/sl/home/house/scene/list` | 场景列表 |
| `/sl/home/user/get/userInfo` | 用户信息 |
| `/sl/home/device/get/info` | 设备静态信息 + 首次状态快照 |
| `/sl/home/device/subdevice/config` | 写设备配置（如低电量阈值） |
| `/sl/cas/authorize/logout` | 登出 |

---

## 5. `openRecord` 编码速览

真实编码是 **`(类别 << 8) | 成员序号`**，不是简单的位标记：

| 值 | 十六进制 | 类别 | 成员 | 场景 |
|---|---|---|---|---|
| 512 | `0x0200` | `0x02` | 0 | 成员 0 的指纹（已确认） |
| 513 | `0x0201` | `0x02` | 1 | 成员 1 的指纹（已确认） |
| 4352 | `0x1100` | `0x11` | 0 | 键盘密码（已确认） |
| 8448 | `0x2100` | `0x21` | 0 | 临时密码（已确认） |

> 早期这里写的是「`bit (9+N)` = 用户槽 N」，那是**错的**（只在 N=0 时巧合成立，
> 并且会把第二枚指纹的 `0x0201` 也算成用户 0）。
> 完整证据、翻车过程和现在的解码实现见 **[§10](#10-openrecord-编码类别--8--成员序号)**。

设备信息里的 `RegisterLockUser: [512]` / `register_users` 仍然有用：
它们是"锁上到底注册了哪些凭证"的权威来源，集成用它和云端凭证台账做交叉核对。

---

## 6. 抓包方法论（供复现）

普通 HTTP 代理是抓不到的，因为：

1. **Flutter 不读系统 HTTP 代理** —— Dart 的 `HttpClient` 默认直连，
   Proxyman / Charles 完全看不到请求。
2. **Clash fake-ip** —— 客户端连的是 `198.18.x.x`，不是真实 IP，
   任何按真实 IP 写的路由规则都会失效。
3. **conntrack 钉死老连接** —— 新加的 NAT 规则对已建立连接无效。

最终可用的方案：**SNI 感知的透明 MITM 代理**。

```
iPhone ──► 路由器 DNAT ──► Mac:8443               ──► 真实服务器
          (按目标 IP)      ├─ SNI 命中目标域名 → 解密记录
                           └─ 其它域名 → 原始 TCP 透传
```

关键点：

- 钉在 **fake-ip 段**（`198.18.0.0/16:443`）而不是真实 IP
- 用 MAC 匹配设备，避免 IP 变化
- 读 TLS ClientHello 的 **SNI** 决定是否解密；非目标域名直接透传，
  这样劫持整个段也不会影响手机其它 App
- 手机需安装并信任自签 CA（`*.smartmideazy.com` 的证书）

---


### 6.1 抓包环境的清理

抓完就不需要了，按顺序拆掉（**不影响集成本身**）：

```bash
# 1. 停掉 Mac 上的代理
pkill -f proxy2.py

# 2. 撤掉路由器上的劫持规则（当前是按手机 MAC 匹配）
ssh <router> 'nft -a list chain inet fw4 dstnat | grep 198.18.0.0/16'
ssh <router> 'nft delete rule inet fw4 dstnat handle <HANDLE>'

# 3. iPhone 移除根证书
#    设置 → 通用 → VPN与设备管理 → REMAC Test CA → 移除描述文件
#    设置 → 通用 → 关于本机 → 证书信任设置 → 关闭 REMAC Test CA
#    设置 → 无线局域网 → ⓘ → 配置 DNS → 改回「自动」

# 4. 如果之前加过 dnsmasq 的 address 覆盖，确认已清空
ssh <router> 'uci show dhcp | grep address'
```

---

## 7. 版本变更风险

以下信号出现时，说明协议挂了：

| 现象 | 可能原因 |
|---|---|
| 登录返回 `3153` 但密码没错 | RSA 公钥或加密方式变了 |
| 所有接口 `3000` 且重登也失败 | 登录接口改版 |
| `/device/v2/list` 一直 `9999` | `fields` 数组要求变了 |
| 门锁状态永远不更新 | 状态字段改名 |

遇到请提 issue 并附上 HA 的 debug 日志（已在诊断信息里脱敏了 token 和手机号）。

---

## 8. 为什么官方 App 能「立刻」知道开锁

这是最容易被忽略、也最关键的一环。

### 完整链路

```
门锁 ──Zigbee(本地无线, ~100ms)──► 网关 ──HTTPS 出站(~1s)──► 云端
                                                          │
                                          ┌───────────────┘
                                          ▼
                              阿里云 EMAS 推送（常连接 :9001）
                                          │
                                          ▼
                                     手机 App UI 立刻更新
```

### 实测证据

抓包期间手机始终保持着一条到阿里云推送服务的**持久 TCP**：

```
192.168.31.176 → emas-link-service.aliyuncs.com : 9001  (DIRECT)
```

在 236 条抓到的 HTTP 请求里：

- **没有任何 WebSocket 升级请求**（无 `Upgrade: websocket`）
- **没有 SSE / long-poll 端点**
- 所有 `/sl/home/...` 都是普通的一问一答

所以：**云端到 App 的实时性，走的是阿里云 EMAS（移动推送/移动链路）的私有长连接，
不是 HTTP 长轮询。**

### 对第三方集成的含义

| 方案 | 可行性 | 延迟 |
|---|---|---|
| 复刻 EMAS 推送协议 | ❌ 需要 App 的 appKey/secret + 实现私有帧协议 | — |
| 云端 WebSocket/SSE | ❌ 不存在 | — |
| 网关本地 API | ❌ **全端口扫描 0 个开放端口**，纯出站设备 | — |
| **轮询活动日志** | ✅ 唯一可行 | **等于轮询间隔** |
| Zigbee 抓包 | 🟡 需要嗅探器和网络密钥 | 真正实时 |
| 门锁直连 ZHA | ✅ 但会脱离睿住生态 | 真正实时 |

### 网关封闭性验证

对 `192.168.31.64`（云端返回的网关 IP）做了 1–65535 全端口 TCP 扫描：

```
开放端口：无
```

该网关只做出站连接，不监听任何端口，因此**不存在可用的本地集成入口**。

### 结论

云端日志本身是**实时写入**的（开锁后约 1–3 秒内就能查到）。
所以本集成把 `scan_interval` 做成可配置项：

- 默认 **5 秒**（约每分钟 12 次请求）
- 最小 **3 秒**，最大 **60 秒**

想要更接近实时，只能靠 Zigbee 侧方案，代价是脱离官方 App。

---

## 9. 账号是单会话的（重要）

### 实测证据

同一时刻、同一客户端、同一请求，只差 token 的签发时间：

| token | 签发时间 | 测试结果（01:20:51） |
|---|---|---|
| `e63O5…` | 00:31:30 | ❌ 3000 authenticationError |
| `<token>` | 00:34:17 | ❌ 3000 authenticationError |
| `OE4qUh…` | 01:00:36 | ❌ 3000 authenticationError |
| `wDuDKj…` | 01:12:48 | ✅ 仍然有效 |

**只有最新的 token 活着。**

这不能用「到期」解释：同一枚 token 连续成功用了 **26 分钟**，
而 `OE4qUh…` 只活了 20 分钟就死了。**唯一解释是每次登录都会作废之前的 token。**

### 结论

```
新登录 → 旧 token 全部失效
```

也就是说：**官方 App 和任何第三方客户端不能同时保持登录**，会互相踢下线。

### token 本身不绑设备

反过来，token 又是完全可移植的：

```
用 App 的 token 从另一台机器调用      → code=0 成功
故意篡改 app-agent 里的 deviceId     → code=0 成功
```

所以正确的共存姿势是：**第三方客户端绝不登录，只借用 App 当前的 token。**

### 官方 App 为什么"很久不用也不问密码"

它把密码存在本地，token 失效就静默重新登录。抓到的登录间隔：

```
00:31:30            ← 用户手动
00:34:17  (+2.8 分)  ← 用户手动
01:00:36  (+26.3 分) ← 自动（用户没有操作手机）
01:12:48  (+12.2 分) ← 自动
```

这也解释了为什么 `/cas/authorize/token/refresh` 在服务端坏掉却没人发现——
App 压根不用它，直接重新登录。

### 对本集成的设计影响

集成提供两种凭据模式：

| 模式 | 会踢掉 App 吗 | 说明 |
|---|---|---|
| `token_source`（推荐） | ❌ 不会 | 从外部源借用 App 当前 token，**永不调用登录接口** |
| 手机号 + 密码 | ✅ 会 | 每次重登都会踢掉 App，App 重登又踢回来，形成对踢循环 |

`token_source` 模式需要一个小工具持续提供 token。参考实现见项目 wiki：
用透明代理截获 App 请求的 `Authorization` 头，暴露成
`GET /latest-token -> {"token": "...", "device_id": "..."}`。

---

## 10. `openRecord` 编码：`(类别 << 8) | 成员序号`

### 规则（v1.3.2 更正）

```python
category = value >> 8      # 开锁类别
member   = value & 0xFF    # 成员/凭证序号（0 起）

0x02 -> 指纹（成员凭证）   0x11 -> 键盘密码   0x21 -> 临时密码
```

### 旧规则是错的，以及它是怎么暴露的

早期结论是「`bit (9 + N)` = 凭证 N」。它只在 **N = 0** 时巧合成立
（`9 + 0 = bit 9` → `0x0200` = 512），因此一直没人怀疑。实际上：

- 旧规则预测用户 1 → `bit 10` → `0x0400`（1024）——**从未出现过**
- 真机上用户 1 的指纹记录是 `0x0201`（513）

暴露过程：家里有人 18:00 左右用**第二枚指纹**开门，HA 却显示
「指纹开锁 · 屋主」。导出 5 天共 20 条解锁记录后规律非常干净：

| openRecord | hex | 出现时间 | 旧规则解码 | 真实含义 |
|---|---|---|---|---|
| 512 | `0x0200` | 06:43 / 09:31 / 11:25 / 19:42 / 20:03 / 21:05 / 22:06 / 22:48 / 23:07 … | 用户 0 | **成员 0（屋主）的指纹** |
| 513 | `0x0201` | 10-25 17:35、10-26 18:56、10-27 18:57、10-28 18:10 | 用户 0 ❌ | **成员 1（第二枚指纹）** |
| 4352 | `0x1100` | — | 密码 | 键盘密码（类别 `0x11`，成员 0） |
| 8448 | `0x2100` | — | 临时密码 | 临时密码（类别 `0x21`，成员 0） |

513 那四条全部落在傍晚 17:30–19:00 的到家时段，而 512 散布在全天——
一眼能看出是"另一个人每天傍晚回家"。旧规则把低字节整个忽略了（只看
`value & (1 << bit)`），所以 513 也命中了 bit 9 → 报成用户 0。

### 实测样本

| openRecord | hex | 类别 | 成员 | 含义 |
|---|---|---|---|---|
| 512 | `0x0200` | `0x02` | 0 | 成员 0 的指纹 |
| 513 | `0x0201` | `0x02` | 1 | 成员 1 的指纹 |
| 4352 | `0x1100` | `0x11` | 0 | 键盘密码 |
| 8448 | `0x2100` | `0x21` | 0 | 临时密码 |

### 派生方式（集成实现）

1. `category = value >> 8`，`member = value & 0xFF`
2. 已知类别 → 方式（`0x02` 指纹 / `0x11` 密码 / `0x21` 临时密码）
3. 指纹类用 `member` 去凭证台账里查 `userNo`：
   - 查到 → 标 `credential_confirmed: true`，带上 `user_no` / `user_name`
     （`userRole`，没填名字时为 `null`）与 `user_type`，UI 显示
     `指纹开锁 · 屋主` 或 `指纹开锁 · 凭证2`
   - 查不到（台账还没拉到 / 是不在 App 里的凭证）→ `credential_confirmed: false`，
     UI 显示 `指纹开锁 · 待确认`，**绝不猜人名**
4. 未知类别 → 回退精确值表，再不行就标 `未知` 并把原始 `bits` 放进
   `unmatched_bits`

> 教训：只看「命中了哪个位」而不校验整数值是否完全符合规则，就会把
> "带额外标记位的记录"错误归到别人头上。现在的实现要么整条记录完全符合
> 规则（才敢报人名），要么只报方式。

### 凭证里的人工命名在哪

`/sl/home/device/subdevice/lock/user/list` 返回的 **`userRole`** 字段
（设备信息里叫 `user_role`）就是你给凭证起的名字：

```json
{"userNo":"0","typeName":"普通指纹","userType":"2","userRole":"屋主"},
{"userNo":"1","typeName":"普通指纹","userType":"2","userRole":""}
```

`typeName` 是凭证**种类**，`userRole` 才是**人名**（上面第二个就是"没起名字的
第二枚指纹"，`userRole` 为空字符串）。搞混了就会把"普通指纹"当成用户名——
这个坑踩过，而且导致"未命名凭证"和"有名字的凭证"在 UI 上看起来一样。

另外 `userType` 参数传 1~5 都返回同样的结果，**没有任何过滤作用**，
所以只需一次请求，不用按类型扫。

## 11. `/device/log/list` 会偶发返回 9999

活动日志接口在长期轮询下**偶尔**返回：

```json
{"data": null, "errorCode": 9999, "msg": "智能服务未响应"}
```

实测 2.5 小时内出现 4 次，参数完全没变——同一份请求体前后都能成功。
所以这不是参数问题，是后端抖动或轻微限流。

**对策**（集成已实现）：

- 抓取失败时保留上一次的缓存记录，不让实体变不可用
- 只在连续失败的第 1 / 10 / 100 次各打一条警告，避免刷日志
- 下一轮自动重试

如果你把 `scan_interval` 调到 3 秒，这类错误会变多。默认 5 秒是实测比较稳的值。
