# 美的美居 vs 云邻e家：门锁能力对照（静态逆向）

目的：找出 **Midea M3 门锁（`midea.doorlock.031`）在美居里能做、而云邻e家没有开放** 的功能。

## 取样

| 项 | 值 |
|---|---|
| 应用 | 美的美居（`com.midea.ai.appliances`） |
| 版本 | **11.7.15.3**（2026-10-20 构建） |
| 来源 | 腾讯应用宝 CDN `imtt.dd.qq.com`（205 MB） |
| 手段 | `unzip` 取 dex/assets + `androguard` 解析类/字段/常量（纯静态，未连美居云） |

## 美居里的门锁 SDK

APK 内含一整套门锁 SDK：`com.midea.msmart.doorlock`，**107 个顶层类**（另有 198 个内部类）。结构：

```
doorlock/
├── DoorLockManager            统一 API（57 个方法）
├── business/                  transport 层：拦截器链 + 协议 + 安全协商
│   ├── DoorLockTransportManager   37 个透传方法
│   ├── interceptor/impl/      控制/查询/上报/OTA/安全协商 拦截器
│   ├── protocol/Command       命令定义
│   └── security/SecurityManager  公钥协商 + 数据加密
├── firmware/                  BleFirmwareOtaUpgrader / McuFirmwareOtaUpgrader
├── openapi/bean/              设备模型（见下）
├── openapi/callback/          19 个回调（扫描/连接/密钥/记录/OTA/网关…）
├── weex/                      Weex 前端模块（锁的 UI 是运行时下载的插件）
└── util/                      DoorLockLogRecorder（售后日志）等
```

### `DoorLockManager` 暴露的能力（方法名即能力）

| 分类 | 方法 |
|---|---|
| 蓝牙直连 | `scan` `scanAndConnect` `connect` `connectByAdmin` `disconnect` `readRssi` `setScanRule` `setMaxConnectCount` |
| Zigbee / 网关 | `startConfigZigbeeNet` `getZigBeeMac` `getZigBeeVersion` `setHomeId` |
| 开锁 / 反锁 | **`doUnLock`**、`setElectronLock`、`queryElectronLockInfo` |
| 凭证管理 | `addKey` `deleteKey` `queryKeyInfo` `queryKeyInfoFast` `setKeyInfoState` |
| 开锁记录 | `queryUnlockRecordList`、**`clearUnlockRecord`** |
| 状态 / 报警 | `getSystemInfo`（含 `backLockStatus`/`dismantleStatus`/`unlockPermissionMode` 等） |
| 设置 | `applyLocalSetting`、`configVolumeSetting` |
| 固件升级 | `getBleFirmwareInfo` `getMcuFirmwareInfo` `getOtaReadyState` `upgradeBleFirmware` `upgradeMcuFirmware` |
| 透传 / 安全 | `doCommonSendData` `transDataWithAck` `transDataNoAck` `authAdmin` `securityAgreement` |

### 枚举常量（`get_init_value()` 直接读出来的）

`DoorLockKeyInfo.KEY_TYPE_*`：

```
1 = 密码      2 = 指纹      3 = RFID 卡      4 = 机械钥匙
```

凭证有效期（`KEY_VALID_TYPE_*`）：`0 = 永久`、`1 = 按次数`、`2 = 按分钟`、`3 = 按小时`
生效方式（`EXECUTE_TYPE_*`）：`0 = 立即`、`1 = 预约（带 startTime）`

`DoorLockAlarmStatusInfo.ALARM_TYPE_*`：

```
1 = 键盘锁定（密码试错）   2 = 劫持/胁迫开锁   3 = 防拆
4 = 机械钥匙开锁           5 = 低电量          6 = 门铃
```

## 顺带解掉了 `openRecord` 的谜

美居的记录模型是 `DoorLockUnlockRecord{keyId, keyType}` —— 两个字段，不是位域。
用它去套云邻e家的 `openRecord`（=`高字节<<8 | 低字节`）：

