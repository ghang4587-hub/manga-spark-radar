# Manga Spark Radar

将本目录放在静态托管（如 GitHub Pages）或本地 HTTP 服务中打开 `index.html` 即可使用；页面不需要安装依赖。由于浏览器会限制 `file://` 读取 JSON，直接双击时截图会降级为封面，建议使用 HTTP 服务以加载 storyboard 与剧情节点数据。

## 当前版本

- 主题：英文配音动态漫 / 漫剧热点
- 样本：30 条公开 YouTube 视频
- 来源：Baichuan Comics、Supreme Anime Drama
- 快照日期：2026-08-28
- 更新方式：手动快照；**没有自动周更**
- 详情能力：每条视频从完整时长内的字幕识别剧情 / 冲突节点，选出 10 个非均匀 storyboard 画面；每张图下方显示字幕线索，支持点击跳时、用户心流与买量改编提示
- 节点数据：`story_nodes.json`（YouTube 字幕语义评分结果；描述用于定位线索）
- 卡片能力：近 7 日新样本、受众结构、结构梗概、Hook 估分

详细判断见 `ANALYSIS.md`。

## 部署

将本目录中的 `index.html` 放到任意静态托管服务即可。若使用 GitHub Pages，可把它放在仓库根目录并开启 Pages。
