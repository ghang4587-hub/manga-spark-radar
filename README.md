# Manga Spark Radar

将本目录放在静态托管（如 GitHub Pages）或本地 HTTP 服务中打开 `index.html` 即可使用；页面不需要安装依赖。由于浏览器会限制 `file://` 读取 JSON，直接双击时截图会降级为封面，建议使用 HTTP 服务以加载 storyboard 与剧情节点数据。

## 当前版本

- 主题：英文配音动态漫 / 漫剧热点
- 样本：30 条公开 YouTube 视频
- 来源：Baichuan Comics、Supreme Anime Drama
- 快照日期：由周更脚本写入（当前基线：2026-08-28）
- 更新方式：`.github/workflows/weekly-update.yml` 每周一 08:00（北京时间）运行
- 样本策略：固定 30 条；优先本周新发布且播放速度高的内容，剔除明确不可播放/下架视频，并在候选充足时淘汰低播放旧样本
- 详情能力：每条视频从完整时长内的字幕识别剧情 / 冲突节点，选出 10 个非均匀 storyboard 画面；每张图下方显示字幕线索，支持点击跳时、用户心流与买量改编提示
- 节点数据：`story_nodes.json`（YouTube 字幕语义评分结果；描述用于定位线索）
- 卡片能力：近 7 日新样本、受众结构、结构梗概、Hook 估分
- 周更配置：`config/channels.json`（频道、样本量、低播放阈值）
- 周更脚本：`scripts/weekly_update.py`（RSS 发现、可播放性检查、播放量排序、写回 30 条样本）

详细判断见 `ANALYSIS.md`。

## 部署

将本目录中的文件放到任意静态托管服务即可使用。若使用 GitHub Pages，请保留 `.github/workflows/weekly-update.yml`、`scripts/weekly_update.py` 和 `config/channels.json`，并给 Actions `contents: write` 权限；工作流会在每周一抓取两条频道的公开 RSS，更新后自动提交并触发 Pages 发布。

YouTube 偶尔会限流或改变页面结构。脚本遇到临时网络错误时保留上一周样本，不会把网站更新成空列表；只有收到明确的不可播放状态才会剔除视频。`min_views` 只是排序/淘汰阈值，不是 YouTube 官方指标。
