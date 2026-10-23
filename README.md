# REMAC 云邻 e家 · Home Assistant 集成

[![hassfest](https://img.shields.io/github/actions/workflow/status/kaen/ha-remac-ehome/hassfest.yml?label=hassfest)](https://github.com/kaen-w/ha-remac-ehome/actions/workflows/hassfest.yml)
[![HACS](https://img.shields.io/github/actions/workflow/status/kaen/ha-remac-ehome/hacs.yml?label=HACS)](https://github.com/kaen-w/ha-remac-ehome/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/kaen/ha-remac-ehome)](LICENSE)

把**睿住（REMAC）X-Brain 系列网关**下的智能门锁接入 Home Assistant。
支持实时开锁事件、状态监控、电量告警与**临时密码生成**。

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
| **开锁实时事件** | ✅ | 15 秒轮询，触发 HA 事件，可直接做自动化 |
| 开锁动态历史 | ✅ | 最近 10 条记录 + 完整属性 |
| **生成临时密码** | ✅ | 1–30 分钟，步长 1 分钟（与官方 App 一致） |
| 用户台账（指纹/密码/卡） | 🟡 | 接口已接，映射待补全 |
| 远程开锁 | ❌ | 该门锁系列**不提供**远程开门，只有凭证管理 |
| 智慧屏开关控制 | ❌ | 控制命令尚未抓取 |

> **关于远程开锁**：这不是偷懒。实测该门锁的透传通道（`/subdevice/operation`）
> 只暴露只读命令，App 里的门锁页做的是「权限管理」——指纹、密码、临时密码、
> 时段授权。远程开门在硬件/固件层面就没有开放。

---

## 安装

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
| 密码 | ✅ | App 的登录密码 |
| 房屋 ID | ❌ | 默认 `10000001`，多套房时按需修改 |
| 客户端指纹 | ❌ | 默认值可用，一般不用改 |

密码的处理方式：先用 `POST /sl/home/config/getConfig {"type":"rsa"}` 取云端
1024 位 RSA 公钥，再按 `base64(RSA_PKCS1v15(password))` 加密后提交。
密码会保存在 HA 的配置项里（和大多数云集成一样），**不会明文出现在日志或诊断数据中**。

### 为什么要填密码

云端的 `accessToken` **实际只有约 15 分钟寿命**（接口声称 7200 秒，实测不符），
而刷新端点 `/sl/cas/authorize/token/refresh` 在服务端本身就是坏的——
官方 App 自己调用也会收到 `7001 refreshToken not exist`，它是靠**本地存密码重新登录**。

所以本集成采用同样的策略：token 失效时自动用密码重新登录。

---

## 实体

| 实体 | 类型 | 说明 |
|---|---|---|
| `lock.<门锁>` | lock | 门锁状态（只读） |
| `sensor.<门锁>_battery` | sensor | 真实电量百分比 |
| `sensor.<门锁>_door_state` | sensor | `open` / `closed` |
| `sensor.<门锁>_last_activity` | sensor | 最近动态时间，属性含最近 10 条记录与凭证台账 |
| `sensor.<门锁>_temporary_passcode` | sensor | 最近生成的临时密码 + 过期时间 |
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

---

## 实时开锁事件

集成每 **15 秒**拉一次活动日志，每条新记录都会触发 HA 事件：

```
event_type: remac_ehome_door
```

事件数据：

| 字段 | 说明 |
|---|---|
| `type` | `unlock` / `door` / `outside_open` / `battery` |
| `method` | 开锁方式：`临时密码` / `指纹` / `密码` / `未知` |
| `record_hex` | 原始 `openRecord` 值，如 `0x2100` |
| `bits` | 置位列表，如 `[8, 13]` |
| `door_open` | 门磁（`type == door` 时） |
| `user_no` / `user_name` | 开锁凭证（映射确认后填充） |
| `time` | 云端记录时间 |
| `dev_code` | 门锁设备码 |

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

### 延迟说明

事件延迟 ≈ 云端写入日志的时间（实测是实时的）+ 最多 15 秒轮询间隔。
想要更快可以改 `const.py` 里的 `LOG_INTERVAL`，但注意别把云端接口打爆
（当前 15 秒 = 每分钟 4 次请求）。

---

## 已知限制

1. **token 寿命短** —— 必须存密码，否则每 15 分钟就要手动更新一次 token。
2. **开锁方式映射不完整** —— 目前只确认了 `0x2100 = 临时密码`。
   想帮忙补全：用指纹、密码、卡片各开一次门，把
   `sensor.*_last_activity` 的 `recent` 属性发到 issue 里。
3. **用户台账映射待补全** —— `/subdevice/lock/user/list` 按 `userType`
   分桶，代码已扫全类型，但 `openRecord` 位与 `userNo` 的对应关系还需要更多样本。
4. **只支持门锁** —— 网关下的「智慧屏开关」(`remac.padSwitch.001`) 只纳入了设备发现，
   没有建 switch 实体，因为开关控制命令还没抓到。
5. **依赖账号密码** —— 不支持纯 token 长期运行。

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

## License

[MIT](LICENSE)

---

## 致谢

- [Home Assistant](https://www.home-assistant.io/)
- [HACS](https://hacs.xyz/)
- 所有帮忙抓样本、报 bug 的用户
