# 个人订阅台账 · Renew Ledger

适合一个家庭或小工作室共用管理员台账。登记人民币月费、年费和下次续费日，查看按到期日排序的列表、逾期天数和折合年支出。选择「已续一期」会推进一个账期，月底遇短月自动取该月末日，长月恢复原日期。所有日期按北京时间展示。应用不连接银行，不扣款，不发送到期推送。

## 安装和登录

TOS 7 x86_64，启用 Docker Engine，预留 TCP 18765。通过支持 Docker 应用包的应用中心安装。首次启动需要能从 Docker Hub 取得固定版 Amazon Linux 2023 官方镜像（内置系统 Python 3 和 SQLite），应用运行期间无需外部服务。应用专属 data 目录须允许 UID/GID 1000 写入，仅授权台账管理员读取该目录。

在桌面打开应用，以 admin 和应用数据目录 data/password.txt 中首次启动生成的随机密码登录。NAS 管理员可在停止应用后替换该文件内容为至少 16 字符的强密码，保留属主和 0600 权限，再启动应用。HTTP Basic 凭据经明文 HTTP 可被截获，仅在受信任局域网使用，跨网络请通过 HTTPS 反向代理。具有该密码的人共享全部编辑权。

## 使用和备份

选择「新增订阅」，填服务名、每期金额、周期和下次续费日。用服务名查询，点「编辑」修改。确认实际续费后点「已续一期」。删除操作需要在单独页面确认。首页年支出按所有现存月费乘 12 加年费计算；查询仅筛选列表。

停止应用后备份整个 data 目录；ledger.db 保存账目，password.txt 保存访问密码。恢复时还原两者及权限。卸载前先备份需保留的数据。

## 构建和验收

python3 build.py 调用 Ruby/Psych 解析 Compose，并生成 dist/renewledger.tar.gz、dist/SHA256SUMS。在 dist 运行 shasum -a 256 -c SHA256SUMS。构建仅使用 Python、Ruby 标准库。compose.template 由构建脚本嵌入可读的 app.py，并转义 Compose 插值。最终压缩包根目录恰有规范所列四个文件。应用代码和图标为本次原创。包仅引用 Docker Official Image library/amazonlinux，镜像及其第三方组件由 Docker Hub 提供。[Amazon Linux 官方镜像及许可信息](https://hub.docker.com/_/amazonlinux)

在隔离且无其他容器的 Linux Docker 测试机内以 root 执行 python3 test.py dist/renewledger.tar.gz。测试器的 root 用于设置挂载属主和检查内核进程状态，应用自身以 1000:1000 运行。

## 反馈与许可

[反馈问题或建议](https://github.com/metal643958961-a11y/renewledger-tos/issues)。请注明应用版本、TOS 版本、操作步骤和实际结果。反馈中请勿包含登录密码或个人订阅记录。

本应用原创部分的使用许可见 [LICENSE](LICENSE)。Amazon Linux 镜像由用户的 Docker Engine 从官方仓库单独拉取。镜像内各软件包适用其上游许可证，可在镜像内通过 RPM 软件包元数据查看。[Amazon Linux 镜像来源](https://github.com/amazonlinux/container-images)
