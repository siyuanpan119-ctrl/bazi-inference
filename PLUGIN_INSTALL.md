# 安装 Bazi Inference Plugin

本仓库根目录已经是一个 OpenAI Plugin，包含 `bazi-inference` Skill。安装后可在 ChatGPT 和 Codex 的新对话中显式调用，也可由系统按任务自动匹配。

## 从 GitHub marketplace 安装

在已安装 Codex CLI 的 Mac 终端运行：

```bash
codex plugin marketplace add siyuanpan119-ctrl/- --ref main
codex plugin add bazi-inference@bazi-inference
```

然后打开 **Plugins**，刷新或重新打开插件页面，在 **Installed** 中确认“八字命理推演（Bazi Inference）”已启用，并新建一个对话。

在 ChatGPT 中输入 `@八字` 或在 Codex 中输入 `$bazi-inference` 进行显式调用。也可以直接提交出生时间、性别、出生城市和问题，让系统根据 Skill 描述自动匹配。

## 更新已安装版本

仓库更新后运行：

```bash
codex plugin marketplace upgrade bazi-inference
codex plugin add bazi-inference@bazi-inference
```

随后新建对话，确保宿主加载更新后的 Skill。
