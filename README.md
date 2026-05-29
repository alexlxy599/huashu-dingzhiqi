
git clone https://github.com/alexlxy599/huashu-dingzhiqi.git
cd huashu-dingzhiqi
pip install flask anthropic openai duckduckgo-search python-dotenv requests
```

## 配置

创建 `.env` 文件（可选）：

```
GITHUB_TOKEN=ghp_your_token_here
```

GitHub Token 用于提升 API 调用额度（5000次/小时），在 [GitHub Settings > Tokens](https://github.com/settings/tokens) 生成，无需勾选任何权限。

## 运行

```bash
python app.py
```

打开 http://localhost:5055

## 使用本地模型（Ollama）

```bash
# 安装 Ollama
brew install ollama

# 拉取模型
ollama pull qwen3:8b

# 在页面上配置
# 选择「OpenAI 兼容接口」→「本地部署」
# API 地址：http://localhost:11434/v1
# 模型名：qwen3:8b
# API Key：ollama
```

## 技术栈

- **后端**：Flask + SQLite
- **前端**：原生 HTML/CSS/JS
- **信息源**：GitHub API、Semantic Scholar、arXiv、DuckDuckGo
- **LLM**：Anthropic Claude / OpenAI 兼容接口
