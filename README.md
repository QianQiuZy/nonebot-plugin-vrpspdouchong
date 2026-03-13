# nonebot-plugin-vrpspdouchong

基于 NoneBot2 的 VR / PSP 斗虫统计插件，提供月度榜单、开播列表、单主播直播场次、SC 记录和流水概览查询，并将结果渲染为图片发送。

当前实现主要面向 OneBot v11 适配器，数据来源依赖外部 VR / PSP 统计接口。

## 功能

- `VR斗虫` / `PSP斗虫` / `大乱斗斗虫`
  - 查询指定月份或指定年份累计的礼物统计榜单
- `VR开播` / `PSP开播` / `大乱斗开播`
  - 查询当前正在直播的房间列表
- `查直播`
  - 查询指定主播某月的直播场次明细
- `查SC`
  - 查询指定主播某月的 SC 记录，数据过多时自动分页并用合并转发发送
- `查流水`
  - 查询指定主播某月的礼物 / SC / 上舰流水概览

## 依赖

- `nonebot2`
- `nonebot-adapter-onebot`
- `httpx`
- `Pillow`
- `fonttools`
- 可选：`regex`

如果没有安装 `fonttools`，字体回退链无法正常工作；如果没有安装 `regex`，插件仍可运行，但复杂 emoji / 字素切分能力会退化。

## 安装

当前仓库为Nonebot2本地插件使用。

1. 将插件放入你的 NoneBot 项目插件目录中（一般为src/plugin）。
2. 建议把目录名改成合法 Python 包名，例如 `nonebot_plugin_vrpspdouchong`。
3. 在 bot 项目中安装运行依赖。

示例：

```bash
pip install httpx pillow fonttools regex
```

然后在 `pyproject.toml`、`bot.py` 或你的插件加载配置中加载该插件。

如果你使用的是 `nonebot.load_plugins()` / `nonebot.load_plugin()`，请按你项目现有的本地插件加载方式接入即可。

## 资源文件

插件依赖 `resource/` 目录中的字体文件进行图片渲染，请不要删除下列文件：

- `resource/NotoSansSC.ttf`
- `resource/NotoSans.ttf`
- `resource/NotoEmoji.ttf`
- `resource/NotoSansSymbols2.ttf`
- `resource/NotoSansYi.ttf`
- `resource/NotoSerifTibetan.ttf`

## 配置项

插件配置定义见 [config.py](https://github.com/qianqiuzy/nonebot-plugin-vrpspdouchong/config.py)。

可用配置如下：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `vr_gift_api_base` | `https://vr.qianqiuzy.cn/gift` | VR 礼物统计 API 基址 |
| `psp_gift_api_base` | `https://psp.qianqiuzy.cn/gift` | PSP 礼物统计 API 基址 |
| `vr_douchong_title` | `VR斗虫` | VR 斗虫榜单图片标题 |
| `psp_douchong_title` | `PSP斗虫` | PSP 斗虫榜单图片标题 |
| `vr_live_title` | `VR开播` | VR 开播列表图片标题 |
| `psp_live_title` | `PSP开播` | PSP 开播列表图片标题 |

## 指令说明

### 斗虫榜单

支持指令：

- `/VR斗虫 [统计周期]`
- `/PSP斗虫 [统计周期]`
- `/大乱斗斗虫 [统计周期]`

统计周期支持以下格式：

- 留空：默认当前月
- `YYYYMM`
- `YYYY-MM`
- `YYYY`

其中：

- 指定 `YYYY` 时，历史年份会统计 `1-12` 月累计
- 指定当年时，会统计当年 `1-当前月` 累计

示例：

```text
/VR斗虫
/VR斗虫 202603
/VR斗虫 2026-03
/VR斗虫 2025
/PSP斗虫 2024
/大乱斗斗虫 2026
```

榜单字段包括：

- 主播名称
- 粉丝数
- 直播状态
- 直播时间
- 有效天
- 舰长 / 提督 / 总督数量
- 粉丝团数量
- 盲盒数 / 盲盒盈亏
- 礼物 / SC / 上舰金额
- 总计

### 开播列表

支持指令：

- `/VR开播`
- `/PSP开播`
- `/大乱斗开播`

返回当前正在直播的房间列表，包含：

- 开播时间
- 主播名称
- 已开播时长
- 即时同接
- 直播标题

### 查直播

指令格式：

```text
/查直播 主播名称 [YYYYMM|YYYY-MM]
```

示例：

```text
/查直播 花礼
/查直播 花礼 202603
/查直播 花礼 2026-03
```

功能说明：

- 先在 VR / PSP 数据源中按主播名称模糊匹配房间
- 再查询该主播指定月份的直播场次
- 返回图片明细表

表格字段包括：

- 开播时间
- 下播时间
- 本场直播时间
- 弹幕数
- 平均同接
- 最高同接
- 本场直播标题
- 盲盒数 / 盲盒盈亏
- 礼物 / 舰长 / SC / 总计

### 查SC

指令格式：

```text
/查SC 主播名称 [YYYYMM|YYYY-MM]
```

示例：

```text
/查SC 花礼
/查SC 花礼 202603
```

功能说明：

- 先按主播名称定位房间
- 查询指定月份 SC 记录
- 单页时直接发图
- 多页时通过合并转发发送

### 查流水

指令格式：

```text
/查流水 主播名称 [YYYYMM|YYYY-MM]
```

示例：

```text
/查流水 花礼
/查流水 花礼 2026-03
```

功能说明：

- 同时拉取 VR 与 PSP 指定月份数据
- 按主播名称模糊匹配
- 返回该主播当月的流水概览卡片

## 返回形式

- 大部分指令返回单张图片
- `查SC` 在记录较多时会拆分为多张图片，并通过 OneBot v11 的合并转发接口发送

因此如果你的平台或适配器不支持合并转发，`查SC` 的多页发送能力可能无法正常工作。

## 注意事项

- 插件当前实现依赖 OneBot v11，其他适配器不能直接使用
- 外部接口不可用时，相关指令会返回“请求数据失败”
- 主播匹配采用包含判断，不是严格精确匹配
- 图片渲染依赖字体资源和 Pillow，部署时需要确保运行环境具备这些依赖
- `大乱斗` 系列指令会合并 VR 和 PSP 数据，但当前不会在表格中额外标注来源平台

## 项目结构

```text
nonebot-plugin-vrpspdouchong/
├── __init__.py
├── config.py
├── toolkit.py
├── commands/
│   ├── douchong.py
│   ├── live_list.py
│   └── query.py
└── resource/
```

## 开源协议

本项目使用 [MIT License](https://github.com/qianqiuzy/nonebot-plugin-vrpspdouchong/LICENSE)。
