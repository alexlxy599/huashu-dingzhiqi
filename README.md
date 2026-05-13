# LinkedIn 消息生成器（话术定制器）

批量生成个性化 LinkedIn 消息的工具，支持**开源社区招聘**和**学术会议合作**两种场景。

## 功能

### 开源社区模式
- 输入姓名 + GitHub 用户名 + LinkedIn 链接（三列可选）
- 通过 GitHub API 获取个人资料、代码仓库等信息
- 结合 DuckDuckGo 搜索补充背景
- 生成个性化招聘话术

### 学术会议模式
- 输入论文标题，自动通过 Semantic Scholar / arXiv 查找作者和摘要
- 为每位作者生成学术合作交流消息
- 支持 ICML、NeurIPS、CVPR、ICLR 等会议预设

### 通用功能
- **多语言**：中文 / English 切换
- **发件人可配置**：姓名、团队、联系方式自动保存
- **历史记录**：生成结果自动存储，支持搜索、复制、删除
- **多模型支持**：Claude (Anthropic)、OpenRouter、智谱 GLM、本地 Ollama 模型
- **导出 Excel**：一键导出生成结果

## 安装

```bash
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
