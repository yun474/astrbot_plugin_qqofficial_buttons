<div align="center">

# QQ 官Bot按钮工具

把 QQ 官方 Bot 的按钮消息交给 LLM 使用，再配一间能拖拖拽拽的独立按钮工作台。

**作者：云云** · AstrBot 4.24.2+

</div>

## 能干什么

- 注册 `send_qq_official_buttons` LLM Tool，让模型在当前 QQ 官 Bot 会话发送按钮。
- 默认只允许 LLM 使用你明确公开的预设，模型不能自己挑群、挑用户乱发。
- 在插件详情页提供独立的“按钮工作台”，不用手搓 JSON。
- 可拖动按钮换行，也可以用位置按钮调整顺序。
- 支持群聊、C2C 私聊、频道、频道私信。
- 支持指令、输入框文字、HTTPS 链接、固定回复、跳转到另一按钮组。
- 支持所有人、管理员、指定 OpenID、频道身份组权限。
- 支持 JSON 导入导出。
- 内部功能按钮使用 HMAC 签名，不能靠改一段指令凭空调用别的功能。

## 安装

把本仓库放进 AstrBot 的 `data/plugins/astrbot_plugin_qqofficial_buttons`，然后在插件管理中重载。

最低要求：

- AstrBot `>= 4.24.2`，因为独立编辑器使用了 Plugin Pages。
- 平台适配器为 `qq_official` 或 `qq_official_webhook`。
- QQ 开放平台账号已经获得内嵌键盘/按钮消息能力。

如果腾讯没给你的机器人开放按钮能力，插件代码写得再漂亮也只会被接口一巴掌拍回来，这个真不是云云能隔着屏幕硬开权限的。

## 使用

安装后打开：

```text
AstrBot WebUI → 插件管理 → QQ 官Bot按钮工具 → 按钮工作台
```

工作台里可以新建按钮组、编辑布局和动作。保存后，在 QQ 会话发送：

```text
/按钮 starter_menu
```

不带 ID 会列出当前启用的按钮组：

```text
/按钮
```

### 给 LLM 使用

插件注册的工具名是：

```text
send_qq_official_buttons
```

在按钮工作台打开“允许 LLM 调用”，模型才能通过 `preset_id` 看到并发送该按钮组。AstrBot 自己的工具管理页仍可随时停用整个工具。

“允许 LLM 临时生成按钮”默认关闭。开启后，LLM 只能临时生成以下动作：

- `command`
- `input`
- `link`

临时按钮不能调用插件功能按钮，也不能指定发送目标，只能发回当前会话。

## 动作类型

| 动作 | 效果 | 备注 |
| --- | --- | --- |
| 发送指令 | 点击后立刻发送动作内容 | 可以填写 `/help` 等 AstrBot 指令 |
| 填入输入框 | 只把文字放入输入框 | 用户确认后再发送 |
| 打开链接 | 打开网页 | 默认仅允许 HTTPS |
| 回复固定文字 | 插件回复预设文字 | 使用签名指令桥，不执行任意代码 |
| 打开另一按钮组 | 发送另一个预设 | 适合做多级菜单 |

插件故意不提供“执行任意 Python/Shell”功能。一个网页表单就能把机器人变成远程命令执行器，那不是自由，是服务器在裸奔。

## 关于原生 Callback

QQ 按钮协议还存在 `type=1` 原生 Callback，会产生 `INTERACTION_CREATE` 事件。但截至 AstrBot 4.26.5，内置 QQ 官方适配器没有开启 interaction intent，也没有把该事件送入插件事件链。

因此本插件稳定版使用 `type=2` 指令桥承载自定义功能，没有用 monkey-patch 强改适配器。等 AstrBot 上游正式支持 interaction 后，可以只替换发送/事件适配层，按钮数据和 WebUI 都不用推倒重写。

## 数据与安全

数据保存在：

```text
data/plugin_data/astrbot_plugin_qqofficial_buttons/buttons.json
```

- WebUI API 由 AstrBot Dashboard 登录态保护。
- 写入使用临时文件加原子替换，尽量避免异常退出写坏 JSON。
- 内部动作带 HMAC 签名。
- 指定用户权限使用 QQ 官方接口提供的 OpenID，不是传统数字 QQ 号。
- 插件会在执行功能动作时再次检查管理员、用户和身份组权限。
- 导出文件不包含签名密钥。

## 配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| 按钮消息承载模式 | 自动 | 优先 Markdown，被拒绝时回退普通正文 |
| 允许 LLM 临时生成按钮 | 关闭 | 建议先只用预设 |
| 启用插件功能按钮 | 开启 | 固定回复和按钮组跳转 |
| 允许 HTTP 链接 | 关闭 | 关闭时只接受 HTTPS |
| 最大行数 | 5 | 插件会钳制到 1～5 |
| 每行最大按钮数 | 5 | 手机端建议放 2～3 个 |

## 已知限制

- QQ 是否展示按钮、可用样式、审核范围和频率限制最终由腾讯平台决定。
- 频道身份组权限需要入站事件带有成员身份组数据；缺少数据时服务端二次校验会拒绝功能按钮。
- 修改 AstrBot 唤醒前缀后，内部 `/qqbtn_action` 指令可能也要跟随适配。默认 `/` 前缀可直接使用。
- 插件只向触发 Tool 或命令的当前会话发按钮，不提供从 WebUI 直接指定 OpenID 群发。

## 正文有了但按钮没出现

先把“按钮消息承载模式”保持为 `auto`，重载插件后发送：

```text
/按钮 starter_menu
```

然后在 AstrBot 日志搜索 `[QQ官Bot按钮] 发送接口已返回`。日志会显示实际使用的
`markdown` / `content-fallback` 模式、按钮数量和接口返回类型。若日志显示接口成功，QQ
里仍只有正文，通常是机器人尚未取得 QQ 开放平台的内嵌键盘/消息按钮权限；这项权限
无法由插件在本地开启。

## 开发检查

```powershell
python -m compileall -q .
python -m json.tool _conf_schema.json
python -m unittest discover -s tests -v
```

## 致谢

按钮数据和交互思路参考了 [Zhalslar/astrbot_plugin_buttons](https://github.com/Zhalslar/astrbot_plugin_buttons)。原插件使用的是 NapCat 私有发包，并已明确标注失效；本插件只参考体验，发送层完全改用 QQ 官方 API。

## License

MIT
