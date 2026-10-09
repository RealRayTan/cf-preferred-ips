# 客户端配置

## 小火箭

`shadowrocket.conf` 是独立的分流配置，不含节点认证信息。节点仍由原来的 EdgeTunnel 订阅提供；不要把它当成节点订阅导入。

在小火箭「配置」页添加以下地址，下载后选择「使用配置」，首页「全局路由」选择「配置」：

```
https://raw.githubusercontent.com/RealRayTan/cf-preferred-ips/main/clients/shadowrocket.conf
```

配置将国内地理 IP、局域网、Apple/iCloud 和已有 Steam 下载域名设为直连，其余请求使用 `CF-故障切换`。这是单独的基础分流配置，启用后会替代当前配置的分流行为；已有自定义规则可以保留原配置，只合并本文件的 `[Proxy Group]`，再将需要代理的规则指向该组。

分组通过正则匹配 `CF-01` 至 `CF-09`，也兼容迁移前的 `CF-01-Q71` 等评分名称。订阅更新后匹配当前节点，不需要逐个添加。若多个订阅中存在同名节点，进入「配置 → 配置文件 ⓘ → 代理分组 → CF-故障切换」，打开「订阅」开关，在「服务器节点」中限定为自己的 EdgeTunnel 订阅。

首次使用时打开该分组，确认包含订阅节点并测试。检测地址为 `https://www.gstatic.com/generate_204`，周期 300 秒，超时 8 秒；故障切换依赖最近一次自动检测，不保证某个网站始终可用或立即切换。

在「设置 → 订阅」开启「打开时更新」和「自动后台更新」，更新间隔可设为 6 小时；iOS「设置 → 通用 → 后台 App 刷新」允许小火箭。节点订阅更新与配置文件更新是两个独立设置。iOS 后台调度不能保证准点执行；强制结束应用后需要重新打开。

参考：[分组及自动更新说明](https://github.com/LOWERTOP/Shadowrocket/wiki) · [分组配置语法](https://github.com/LOWERTOP/Shadowrocket/blob/main/lazy_group.conf)
