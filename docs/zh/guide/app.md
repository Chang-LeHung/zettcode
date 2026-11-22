# 桌面端与手机端

两者都是网页网关的一扇窗，不是第二个客户端：点开一个服务器就加载该网关自己的页面，所以聊天、daemon、群、Graph、日志和
配置都是你已经熟悉的那个页面。桌面端只有一个窗口，对话里的链接用系统浏览器打开。

| 应用 | 平台 | 怎么得到 |
| --- | --- | --- |
| 桌面端（Electron） | macOS Apple Silicon、Windows、Linux | `desktop-v<版本>` 安装包，或从仓库 `make desktop` |
| 安卓端（WebView） | Android | [0.1.1 的 APK](https://github.com/Chang-LeHung/zettcode/releases/tag/zettcode-mobile-0.1.1)，或 `make mobile` 和 `make mobile-apk`（需要 `ANDROID_HOME`） |

APK 位于 `clients/mobile/android/app/build/outputs/apk/debug/`。`make desktop-package` 为当前系统写出安装包。

macOS 版只做 ad-hoc 签名、没有公证，所以第一次启动会以“无法验证开发者”被拦下：先让它被拦一次，再到
**系统设置 → 隐私与安全性**点**仍要打开**。提示“App 已损坏”的安装包（`desktop-v0.2.0` 那批没有签名）需要：

```sh
xattr -dr com.apple.quarantine /Applications/ZettCode.app
```

Windows 的 SmartScreen 要点“更多信息 → 仍要运行”。安装包还没有在真实的 Windows 或 Linux 机器上试过，
打不开请反馈。

## 连到一个网关

在一个设备能访问的地址上启动带令牌的网关：

```sh
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

`start` 会打印地址和令牌。用机器的局域网地址，不要用 `127.0.0.1`，并在防火墙里放行端口。把地址填进应用：安卓的选择页
要的是 `http://192.168.1.20:8765` 这样的裸地址，不能带路径。网关页面随后要一次令牌，并保存 30 天的 cookie。
两个应用都不存令牌：桌面端存地址列表和上次的服务器，安卓端存在选择页的 `localStorage`。
**Server → Switch server…**（Ctrl/Cmd+Shift+S）回到列表，连不上的服务器也会回到列表。

页面是明文 HTTP，离开可信网络时请放在 TLS 后面；明文局域网里令牌会以明文经过网络。要让所有设备退出登录，用新令牌重启
（`zettcode gateway restart --token <新令牌>`），再到每台设备上编辑服务器。

## 做不到的事

- 你看到的页面是网关的，想要新功能就运行较新的网关；壳本身很少需要更新。
- 通知只在窗口打开时出现：两个应用都没有推送服务。
- 安卓壳里指向其他站点的链接在同一个 WebView 里打开，没有地址栏；返回键回到服务器列表。
- 没有二维码或深链，地址要手动输入或粘贴。
- 这个仓库不包含 iOS 应用。
