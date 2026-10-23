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

## 7. 版本变更风险

以下信号出现时，说明协议挂了：

| 现象 | 可能原因 |
|---|---|
| 登录返回 `3153` 但密码没错 | RSA 公钥或加密方式变了 |
| 所有接口 `3000` 且重登也失败 | 登录接口改版 |
| `/device/v2/list` 一直 `9999` | `fields` 数组要求变了 |
| 门锁状态永远不更新 | 状态字段改名 |

遇到请提 issue 并附上 HA 的 debug 日志（已在诊断信息里脱敏了 token 和手机号）。
