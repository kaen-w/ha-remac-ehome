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

接口声称 `expires: 7200`，但实测：

| 时间 | 事件 |
|---|---|
| 00:34:17 | 登录，拿到 token |
| 00:49:55 | 该 token 仍可用（生成临时密码成功） |
| 00:52:00 | 该 token 已失效（`3000`） |

**实际寿命 ≈ 15 分钟**。

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

## 5. `openRecord` 位域分析

已验证样本（来自真实门锁）：

| 值 | 十六进制 | 置位 | 场景 |
|---|---|---|---|
| 8448 | `0x2100` | `[8, 13]` | **临时密码开锁**（已确认） |
| 512 | `0x0200` | `[9]` | 已注册指纹用户 |
| 4352 | `0x1100` | `[8, 12]` | 未确认 |

另外设备信息里有：

```json
"extraAttr": {
  "RegisterLockUser": [512],
  "register_users": [{"user_no": 0, "type_name": "普通指纹", "user_type": 2}]
}
```

`RegisterLockUser: [512]` 与 `user_no: 0` 同时出现，暗示
`512 = 1 << 9` 可能对应「用户槽 0」。

**这部分还没解完。** 想贡献样本：

1. 用指纹开一次门
2. 用密码开一次门
3. 用感应卡开一次门（如果有）

然后把 `sensor.<门锁>_last_activity` 的 `recent` 属性贴到 issue 里。

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
| `OAd7rl…` | 00:34:17 | ❌ 3000 authenticationError |
| `OE4qUh…` | 01:00:36 | ❌ 3000 authenticationError |
| `wDuDKj…` | 01:12:48 | ✅ 仍然有效 |

**只有最新的 token 活着。**

这不能用「到期」解释：`OAd7rl…` 连续成功用了 **26 分钟**，
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

## 10. `openRecord` 位域（已解出用户编码）

### 规则

```
bit (9 + N)  =  凭证编号 N
```

验证依据：设备自身返回的凭证清单是

```json
"extraAttr": {
  "register_users": [{"user_no": 0, "user_role": "屋主", "type_name": "普通指纹"}],
  "RegisterLockUser": [512]
}
```

`user_no: 0` ↔ `512` ↔ `bit 9`，完全吻合。

### 实测样本

| openRecord | hex | 位 | 含义 |
|---|---|---|---|
| 512 | `0x0200` | `[9]` | **用户 0（屋主）的指纹开锁** |
| 8448 | `0x2100` | `[8, 13]` | **临时密码开锁** |

临时密码占用的是临时槽位（bit 13 → 编号 4），不在凭证清单里，
所以按精确值匹配打上「临时密码」标签。

### 派生方式

集成不再靠固定值查表，而是：

1. 用 `bit (9+N)` 匹配已注册凭证 → 方式取自该凭证的 `type_name`
   （`普通指纹` → `指纹`，`数字密码` → `密码`，`感应卡` → `感应卡`）
2. 匹配不到时，才回退到精确值表
3. 都不匹配 → 标为 `未知`，但把原始 `bits` 一起放到事件里

这样加新指纹 / 新密码都不用改代码。

### 凭证里的人工命名在哪

`/sl/home/device/subdevice/lock/user/list` 返回的 **`userRole`** 字段
（设备信息里叫 `user_role`）就是你给凭证起的名字：

```json
{"userNo":"0","typeName":"普通指纹","userType":"2","userRole":"屋主"}
```

`typeName` 是凭证**种类**，`userRole` 才是**人名**。搞混了就会把
"普通指纹"当成用户名——这个坑踩过。

另外 `userType` 参数传 1~5 都返回同样的结果，**没有任何过滤作用**，
所以只需一次请求，不用按类型扫。
