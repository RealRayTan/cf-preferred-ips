# Cloudflare 入口 IP 定时筛选

GitHub Actions 每天北京时间 09:15、21:15 运行，可在 Actions 手动执行。Mac 无需开机。GitHub 定时任务可能排队，不能保证准点。

使用 [CFData-WEB v1.8.3](https://github.com/PoemMisty/CFData-WEB) 的 HTTPing 初筛；从 Cloudflare 官方 IPv4 网段抽样约 480 个地址，并复测上次有效结果。每次抽样不同，不是扫描整个地址空间。

初筛后对最多 60 个候选各检查三次 HTTPS，请求必须全部成功、数据中心保持一致、单次耗时不超过 1500ms。按最大耗时、再按中位数排序，最多保留 20 个。这是连通性检查，没有进行下载速度测试。

## 列表

- `ip.txt`：实际数据中心位于 JP/KR/SG 的入口。按 trace 的 colo 和 Cloudflare 官方状态页的城市、国家对应表判断；没有亚洲合格结果时保留旧文件。首次未筛出结果时不会创建此文件。
- `global.txt`：不限制地区的云端结果，供备用对比。不会自动混入亚洲列表。
- `status.json`：本次扫描时间、地区分布、合格数量和最后一次亚洲列表更新时间。

云端结果反映 GitHub 服务器线路。Cloudflare Anycast 的路由随访问地点变化，同一个 IP 在家里可能连接到不同数据中心。入口地区不代表 EdgeTunnel 出口地区，也不能保证 Gemini 等服务可用。

## 接入 EdgeTunnel

当 `ip.txt` 存在且状态显示有有效结果后，将以下链接填入 EdgeTunnel「自定义优选」的「追加 API」，保存后刷新小火箭原有订阅：

`https://raw.githubusercontent.com/RealRayTan/cf-preferred-ips/main/ip.txt`

如果首次没有亚洲结果，暂时继续使用原来的美国节点；想对比普通云端候选可自行改用 `global.txt`。小火箭继续订阅 EdgeTunnel 原地址，GitHub 文本不是 VLESS 订阅。

仓库公开，仅包含入口 IP 和测速结果；不存储 EdgeTunnel 管理密码、UUID、订阅密钥或 SOCKS5 凭据。无需手动配置 GitHub Secrets。

## 排查

在 Actions → Update preferred IPs → Run workflow 手动更新；扫描原始结果保留在运行附件里 7 天。`no_asian_candidates` 表示任务完成但没有找到所需地区，不代表筛选成功。GitHub 公共仓库长时间没有活动可能停用定时运行；必要时在 Actions 重新启用。

参考：[EdgeTunnel 优选 API](https://blog.cmliussss.com/p/edt2/)；[GitHub 定时任务](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
