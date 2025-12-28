<h1 align="center">博客镜像器</h1>
<p align="center">基于 wget 的 Typecho 博客静态化工具，使用 uv 管理。</p>

## ✨ 项目特点

- 默认适配 Typecho 公开页，自动避开后台、登录、评论接口。
- 产出目录 `site/` 可直接部署到 Cloudflare Pages / GitHub Pages。
- 抓取后重写站内链接与外链图片为本地相对路径，保证离线可用。
- 先 `--spider` 探活，抓到 `site_tmp/` 后原子替换 `site/`，失败保留旧版。

## 🧰 环境与安装

- Python 3.9+。
- 推荐 `pip install uv`。

## 🚀 快速使用

```bash
# 指定站点与输出目录
uv run python mirror.py --url https://example.com/ --output-dir my_site

# 从零抓取（默认网址需在 .py 中修改）
uv run python mirror.py

# 增量抓取（默认网址需在 .py 中修改）
uv run python mirror.py --no-clean

# 仅探活（默认网址需在 .py 中修改）
uv run python mirror.py --spider
```

## 🤖 自动化

- 参考 `run_mirror.sh`：`git pull` -> `uv run python mirror.py` -> 有变更自动提交推送，可挂定时任务。

## 📄 许可证

- 代码遵循 GNU GPL v3.0。
- 内置 `wget.exe` 来源 GNU Wget（GPLv3），源码：https://ftp.gnu.org/gnu/wget/