| openRecord | 高字节 | 低字节 | 含义 | 证据 |
|---|---|---|---|---|
| `0x0200` (512) | 2 | 0 | keyType=指纹, keyId=0 → 屋主 | 真实记录 + 台账 userNo 0 = 屋主 |
| `0x0201` (513) | 2 | 1 | keyType=指纹, keyId=1 → 第二枚指纹 | 4 条傍晚记录 + 台账 userNo 1 |
| `0x1100` (4352) | 17 | 0 | 键盘密码（云端的独立编码） | 真实记录 |
| `0x2100` (8448) | 33 | 0 | 临时密码 | 真实记录 |

`0x02` 与美居的 `KEY_TYPE_FINGERPRINT = 2` 完全吻合，**印证了 v1.3.2 的修复**
（之前把 `0x0201` 也算成用户 0 是错的）。
据此把 `0x03xx`（感应卡）、`0x04xx`（机械钥匙）也纳入解码（v1.4.3）。

## 与云邻e家的能力差

| 能力 | 云邻e家（已验证） | 美居（静态确认有 SDK 支持） |
|---|---|---|
| 门磁 / 电量 / 在线 | ✅ | ✅ |
| 开锁记录 | ✅ `/device/log/list` | ✅ 且支持**清空记录** |
| 凭证台账（读） | ✅ 只有指纹/密码两类 | ✅ 4 类：密码/指纹/卡/机械钥匙 |
| **增删凭证** | ❌ 只有 `lock/user/update` | ✅ `addKey` / `deleteKey` / `setKeyInfoState` |
| **凭证有效期** | ❌ | ✅ 永久 / 按分钟 / 按小时 / **按次数** |
| **预约生效（startTime）** | ❌ | ✅ |
| 临时密码 | ✅ 只能"生成" | ✅ 走凭证体系，可查列表/状态 |
| **远程开锁** | ❌ 明确不支持 | ✅ `doUnLock` |
| **电子反锁** | ❌ | ✅ 查询 + 设置 |
| **报警推送** | ❌ 只有低电量 | ✅ 6 类：键盘锁定 / 劫持 / 防拆 / 机械钥匙 / 低电量 / 门铃 |
| **固件升级** | ❌ 完全没有 | ✅ 蓝牙固件 + MCU 固件 OTA |
| **Zigbee 配网 / 网关信息** | ❌ 只能在睿住网关侧做 | ✅ 配网 + MAC/版本查询 |
| 门锁设置 | 只有 `LockVolumeLevel` | 音量 / 语言 / 开锁权限模式 / 低电模式 / 恢复出厂 |
| **手机蓝牙直连门锁** | ❌ 纯云 | ✅（不依赖网关） |
| **分享钥匙** | ❌ | ✅ QQ / 微信 / 朋友圈 / 微博 / 短信 |
| 系统信息 / 出厂信息 | ❌ | ✅ |

### 前提条件

美居字符串里明确写着：

> 您可以通过绑定网关以启用远程管理功能
> 请确保网关在线并升级网关到最新版本

也就是说：**手机蓝牙直连不需要网关**（贴门就能管），但**远程**（含远程开锁）必须有美的系网关在线。你的门锁目前绑在睿住 X-Brain4 上，要走美居远程就得另配一台美的网关重新组网 —— 这会和睿住云冲突（同一把 Zigbee 锁不能同时挂两个网关）。

## 结论

1. 云邻e家 = 云端管理 + 凭证/临时密码的最小集合，**故意不开放远程开锁、固件升级、报警、配网**。
2. 门锁硬件本身支持的能力远多于睿住开放的：**远程开锁、电子反锁、6 类报警、固件 OTA、按次数有效期、4 类凭证、蓝牙直连**。
3. 想用上这些，只有两条路：
   - **换美的网关**走美居（要重新组网，放弃睿住 App）；
   - 继续在睿住云上挖 —— 但睿住没有对应接口，除非固件/云端升级开放（基本无望）。

## 局限

本文全部基于 APK 静态分析：能确认「SDK 支持什么」，不能确认「美的云给你这台锁开放什么」。
要坐实第 3 点，需要在美居里真实绑一台美的网关做验证。
