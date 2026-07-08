# 项目交接总纲

给接手继续开发的人（或 AI 工具）看的精简入口。详细的技术记录/踩坑日志在各自的
`README.md` 里（很长，建议按需查阅，不用一次读完）。

## 这个项目是什么

客户目前用 **20 部手机登 20 个微信号**人工发朋友圈，想自动化。客户已明确要求必须支持
**iPhone**，所以后续主线从“Android 真机全自动优先”切换为 **iPhone 优先**。仓库里仍保留
两条已探索路线：

| | PC 版（根目录 `src/`） | 手机版（`phone/`） |
|---|---|---|
| 原理 | 一台电脑多开微信客户端，图像识别+模拟点击操作 PC 窗口 | Android：PC 通过 ADB 驱动真机；iPhone：通过 pymobiledevice3 / CoreDevice / WiFi lockdown 探索 |
| 风控隔离性 | 差——已实测确认"一台 PC 多开 2 个微信"会触发风控（照片/视频发不出去） | 好——每台手机独立设备指纹，可各走 SIM 流量，天然对应客户"20 部真机"的场景 |
| 成熟度 | 较成熟，能发图/视频，还有个视频误报的尾巴没根治 | Android 核心链路已验证；iPhone 已验证 USB 下可识别设备、复制文案、打开微信，WiFi 下可识别在线设备/读机型信息，但无线开发者服务 tunnel 尚未跑通 |
| 结论倾向 | 不再作为客户主线 | iPhone 是客户主线；Android 只作为技术储备/备用路线 |

**两条路线代码完全独立，互不调用**，只是放在同一个 git 仓库方便管理。

## 从这里开始

- PC 版详细文档：[`README.md`](README.md)（664 行，含完整踩坑史）
- 手机版详细文档：[`phone/README.md`](phone/README.md)（架构、已跑通能力、待办）
- 手机端一次性配置步骤：[`phone/手机配置清单.md`](phone/手机配置清单.md)（给操作员看，不是给开发者）

## 关键教训（别重新踩一遍）

这几条是花了不少时间才搞明白的，看到类似症状先想到这里：

1. **cv2.imread/imwrite 在 Windows 上遇到含中文的路径会静默失败**（返回 None/False，
   不报错）。PC 版打包目录名是中文，曾经导致"找不到按钮"排查了两天，最后发现是
   模板图根本没加载进来。**所有 cv2 文件 I/O 一律走字节流**（`np.fromfile`+`imdecode`
   / `imencode`+文件句柄写），不要直接传中文路径给 cv2 的 API。
2. **微信 8.0.52+ 对无障碍服务（AccessibilityService）做了节点混淆**，主流安卓自动化
   框架在微信上平均 14 天失效。所以手机版走**截屏 + 按屏幕比例坐标点击**，不用
   无障碍——这是刻意的技术选型，别想着"换回无障碍服务更省事"。
3. **手机型号/分辨率不统一，坐标不能全局写死**。手机版的坐标按机型存在
   `phone/src/device_profile.py` 的 Profile 库里，新机型接入前必须先标定
   （截屏走一遍流程记录比例坐标），不能假设别的机型能直接用同一份坐标。
4. **无线 adb 的设备号（ip:port）不稳定**，daemon 重启/手机重连就会变。凡是要
   "记住某台设备"（备注名、任务归属）都必须用 `ro.serialno`（硬件序列号）做 key，
   不能用连接串。这个坑在手机版踩过两次（`device_alias`→`device_registry` 重构、
   任务字段从 `device_serial` 改成 `device_hw_serial`）。
   iPhone 侧同理用 UDID 作为设备身份，别名按 UDID 持久化。
5. **测试素材只能用现场生成的合成图片，不能拿仓库里现成的 "test_*" 文件夹**。
   `wechat-moment/test_images/` 等目录里放的实际是真实个人照片，曾经误当"随便的
   测试图"直接发布到了真实朋友圈——这类会产生真实外部效果（发布/发送）的验证，
   一律用 PIL/OpenCV 现场生成纯色图/静音视频，用完即弃。
