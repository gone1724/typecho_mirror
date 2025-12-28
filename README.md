# 博客镜像器

这是一个用 uv 管理的 Python 小工具，基于 wget 把博客抓成可直接部署的静态站点。

---

## 项目特点

* 默认适配 Typecho 公开页面，自动排除后台、登录、评论接口等交互路径。
* 输出目录默认为 `./site/`，可直接推送到 Cloudflare Pages / GitHub Pages。
* 抓取后会重写站内链接与外链图片为本地相对路径，保证离线可用。
* 抓取逻辑为先 `--spider` 探活，在 `site_tmp/` 完成后原子替换 `site/`，失败则保留旧版本。

## 环境与安装

- Python 3.9+。
- 推荐安装 uv：`pip install uv`

## 常用命令

```bash
# 指定站点与输出目录（请填公开网址）
uv run python mirror.py --url https://example.com/ --output-dir my_site

# 默认：清空临时目录，从零抓取
uv run python mirror.py

# 增量：先复制已有 site/，再抓取
uv run python mirror.py --no-clean

# 仅探活，不下载
uv run python mirror.py --spider
```

## 自动化

参考 `run_mirror.sh`：`git pull` -> `uv run python mirror.py` -> 有变更则自动提交推送，可放入定时任务。

## 许可证 | License

- 代码遵循 GNU GPL v3.0。
- 内置 `wget.exe` 来自 GNU Wget（GPLv3），源码：[https://ftp.gnu.org/gnu/wget/](https://ftp.gnu.org/gnu/wget/)
