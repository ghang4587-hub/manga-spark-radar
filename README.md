# Manga Spark Radar

将本目录放在静态托管（如 GitHub Pages）或本地 HTTP 服务中打开 `index.html` 即可使用；页面不需要安装依赖。由于浏览器会限制 `file://` 读取 JSON，直接双击时截图会降级为封面，建议使用 HTTP 服务以加载 storyboard 与剧情节点数据。

## 当前版本

- 主题：国内外漫剧 / 动态漫热点
- 样本：40 条趋势样本池（国内 20、海外 20）
- 首页视图：16 条本周重点（国内 8、海外 8）
- 深度跟踪：8 条（国内 4、海外 4）
- 来源：B站、爱奇艺、Baichuan Comics、Supreme Anime Drama
- 快照日期：由周更脚本写入（当前基线：2026-09-01）
- 更新方式：`.github/workflows/weekly-update.yml` 每周一 08:00（北京时间）运行
- 样本策略：完整池固定 40 条；海外周更池固定 20 条并按频道配额，国内保留 20 条合规公开样本；默认重点和深度视图按国内外配额展示，剔除明确不可播放/下架视频，并在同区域有更高价值候选时淘汰低播放旧样本
- 详情能力：每条视频从完整时长内的字幕识别剧情 / 冲突节点，选出 10 个非均匀 storyboard 画面；每张图下方显示字幕线索，支持点击跳时、用户心流与买量改编提示
- 节点数据：`story_nodes.json`（YouTube 字幕语义评分结果；描述用于定位线索；国内样本不伪造字幕节点）
- 卡片能力：近 7 日新样本、受众结构、结构梗概、Hook 估分
- 周更配置：`config/channels.json`（频道、样本量、低播放阈值）
- 周更脚本：`scripts/weekly_update.py`（RSS 发现、可播放性检查、播放量排序、按频道配额写回 20 条海外样本）
- 国内样本：`data/domestic_samples.js`（B站与爱奇艺公开标题、封面、题材和来源链接；爱奇艺无统一公开播放量时显示站内字段）
- 本地封面：`assets/covers/`（海外样本对应漫剧封面；国内样本使用平台公开封面，并在加载失败时显示明确占位状态）
- 播放说明：播放器改用标准 YouTube 嵌入；若出现“请登录”验证，可点击播放器下方“在 YouTube 打开原片”，登录后从对应时间点继续观看。

详细判断见 `ANALYSIS.md`。

## 部署

将本目录中的文件放到任意静态托管服务即可使用。若使用 GitHub Pages，请保留 `.github/workflows/weekly-update.yml`、`scripts/weekly_update.py`、`config/channels.json` 和 `data/domestic_samples.js`，并给 Actions `contents: write` 权限；工作流会在每周一抓取两条海外频道的公开 RSS，按频道配额更新 20 条海外样本后自动提交并触发 Pages 发布。国内样本首版使用人工核验的公开字段，后续接入平台合规 API 时再纳入自动周更。

YouTube 偶尔会限流、改变页面结构或暂时关闭 RSS。脚本会在 RSS 失败时回退到频道视频页，并在临时网络错误时保留上一周样本，不会把网站更新成空列表；只有收到明确的不可播放状态才会剔除视频。`min_views` 只是排序/淘汰阈值，不是 YouTube 官方指标。