6. **风控是真实存在且没有确定性解法的**。已验证：同设备多微信账号会触发拒发；
   风控拒绝横幅可能几分钟后才出现（PC 版和手机版都有"发布成功"误报的已知问题，
   都没根治，见各自 README 的"失败检测"章节）。任何"完全解决风控"的方案都要
   打问号，只能靠观察和缓解，不能承诺零风险。
7. **iPhone 不等于 Android 自动化能力**。2026-07-08 在 iPhone13,3 / iOS 26.5、iPhone14,2 / iOS 26.5.2 上验证：
   `pymobiledevice3` 可以识别 USB 设备、挂载 DeveloperDiskImage、打开微信、写剪贴板和截图；
   但 CoreDevice 远程触控报错要求 iOS 27.0+，WDA 需要额外签名 Runner，不适合明天交付。
   所以 iPhone 只能作为半自动模式：到点复制文案并打开微信，人工选择素材和发表。
8. **iPhone WiFi 发现可行，但不等于无线控制可行**。已在 `192.168.1.34` 验证：
   WiFi lockdown `62078` 和 RemotePairing `49152` 开放，电脑可不插线读取 iPhone 机型/iOS；
   但 `developer core-device ... --userspace` 仍报 `Device is not connected`，`remote start-tunnel -t wifi`
   需要管理员隧道且当前未拿到可用 RSD 地址。后续要把“无线识别”和“无线开发者服务 tunnel”分开推进。

## 环境准备速览

- PC 版：Python 3.12，`pip install -r requirements.txt`（Windows 跑真实发布，Mac 只能
  跑 mock）。打包用 `build_exe.spec`（PyInstaller，onedir 模式）。
- 手机版：Python 3.12，`pip install -r phone/requirements.txt`。开发/打包需要 Google 官方
  `platform-tools`（adb），仓库里没带（体积大，`.gitignore` 已排除），但**这台开发机
  本地已经放好了**：`phone/platform-tools/adb.exe`。打包用 `phone_build_exe.spec`，
  交付包会把 adb 放进 `dist/朋友圈发布助手/_internal/platform-tools/adb.exe`；
  `main.py` 的 `_find_adb_path()` 会同时兼容开发路径和打包后的 `_internal` 路径。
  换新机器开发才需要重新下载。
  手机端一次性配置见"手机配置清单.md"（开发者选项、ADBKeyboard 输入法等，MIUI 上
  有几个必须踩的坑）。
- iPhone 模式需要 iTunes/Apple Mobile Device Support + `pymobiledevice3`。手机需开启开发者模式并信任
  这台电脑。当前 USB 半自动能力已验证；WiFi 在线识别已验证，WiFi 打开微信/复制文案尚未跑通。
- 两个程序共用同一套注册码算法（同私钥），但各自独立的 `activation.dat`，本地测试
  设 `WM_DEBUG=1` 跳过激活。

## 当前明确的待办（汇总，详细版见各自 README 底部"下一步"）

**PC 版：**
- 视频发布后"回头巡检朋友圈"确认真实状态（当前是等固定秒数没等到失败横幅就报成功，
  会误报）

**手机版 / iPhone 主线（当前重点）：**
- iPhone 全自动发布仍未解决：优先调研和验证 WDA/Appium/XCUITest 签名 Runner，或 iOS 27+ CoreDevice
  远程触控；仅靠当前 pymobiledevice3 在 iOS 26.5.x 上不能远程点选微信 UI。
- iPhone WiFi tunnel 继续攻：已能 WiFi 识别设备，下一步是稳定拿到 RSD tunnel，让无线复制文案/打开微信可用。
- iPhone 半自动流程要产品化：设备台账、定时任务、复制文案、打开微信、截图留证、人工确认状态。

**Android 已验证路线（备用）：**
- 只验证过小米15；新机型仍要先标定坐标 Profile（尤其微信首页→朋友圈、相册选择器顶部网格）
- 自动失败检测/发布后回看确认还没做完整闭环；当前点击流程走完后标记"待确认"，需要人工回看朋友圈确认真实状态
- 只验证过 1 台真机（小米15），20 台并行管理、USB hub 连接方案都没搭
- "到时间自动触发"和最新的设备清单改动（离线显示/自动重扫描）**都还没做真机验证**，
  只做过结构性冒烟测试（构造假数据测 GUI 逻辑），这个尤其要优先补验证，不要假设它能用
